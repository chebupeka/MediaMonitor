/**
 * Имитация проверки текста на ИИ — ТОЛЬКО МОКАП. Настоящий детектор (GigaCheck) подключится
 * на сервере по тому же контракту (`MonitorApi.checkAiText`, `ResultItem.aiCheck`).
 *
 * Одинаковость результата — как будет на сервере:
 * - текст нормализуется одной функцией (src/lib/ai-normalize.ts), ключ — SHA-256 нормализованного
 *   текста + модель;
 * - оценка зависит только от ключа: заданная для нескольких демо-постов (PostSpec.ai), иначе —
 *   из самого хеша. Никакой случайности;
 * - один метод для отдельной проверки, подборки и «Распространения» и общий кэш: первый
 *   результат сохраняется и переиспользуется (в том числе время проверки).
 * Сбой модели (`unavailable`) не кэшируется: после восстановления текст проверится.
 */
import type { AiCheck } from '../types';
import { aiLevelForScore, aiTextKey } from '@/lib/ai-check';
import { nowIso } from './clock';
import { BDD_AI_SCORES } from './datasets/bdd';
import { RELEASE_AI_SCORES } from './datasets/release';

/** Модель в имитации. На сервере — модель и её версия. */
export const DEMO_AI_MODEL = 'demo';

let presets: Map<string, number> | null = null;

/** Заданные оценки демо-постов по ключу текста (считаются один раз, при первой проверке). */
function presetScores(): Map<string, number> {
  if (!presets) {
    presets = new Map();
    for (const [text, score] of [...RELEASE_AI_SCORES, ...BDD_AI_SCORES]) {
      presets.set(aiTextKey(text).textHash, score);
    }
  }
  return presets;
}

/**
 * Оценка из хеша: первые 48 бит → u ∈ [0, 1), score = u³. Куб сдвигает оценки вниз, как
 * у настоящих текстов: «похоже на ИИ» — около 5% случайных текстов, «признаки» — около 10%.
 */
function hashScore(textHash: string): number {
  const u = Number.parseInt(textHash.slice(0, 12), 16) / 2 ** 48;
  return Math.round(u ** 3 * 1000) / 1000;
}

const cache = new Map<string, AiCheck>();

/**
 * Проверить текст. `modelDown` — модель не отвечает (сценарий «Нейросеть недоступна»):
 * уже проверенные тексты берутся из кэша, короткие — «мало текста», остальные — `unavailable`.
 */
export function demoAiCheck(text: string, { modelDown = false } = {}): AiCheck {
  const key = aiTextKey(text);
  const cacheKey = `${DEMO_AI_MODEL}:${key.textHash}`;
  const cached = cache.get(cacheKey);
  if (cached) return { ...cached };

  const base = { model: DEMO_AI_MODEL, textHash: key.textHash, words: key.words };
  if (!key.tooShort && modelDown) {
    return { ...base, level: 'unavailable', score: null, checkedAt: nowIso() };
  }
  const score = key.tooShort ? null : (presetScores().get(key.textHash) ?? hashScore(key.textHash));
  const result: AiCheck = {
    ...base,
    level: score === null ? 'too-short' : aiLevelForScore(score),
    score,
    checkedAt: nowIso(),
  };
  cache.set(cacheKey, result);
  return { ...result };
}
