import type { ReactNode } from 'react';
import { formatNumber } from '@/lib/format';
import styles from './Chip.module.css';
import { cx } from './cx';

export interface ChipProps {
  children: ReactNode;
  /** Счётчик справа: «Прямо 22» */
  count?: number;
  /** Значок слева (декоративный) */
  icon?: ReactNode;
  /** Нажимаемый чип-переключатель: рисуется кнопкой с aria-pressed */
  onClick?: () => void;
  selected?: boolean;
  size?: 'sm' | 'md';
  /** Мягкий акцент: информационный или предупреждающий */
  tone?: 'neutral' | 'info' | 'warning';
  disabled?: boolean;
  title?: string;
  className?: string;
}

/**
 * Чип. Без `onClick` — статичная метка (условия поиска, тип источника).
 * С `onClick` — переключатель фильтра (aria-pressed), например «Прямо 22».
 */
export function Chip({
  children,
  count,
  icon,
  onClick,
  selected = false,
  size = 'md',
  tone = 'neutral',
  disabled,
  title,
  className,
}: ChipProps) {
  const classes = cx(
    styles.chip,
    styles[size],
    styles[tone],
    onClick && styles.interactive,
    selected && styles.selected,
    className,
  );
  const content = (
    <>
      {icon && (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      )}
      <span className={styles.label}>{children}</span>
      {count !== undefined && <span className={styles.count}>{formatNumber(count)}</span>}
    </>
  );
  if (onClick) {
    return (
      <button
        type="button"
        className={classes}
        aria-pressed={selected}
        onClick={onClick}
        disabled={disabled}
        title={title}
      >
        {content}
      </button>
    );
  }
  return (
    <span className={classes} title={title}>
      {content}
    </span>
  );
}
