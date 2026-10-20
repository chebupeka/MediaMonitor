/**
 * Передача выделенного текста из фона расширения в интерфейс.
 *
 * Фон кладёт текст в storage.session (живёт до закрытия браузера, на диск не пишется),
 * панель при загрузке забирает его и удаляет. Если панель уже открыта, она узнаёт
 * о новом тексте из storage.onChanged.
 */
import { browser } from 'wxt/browser';

/** Что сделать с выделением: найти, где опубликовано, или проверить текст на ИИ. */
export type SelectionAction = 'find' | 'ai-check';

export interface PendingSelection {
  /** Выделенный текст, обрезанный до MAX_TEXT_LENGTH */
  text: string;
  /** Пункт меню; нет — «Найти, где это опубликовано» (так было до проверки на ИИ) */
  action?: SelectionAction;
  /** Страница, на которой выделили текст, — пригодится, чтобы показать исходник */
  pageUrl?: string;
  pageTitle?: string;
  /** Когда выделили, мс с 1970 года */
  at: number;
}

const KEY = 'mm:pendingSelection';

/** Старое выделение не запускает поиск: панель могли открыть значком через час. */
const TTL_MS = 60_000;

/** Ограничение длины запроса на открытом стенде (05-scenarios.md, НТ-6). */
export const MAX_TEXT_LENGTH = 20_000;

/** Хранилище сессии; его нет, если страницу открыли не как страницу расширения. */
function sessionArea() {
  try {
    return browser?.storage?.session ?? null;
  } catch {
    return null;
  }
}

function isPendingSelection(value: unknown): value is PendingSelection {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.text === 'string' &&
    typeof v.at === 'number' &&
    (v.action === undefined || v.action === 'find' || v.action === 'ai-check')
  );
}

export async function putPendingSelection(selection: PendingSelection): Promise<void> {
  const area = sessionArea();
  if (!area) return;
  await area.set({ [KEY]: { ...selection, text: selection.text.slice(0, MAX_TEXT_LENGTH) } });
}

/** Забрать выделение, если оно свежее. После вызова его в хранилище нет. */
export async function takePendingSelection(): Promise<PendingSelection | null> {
  const area = sessionArea();
  if (!area) return null;
  const stored = await area.get(KEY);
  await area.remove(KEY);
  const value = stored[KEY];
  if (!isPendingSelection(value) || Date.now() - value.at > TTL_MS) return null;
  return value;
}

/** Сообщить, когда фон положил новое выделение. Возвращает отписку. */
export function onPendingSelection(callback: () => void): () => void {
  const storage = sessionArea() ? browser.storage : null;
  if (!storage) return () => undefined;
  const listener = (changes: Record<string, { newValue?: unknown }>, areaName: string) => {
    if (areaName === 'session' && isPendingSelection(changes[KEY]?.newValue)) callback();
  };
  storage.onChanged.addListener(listener);
  return () => storage.onChanged.removeListener(listener);
}
