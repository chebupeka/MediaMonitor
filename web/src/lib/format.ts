/**
 * Форматирование дат, чисел и счётчиков. Все даты — по красноярскому времени
 * (UTC+7) с подписью (НТ-12). Не форматируйте даты в экранах сами — только отсюда.
 */
import type { IsoDate, IsoDateTime, Period, Publication } from '@/api/types';

export const TIME_ZONE = 'Asia/Krasnoyarsk';
/** Подпись часового пояса: в шапке, в строке состояния, в XLSX. */
export const TIME_ZONE_LABEL = 'время красноярское';
export const TIME_ZONE_LABEL_FULL = 'время красноярское, UTC+7';

const MONTHS_SHORT = [
  'янв',
  'фев',
  'мар',
  'апр',
  'мая',
  'июн',
  'июл',
  'авг',
  'сен',
  'окт',
  'ноя',
  'дек',
];
const MONTHS_LONG = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря',
];

/** Год, который считаем текущим: его в датах не пишем. */
const CURRENT_YEAR = 2026;

interface KrskParts {
  year: number;
  month: number; // 0–11
  day: number;
  hour: number;
  minute: number;
}

const partsFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** Разобрать момент на части по красноярскому времени. */
export function krskParts(iso: IsoDateTime): KrskParts {
  const parts = partsFormatter.formatToParts(new Date(iso));
  const get = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((p) => p.type === type)?.value ?? 0);
  return {
    year: get('year'),
    month: get('month') - 1,
    day: get('day'),
    hour: get('hour') % 24,
    minute: get('minute'),
  };
}

const pad = (n: number): string => String(n).padStart(2, '0');

/** «10:02» */
export function formatTime(iso: IsoDateTime): string {
  const p = krskParts(iso);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

/** «14 окт» (с годом, если он не текущий: «14 окт 2025») */
export function formatDate(iso: IsoDateTime): string {
  const p = krskParts(iso);
  const base = `${p.day} ${MONTHS_SHORT[p.month] ?? ''}`;
  return p.year === CURRENT_YEAR ? base : `${base} ${p.year}`;
}

/** «14 октября 2026» */
export function formatDateLong(iso: IsoDateTime): string {
  const p = krskParts(iso);
  return `${p.day} ${MONTHS_LONG[p.month] ?? ''} ${p.year}`;
}

/** «14 окт, 10:02» */
export function formatDateTime(iso: IsoDateTime): string {
  return `${formatDate(iso)}, ${formatTime(iso)}`;
}

/** Дата публикации для карточки: «14 окт, 10:02», «≈ 14 окт, 11:05» или «дата неизвестна». */
export function formatPublishedAt(
  publication: Pick<Publication, 'publishedAt' | 'timeReliability'>,
): string {
  if (!publication.publishedAt) return 'дата неизвестна';
  const value = formatDateTime(publication.publishedAt);
  return publication.timeReliability === 'approximate' ? `≈ ${value}` : value;
}

/** Календарная дата `YYYY-MM-DD` → части. */
function dateParts(date: IsoDate): { year: number; month: number; day: number } {
  const [y = '0', m = '1', d = '1'] = date.split('-');
  return { year: Number(y), month: Number(m) - 1, day: Number(d) };
}

/** «19 окт» для календарной даты. */
export function formatIsoDate(date: IsoDate): string {
  const p = dateParts(date);
  const base = `${p.day} ${MONTHS_SHORT[p.month] ?? ''}`;
  return p.year === CURRENT_YEAR ? base : `${base} ${p.year}`;
}

/** Период: «1–19 окт», «20 сен – 19 окт», «19 окт». */
export function formatPeriod(period: Pick<Period, 'from' | 'to'>): string {
  const a = dateParts(period.from);
  const b = dateParts(period.to);
  if (period.from === period.to) return formatIsoDate(period.from);
  if (a.year === b.year && a.month === b.month) {
    const tail = `${MONTHS_SHORT[b.month] ?? ''}${b.year === CURRENT_YEAR ? '' : ` ${b.year}`}`;
    return `${a.day}–${b.day} ${tail}`;
  }
  return `${formatIsoDate(period.from)} – ${formatIsoDate(period.to)}`;
}

const numberFormatter = new Intl.NumberFormat('ru-RU');

/** «1 100» (разделитель — неразрывный пробел) */
export function formatNumber(value: number): string {
  return numberFormatter.format(value);
}

const oneDecimal = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
const twoDecimals = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });

/** Компактно: «950», «84,3 тыс.», «1,04 млн». `null` → «нет данных». */
export function formatCompact(value: number | null): string {
  if (value === null) return 'нет данных';
  if (value >= 1_000_000) return `${twoDecimals.format(value / 1_000_000)} млн`;
  if (value >= 10_000) return `${oneDecimal.format(value / 1_000)} тыс.`;
  return formatNumber(value);
}

/** Доля: 0.72 → «72%» */
export function formatShare(share: number): string {
  return `${Math.round(share * 100)}%`;
}

/**
 * Русское множественное число.
 * `plural(5, ['публикация', 'публикации', 'публикаций'])` → «публикаций».
 */
export function plural(n: number, forms: readonly [string, string, string]): string {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return forms[2];
  if (last > 1 && last < 5) return forms[1];
  if (last === 1) return forms[0];
  return forms[2];
}

/** «15 размещений» */
export function formatCount(n: number, forms: readonly [string, string, string]): string {
  return `${formatNumber(n)} ${plural(n, forms)}`;
}

/** Готовые формы для частых слов. */
export const WORDS = {
  publication: ['публикация', 'публикации', 'публикаций'],
  placement: ['размещение', 'размещения', 'размещений'],
  record: ['запись', 'записи', 'записей'],
  source: ['источник', 'источника', 'источников'],
  group: ['группа', 'группы', 'групп'],
  search: ['поиск', 'поиска', 'поисков'],
  second: ['секунда', 'секунды', 'секунд'],
  newItem: ['новая', 'новых', 'новых'],
} as const satisfies Record<string, readonly [string, string, string]>;

/** Обрезать строку по слову: «Безопасность дорожного…» */
export function truncateText(value: string, max: number): string {
  if (value.length <= max) return value;
  const cut = value.slice(0, max);
  const space = cut.lastIndexOf(' ');
  return `${cut.slice(0, space > max * 0.6 ? space : max).replace(/[,.;:—\s-]+$/u, '')}…`;
}
