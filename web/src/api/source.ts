/**
 * Откуда интерфейс берёт данные: имитация мокапа или настоящий сервер.
 *
 * Порядок выбора:
 * 1. выбор в панели «Демо-сценарий» → «Данные» (хранится в браузере);
 * 2. адрес сервера из сборки `VITE_API_URL` → сервер;
 * 3. иначе — имитация.
 *
 * Смена источника перезагружает страницу: экраны, подборки и потоки поиска начинают
 * с чистого листа, а не смешивают данные имитации и сервера.
 */

export type DataSource = { kind: 'fake' } | { kind: 'server'; url: string };

const STORAGE_KEY = 'mm-data-source';

/** Адрес сервера по умолчанию для поля в панели (так запускается server/ без Docker). */
export const LOCAL_API_URL = 'http://127.0.0.1:8000';

/** Привести адрес к виду `http(s)://хост[:порт][/путь]` без завершающей косой черты. */
export function normalizeApiUrl(raw: string | null | undefined): string | null {
  const value = (raw ?? '').trim();
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    if (url.search || url.hash || url.username || url.password) return null;
    return `${url.origin}${url.pathname}`.replace(/\/+$/u, '');
  } catch {
    return null;
  }
}

/** Адрес сервера, заданный при сборке (`VITE_API_URL`); `null` — не задан. */
export const BUILD_API_URL = normalizeApiUrl(import.meta.env.VITE_API_URL);

/**
 * Интерфейс открыт в расширении. Там политика безопасности (CSP) и host_permissions
 * пускают только к адресу из сборки, поэтому другой адрес в панели не выбрать.
 */
export const IN_EXTENSION =
  typeof location !== 'undefined' && /^(chrome|moz)-extension:$/u.test(location.protocol);

function readStored(): DataSource | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { kind?: unknown; url?: unknown };
    if (parsed.kind === 'fake') return { kind: 'fake' };
    if (parsed.kind === 'server' && typeof parsed.url === 'string') {
      const url = normalizeApiUrl(parsed.url);
      return url ? { kind: 'server', url } : null;
    }
    return null;
  } catch {
    return null;
  }
}

/** Источник данных для этой загрузки страницы. */
export function resolveDataSource(): DataSource {
  const stored = readStored();
  if (stored?.kind === 'fake') return stored;
  if (stored?.kind === 'server' && !IN_EXTENSION) return stored;
  return BUILD_API_URL ? { kind: 'server', url: BUILD_API_URL } : { kind: 'fake' };
}

/** Адрес, который панель предлагает для сервера: из сборки, прежний выбор или локальный. */
export function suggestedApiUrl(): string {
  const stored = readStored();
  if (IN_EXTENSION) return BUILD_API_URL ?? '';
  return (stored?.kind === 'server' ? stored.url : null) ?? BUILD_API_URL ?? LOCAL_API_URL;
}

/** Выбрать источник данных и перезагрузить страницу. */
export function chooseDataSource(next: DataSource): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // хранилище недоступно — выбор действует до перезагрузки только через VITE_API_URL
  }
  window.location.reload();
}
