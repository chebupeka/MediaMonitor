import { ToggleGroup as RadixToggleGroup } from 'radix-ui';
import type { ReactNode } from 'react';
import { formatNumber } from '@/lib/format';
import styles from './ToggleGroup.module.css';
import { cx } from './cx';

export interface ToggleItem<T extends string> {
  value: T;
  label: ReactNode;
  /** Счётчик: «Группы 3» */
  count?: number;
  icon?: ReactNode;
  disabled?: boolean;
  /** Подсказка (атрибут title) */
  hint?: string;
}

export interface ToggleGroupProps<T extends string> {
  /** Подпись группы для скринридера: «Сортировка», «Режим копий» */
  label: string;
  items: readonly ToggleItem<T>[];
  value: T;
  onValueChange: (value: T) => void;
  size?: 'sm' | 'md';
  fullWidth?: boolean;
  className?: string;
}

/**
 * Переключатель «один из нескольких» (сегменты): режим копий «все / группы / скрыть»,
 * сортировка «по времени / по популярности», «Мои источники / Везде».
 * Выбор нельзя снять совсем: всегда выбран один вариант.
 */
export function ToggleGroup<T extends string>({
  label,
  items,
  value,
  onValueChange,
  size = 'md',
  fullWidth = false,
  className,
}: ToggleGroupProps<T>) {
  return (
    <RadixToggleGroup.Root
      type="single"
      aria-label={label}
      value={value}
      onValueChange={(next: string) => {
        const item = items.find((i) => i.value === next);
        if (item) onValueChange(item.value);
      }}
      className={cx(styles.root, styles[size], fullWidth && styles.fullWidth, className)}
    >
      {items.map((item) => (
        <RadixToggleGroup.Item
          key={item.value}
          value={item.value}
          disabled={item.disabled}
          title={item.hint}
          className={styles.item}
        >
          {item.icon && (
            <span className={styles.icon} aria-hidden="true">
              {item.icon}
            </span>
          )}
          <span>{item.label}</span>
          {item.count !== undefined && (
            <span className={styles.count}>{formatNumber(item.count)}</span>
          )}
        </RadixToggleGroup.Item>
      ))}
    </RadixToggleGroup.Root>
  );
}
