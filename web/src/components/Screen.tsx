import type { ReactNode } from 'react';
import { DisplayText, Kicker } from './Display';
import styles from './Screen.module.css';
import { cx } from './cx';

export interface ScreenProps {
  /**
   * Заголовок экрана (h1), один на экран — узким гротеском капсом, как на сайте.
   * В строке слова в *звёздочках* — контуром: `"Поиск *по смыслу*"`.
   */
  title: ReactNode;
  /** Номер раздела в подписи над заголовком, золотом: «01» */
  index?: string;
  /** Подпись-раздел над заголовком: «Поиск · Красноярский край» */
  eyebrow?: ReactNode;
  /** Пояснение под заголовком простым языком */
  lead?: ReactNode;
  /** Кнопки справа от заголовка */
  actions?: ReactNode;
  /** Ширина: `default` — рабочая, `narrow` — текстовая, `full` — без ограничения */
  width?: 'default' | 'narrow' | 'full';
  /**
   * Крупная сцена точек — главный визуальный акцент, как на сайте. На широкой вкладке —
   * справа во всю высоту первого экрана, в боковой панели — во всю ширину под заголовком.
   */
  scene?: ReactNode;
  /**
   * `sticky` — сцена держится справа, пока листают содержимое (Поиск: подборка рядом с
   * картой); `hero` — сцена только рядом с шапкой и `intro`, ниже содержимое во всю ширину.
   */
  sceneMode?: 'sticky' | 'hero';
  /** В режиме `hero`: что стоит под заголовком рядом со сценой */
  intro?: ReactNode;
  children?: ReactNode;
  className?: string;
}

/**
 * Каркас экрана: подпись-раздел, заголовок, пояснение, действия, сцена точек и содержимое
 * с общими отступами. Одинаков для всех экранов, вкладки и узкой панели (контейнерные запросы).
 */
export function Screen({
  title,
  index,
  lead,
  actions,
  eyebrow,
  width = 'default',
  scene,
  sceneMode = 'sticky',
  intro,
  children,
  className,
}: ScreenProps) {
  const head = (
    <header className={styles.header}>
      <div className={styles.titles}>
        {eyebrow && (
          <Kicker index={index} className={styles.eyebrow}>
            {eyebrow}
          </Kicker>
        )}
        <h1 className={styles.title}>
          {typeof title === 'string' ? <DisplayText text={title} delay={120} /> : title}
        </h1>
        {lead && <div className={styles.lead}>{lead}</div>}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </header>
  );

  if (!scene)
    return (
      <div className={cx(styles.screen, styles[width], className)}>
        {head}
        {children}
      </div>
    );

  const sticky = sceneMode === 'sticky';
  const body = sticky ? children : intro;
  return (
    <div
      className={cx(
        styles.screen,
        styles.withScene,
        sticky ? styles.sticky : styles.hero,
        styles[width],
        className,
      )}
    >
      <div className={styles.main}>
        {head}
        {body !== undefined && body !== null && <div className={styles.body}>{body}</div>}
      </div>
      <div className={styles.sceneCol}>
        <div className={styles.scene}>{scene}</div>
      </div>
      {!sticky && children !== undefined && <div className={styles.below}>{children}</div>}
    </div>
  );
}

/** Раздел экрана с заголовком h2 — узким гротеском капсом, как разделы сайта. */
export function Section({
  title,
  index,
  aside,
  children,
  className,
  id,
}: {
  /** Строка: слова в *звёздочках* — контуром; проявляется «расшифровкой», когда видна */
  title?: ReactNode;
  /** Номер раздела золотом перед заголовком: «01» */
  index?: string;
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
              {index && <span className={styles.sectionNum}>{index}</span>}
              {typeof title === 'string' ? <DisplayText text={title} onView /> : title}
            </h2>
          )}
          {aside && <div className={styles.sectionAside}>{aside}</div>}
        </div>
      )}
      {children}
    </section>
  );
}
