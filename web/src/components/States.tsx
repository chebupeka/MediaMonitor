import { RotateCw, WifiOff } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from './Button';
import styles from './States.module.css';
import { cx } from './cx';

// ---------------------------------------------------------------- точки-иллюстрации

/** Небольшая декоративная иллюстрация из точек: «рассеялись» (пусто) или «серые» (сбой). */
function DotsArt({ kind }: { kind: 'empty' | 'error' | 'start' }) {
  const dots =
    kind === 'start'
      ? [
          [20, 30, 3],
          [34, 22, 4],
          [48, 30, 3],
          [40, 42, 5],
          [26, 44, 3],
          [56, 44, 3],
          [48, 54, 4],
        ]
      : [
          [8, 50, 2],
          [18, 34, 3],
          [30, 54, 2],
          [40, 20, 2.5],
          [52, 44, 3],
          [62, 28, 2],
          [70, 52, 2],
        ];
  return (
    <svg className={cx(styles.art, styles[`art${kind}`])} viewBox="0 0 80 72" aria-hidden="true">
      {dots.map(([cx_, cy, r], i) => (
        <circle
          key={i}
          cx={cx_}
          cy={cy}
          r={r}
          className={styles.artDot}
          style={{ opacity: 0.35 + (i % 3) * 0.2 }}
        />
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------- пусто

export interface EmptyStateProps {
  title: string;
  description?: ReactNode;
  /** Кнопки и подсказки: «Расширить период», «Искать везде» */
  actions?: ReactNode;
  /** `empty` — ничего не нашли (без тревоги); `start` — первый запуск или пустой список */
  variant?: 'empty' | 'start';
  compact?: boolean;
  className?: string;
}

/** Пустое состояние: спокойно, с подсказками, что делать дальше. Это не ошибка (ТЗ-Ф43). */
export function EmptyState({
  title,
  description,
  actions,
  variant = 'empty',
  compact = false,
  className,
}: EmptyStateProps) {
  return (
    <div className={cx(styles.state, compact && styles.compact, className)} role="status">
      <DotsArt kind={variant} />
      <h2 className={styles.title}>{title}</h2>
      {description && <div className={styles.description}>{description}</div>}
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- ошибка

export interface ErrorStateProps {
  title: string;
  description?: ReactNode;
  /** Показать «Повторить» */
  onRetry?: () => void;
  retryLabel?: string;
  retrying?: boolean;
  /** `offline` — нет связи у пользователя (НТ-23), отдельно от сбоя площадки */
  kind?: 'error' | 'offline';
  actions?: ReactNode;
  compact?: boolean;
  className?: string;
}

/** Ошибка: что случилось, что сохранено и что сделать. Объявляется скринридером. */
export function ErrorState({
  title,
  description,
  onRetry,
  retryLabel = 'Повторить',
  retrying = false,
  kind = 'error',
  actions,
  compact = false,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cx(styles.state, styles.error, compact && styles.compact, className)}
      role="alert"
    >
      {kind === 'offline' ? (
        <span className={styles.offlineIcon} aria-hidden="true">
          <WifiOff />
        </span>
      ) : (
        <DotsArt kind="error" />
      )}
      <h2 className={styles.title}>{title}</h2>
      {description && <div className={styles.description}>{description}</div>}
      {(onRetry || actions) && (
        <div className={styles.actions}>
          {onRetry && (
            <Button variant="primary" iconStart={<RotateCw />} onClick={onRetry} loading={retrying}>
              {retryLabel}
            </Button>
          )}
          {actions}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- загрузка

export interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  radius?: 'sm' | 'md' | 'lg' | 'pill';
  className?: string;
}

/** Заглушка на время загрузки. Декоративная: о загрузке объявляйте текстом. */
export function Skeleton({ width = '100%', height = 14, radius = 'sm', className }: SkeletonProps) {
  return (
    <span
      className={cx(styles.skeleton, styles[`r${radius}`], className)}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}

/** Несколько строк-заглушек текста. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <span className={cx(styles.skeletonText, className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? '62%' : '100%'} />
      ))}
    </span>
  );
}
