import type { ElementType, HTMLAttributes, ReactNode } from 'react';
import styles from './Card.module.css';
import { cx } from './cx';

export interface CardProps extends HTMLAttributes<HTMLElement> {
  /** HTML-элемент: `article` для публикации, `section` для блока экрана */
  as?: ElementType;
  /**
   * - `default` — обычная карточка;
   * - `muted` — вторичный блок без рамки;
   * - `excluded` — исключённая запись («не то», ТЗ-Ф48): приглушена;
   * - `accent` — выделенная (новое, первоисточник).
   */
  tone?: 'default' | 'muted' | 'excluded' | 'accent';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  children?: ReactNode;
}

/** Каркас карточки. Содержимое карточки публикации собирает экран «Поиск». */
export function Card({
  as: Tag = 'div',
  tone = 'default',
  padding = 'md',
  className,
  children,
  ...rest
}: CardProps) {
  return (
    <Tag className={cx(styles.card, styles[tone], styles[`pad${padding}`], className)} {...rest}>
      {children}
    </Tag>
  );
}

/** Шапка карточки: слева — заголовок или мета, справа — `aside` (метка, действия). */
export function CardHeader({
  children,
  aside,
  className,
}: {
  children: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx(styles.header, className)}>
      <div className={styles.headerMain}>{children}</div>
      {aside && <div className={styles.headerAside}>{aside}</div>}
    </div>
  );
}

/** Строка мета-данных: «VK · Телеканал края · 14 окт, 10:02». */
export function CardMeta({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx(styles.meta, className)}>{children}</div>;
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx(styles.body, className)}>{children}</div>;
}

/** Низ карточки: действия и пометки. */
export function CardFooter({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx(styles.footer, className)}>{children}</div>;
}
