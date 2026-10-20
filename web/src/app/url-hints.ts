/**
 * Необязательные подсказки начального состояния из адреса — ТОЛЬКО для
 * скриншотов и ручной проверки: `index.html?screen=search&layout=panel&theme=dark`.
 * Навигация от адреса не зависит: без параметров всё работает так же.
 */
import type { ScreenId } from './navigation';

const SCREEN_IDS: readonly ScreenId[] = [
  'landing',
  'search',
  'spread',
  'ai-check',
  'sources',
  'recent',
  'how',
  'status',
  'demo-page',
  'gallery',
];

function params(): URLSearchParams {
  try {
    return new URLSearchParams(window.location.search);
  } catch {
    return new URLSearchParams();
  }
}

export function urlScreen(): ScreenId | null {
  const value = params().get('screen');
  return SCREEN_IDS.find((id) => id === value) ?? null;
}

export function urlTheme(): 'light' | 'dark' | 'system' | null {
  const value = params().get('theme');
  return value === 'light' || value === 'dark' || value === 'system' ? value : null;
}

export function urlLayout(): 'site' | 'panel' | null {
  const value = params().get('layout');
  return value === 'site' || value === 'panel' ? value : null;
}

/**
 * Текст, с которым экран сразу запускается: «Поиск» — `?screen=search&q=…`,
 * «Проверка на ИИ» — `?screen=ai-check&q=…` (так приходит выделение из расширения).
 */
export function urlQuery(): string | null {
  return params().get('q');
}

/**
 * Флаг вида из адреса — только для скриншотов: `&warm=1`, `&lowvision=1` (или `=0`).
 * Не задан — `null`.
 */
export function urlFlag(name: 'warm' | 'lowvision'): boolean | null {
  const value = params().get(name);
  if (value === '1' || value === 'true') return true;
  if (value === '0' || value === 'false') return false;
  return null;
}
