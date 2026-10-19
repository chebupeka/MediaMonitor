import { FlaskConical } from 'lucide-react';
import { Tooltip } from './Tooltip';
import styles from './DemoBadge.module.css';
import { cx } from './cx';

/**
 * Пометка «Демо-данные» (бриф: «везде заметная пометка»). Фокусируемая,
 * чтобы пояснение было доступно и с клавиатуры. На узком экране — «Демо».
 */
export function DemoBadge({ short = false, className }: { short?: boolean; className?: string }) {
  return (
    <Tooltip content="Мокап для команды: все публикации, источники и цифры вымышлены. Города края — настоящие.">
      <button
        type="button"
        className={cx(styles.badge, short && styles.forceShort, className)}
        aria-label="Демо-данные"
      >
        <FlaskConical aria-hidden="true" className={styles.icon} />
        <span className={styles.long} aria-hidden="true">
          Демо-данные
        </span>
        <span className={styles.short} aria-hidden="true">
          Демо
        </span>
      </button>
    </Tooltip>
  );
}
