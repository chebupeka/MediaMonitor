import type { SearchEvent, SearchRun } from '../types';

const TERMINAL: ReadonlySet<SearchEvent['type']> = new Set(['finished', 'stopped', 'failed']);

/**
 * Поток событий хода поиска. Хранит историю: поздний подписчик сначала получает
 * всё, что уже случилось, потом новые события. Реализует и AsyncIterable, и подписку.
 */
export class FakeSearchRun implements SearchRun {
  readonly searchId: string;
  private readonly history: SearchEvent[] = [];
  private readonly listeners = new Set<(event: SearchEvent) => void>();
  private waiters: (() => void)[] = [];
  private isClosed = false;
  private stopHandler: (() => void) | null = null;

  constructor(searchId: string) {
    this.searchId = searchId;
  }

  get closed(): boolean {
    return this.isClosed;
  }

  /** Для имитации: что делать при «Остановить». */
  onStop(handler: () => void): void {
    this.stopHandler = handler;
  }

  /** Для имитации: отправить событие. */
  emit(event: SearchEvent): void {
    if (this.isClosed) return;
    this.history.push(event);
    if (TERMINAL.has(event.type)) this.isClosed = true;
    this.listeners.forEach((listener) => listener(event));
    const waiters = this.waiters;
    this.waiters = [];
    waiters.forEach((wake) => wake());
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
    this.stopHandler?.();
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
}
