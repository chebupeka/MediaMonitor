/**
 * Настоящий сервер: реализация `MonitorApi` через HTTP — по таблице
 * «метод MonitorApi → HTTP-запрос» в docs/12-tech-design.md §4.
 *
 * - Рабочее место (Р8): ключ хранится в браузере (отдельно для каждого адреса сервера)
 *   и уходит заголовком `X-Workspace-Key`. Ключа нет или сервер его не знает — клиент
 *   сам создаёт новое место (`POST /api/workspaces`). Ссылка «Открыть на другом
 *   компьютере» (`…#workspace=<ключ>`) открывает то место при загрузке страницы.
 * - Ход поиска — поток SSE через fetch (http-run.ts): EventSource не передаёт заголовки.
 * - Файл XLSX собирает сервер (`GET …/export.xlsx`): тот же состав, что в предпросмотре.
 * - Ошибки — `MonitorApiError` с кодом контракта; лимиты (`too-many-requests` + сколько
 *   ждать), «нет связи» (`offline`), «не найдено» (в том числе чужой поиск, НТ-7).
 * - Связь (НТ-23): `navigator.onLine`, ошибки сети и обрывы потока → «нет связи»;
 *   пока её нет, клиент раз в 3 с спрашивает `GET /health`.
 */
import { MonitorApiError, isApiError, type MonitorApi } from './client';
import { HttpSearchRun, type RunTicket, type RunTransport } from './http-run';
import type {
  AiCheck,
  ApiError,
  CatalogSource,
  ConnectionState,
  ExportFile,
  ExportOptions,
  ExportPreview,
  ImportPreview,
  ImportReport,
  LinkRecheckReport,
  QueryAnalysis,
  RecentSearch,
  ResultItem,
  Selection,
  SelectionCounts,
  Source,
  SourceCheck,
  SourcesRecheckReport,
  SpreadReport,
  StandStatus,
  StartState,
  TopicUnderstanding,
  Workspace,
  WorkspaceLink,
} from './types';

/** Реализация на сервере: тот же `MonitorApi` плюс адрес сервера. */
export interface HttpMonitorApi extends MonitorApi {
  readonly baseUrl: string;
}

const KEY_STORAGE_PREFIX = 'mm-workspace-key:';
const PROBE_MS = 3_000;
const XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

const OFFLINE_MESSAGE =
  'Нет связи с сервером. Проверьте подключение — данные на сервере не потеряются.';
const BAD_RESPONSE_MESSAGE = 'Сервер прислал непонятный ответ. Повторите действие.';

const ERROR_CODES: ReadonlySet<string> = new Set<ApiError['code']>([
  'offline',
  'too-many-requests',
  'too-long',
  'not-found',
  'invalid',
  'server',
]);

type QueryValue = string | number | boolean | readonly string[] | undefined;

interface RequestOptions {
  /** Тело JSON. */
  body?: unknown;
  /** Тело multipart (импорт файла). */
  form?: FormData;
  query?: Record<string, QueryValue>;
  /** Передавать ключ рабочего места (по умолчанию да). */
  auth?: boolean;
  /** Конкретный ключ вместо текущего (проверка ключа при входе). */
  key?: string;
  accept?: string;
  signal?: AbortSignal;
}

// ---------------------------------------------------------------- ошибки

function isErrorPayload(value: unknown): value is ApiError {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.code === 'string' && ERROR_CODES.has(v.code) && typeof v.message === 'string';
}

function fallbackError(status: number): { code: ApiError['code']; message: string } {
  if (status === 404) return { code: 'not-found', message: 'Не найдено. Возможно, это удалили.' };
  if (status === 413) return { code: 'too-long', message: 'Запрос слишком большой для стенда.' };
  if (status === 400 || status === 422)
    return { code: 'invalid', message: 'Данные не прошли проверку на сервере.' };
  if (status === 429)
    return {
      code: 'too-many-requests',
      message: 'Слишком много запросов. Подождите немного и повторите.',
    };
  if (status === 502 || status === 503 || status === 504)
    return { code: 'server', message: 'Сервер временно недоступен. Повторите через минуту.' };
  return { code: 'server', message: 'На сервере что-то пошло не так. Повторите через минуту.' };
}

