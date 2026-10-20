/**
 * Ход поиска с настоящего сервера — поток SSE, прочитанный через fetch (НТ-2, НТ-23).
 *
 * Браузерный EventSource не передаёт заголовок с ключом рабочего места, поэтому поток
 * читается из тела ответа fetch (ReadableStream). При обрыве связи поток сообщает
 * `connection-lost`, переподключается с `?after=<номер последнего события>` — сервер
 * досылает пропущенное, поиск при этом не перезапускается — и сообщает
 * `connection-restored`. Эти два события создаёт клиент (docs/12-tech-design.md §4).
 */
import { isApiError, plainApiError } from './client';
import type { ApiError, ConnectionState, SearchEvent, SearchRun, Selection } from './types';

/** Ответ сервера на запуск поиска или повтор площадки: откуда читать поток. */
export interface RunTicket {
  searchId: string;
  after: number;
}

/** Что потоку нужно от HTTP-клиента (http.ts). */
export interface RunTransport {
  /** Открыть поток событий. Ошибка HTTP или сети — MonitorApiError. */
  openStream(path: string, signal: AbortSignal): Promise<Response>;
  getSelection(searchId: string): Promise<Selection>;
  stop(searchId: string): Promise<void>;
  /** Сеть не ответила: отметить «нет связи» (баннер, проверка /health). */
  markOffline(): void;
  getConnection(): ConnectionState;
  onConnectionChange(listener: (state: ConnectionState) => void): () => void;
}

const TERMINAL: ReadonlySet<SearchEvent['type']> = new Set(['finished', 'stopped', 'failed']);

/** Сервер шлёт `: ping` каждые 15 с; тишина дольше — соединение повисло, переподключаемся. */
const SILENCE_MS = 40_000;
/** Паузы между попытками переподключения. */
const RETRY_MS = [1_000, 2_000, 4_000, 8_000];
const MAX_RETRY_MS = 10_000;
/** Сколько раз подряд повторять при ошибке сервера (5xx), прежде чем сдаться. */
const MAX_SERVER_RETRIES = 4;

const LOST_MESSAGE =
  'Нет связи с сервером. Поиск продолжается на сервере — результаты появятся, когда связь вернётся.';
const RESTORED_MESSAGE = 'Связь восстановлена. Догружаем найденное.';

/** Ошибка запуска или потока → ошибка контракта для события `failed`; причина не теряется. */
export function toApiError(value: unknown): ApiError {
  if (isApiError(value)) return plainApiError(value);
  return { code: 'server', message: 'Поиск не удался. Повторите через минуту.' };
}

// ---------------------------------------------------------------- разбор SSE

interface SseMessage {
  id: string | null;
  event: string | null;
  data: string;
}

/**
 * Разбор потока `text/event-stream` по стандарту: строки `поле: значение`, сообщение
 * заканчивается пустой строкой, `:` в начале — комментарий (пинг). Переводы строк —
 * `\n`, `\r\n` или `\r`; кусок может оборваться посреди строки.
 */
export class SseParser {
  private buffer = '';
  private data: string[] = [];
  private id: string | null = null;
  private event: string | null = null;

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const messages: SseMessage[] = [];
    for (;;) {
      const match = /\r\n|\r|\n/u.exec(this.buffer);
      if (!match) break;
      // `\r` в самом конце может оказаться началом `\r\n` — ждём следующий кусок.
      if (match[0] === '\r' && match.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      const message = this.line(line);
      if (message) messages.push(message);
    }
    return messages;
  }

  private line(line: string): SseMessage | null {
    if (line === '') {
      const message =
        this.data.length > 0
          ? { id: this.id, event: this.event, data: this.data.join('\n') }
          : null;
      this.data = [];
      this.event = null;
      this.id = null;
      return message;
    }
    if (line.startsWith(':')) return null;
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'data') this.data.push(value);
    else if (field === 'id') this.id = value;
    else if (field === 'event') this.event = value;
    return null;
  }
}

// ---------------------------------------------------------------- поток поиска

type Opening =
  { kind: 'ticket'; ticket: () => Promise<RunTicket> } | { kind: 'attach'; searchId: string };

