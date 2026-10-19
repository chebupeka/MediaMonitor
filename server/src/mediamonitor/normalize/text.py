"""Текст поста: предложения, выдержка, заголовок, нормализация для сравнения.

Выдержка всегда — подстрока настоящего текста (ТЗ-Ф34, Р5): строим её только
по границам предложений исходного текста.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from mediamonitor.labels import truncate_text

HEADLINE_MAX = 120
EXCERPT_MAX = 280

# Сокращения, после которых точка не заканчивает предложение.
_ABBREVIATIONS = {
    "г",
    "гг",
    "ул",
    "пр",
    "пр-т",
    "пер",
    "д",
    "им",
    "т",
    "тыс",
    "млн",
    "млрд",
    "руб",
    "коп",
    "см",
    "ст",
    "п",
    "пос",
    "обл",
    "р-н",
    "р",
    "с",
    "кв",
    "корп",
    "стр",
    "мкр",
    "др",
    "т.е",
    "т.д",
    "т.п",
}
_BOUNDARY = re.compile(r"[.!?…]+[»\"”')\]]*(?=\s)|\n+")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Span:
    start: int
    end: int


def split_sentences(text: str) -> list[Span]:
    """Разбить текст на предложения: границы в символах исходного текста, без пробелов по краям."""
    spans: list[Span] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        end = match.end()
        if match.group(0)[0] == "." and not match.group(0).startswith(".."):
            word = re.search(r"([\w\-.]+)\.$", text[start : match.start() + 1])
            token = (word.group(1) if word else "").lower()
            nxt = text[end:].lstrip()[:1]
            # «г. Красноярск», «А. С. Пушкин» — не конец предложения.
            if token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha()) or nxt.islower():
                continue
        _push(text, start, end, spans)
        start = end
    _push(text, start, len(text), spans)
    return spans


def _push(text: str, start: int, end: int, spans: list[Span]) -> None:
    chunk = text[start:end]
    left = len(chunk) - len(chunk.lstrip())
    right = len(chunk.rstrip())
    if right > left:
        spans.append(Span(start + left, start + right))


def headline(title: str | None, text: str | None, spans: list[Span]) -> tuple[str, bool]:
    """Заголовок или начало поста (ТЗ-Ф34). Второе значение — взят ли заголовок площадки."""
    if title and title.strip():
        return truncate_text(title.strip(), HEADLINE_MAX), True
    if text and spans:
        first = spans[0]
        return truncate_text(text[first.start : first.end], HEADLINE_MAX), False
    return "Пост без текста", False


def excerpt_bounds(spans: list[Span], index: int, text_length: int) -> tuple[int, int]:
    """Выдержка от предложения `index` и до двух следующих, пока помещается в EXCERPT_MAX."""
    first = spans[index]
    end = first.end
    for j in range(index + 1, min(len(spans), index + 3)):
        if spans[j].end - first.start > EXCERPT_MAX:
            break
        end = spans[j].end
    return first.start, min(end, text_length)


def words(text: str) -> list[str]:
    """Слова в нижнем регистре, «ё» → «е»."""
    return [w.lower().replace("ё", "е") for w in _WORD.findall(text)]


def shingles(text: str, size: int = 3) -> set[str]:
    """Фразы из `size` подряд идущих слов — основа поиска копий (шаг 1 воронки)."""
    tokens = words(text)
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def content_hash(text: str | None) -> str | None:
    """Хеш нормализованного текста: одинаковые тексты с разной разметкой совпадают."""
    if not text:
        return None
    normalized = " ".join(words(text))
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def clean_text(value: str | None) -> str | None:
    """Убрать управляющие символы (кроме переводов строки) и нулевые байты; пустое → None."""
    if value is None:
        return None
    cleaned = "".join(ch for ch in value if ch in "\n\t" or ch >= " ").replace("\r", "")
    cleaned = cleaned.strip()
    return cleaned or None
