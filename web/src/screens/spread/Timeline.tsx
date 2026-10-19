/**
 * «Как расходилась новость»: дорожка на площадку, точка на размещение (П6, Р10).
 * По горизонтали — время по Красноярску от первой публикации до последней; деления —
 * полночь каждого дня. Исходный пост обведён, приблизительное время (MAX) — пунктиром.
 * Каждая точка — ссылка на пост; те же данные есть в таблице ниже.
 */
import type { PlatformId, SpreadPlacement, WavePoint } from '@/api/types';
import { cx } from '@/components';
import { WORDS, formatCount, formatDate, formatPublishedAt, formatTime } from '@/lib/format';
import { PLATFORMS, PLATFORM_ORDER, PLACEMENT_TYPE_LABEL } from '@/lib/labels';
import styles from './spread.module.css';

const DAY_MS = 86_400_000;
/** Красноярск — UTC+7 круглый год */
const KRSK_OFFSET_MS = 7 * 3_600_000;

interface TimelineProps {
  placements: readonly SpreadPlacement[];
  hourly: readonly WavePoint[];
}

export function Timeline({ placements, hourly }: TimelineProps) {
  const dated = placements.filter((p) => p.publishedAt !== null);
  const undated = placements.length - dated.length;
  const times = dated.map((p) => Date.parse(p.publishedAt ?? ''));
  const min = Math.min(...times);
  const max = Math.max(...times);
  const span = Math.max(max - min, 1);
  const x = (t: number) => (max === min ? 50 : ((t - min) / span) * 100);

  // Деления — полночь по Красноярску внутри промежутка
  const ticks: { at: number; label: string }[] = [];
  if (dated.length > 0) {
    const firstMidnight = Math.ceil((min + KRSK_OFFSET_MS) / DAY_MS) * DAY_MS - KRSK_OFFSET_MS;
    for (let t = firstMidnight; t <= max; t += DAY_MS)
      ticks.push({ at: x(t), label: formatDate(new Date(t).toISOString()) });
  }

  const peak = hourly.reduce<WavePoint | null>(
    (best, p) => (best === null || p.count > best.count ? p : best),
    null,
  );

  return (
    <div className={styles.timeline}>
      <div
        className={styles.lanes}
        role="img"
        aria-label={`Размещения по времени: ${PLATFORM_ORDER.map(
          (id) => `${PLATFORMS[id].name} ${placements.filter((p) => p.platform === id).length}`,
        ).join(', ')}. Подробности — в таблице ниже.`}
      >
        {PLATFORM_ORDER.map((platform: PlatformId) => (
          <div key={platform} className={styles.lane}>
            <span className={styles.laneName}>
              <span
                className={styles.laneDot}
                style={{ background: PLATFORMS[platform].colorVar }}
                aria-hidden="true"
              />
              {PLATFORMS[platform].short}
            </span>
            <div className={styles.track}>
              {ticks.map((tick) => (
                <span key={tick.at} className={styles.tickLine} style={{ left: `${tick.at}%` }} />
              ))}
              {dated
                .filter((p) => p.platform === platform)
                .map((p) => (
                  <a
                    key={p.itemId}
                    href={p.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    tabIndex={-1}
                    className={cx(
                      styles.point,
                      p.isOriginal && styles.pointOriginal,
                      p.timeReliability === 'approximate' && styles.pointApprox,
                    )}
                    style={{
                      left: `${x(Date.parse(p.publishedAt ?? ''))}%`,
                      background: PLATFORMS[platform].colorVar,
                    }}
                    title={`${p.sourceName} · ${formatPublishedAt(p)} · ${
                      p.isOriginal ? 'исходный' : PLACEMENT_TYPE_LABEL[p.placementType]
                    }`}
                  />
                ))}
            </div>
          </div>
        ))}
        <div className={styles.axis} aria-hidden="true">
          {ticks.map((tick) => (
            <span key={tick.at} className={styles.tick} style={{ left: `${tick.at}%` }}>
              {tick.label}
            </span>
          ))}
        </div>
      </div>
      <p className={styles.note}>
        {peak && peak.count > 1
          ? `Чаще всего перепечатывали ${formatDate(peak.start)} с ${formatTime(peak.start)} — ${formatCount(peak.count, WORDS.placement)} за час. `
          : ''}
        Обведена исходная публикация, пунктиром — время приблизительное.
        {undated > 0 ? ` Без даты: ${formatCount(undated, WORDS.placement)}, на шкале их нет.` : ''}
      </p>
    </div>
  );
}
