/**
 * Типографика сайта «Медиарадар»: заголовок узким гротеском капсом, где одно слово —
 * контуром, и подпись-раздел «01 Запрос · система слушает». Слова в *звёздочках* — контуром:
 * `"Поиск *по смыслу*"`. Заголовки проявляются «расшифровкой», как на сайте.
 */
import type { ReactNode } from 'react';
import { ScrambleText } from './Scramble';
import styles from './Display.module.css';
import { cx } from './cx';

interface Part {
  text: string;
  outline: boolean;
}

/** «Поиск *по смыслу*» → [«Поиск », «по смыслу» контуром] */
export function parseDisplay(text: string): Part[] {
  return text
    .split(/(\*[^*]+\*)/u)
    .filter((s) => s.length > 0)
    .map((s) =>
      s.startsWith('*') && s.endsWith('*') && s.length > 2
        ? { text: s.slice(1, -1), outline: true }
        : { text: s, outline: false },
    );
}

/** Текст без звёздочек — для заголовка окна и скринридера. */
export function plainDisplay(text: string): string {
  return parseDisplay(text)
    .map((p) => p.text)
    .join('');
}

export interface DisplayTextProps {
  /** Слова в *звёздочках* — контуром */
  text: string;
  /** Расшифровка при появлении (на сайте — у всех заголовков) */
  scramble?: boolean;
  /** Начать расшифровку, когда заголовок покажется на экране */
  onView?: boolean;
  /** Задержка первого слова, мс; следующие — через 150 мс, как на сайте */
  delay?: number;
}

/** Слова заголовка; контурные — с атрибутом data-outline (его знает «расшифровка»). */
export function DisplayText({
  text,
  scramble = true,
  onView = false,
  delay = 0,
}: DisplayTextProps) {
  return (
    <>
      {parseDisplay(text).map((p, i) => {
        const inner = scramble ? (
          <ScrambleText text={p.text} delay={delay + i * 150} onView={onView} />
        ) : (
          p.text
        );
        return p.outline ? (
          <span key={i} className={styles.outline} data-outline="">
            {inner}
          </span>
        ) : (
          <span key={i}>{inner}</span>
        );
      })}
    </>
  );
}

export interface KickerProps {
  /** Номер раздела, золотом: «01» */
  index?: string;
  children: ReactNode;
  className?: string;
  /** Расшифровка подписи (если это строка) */
  scramble?: boolean;
}

/** Подпись-раздел над заголовком, как на сайте: «01 Запрос · система слушает». */
export function Kicker({ index, children, className, scramble = true }: KickerProps) {
  return (
    <p className={cx(styles.kicker, className)}>
      {index && <span className={styles.kickerNum}>{index}</span>}
      {typeof children === 'string' && scramble ? <ScrambleText text={children} /> : children}
    </p>
  );
}
