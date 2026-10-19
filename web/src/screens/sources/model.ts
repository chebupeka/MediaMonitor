/**
 * Подписи и вспомогательные функции экрана «Источники» (П5, П9, П13).
 * Общие подписи (площадки, типы) — из @/lib/labels; здесь только то, что нужно этому экрану.
 */
import type { PlatformId, Source, SourceCheck, SourceType } from '@/api/types';
import type { StatusIcon, StatusTone } from '@/lib/labels';
import { formatCompact, plural } from '@/lib/format';

/** Порядок типов в фильтрах и переключателях. */
export const SOURCE_TYPE_ORDER: readonly SourceType[] = [
  'media',
  'authority',
  'municipal',
  'institution',
  'community',
  'blogger',
];

export const ORIGIN_LABEL: Record<Source['origin'], string> = {
  manual: 'добавлен вручную',
  catalog: 'из каталога',
  import: 'из Excel',
};

export interface CheckView {
  tone: StatusTone;
  icon: StatusIcon;
  /** Короткий статус: «доступен», «закрыт — искать нельзя» */
  text: string;
}

/** Результат проверки источника: значок + текст, не только цвет. */
export function checkView(check: Pick<SourceCheck, 'state'>): CheckView {
  switch (check.state) {
    case 'ok':
      return { tone: 'good', icon: 'check', text: 'доступен' };
    case 'closed':
      return { tone: 'critical', icon: 'lock', text: 'закрыт — искать нельзя' };
    case 'not-found':
      return { tone: 'critical', icon: 'error', text: 'не найден' };
    case 'not-regional':
      return { tone: 'info', icon: 'info', text: 'пишет не только о крае' };
    case 'duplicate':
      return { tone: 'info', icon: 'info', text: 'уже в списке' };
    case 'not-supported':
      return { tone: 'warning', icon: 'warning', text: 'не группа VK, OK или MAX' };
    case 'post-link':
      return { tone: 'warning', icon: 'warning', text: 'ссылка на пост, а не на группу' };
  }
}

/** Заголовок ответа проверки в окне «Добавить по ссылке». */
export const VERDICT_TITLE: Record<SourceCheck['state'], string> = {
  ok: 'Доступен — можно искать',
  'not-regional': 'Доступен, но пишет не только о крае',
  closed: 'Закрытая группа — искать в ней нельзя',
  'not-found': 'По ссылке ничего нет',
  'not-supported': 'Это не группа VK, OK или MAX',
  duplicate: 'Уже есть в вашем списке',
  'post-link': 'Это ссылка на пост, а не на группу',
};

/** Источник, по которому поиск сейчас невозможен. */
export function hasProblem(source: Pick<Source, 'check'>): boolean {
  return source.check.state === 'closed' || source.check.state === 'not-found';
}

/** «vk.com/demo_tv_kraya» — адрес без протокола и www, для показа. */
export function shortUrl(url: string): string {
  return url
    .trim()
    .replace(/^https?:\/\//u, '')
    .replace(/^www\./u, '')
    .replace(/\/+$/u, '');
}

/** Похоже ли на адрес — чтобы не проверять «на лету» каждую букву. */
export function looksLikeUrl(value: string): boolean {
  const v = value.trim();
  return v.length >= 6 && /[./]/u.test(v) && !/\s/u.test(v);
}

const SUBSCRIBER_WORDS = ['подписчик', 'подписчика', 'подписчиков'] as const;

/** «41,2 тыс. подписчиков», «подписчиков: нет данных» */
export function subscribersText(value: number | null): string {
  if (value === null) return 'подписчиков: нет данных';
  const word = value >= 10_000 ? 'подписчиков' : plural(value, SUBSCRIBER_WORDS);
  return `${formatCompact(value)} ${word}`;
}

/** Города и районы края для подсказки в поле «Город или район» (только настоящие). */
const KNOWN_DISTRICTS: readonly string[] = [
  'весь край',
  'Красноярск',
  'Норильск',
  'Ачинск',
  'Канск',
  'Минусинск',
  'Лесосибирск',
  'Железногорск',
  'Зеленогорск',
  'Шарыпово',
  'Дивногорск',
  'Енисейск',
  'Таймырский район',
  'Енисейский район',
  'Богучанский район',
  'Канский район',
  'Эвенкийский район',
];

export function districtOptions(sources: readonly { district: string | null }[]): string[] {
  const set = new Set<string>(KNOWN_DISTRICTS);
  for (const s of sources) if (s.district) set.add(s.district);
  return [...set];
}

export type PlatformFilter = 'all' | PlatformId;
export type TypeFilter = 'all' | SourceType;
export type SortKey = 'name' | 'subscribers' | 'added';

export const SORTS: { value: SortKey; label: string }[] = [
  { value: 'name', label: 'По названию' },
  { value: 'subscribers', label: 'По подписчикам' },
  { value: 'added', label: 'Новые' },
];

export function sortSources(list: readonly Source[], key: SortKey): Source[] {
  const copy = [...list];
  switch (key) {
    case 'name':
      return copy.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    case 'subscribers':
      return copy.sort((a, b) => (b.subscribers ?? -1) - (a.subscribers ?? -1));
    case 'added':
      return copy.sort((a, b) => Date.parse(b.addedAt) - Date.parse(a.addedAt));
  }
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/ё/gu, 'е').trim();
}

/** Поиск по списку: название, район, адрес, тип, описание. Без учёта регистра и «ё». */
export function matchesQuery(
  source: { name: string; district: string | null; url: string; description?: string },
  query: string,
  typeLabel: string,
): boolean {
  const q = normalize(query);
  if (!q) return true;
  const hay = normalize(
    [
      source.name,
      source.district ?? '',
      shortUrl(source.url),
      typeLabel,
      source.description ?? '',
    ].join(' '),
  );
  return q.split(/\s+/u).every((word) => hay.includes(word));
}
