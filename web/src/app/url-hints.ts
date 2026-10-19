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

/** Запрос для экрана «Поиск», который сразу запускается: `?screen=search&q=…` */
export function urlQuery(): string | null {
  return params().get('q');
}