/**
 * Запущенный поиск на сервере. Как и имитация, хранит историю: поздний подписчик
 * сначала получает всё, что уже пришло, потом новые события.
 *
 * `searchId` до ответа сервера на запуск — пустая строка: настоящий id приходит
 * в ответе `POST /api/searches` и в событии `started` (`conditions.searchId`).
 */
export class HttpSearchRun implements SearchRun {
  private id: string;
  private readonly history: SearchEvent[] = [];
  private readonly listeners = new Set<(event: SearchEvent) => void>();
  private waiters: (() => void)[] = [];
  private isClosed = false;
  private stopWanted = false;
  /** Номер последнего полученного события: с него продолжаем после обрыва. */
  private lastSeq = 0;
  private lost = false;
  private abort: AbortController | null = null;

  private constructor(
    private readonly transport: RunTransport,
    searchId: string,
  ) {
    this.id = searchId;
  }

  /** Новый поиск или повтор площадки: сначала запрос-билет, потом поток с `after`. */
  static fromTicket(
    transport: RunTransport,
    knownId: string,
    ticket: () => Promise<RunTicket>,
  ): HttpSearchRun {
    const run = new HttpSearchRun(transport, knownId);
    void run.begin({ kind: 'ticket', ticket });
    return run;
  }

  /** Подключиться к поиску без перезапуска: снимок подборки, затем ход или итог. */
  static attach(transport: RunTransport, searchId: string): HttpSearchRun {
    const run = new HttpSearchRun(transport, searchId);
    void run.begin({ kind: 'attach', searchId });
    return run;
  }

  get searchId(): string {
    return this.id;
  }

  get closed(): boolean {
    return this.isClosed;
  }

