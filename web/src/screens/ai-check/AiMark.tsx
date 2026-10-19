/**
 * Метка проверки на ИИ для карточек подборки и строк «Распространения» и значок уровня.
 *
 * Метка есть только у «похоже на ИИ» и «признаки ИИ»; у «не похоже», «мало текста» и сбоя
 * её нет. Не только цветом: две точки (●● / ●○) и текст. Подсказка — при наведении и при
 * фокусе с клавиатуры: одна строка и «Оценка модели, не доказательство». Без красного.
 */
import type { AiCheck, AiLevel } from '@/api/types';
import { Tooltip, cx } from '@/components';
import { AI_DISCLAIMER, AI_LEVEL_DOTS, AI_MARK, aiMarkedLevel } from '@/lib/ai-check';
import styles from './AiMark.module.css';

/** Две точки уровня: ●● похоже на ИИ, ●○ признаки, ○○ не похоже. Декоративные. */
export function AiDots({ level, size = 'sm' }: { level: AiLevel; size?: 'sm' | 'lg' }) {
  const filled = AI_LEVEL_DOTS[level];
  if (filled === undefined) return null;
  return (
    <span className={cx(styles.dots, styles[size])} aria-hidden="true">
      <span className={filled >= 1 ? styles.on : styles.off} />
      <span className={filled >= 2 ? styles.on : styles.off} />
    </span>
  );
}

export function AiMark({ check, className }: { check: AiCheck | undefined; className?: string }) {
  const level = aiMarkedLevel(check);
  if (!level) return null;
  const mark = AI_MARK[level];
  return (
    <Tooltip
      content={
        <>
          <span className={styles.hint}>{mark.hint}</span>
          <span>{AI_DISCLAIMER}.</span>
        </>
      }
    >
      <button type="button" className={cx(styles.mark, className)} data-level={level}>
        <AiDots level={level} />
        <span>{mark.label}</span>
      </button>
    </Tooltip>
  );
}
