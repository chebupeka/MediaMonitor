import { RotateCw, TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';
import type { PlatformId, PlatformStatus, SearchConditions } from '@/api/types';
import {
  TIME_ZONE_LABEL,
  formatDateTime,
  formatNumber,
  formatPeriod,
  truncateText,
} from '@/lib/format';
import {
  MODE_LABEL,
  PLATFORMS,
  PLATFORM_ORDER,
  QUERY_KIND_LABEL,
  freshnessView,
  platformStatusView,
} from '@/lib/labels';
import { Button } from './Button';
import { Chip } from './Chip';
import { PlatformLabel } from './PlatformDot';
import { StatusBadgeFromView } from './StatusBadge';
import styles from './StatusLine.module.css';
import { cx } from './cx';

export interface StatusLineProps {
  /** Условия ВЫПОЛНЕННОГО поиска (НТ-1), не текущие значения полей */
  conditions: SearchConditions;
  /**
   * Статусы площадок. Показываются площадки из `conditions.platforms` (пусто — все);
   * недостающие среди них — как «ожидает»
   */
  statuses: readonly PlatformStatus[];
  /** «Найдено N» без исключённых; `null` — не показывать */
  total?: number | null;
  /** Поиск ещё идёт */
  running?: boolean;
  /** Поиск остановлен человеком: внизу «Поиск остановлен …», а не «выполнен» */
  stopped?: boolean;
  /** «Повторить» по площадке (ТЗ-Ф44) */
  onRetry?: (platform: PlatformId) => void;
  /** Площадка, которую сейчас повторяют: кнопка в состоянии загрузки */
  retrying?: PlatformId | null;
  /** Какой источник проверяется сейчас — для хода поиска */
  currentSource?: Partial<Record<PlatformId, string | null>>;
  /** Кнопки справа: «Скачать XLSX — 35 записей» */
  actions?: ReactNode;
  /**
   * Плашка «Условия изменены — подборка относится к прежним» (НТ-1).
   * Передайте обработчик, чтобы показать плашку с кнопкой «Найти».
   */
  onConditionsChangedRun?: (() => void) | null;
  className?: string;
}

const NOTE_TONE: Partial<Record<string, string | undefined>> = {
  critical: styles.noteCritical,
  warning: styles.noteWarning,
  info: styles.noteInfo,
};

function placeholder(platform: PlatformId): PlatformStatus {
  return {
    platform,
    state: 'waiting',
    found: 0,
    progress: null,
    problem: null,
    freshness: null,
    cap: null,
    updatedAt: null,
  };
}

/**
 * «Данные с задержкой» (MAX, ~24 ч) — только у площадки, которая участвовала в поиске и
 * ответила: у ожидающей, не ответившей или без доступа пометка ни о чём.
 */
function answeredFreshness(status: PlatformStatus) {
  const answered =
    status.state === 'found' ||
    status.state === 'nothing' ||
    status.state === 'partial' ||
    status.state === 'stopped';
  return answered ? freshnessView(status) : null;
}

/**
 * Строка условий и статусов (Р9 п. 3): что искали, где, за какой период, сколько
 * найдено и как ответила каждая площадка из полного набора (НТ-3, НТ-4).
 * Всегда над подборкой. Работает и в узкой панели (контейнерные запросы).
 */
export function StatusLine({
  conditions,
  statuses,
  total = null,
  running = false,
  stopped = false,
  onRetry,
  retrying = null,
  currentSource,
  actions,
  onConditionsChangedRun = null,
  className,
}: StatusLineProps) {
  const byPlatform = new Map(statuses.map((s) => [s.platform, s]));
  // Только площадки этого поиска: выключенная на сервере не висит «ожидает».
  const requested = new Set(conditions.platforms);
  const shown =
    requested.size > 0 ? PLATFORM_ORDER.filter((p) => requested.has(p)) : PLATFORM_ORDER;
  const full = shown.map((p) => byPlatform.get(p) ?? placeholder(p));
  const notes = full.flatMap((s) => {
    const view = platformStatusView(s);
    const fresh = answeredFreshness(s);
    const lines: { key: string; platform: PlatformId; text: string; tone: string }[] = [];
    if (view.detail && (s.state === 'partial' || s.state === 'error' || s.state === 'no-access')) {
      lines.push({
        key: `${s.platform}-p`,
        platform: s.platform,
        text: view.detail,
        tone: view.tone,
      });
    }
    if (s.cap)
      lines.push({
        key: `${s.platform}-c`,
        platform: s.platform,
        text: s.cap.note,
        tone: 'warning',
      });
    if (fresh?.detail && !running) {
      lines.push({
        key: `${s.platform}-f`,
        platform: s.platform,
        text: fresh.detail,
        tone: 'info',
      });
    }
    // Постоянная оговорка о покрытии: «Подключено 43 сайта из 48: …»
    if (s.note && !running) {
      lines.push({ key: `${s.platform}-n`, platform: s.platform, text: s.note, tone: 'info' });
    }
    return lines;
  });
  const finished = conditions.finishedAt;

  return (
    <section className={cx(styles.root, className)} aria-label="Условия и статус поиска">
      {onConditionsChangedRun && (
        <div className={styles.changed} role="status">
          <TriangleAlert aria-hidden="true" className={styles.changedIcon} />
          <span>
            <strong>Условия изменены</strong> — подборка ниже относится к прежним условиям.
          </span>
          <Button size="sm" variant="primary" onClick={onConditionsChangedRun}>
            Найти по новым
          </Button>
        </div>
      )}

      <ul className={styles.conditions} aria-label="Условия поиска">
        <li>
          <Chip title={conditions.text}>
            {QUERY_KIND_LABEL[conditions.kind]}:{' '}
            <strong>«{truncateText(conditions.label, 60)}»</strong>
          </Chip>
        </li>
        {conditions.meaningLabel && (
          <li>
            <Chip>
              Значение: <strong>{conditions.meaningLabel}</strong>
            </Chip>
          </li>
        )}
        <li>
          <Chip>
            Период: <strong>{formatPeriod(conditions.period)}</strong>
          </Chip>
        </li>
        <li>
          <Chip>
            Регион: <strong>{conditions.region.name}</strong>
          </Chip>
        </li>
        <li>
          <Chip>
            Источники:{' '}
            <strong>
              {MODE_LABEL[conditions.mode]}
              {conditions.mode === 'my-sources' && conditions.sourceCount !== null
                ? ` (${formatNumber(conditions.sourceCount)})`
                : ''}
            </strong>
          </Chip>
        </li>
      </ul>

      <div className={styles.statusRow}>
        {total !== null && (
          <p className={styles.total}>
            Найдено <strong className={styles.totalValue}>{formatNumber(total)}</strong>
          </p>
        )}
        <ul className={styles.platforms} aria-label="Статус площадок">
          {full.map((s) => {
            const view = platformStatusView(s);
            const fresh = answeredFreshness(s);
            const source = currentSource?.[s.platform];
            return (
              <li key={s.platform} className={styles.platform}>
                <PlatformLabel platform={s.platform} />
                <StatusBadgeFromView view={view} size="sm" />
                {fresh && !running && (
                  <StatusBadgeFromView view={fresh} size="sm" variant="plain" />
                )}
                {s.state === 'searching' && source && (
                  <span className={styles.current}>{truncateText(source, 28)}</span>
                )}
                {view.retry && onRetry && s.state !== 'stopped' && (
                  <Button
                    size="sm"
                    variant="secondary"
                    iconStart={<RotateCw />}
                    loading={retrying === s.platform}
                    onClick={() => onRetry(s.platform)}
                    aria-label={`Повторить поиск: ${PLATFORMS[s.platform].name}`}
                  >
                    Повторить
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
        {actions && <div className={styles.actions}>{actions}</div>}
      </div>

      {notes.length > 0 && (
        <ul className={styles.notes} aria-label="Пояснения к статусам площадок">
          {notes.map((n) => (
            <li key={n.key} className={cx(styles.note, NOTE_TONE[n.tone])}>
              <strong>{PLATFORMS[n.platform].short}:</strong> {n.text}
            </li>
          ))}
        </ul>
      )}

      <p className={styles.time}>
        {running || !finished
          ? `Поиск начат ${formatDateTime(conditions.startedAt)}`
          : `${stopped ? 'Поиск остановлен' : 'Поиск выполнен'} ${formatDateTime(finished)}`}{' '}
        · {TIME_ZONE_LABEL}
      </p>
    </section>
  );
}
