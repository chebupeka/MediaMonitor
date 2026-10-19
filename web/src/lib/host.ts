/**
 * Возможности страницы, на которой запущен интерфейс.
 *
 * Сайт-мокап и расширение запускают один и тот же App, но расширение умеет больше:
 * у него хранилище сеанса, общее для боковой панели и вкладки, и оно может открыть
 * интерфейс во вкладке. Расширение подставляет свои возможности до загрузки App
 * (extension/lib/boot.tsx); на сайте остаются значения по умолчанию.
 */

/** Хранилище на время сеанса браузера. Значения — простые данные, как в JSON. */
export interface SessionStore {
  /** Значение по ключу; `undefined`, если его нет. Что внутри — проверяет вызывающий. */
  get(key: string): Promise<unknown>;
  /** Сбой записи (переполнено, запрещено) не мешает работе: просто не запомним. */
  set(key: string, value: unknown): Promise<void>;
}

export interface Host {
  session: SessionStore;
  /** Открыть интерфейс во вкладке с текущим поиском. Есть только в боковой панели расширения. */
  openInTab: (() => Promise<void>) | null;
}

/** На сайте — sessionStorage вкладки: поиск переживает перезагрузку страницы. */
const webSession: SessionStore = {
  get(key) {
    try {
      const raw = window.sessionStorage.getItem(key);
      return Promise.resolve(raw === null ? undefined : (JSON.parse(raw) as unknown));
    } catch {
      return Promise.resolve(undefined);
    }
  },
  set(key, value) {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      // нет места или хранилище запрещено — работаем без сохранения
    }
    return Promise.resolve();
  },
};

let current: Host = { session: webSession, openInTab: null };

export function getHost(): Host {
  return current;
}

export function setHost(next: Partial<Host>): void {
  current = { ...current, ...next };
}
