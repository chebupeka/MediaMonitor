/**
 * Что экран «Поиск» помнит между открытиями: боковую панель закрыли и открыли, поиск
 * перенесли во вкладку, страницу перезагрузили. Без этого человек заново вводил бы запрос
 * и условия (Критерии: «переходы не требуют повторного ввода уже заданных условий»).
 *
 * Лежит в хранилище сеанса (lib/host.ts): в расширении — storage.session, общее для панели
 * и вкладки, на диск не пишется; на сайте — sessionStorage вкладки.
 */
import type { PeriodPreset, Relevance, SearchMode } from '@/api/types';
import { getHost } from '@/lib/host';

export interface SavedSearch {
  text: string;
  preset: PeriodPreset;
  mode: SearchMode;
  filter: Relevance | 'all';
  /** Законченный поиск, подборку которого показать снова; `null` — только черновик запроса. */
  searchId: string | null;
}

const KEY = 'mm:search';

const PRESETS: readonly PeriodPreset[] = ['today', '7d', '30d'];
const MODES: readonly SearchMode[] = ['everywhere', 'my-sources'];
const FILTERS: readonly (Relevance | 'all')[] = ['all', 'direct', 'indirect', 'disputed'];

function pick<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return allowed.find((a) => a === value) ?? fallback;
}

export async function loadSavedSearch(): Promise<SavedSearch | null> {
  const value = await getHost().session.get(KEY);
  if (typeof value !== 'object' || value === null) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.text !== 'string') return null;
  return {
    text: v.text,
    preset: pick(v.preset, PRESETS, '30d'),
    mode: pick(v.mode, MODES, 'everywhere'),
    filter: pick(v.filter, FILTERS, 'all'),
    searchId: typeof v.searchId === 'string' ? v.searchId : null,
  };
}

export function saveSearch(saved: SavedSearch): Promise<void> {
  return getHost().session.set(KEY, saved);
}