/** Ответ с ошибкой → `MonitorApiError` в форме контракта. */
async function errorFrom(response: Response): Promise<MonitorApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const header = Number.parseInt(response.headers.get('Retry-After') ?? '', 10);
  const retryHeader = Number.isFinite(header) && header >= 0 ? header : undefined;
  if (isErrorPayload(payload)) {
    return new MonitorApiError(payload.code, payload.message, payload.retryAfterSec ?? retryHeader);
  }
  const fallback = fallbackError(response.status);
  return new MonitorApiError(fallback.code, fallback.message, retryHeader);
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

// ---------------------------------------------------------------- ключ рабочего места

/** Ключ из ссылки или как есть: «https://…/#workspace=abc» → «abc» (как на сервере). */
export function cleanWorkspaceKey(raw: string): string {
  let value = raw.trim();
  const marker = '#workspace=';
  const at = value.indexOf(marker);
  if (at >= 0) value = value.slice(at + marker.length);
  return (value.split('&')[0] ?? '').trim();
}

/** Ключ из адреса страницы (`#workspace=<ключ>`); фрагмент убираем из адреса. */
function takeLinkKey(): string | null {
  if (typeof window === 'undefined') return null;
  const hash = window.location.hash;
  const match = /(?:^#|&)workspace=([^&]+)/u.exec(hash);
  if (!match?.[1]) return null;
  const rest = hash
    .replace(/^#/u, '')
    .split('&')
    .filter((part) => !part.startsWith('workspace='))
    .join('&');
  try {
    const url = `${window.location.pathname}${window.location.search}${rest ? `#${rest}` : ''}`;
    window.history.replaceState(window.history.state, '', url);
  } catch {
    // адрес не поменять (песочница) — не страшно
  }
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

// ---------------------------------------------------------------- транспорт

class HttpTransport implements RunTransport {
  private keyPromise: Promise<string> | null = null;
  private state: ConnectionState;
  private readonly listeners = new Set<(state: ConnectionState) => void>();
  private probeTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly keyStorage: string;

  constructor(readonly baseUrl: string) {
    this.keyStorage = `${KEY_STORAGE_PREFIX}${baseUrl}`;
    this.state =
      typeof navigator !== 'undefined' && navigator.onLine === false ? 'offline' : 'online';
    if (typeof window !== 'undefined') {
      window.addEventListener('offline', () => this.setConnection('offline'));
      window.addEventListener('online', () => void this.probe());
    }
    if (this.state === 'offline') this.scheduleProbe();
  }

  // ---------------------------------------------------------------- связь

  getConnection(): ConnectionState {
    return this.state;
  }

  onConnectionChange(listener: (state: ConnectionState) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  markOffline(): void {
    this.setConnection('offline');
  }

  private markOnline(): void {
    if (this.probeTimer) clearTimeout(this.probeTimer);
    this.probeTimer = null;
    this.setConnection('online');
  }

  private setConnection(next: ConnectionState): void {
    if (next === 'offline') this.scheduleProbe();
    if (next === this.state) return;
    this.state = next;
    this.listeners.forEach((listener) => listener(next));
  }

  private scheduleProbe(): void {
    if (this.probeTimer) return;
    this.probeTimer = setTimeout(() => {
      this.probeTimer = null;
      void this.probe();
    }, PROBE_MS);
  }

  /** Проверить, отвечает ли сервер (`GET /health`). */
  private async probe(): Promise<void> {
    try {
      const response = await fetch(`${this.baseUrl}/health`, {
        cache: 'no-store',
        credentials: 'omit',
      });
      if (response.ok) {
        this.markOnline();
        return;
      }
    } catch {
      // сервер не ответил
    }
    if (this.state === 'offline') this.scheduleProbe();
  }

  // ---------------------------------------------------------------- рабочее место

  private readKey(): string | null {
    try {
      return window.localStorage.getItem(this.keyStorage);
    } catch {
      return null;
    }
  }

  private storeKey(key: string): void {
    try {
      window.localStorage.setItem(this.keyStorage, key);
    } catch {
      // без хранилища ключ живёт до перезагрузки
    }
  }

  /** Ключ текущего рабочего места; при первом обращении — проверить или создать. */
  workspaceKey(): Promise<string> {
    this.keyPromise ??= this.resolveKey().catch((error: unknown) => {
      this.keyPromise = null;
      throw error;
    });
    return this.keyPromise;
  }

  private async resolveKey(): Promise<string> {
    const fromLink = takeLinkKey();
    if (fromLink) {
      try {
        return await this.adoptKey(fromLink);
      } catch (error) {
        if (!isApiError(error) || error.code !== 'not-found') throw error;
        console.warn('Рабочее место по ссылке не найдено: остаёмся в своём.');
      }
    }
    const stored = this.readKey();
    if (stored) {
      try {
        await this.json<Workspace>('GET', '/api/workspace', { key: stored });
        return stored;
      } catch (error) {
        // Сервер не знает ключ (база пересоздана) — заводим новое место.
        if (!isApiError(error) || error.code !== 'not-found') throw error;
      }
    }
    const link = await this.json<WorkspaceLink>('POST', '/api/workspaces', { auth: false });
    this.storeKey(link.key);
    return link.key;
  }

  /** Открыть место по ключу или ссылке и запомнить ключ. Неизвестный ключ — `not-found`. */
  private async adoptKey(raw: string): Promise<string> {
    const key = cleanWorkspaceKey(raw);
    await this.json<Workspace>('POST', '/api/workspace/open', { body: { key }, auth: false });
    this.storeKey(key);
    return key;
  }

  async openWorkspace(raw: string): Promise<Workspace> {
    const key = cleanWorkspaceKey(raw);
    const workspace = await this.json<Workspace>('POST', '/api/workspace/open', {
      body: { key },
      auth: false,
    });
    this.storeKey(key);
    this.keyPromise = Promise.resolve(key);
    return workspace;
  }

  // ---------------------------------------------------------------- запросы

  private url(path: string, query?: Record<string, QueryValue>): string {
    const url = new URL(`${this.baseUrl}${path}`);
    for (const [name, value] of Object.entries(query ?? {})) {
      if (value === undefined) continue;
      // Список — повторяющийся параметр: `onlyRelevance=direct&onlyRelevance=indirect`.
      if (typeof value === 'object') for (const item of value) url.searchParams.append(name, item);
      else url.searchParams.set(name, String(value));
    }
    return url.href;
  }

  /** Запрос; не-2xx — `MonitorApiError`, сеть не ответила — `offline`. */
  async request(method: string, path: string, options: RequestOptions = {}): Promise<Response> {
    const headers: Record<string, string> = { Accept: options.accept ?? 'application/json' };
    if (options.auth !== false)
      headers['X-Workspace-Key'] = options.key ?? (await this.workspaceKey());
    let body: BodyInit | undefined;
    if (options.form) body = options.form;
    else if (options.body !== undefined) {
      body = JSON.stringify(options.body);
      headers['Content-Type'] = 'application/json';
    }
    let response: Response;
    try {
      response = await fetch(this.url(path, options.query), {
        method,
        headers,
        body,
        signal: options.signal,
        cache: 'no-store',
        credentials: 'omit',
      });
    } catch (error) {
      if (isAbort(error)) throw error;
      this.markOffline();
      throw new MonitorApiError('offline', OFFLINE_MESSAGE);
    }
    this.markOnline();
    if (!response.ok) throw await errorFrom(response);
    return response;
  }

  async json<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const response = await this.request(method, path, options);
    try {
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof TypeError) {
        this.markOffline();
        throw new MonitorApiError('offline', OFFLINE_MESSAGE);
      }
      throw new MonitorApiError('server', BAD_RESPONSE_MESSAGE);
    }
  }

  /** Запрос без тела ответа (204). */
  async send(method: string, path: string, options: RequestOptions = {}): Promise<void> {
    const response = await this.request(method, path, options);
    await response.body?.cancel();
  }

  // ---------------------------------------------------------------- для потока (http-run.ts)

  openStream(path: string, signal: AbortSignal): Promise<Response> {
    return this.request('GET', path, { accept: 'text/event-stream', signal });
  }

  getSelection(searchId: string): Promise<Selection> {
    return this.json<Selection>('GET', searchPath(searchId));
  }

  stop(searchId: string): Promise<void> {
    return this.send('POST', `${searchPath(searchId)}/stop`);
  }
}

function searchPath(searchId: string): string {
  return `/api/searches/${encodeURIComponent(searchId)}`;
}

function sourcePath(sourceId: string): string {
  return `/api/sources/${encodeURIComponent(sourceId)}`;
}

function exportQuery(options?: ExportOptions): Record<string, QueryValue> {
  return {
    onlyRelevance:
      options?.onlyRelevance && options.onlyRelevance.length > 0
        ? options.onlyRelevance
        : undefined,
  };
}

/** Число строк файла из заголовка `X-Export-Rows`; нет заголовка — `null`. */
function rowCountFrom(header: string | null): number | null {
  const value = Number.parseInt(header ?? '', 10);
  return Number.isFinite(value) && value >= 0 ? value : null;
}

/** Имя файла из `Content-Disposition` (сервер отдаёт `filename*=UTF-8''…`). */
function fileNameFrom(disposition: string | null): string | null {
  if (!disposition) return null;
  const encoded = /filename\*=UTF-8''([^;]+)/iu.exec(disposition)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded.trim());
    } catch {
      // ниже — простое имя
    }
  }
  return /filename="([^"]+)"/iu.exec(disposition)?.[1] ?? null;
}

