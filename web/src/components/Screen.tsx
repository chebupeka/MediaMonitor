import type { ReactNode } from 'react';
import styles from './Screen.module.css';
import { cx } from './cx';

export interface ScreenProps {
  /** Заголовок экрана (h1). Один на экран. */
  title: ReactNode;
  /** Пояснение под заголовком простым языком */
  lead?: ReactNode;
  /** Кнопки справа от заголовка */
  actions?: ReactNode;
  /** Строка над заголовком: «Поиск › Распространение» */
  eyebrow?: ReactNode;
  /** Ширина: `default` — рабочая, `narrow` — текстовая, `full` — без ограничения */
  width?: 'default' | 'narrow' | 'full';
  children?: ReactNode;
  className?: string;
}

/**
 * Каркас экрана: заголовок, пояснение, действия и содержимое с общими отступами.
 * Одинаков для всех экранов, сайта и узкой панели (контейнерные запросы).
 */
export function Screen({
  title,
  lead,
  actions,
  eyebrow,
  width = 'default',
  children,
  className,
}: ScreenProps) {
  return (
    <div className={cx(styles.screen, styles[width], className)}>
      <header className={styles.header}>
        <div className={styles.titles}>
          {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
          <h1 className={styles.title}>{title}</h1>
          {lead && <div className={styles.lead}>{lead}</div>}
        </div>
        {actions && <div className={styles.actions}>{actions}</div>}
      </header>
      {children}
    </div>
  );
}

/** Раздел экрана с заголовком h2. */
export function Section({
  title,
  aside,
  children,
  className,
  id,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
  className?: string;
  id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section
      className={cx(styles.section, className)}
      aria-labelledby={title ? headingId : undefined}
      id={id}
    >
      {(title || aside) && (
        <div className={styles.sectionHead}>
          {title && (
            <h2 id={headingId} className={styles.sectionTitle}>
              {title}
            </h2>
          )}
          {aside && <div className={styles.sectionAside}>{aside}</div>}
        </div>
      )}
      {children}
    </section>
  );
}
