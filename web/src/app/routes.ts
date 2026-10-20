/**
 * Адреса разделов веб-версии (решение Р-В4): `/app/<раздел>` через History API.
 * «Назад» и «Вперёд» браузера ходят по разделам, F5 оставляет на том же экране, на раздел
 * можно дать ссылку или поставить закладку. У «Распространения» — `?search=<id>&group=<id>`:
 * иначе после F5 экран пуст. Остальные параметры переходов (текст запроса, «сразу искать»)
 * в адрес не попадают — чужая ссылка не должна запускать поиск и тратить квоту (Р-В6).
 *
 * Только веб-версия. Мокап (в том числе одним файлом) и расширение работают без адресов —
 * навигация в памяти (src/app/navigation.tsx): там страница открыта как файл или изнутри
 * расширения, и путь в адресе менять нельзя.
 */
import { IS_WEB_BUILD } from '@/lib/build';
import type { ScreenId, ScreenParamsMap } from './navigation';

/** Синхронизировать экран с адресом (только веб-версия на сервере). */
export const URL_ROUTING = IS_WEB_BUILD;

/** Разделы веб-версии и их пути от `/app/`. «Поиск» — сам `/app/`. */
const PATHS: readonly (readonly [ScreenId, string])[] = [
  ['search', ''],
  ['spread', 'spread'],
  ['ai-check', 'ai-check'],
  ['sources', 'sources'],
  ['recent', 'recent'],
  ['how', 'how'],
  ['status', 'status'],
];

export interface Route {
  screen: ScreenId;
  params: ScreenParamsMap[ScreenId];
}

/** Корень приложения в адресе: `/app/` у веб-версии. */
function basePath(): string {
  const base = import.meta.env.BASE_URL || '/';
  return base.endsWith('/') ? base : `${base}/`;
}

/** Экран и его параметры по адресу. Неизвестный путь — экран «Такого раздела нет». */
export function routeFromLocation(
  location: { pathname: string; search: string } = window.location,
): Route {
  const base = basePath();
  let path = location.pathname;
  try {
    path = decodeURI(path);
  } catch {
    // адрес как есть
  }
  let rest: string | null = null;
  if (path.startsWith(base)) rest = path.slice(base.length);
  else if (`${path}/` === base) rest = '';
  // `/app/index.html` — тот же «Поиск»
  const name = (rest ?? '').replace(/\/+$/u, '').replace(/^index\.html$/u, '');
  const found = rest === null ? undefined : PATHS.find(([, p]) => p === name);
  if (!found) return { screen: 'not-found', params: {} };
  const [screen] = found;
  if (screen === 'spread') {
    const query = new URLSearchParams(location.search);
    const searchId = query.get('search');
    const groupId = query.get('group');
    return {
      screen,
      params: { ...(searchId ? { searchId } : {}), ...(groupId ? { groupId } : {}) },
    };
  }
  return { screen, params: {} };
}

/** Адрес экрана; у экранов без своего адреса (мокап) — корень приложения. */
export function urlFor(screen: ScreenId, params: ScreenParamsMap[ScreenId]): string {
  const path = PATHS.find(([id]) => id === screen)?.[1] ?? '';
  let url = `${basePath()}${path}`;
  if (screen === 'spread') {
    const p = params as ScreenParamsMap['spread'];
    const query = new URLSearchParams();
    if (p.searchId) query.set('search', p.searchId);
    if (p.groupId) query.set('group', p.groupId);
    const text = query.toString();
    if (text) url += `?${text}`;
  }
  return url;
}

/** Есть ли у экрана свой адрес в веб-версии (мокапные экраны — нет). */
export function hasRoute(screen: ScreenId): boolean {
  return PATHS.some(([id]) => id === screen);
}
