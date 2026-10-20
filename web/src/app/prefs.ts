/**
 * Настройки вида — как на сайте «Медиарадар» (site/prefs.js): тема (тёмная или светлая
 * «чернила на бумаге»), «Тёплый свет» (только в светлой) и версия для слабовидящих.
 *
 * Состояние — атрибуты на <html>: data-theme, data-warm, data-lowvision (значения — в
 * tokens.css). Выбор хранится в браузере под теми же ключами, что у сайта (mr-theme, mr-warm,
 * mr-lowvision). При первом запуске тема — как в системе, и пока человек сам не выбрал, она
 * следует за системой. Атрибуты ставятся до первой отрисовки (`applyPrefs(readPrefs())` в
 * main.tsx и extension/lib/boot.tsx), иначе страница мигнула бы чужой темой.
 * Смена — плавным перетеканием за 0,35 с (View Transitions, base.css).
 */
import { urlFlag, urlTheme } from './url-hints';

export type Theme = 'light' | 'dark';

export interface Prefs {
  theme: Theme;
  /** «Тёплый свет»: действует только в светлой теме, но выбор помнится */
  warm: boolean;
  lowVision: boolean;
  /** Тему выбрал человек (иначе — как в системе) */
  chosen: boolean;
}

const KEY_THEME = 'mr-theme';
const KEY_WARM = 'mr-warm';
const KEY_LOWVISION = 'mr-lowvision';

function load(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // хранилище недоступно — выбор живёт до перезагрузки
  }
}

export function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** Сохранённый выбор (и подсказки из адреса — только для скриншотов). */
export function readPrefs(): Prefs {
  const stored = load(KEY_THEME);
  const hint = urlTheme();
  const theme: Theme =
    hint === 'light' || hint === 'dark'
      ? hint
      : stored === 'light' || stored === 'dark'
        ? stored
        : systemTheme();
  return {
    theme,
    warm: urlFlag('warm') ?? load(KEY_WARM) === '1',
    lowVision: urlFlag('lowvision') ?? load(KEY_LOWVISION) === '1',
    chosen: stored === 'light' || stored === 'dark',
  };
}

/** Запомнить выбор человека. */
export function savePrefs(next: Prefs, prev: Prefs): void {
  if (next.theme !== prev.theme || next.chosen !== prev.chosen)
    save(KEY_THEME, next.chosen ? next.theme : null);
  if (next.warm !== prev.warm) save(KEY_WARM, next.warm ? '1' : null);
  if (next.lowVision !== prev.lowVision) save(KEY_LOWVISION, next.lowVision ? '1' : null);
}

/** Атрибуты режима на <html>. */
export function applyPrefs(p: Prefs): void {
  const root = document.documentElement;
  root.dataset.theme = p.theme;
  root.toggleAttribute('data-warm', p.warm);
  root.toggleAttribute('data-lowvision', p.lowVision);
}

/** Имя текущего вида — для холстов: при смене перечитать цвета из токенов. */
export function prefsKey(p: Prefs): string {
  return `${p.theme}${p.theme === 'light' && p.warm ? '-warm' : ''}${p.lowVision ? '-lowvision' : ''}`;
}

/**
 * Сменить вид плавно: браузер снимает страницу как была и растворяет снимок поверх новой
 * за 0,35 с. Без View Transitions или при «уменьшить движение» — сразу.
 */
export function withTransition(update: () => void): void {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (reduced || typeof doc.startViewTransition !== 'function') {
    update();
    return;
  }
  doc.startViewTransition(update);
}
