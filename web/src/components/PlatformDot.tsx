import type { PlatformId } from '@/api/types';
import { PLATFORMS } from '@/lib/labels';
import styles from './PlatformDot.module.css';
import { cx } from './cx';

export interface PlatformDotProps {
  platform: PlatformId;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

/** Точка цвета площадки. Декоративная: рядом всегда должно быть название. */
export function PlatformDot({ platform, size = 'md', className }: PlatformDotProps) {
  return (
    <span
      className={cx(styles.dot, styles[platform], styles[size], className)}
      aria-hidden="true"
    />
  );
}

export interface PlatformLabelProps {
  platform: PlatformId;
  /** `short` — «VK», `full` — «ВКонтакте» */
  name?: 'short' | 'full';
  className?: string;
}

/** Точка + название площадки. */
export function PlatformLabel({ platform, name = 'short', className }: PlatformLabelProps) {
  const meta = PLATFORMS[platform];
  return (
    <span className={cx(styles.label, className)}>
      <PlatformDot platform={platform} />
      {name === 'short' ? (
        <abbr title={meta.name} className={styles.abbr}>
          {meta.short}
        </abbr>
      ) : (
        meta.name
      )}
    </span>
  );
}
