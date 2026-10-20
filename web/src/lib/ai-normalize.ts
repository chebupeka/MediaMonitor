/**
 * Нормализация текста для проверки на ИИ — ОДНА функция для всех мест (04-decisions.md,
 * «Проверка текста на ИИ», уточнение): отдельная проверка, подборка и «Распространение».
 * От нормализованного текста считаются ключ (SHA-256) и число слов, поэтому один и тот же
 * текст с другими пробелами, переносами и невидимыми символами даёт один результат.
 *
 * Шаги (по порядку):
 * 1. Unicode NFC;
 * 2. удалить U+200B–U+200D (нулевой ширины), U+FEFF (BOM), U+00AD (мягкий перенос);
 * 3. U+00A0 (неразрывный пробел) → пробел;
 * 4. любую последовательность пробельных символов → один пробел;
 * 5. обрезать пробелы по краям.
 * Слова — части нормализованного текста между пробелами.
 *
 * Пробельные символы — ровно те, что `str.isspace()` в Python, поэтому на сервере то же самое
 * даёт `' '.join(unicodedata.normalize('NFC', t).translate(DROP).replace('\xa0', ' ').split())`.
 * Сверка — тест-векторы ниже (`AI_NORMALIZE_VECTORS`, с SHA-256) и `npm run check:ai`.
 */

/** Меньше стольких слов — «мало текста для оценки» (`too-short`), модель не вызываем. */
export const AI_MIN_WORDS = 40;

/** Невидимые символы, которые удаляем (а не заменяем пробелом). */
const INVISIBLE = /[\u200B-\u200D\uFEFF\u00AD]/gu;

/**
 * Пробельные символы — как `str.isspace()` в Python: U+0009–U+000D, U+001C–U+001F, пробел,
 * U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000.
 * (`\s` в JavaScript отличается: в нём нет U+001C–U+001F и U+0085.)
 */
const WHITESPACE =
  // eslint-disable-next-line no-control-regex -- U+001C–U+001F пробельные в Python: как на сервере
  /[\t\n\v\f\r\u001C-\u001F \u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+/gu;

/** Нормализовать текст перед проверкой на ИИ. */
export function normalizeAiText(text: string): string {
  return text
    .normalize('NFC')
    .replace(INVISIBLE, '')
    .replace(/\u00A0/gu, ' ')
    .replace(WHITESPACE, ' ')
    .replace(/^ | $/gu, '');
}

/** Слов в УЖЕ нормализованном тексте. */
export function countAiWords(normalized: string): number {
  return normalized === '' ? 0 : normalized.split(' ').length;
}

export interface AiNormalizeVector {
  /** Что проверяем */
  note: string;
  input: string;
  normalized: string;
  words: number;
  /** SHA-256 (hex) нормализованного текста в UTF-8 */
  sha256: string;
}

/**
 * Тест-векторы нормализации — общие для интерфейса и сервера. Значения SHA-256 посчитаны
 * node:crypto и сверены с Python (`hashlib`, `' '.join(s.split())`).
 */
export const AI_NORMALIZE_VECTORS: readonly AiNormalizeVector[] = [
  {
    note: 'обычный текст не меняется',
    input: 'Простой текст без лишнего.',
    normalized: 'Простой текст без лишнего.',
    words: 4,
    sha256: 'cbc8247d692231b0417e4b2e1b2bd3954272672735d8710ba3038676525d0dc2',
  },
  {
    note: 'пробелы, абзацы, табуляция и \\r\\n схлопываются, края обрезаются',
    input: '  В Норильске\n\nоткрылась\tшкола.\r\n',
    normalized: 'В Норильске открылась школа.',
    words: 4,
    sha256: 'efc2c2d72720a98d8b28e97067d594ca97949963dfcced01ce010973b48b8c78',
  },
  {
    note: 'неразрывный и узкий неразрывный пробел → пробел',
    input: 'на\u00A01\u202F100 мест',
    normalized: 'на 1 100 мест',
    words: 4,
    sha256: 'c56696063bbb1ad041ccb1faec5d7c202fd1ff1699f00cba9540a58ed2855920',
  },
  {
    note: 'мягкий перенос, символы нулевой ширины и BOM удаляются',
    input: 'шко\u00ADла\u200B на\u200C\u200D\uFEFF 1100',
    normalized: 'школа на 1100',
    words: 3,
    sha256: 'a561a5f452db561793b480e58a53fe5e253ca1239ea1bf8e26ce03d5f5f36145',
  },
  {
    note: 'NFC: «е» + U+0308 → «ё», «и» + U+0306 → «й»',
    input: 'е\u0308лка и\u0306од',
    normalized: 'ёлка йод',
    words: 2,
    sha256: 'adb4a2a1b1576b1204b9b89edb86ad7db1c3c0f6ebb9e61ca2ea1d3e4f0901ed',
  },
  {
    note: 'только невидимые и пробелы → пустая строка, 0 слов',
    input: '\u200B \u00A0\uFEFF\n',
    normalized: '',
    words: 0,
    sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  },
  {
    note: 'пробельные символы Python: U+0085, U+001F, U+2028, U+3000',
    input: 'a\u0085b\u001Fc\u2028d\u3000e',
    normalized: 'a b c d e',
    words: 5,
    sha256: '52cf9f06f83e0a0a90dc25dcf548c18421244f9520c577672cd27b6618f12134',
  },
  {
    note: 'символ нулевой ширины между словами удаляется, а не становится пробелом',
    input: 'слово\u200Bслово',
    normalized: 'словослово',
    words: 1,
    sha256: '9037f7bf1469855d3eb44a8621df9c95684d29cabfabb1442e904f19864a7624',
  },
];
