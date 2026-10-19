/**
 * Период для «Повторить» (П12, SC-20): готовый период («7 дней», «30 дней») пересчитываем
 * от сегодняшнего дня — так повтор ищет и то, что вышло после прошлого поиска.
 * Свой период из календаря оставляем как был.
 */
import type { IsoDate, Period } from '@/api/types';

function shift(date: IsoDate, days: number): IsoDate {
  const [y = 1970, m = 1, d = 1] = date.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d) + days * 86_400_000);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

/** Новый период для повтора. `today` — сегодняшняя дата по Красноярску. */
export function repeatPeriod(period: Period, today: IsoDate): Period {
  switch (period.preset) {
    case 'today':
      return { preset: 'today', from: today, to: today };
    case '24h':
      return { preset: '24h', from: shift(today, -1), to: today };
    case '7d':
      return { preset: '7d', from: shift(today, -6), to: today };
    case '30d':
      return { preset: '30d', from: shift(today, -29), to: today };
    case 'custom':
      return period;
  }
}

/** Сколько календарных дней между датами (b − a). */
export function daysBetween(a: IsoDate, b: IsoDate): number {
  const ms = (d: IsoDate): number => {
    const [y = 1970, m = 1, day = 1] = d.split('-').map(Number);
    return Date.UTC(y, m - 1, day);
  };
  return Math.round((ms(b) - ms(a)) / 86_400_000);
}
