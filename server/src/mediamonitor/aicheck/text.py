"""Нормализация текста для проверки на ИИ — одна функция для всех мест (04-decisions.md,
«Проверка текста на ИИ», уточнение команды).

Один и тот же текст должен давать один результат в отдельной проверке, в карточке
подборки и в «Распространении». Поэтому ключ результата — SHA-256 нормализованного
текста, а нормализация повторяет интерфейс (web/src/lib/ai-normalize.ts) шаг в шаг:

1. Unicode NFC;
2. удалить U+200B–U+200D (нулевой ширины), U+FEFF (BOM), U+00AD (мягкий перенос);
3. U+00A0 (неразрывный пробел) → пробел;
4. любую последовательность пробельных символов → один пробел; пробельные — как
   `str.isspace()` в Python (`WHITESPACE` в интерфейсе);
5. обрезать пробел по краям.

Хеш — SHA-256 (hex, строчные) от UTF-8 нормализованного текста; одиночные суррогаты
заменяются на U+FFFD, как это делает `TextEncoder` браузера. Слова — части текста
между пробелами. Сверка с интерфейсом — общие тест-векторы (`AI_NORMALIZE_VECTORS`,
tests/test_ai_check.py).

Символы заданы кодами (`chr`), а не литералами: невидимые символы в исходнике легко
потерять или подменить при правке.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache


def _chars(*codes: int | tuple[int, int]) -> str:
    """Класс символов для регулярного выражения по кодам (число или диапазон «от, до»)."""
    parts = []
    for code in codes:
        if isinstance(code, tuple):
            parts.append(f"{re.escape(chr(code[0]))}-{re.escape(chr(code[1]))}")
        else:
            parts.append(re.escape(chr(code)))
    return "[" + "".join(parts) + "]"


NBSP = chr(0x00A0)
# Невидимые символы, которые удаляем совсем: U+200B–U+200D, U+FEFF, U+00AD.
INVISIBLE_CODES = ((0x200B, 0x200D), 0xFEFF, 0x00AD)
# Пробельные символы — как `str.isspace()` в Python и `WHITESPACE` в интерфейсе. Перечислены
# явно, чтобы не зависеть от версии Unicode в Python и в браузере.
WHITESPACE_CODES = (
    (0x0009, 0x000D),  # \t \n \v \f \r
    (0x001C, 0x001F),
    0x0020,
    0x0085,
    0x00A0,
    0x1680,
    (0x2000, 0x200A),
    0x2028,
    0x2029,
    0x202F,
    0x205F,
    0x3000,
)
_INVISIBLE = re.compile(_chars(*INVISIBLE_CODES))
_WHITESPACE = re.compile(_chars(*WHITESPACE_CODES) + "+")
_LONE_SURROGATE = re.compile(_chars((0xD800, 0xDFFF)))
_REPLACEMENT = chr(0xFFFD)


def normalize_text(text: str) -> str:
    """Текст для проверки: NFC, без невидимых символов, схлопнутые пробелы, без краёв."""
    value = unicodedata.normalize("NFC", text)
    value = _INVISIBLE.sub("", value)
    value = value.replace(NBSP, " ")
    value = _WHITESPACE.sub(" ", value)
    return value.strip(" ")


def _utf8(text: str) -> bytes:
    return _LONE_SURROGATE.sub(_REPLACEMENT, text).encode("utf-8")


def text_hash(normalized: str) -> str:
    """SHA-256 (hex) от UTF-8 нормализованного текста."""
    return hashlib.sha256(_utf8(normalized)).hexdigest()


def count_words(normalized: str) -> int:
    """Слова — по пробелам нормализованного текста; пустой текст — 0 слов."""
    return len(normalized.split(" ")) if normalized else 0


@dataclass(frozen=True)
class PreparedText:
    """Текст, готовый к проверке: что уходит в модель, ключ кэша и число слов."""

    text: str
    hash: str
    words: int


def _prepare(text: str) -> PreparedText:
    normalized = normalize_text(text)
    return PreparedText(text=normalized, hash=text_hash(normalized), words=count_words(normalized))


# Подборка зовёт `prepare` для каждой записи на каждом шаге — короткие тексты (а это почти
# все посты) запоминаем; длинные не держим в памяти, их нормализация дешевле риска.
_CACHED_MAX_CHARS = 5_000
_prepare_cached = lru_cache(maxsize=2048)(_prepare)


def prepare(text: str) -> PreparedText:
    """Нормализация, хеш и слова одним вызовом."""
    if len(text) > _CACHED_MAX_CHARS:
        return _prepare(text)
    return _prepare_cached(text)