  subscribe(listener: (event: SearchEvent) => void): () => void {
    this.history.forEach((event) => listener(event));
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  stop(): void {
    if (this.isClosed) return;
    // Найденное сохранится: сервер пришлёт `stopped` в этом же потоке.
    if (this.id) void this.transport.stop(this.id).catch(() => undefined);
    else this.stopWanted = true;
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<SearchEvent, void, undefined> {
    let index = 0;
    for (;;) {
      while (index < this.history.length) {
        const event = this.history[index];
        index += 1;
        if (event) yield event;
      }
      if (this.isClosed) return;
      await new Promise<void>((resolve) => {
        this.waiters.push(resolve);
      });
    }
  }

  // ---------------------------------------------------------------- внутреннее

  private emit(event: SearchEvent): void {
    if (this.isClosed) return;
    if (event.type === 'started' && !this.id) this.id = event.conditions.searchId;
    this.history.push(event);
    if (TERMINAL.has(event.type)) {
      this.isClosed = true;
      this.abort?.abort();
    }
    this.listeners.forEach((listener) => listener(event));
    const waiters = this.waiters;
    this.waiters = [];
    waiters.forEach((wake) => wake());
  }

  private fail(error: unknown): void {
    this.emit({ type: 'failed', error: toApiError(error) });
  }

  private async begin(opening: Opening): Promise<void> {
    let snapshot = false;
    if (opening.kind === 'ticket') {
      let ticket: RunTicket;
      try {
        ticket = await opening.ticket();
      } catch (error) {
        // Ошибка запуска (лимиты, нет связи, чужой поиск) — событием `failed`, как требует контракт.
        this.fail(error);
        return;
      }
      this.id = ticket.searchId;
      this.lastSeq = ticket.after;
      if (this.stopWanted) void this.transport.stop(this.id).catch(() => undefined);
    } else {
      snapshot = true;
    }
    try {
      await this.read(snapshot);
    } catch (error) {
      this.fail(error);
    }
  }

  /**
   * Читать поток до итогового события, переподключаясь после обрывов. Поток нового
   * поиска или повтора продолжается с номера последнего события; поток открытого поиска
   * (`attachSearch`) каждый раз начинается со снимка: снимок — полное текущее состояние,
   * а повтор `started` и `items` экраны просто сливают с тем, что уже есть.
   */
  private async read(snapshot: boolean): Promise<void> {
    let attempt = 0;
    let serverErrors = 0;
    while (!this.isClosed) {
      const query = snapshot ? 'snapshot=true' : `after=${this.lastSeq}`;
      const abort = new AbortController();
      this.abort = abort;
      let response: Response;
      try {
        response = await this.transport.openStream(
          `/api/searches/${encodeURIComponent(this.id)}/events?${query}`,
          abort.signal,
        );
      } catch (error) {
        if (this.isClosed) return;
        if (isApiError(error) && error.code === 'offline') {
          this.markLost();
          await this.pause(attempt);
          attempt += 1;
          continue;
        }
        if (isApiError(error) && error.code === 'too-many-requests') {
          await this.pause(attempt, (error.retryAfterSec ?? 5) * 1000);
          attempt += 1;
          continue;
        }
        if (isApiError(error) && error.code === 'server' && serverErrors < MAX_SERVER_RETRIES) {
          serverErrors += 1;
          await this.pause(attempt);
          attempt += 1;
          continue;
        }
        throw error; // 404 — поиск не найден (или чужой); прочее — показываем
      }

      if (this.lost) {
        this.lost = false;
        this.emit({ type: 'connection-restored', message: RESTORED_MESSAGE });
      }
      attempt = 0;
      serverErrors = 0;

      const outcome = await this.consume(response, abort);
      if (this.isClosed) return;
      if (outcome === 'broken') {
        this.markLost();
        await this.pause(attempt);
        attempt += 1;
        continue;
      }
      // Сервер закрыл поток без итога: поиск уже не идёт — итог берём из подборки.
      if (await this.finishFromSelection()) return;
      await this.pause(0);
    }
  }

  /** Прочитать один ответ-поток. `ended` — сервер закрыл поток сам, `broken` — обрыв. */
  private async consume(response: Response, abort: AbortController): Promise<'ended' | 'broken'> {
    const body = response.body;
    if (!body) return 'broken';
    const reader = body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    let silence: ReturnType<typeof setTimeout> | null = null;
    const watch = () => {
      if (silence) clearTimeout(silence);
      silence = setTimeout(() => abort.abort(), SILENCE_MS);
    };
    // Браузер сообщил «нет сети» — не ждём тишины, переподключаемся сразу.
    const unsubscribe = this.transport.onConnectionChange((state) => {
      if (state === 'offline') abort.abort();
    });
    watch();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) return 'ended';
        watch();
        for (const message of parser.feed(decoder.decode(value, { stream: true }))) {
          const seq = message.id === null ? Number.NaN : Number(message.id);
          if (Number.isInteger(seq) && seq > this.lastSeq) this.lastSeq = seq;
          let event: SearchEvent;
          try {
            event = JSON.parse(message.data) as SearchEvent;
          } catch {
            continue; // непонятное сообщение потока пропускаем, номер учли
          }
          this.emit(event);
          if (this.isClosed) return 'ended';
        }
      }
    } catch {
      // Обрыв сети, тишина дольше SILENCE_MS или «нет сети» от браузера (abort).
      return this.isClosed ? 'ended' : 'broken';
    } finally {
      if (silence) clearTimeout(silence);
      unsubscribe();
      reader.cancel().catch(() => undefined);
    }
  }

  /** Поток закрылся без итога. Если поиск закончен — отдать итог из подборки. */
  private async finishFromSelection(): Promise<boolean> {
    let selection: Selection;
    try {
      selection = await this.transport.getSelection(this.id);
    } catch (error) {
      if (isApiError(error) && error.code === 'offline') {
        this.markLost();
        return false;
      }
      throw error;
    }
    if (selection.phase === 'running') return false;
    this.emit(
      selection.phase === 'stopped'
        ? { type: 'stopped', selection }
        : { type: 'finished', selection },
    );
    return true;
  }

  private markLost(): void {
    this.transport.markOffline();
    if (this.lost) return;
    this.lost = true;
    this.emit({ type: 'connection-lost', message: LOST_MESSAGE });
  }

  /** Пауза перед повтором; связь вернулась раньше — продолжаем сразу. */
  private pause(attempt: number, minimum = 0): Promise<void> {
    const ms = Math.max(minimum, RETRY_MS[attempt] ?? MAX_RETRY_MS);
    return new Promise<void>((resolve) => {
      let unsubscribe: (() => void) | null = null;
      const timer = setTimeout(() => {
        unsubscribe?.();
        resolve();
      }, ms);
      if (this.transport.getConnection() === 'offline') {
        unsubscribe = this.transport.onConnectionChange((state) => {
          if (state !== 'online') return;
          clearTimeout(timer);
          unsubscribe?.();
          resolve();
        });
      }
    });
  }
}