// ---------------------------------------------------------------- MonitorApi

/** HTTP-клиент настоящего сервера. `baseUrl` — без завершающей «/», например `http://127.0.0.1:8000`. */
export function createHttpApi(baseUrl: string): HttpMonitorApi {
  const t = new HttpTransport(baseUrl);
  // Рабочее место — сразу при загрузке: ключ из ссылки `#workspace=` не задерживается в адресе,
  // а первый экран не ждёт создания места. Ошибку (нет связи) повторит первый же запрос.
  void t.workspaceKey().catch(() => undefined);
  const ticket = (path: string, body?: unknown) => () =>
    t.json<RunTicket>('POST', path, body === undefined ? {} : { body });

  return {
    baseUrl,

    getStartState: () => t.json<StartState>('GET', '/api/start'),

    analyzeQuery: (text) =>
      t.json<QueryAnalysis>('POST', '/api/query/analyze', { body: { text }, auth: false }),

    understandTopic: (text, options) =>
      t.json<TopicUnderstanding>('POST', '/api/query/topic', {
        body: { text, meaningId: options?.meaningId, correction: options?.correction },
        auth: false,
      }),

    startSearch: (request) => HttpSearchRun.fromTicket(t, '', ticket('/api/searches', request)),

    stopSearch: (searchId) => t.stop(searchId),

    retryPlatform: (searchId, platform) =>
      HttpSearchRun.fromTicket(
        t,
        searchId,
        ticket(`${searchPath(searchId)}/platforms/${encodeURIComponent(platform)}/retry`),
      ),

    getSelection: (searchId) => t.getSelection(searchId),

    // Проверка на ИИ: сервер нормализует текст той же функцией (src/lib/ai-normalize.ts),
    // кэширует по SHA-256 + модели и отвечает `AiCheck` (`too-short` и `unavailable` — не ошибки).
    checkAiText: (text) => t.json<AiCheck>('POST', '/api/ai-check', { body: { text } }),

    setExcluded: (searchId, itemIds, excluded) =>
      t.json<SelectionCounts>('POST', `${searchPath(searchId)}/exclusions`, {
        body: { itemIds, excluded },
      }),

    excludeSource: (searchId, sourceId) =>
      t.json<{ itemIds: string[]; counts: SelectionCounts }>(
        'POST',
        `${searchPath(searchId)}/exclusions/source`,
        { body: { sourceId } },
      ),

    addByUrl: (searchId, url) =>
      t.json<ResultItem>('POST', `${searchPath(searchId)}/items`, { body: { url } }),

    recheckLinks: (searchId) =>
      t.json<LinkRecheckReport>('POST', `${searchPath(searchId)}/links/recheck`),

    getSpread: (searchId, groupId) =>
      t.json<SpreadReport>('GET', `${searchPath(searchId)}/spread`, { query: { groupId } }),

    getExportPreview: (searchId, options) =>
      t.json<ExportPreview>('GET', `${searchPath(searchId)}/export/preview`, {
        query: exportQuery(options),
      }),

    getExportFile: async (searchId, options): Promise<ExportFile> => {
      const response = await t.request('GET', `${searchPath(searchId)}/export.xlsx`, {
        query: exportQuery(options),
        accept: XLSX_TYPE,
      });
      let file: Blob;
      try {
        file = await response.blob();
      } catch {
        t.markOffline();
        throw new MonitorApiError('offline', OFFLINE_MESSAGE);
      }
      // Число строк сервер отдаёт заголовком; старый сервер без него — берём из предпросмотра.
      const rowCount =
        rowCountFrom(response.headers.get('X-Export-Rows')) ??
        (
          await t.json<ExportPreview>('GET', `${searchPath(searchId)}/export/preview`, {
            query: exportQuery(options),
          })
        ).rowCount;
      return {
        fileName: fileNameFrom(response.headers.get('Content-Disposition')) ?? 'mediamonitor.xlsx',
        rowCount,
        file,
      };
    },

    listSources: () => t.json<Source[]>('GET', '/api/sources'),

    checkSource: (url) => t.json<SourceCheck>('POST', '/api/sources/check', { body: { url } }),

    addSource: (input) => t.json<Source>('POST', '/api/sources', { body: input }),

    updateSource: (id, patch) => t.json<Source>('PATCH', sourcePath(id), { body: patch }),

    removeSource: (id) => t.send('DELETE', sourcePath(id)),

    restoreSource: (id) => t.json<Source>('POST', `${sourcePath(id)}/restore`),

    recheckSources: () => t.json<SourcesRecheckReport>('POST', '/api/sources/recheck'),

    previewImport: (file) => {
      const form = new FormData();
      form.append('file', file, file.name);
      return t.json<ImportPreview>('POST', '/api/sources/import/preview', { form });
    },

    importSources: async (source) => {
      // Файл без предпросмотра: сначала разбор, потом ровно строки «добавим» этого разбора.
      let previewId: string;
      if (typeof source === 'string') {
        previewId = source;
      } else {
        const form = new FormData();
        form.append('file', source, source.name);
        previewId = (await t.json<ImportPreview>('POST', '/api/sources/import/preview', { form }))
          .previewId;
      }
      return t.json<ImportReport>('POST', `/api/sources/import/${encodeURIComponent(previewId)}`);
    },

    getCatalog: () => t.json<CatalogSource[]>('GET', '/api/catalog'),

    addFromCatalog: (ids) =>
      t.json<Source[]>('POST', '/api/sources/from-catalog', { body: { ids } }),

    getWorkspace: () => t.json<Workspace>('GET', '/api/workspace'),

    getWorkspaceLink: () => t.json<WorkspaceLink>('GET', '/api/workspace/link'),

    openWorkspace: (key) => t.openWorkspace(key),

    listRecent: () => t.json<RecentSearch[]>('GET', '/api/recent'),

    getStandStatus: () => t.json<StandStatus>('GET', '/api/stand', { auth: false }),

    getConnection: () => t.getConnection(),

    onConnectionChange: (listener) => t.onConnectionChange(listener),
  };
}
