/**
 * Проверка текста на ИИ: пороги уровней, ключ текста и подписи для интерфейса.
 *
 * Правила показа без обвинений (research/ai-text-detection.md §3, 04-decisions.md):
 * три уровня вместо процентов; только «похоже», «признаки» — никогда «написано ИИ»;
 * без красного; рядом всегда «Оценка модели, не доказательство»; меньше 40 слов не
 * оцениваем; сбой модели — «проверка недоступна», а не «не похоже».
 */
import type { AiCheck, AiLevel } from '@/api/types';
import { AI_MIN_WORDS, countAiWords, normalizeAiText } from './ai-normalize';
import { sha256Hex } from './sha256';

/**
 * Пороги уровней по оценке модели (score 0..1). Предварительные: откалибруем на своём эталоне
 * так, чтобы на заведомо человеческих текстах «похоже на ИИ» было не чаще 2–3%.
 */
export const AI_THRESHOLDS = {
  /** score ≥ этого — `likely-ai`, «похоже на ИИ» */
  likelyAi: 0.85,
  /** score ≥ этого — `signs`, «есть признаки ИИ»; ниже — `unlikely` */
  signs: 0.6,
} as const;

/** Уровень по оценке модели (для текстов от 40 слов). */
export function aiLevelForScore(score: number): 'likely-ai' | 'signs' | 'unlikely' {
  if (score >= AI_THRESHOLDS.likelyAi) return 'likely-ai';
  if (score >= AI_THRESHOLDS.signs) return 'signs';
  return 'unlikely';
}

/** Нормализованный текст, его ключ и длина — от них зависит результат проверки. */
export interface AiTextKey {
  normalized: string;
  /** SHA-256 (hex) нормализованного текста */
  textHash: string;
  words: number;
  /** Меньше 40 слов: модель не вызываем, уровень `too-short` */
  tooShort: boolean;
}

export function aiTextKey(text: string): AiTextKey {
  const normalized = normalizeAiText(text);
  const words = countAiWords(normalized);
  return { normalized, textHash: sha256Hex(normalized), words, tooShort: words < AI_MIN_WORDS };
}

// ---------------------------------------------------------------- подписи

/** Крупное слово результата на экране «Проверка на ИИ». */
export const AI_LEVEL_TITLE: Record<AiLevel, string> = {
  'likely-ai': 'Похоже на ИИ',
  signs: 'Есть признаки ИИ',
  unlikely: 'Не похоже на ИИ',
  'too-short': 'Мало текста для оценки',
  unavailable: 'Проверка недоступна',
};

/** Уровни, у которых в подборке и «Распространении» есть метка. */
export type AiMarkedLevel = 'likely-ai' | 'signs';

/** Метка в карточке и подсказка к ней (одна строка + оговорка). */
export const AI_MARK: Record<AiMarkedLevel, { label: string; hint: string }> = {
  'likely-ai': {
    label: 'похоже на ИИ',
    hint: 'Модель считает, что текст похож на написанный нейросетью.',
  },
  signs: {
    label: 'признаки ИИ',
    hint: 'Модель видит в тексте отдельные признаки текста нейросети.',
  },
};

/** Оговорка рядом с любым результатом модели. */
export const AI_DISCLAIMER = 'Оценка модели, не доказательство';

/** Сколько точек из двух закрашено: ●● похоже, ●○ признаки, ○○ не похоже. */
export const AI_LEVEL_DOTS: Partial<Record<AiLevel, 0 | 1 | 2>> = {
  'likely-ai': 2,
  signs: 1,
  unlikely: 0,
};

/** Уровень для метки; `null` — метку не показываем (не похоже, мало текста, сбой, нет проверки). */
export function aiMarkedLevel(check: AiCheck | null | undefined): AiMarkedLevel | null {
  if (check?.level === 'likely-ai' || check?.level === 'signs') return check.level;
  return null;
}
