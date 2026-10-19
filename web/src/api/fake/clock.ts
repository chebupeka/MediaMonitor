/**
 * Часы мокапа. Демо-данные привязаны к «сегодня» = 19 октября 2026, 14:32
 * по красноярскому времени (UTC+7). Часы идут от этого момента с реальной скоростью,
 * чтобы «получено в 14:32» и время поиска выглядели живыми и не расходились с данными.
 */

const OFFSET_HOURS = 7;
const OFFSET_MS = OFFSET_HOURS * 3600_000;

export const DEMO_START_ISO = '2026-10-19T14:32:00+07:00';
const DEMO_START_MS = Date.parse(DEMO_START_ISO);
const LOADED_AT = Date.now();

/** Текущий момент по часам мокапа. */
export function demoNowMs(): number {
  return DEMO_START_MS + (Date.now() - LOADED_AT);
}

const pad = (n: number): string => String(n).padStart(2, '0');

/** Момент → ISO со смещением +07:00. */
export function toKrskIso(ms: number): string {
  const d = new Date(ms + OFFSET_MS);
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
    `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}+07:00`
  );
}

/** Сейчас по часам мокапа, ISO. */
export function nowIso(): string {
  return toKrskIso(demoNowMs());
}

/** Момент → дата `YYYY-MM-DD` по красноярскому времени. */
export function krskDate(ms: number): string {
  return toKrskIso(ms).slice(0, 10);
}

/** Удобная запись для данных: `at('2026-10-14 10:02')` → `2026-10-14T10:02:00+07:00`. */
export function at(local: string): string {
  const [date, time = '00:00'] = local.split(' ');
  return `${date}T${time}:00+07:00`;
}

/** Сдвиг даты `YYYY-MM-DD` на n дней. */
export function addDays(date: string, days: number): string {
  const ms = Date.parse(`${date}T12:00:00+07:00`) + days * 86400_000;
  return krskDate(ms);
}

/** Начало и конец календарного дня по Красноярску, мс. */
export function dayStartMs(date: string): number {
  return Date.parse(`${date}T00:00:00+07:00`);
}
export function dayEndMs(date: string): number {
  return Date.parse(`${date}T23:59:59+07:00`);
}
