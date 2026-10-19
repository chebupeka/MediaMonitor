"""Нормализация текста, токены с позициями, предложения и абзацы.

Все отрезки — в координатах исходной строки: `text[start:end]`. Сервер должен
делить `publication.text` на предложения этой же функцией (`split_sentences`),
иначе номер предложения-доказательства разойдётся с интерфейсом.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from razdel import sentenize

from mm_matching.types import Sentence, TextRange

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_PARAGRAPH_RE = re.compile(r"[^\n]+")

# Частые служебные слова: не считаем их «общими словами» при выборе доказательства.
STOPWORDS = frozenset(
    """
    а без более бы был была были было быть в вам вас весь во вот все всего всех вы где да даже
    для до его ее если есть еще же за здесь и из или им их к как когда кто ли либо мы на над
    надо наш не него нее нет ни них но ну о об однако он она они оно от по под при про с так
    также такой там те тем то того тоже той только том ты у уже хотя чего чей чем что чтобы
    эта эти это этого этой этом этот я который которая которые которых году года год г
    будет будут может могут очень после через между свой своих своей этих сам сама
    сообщает сообщил сообщили сообщают рассказали рассказал отметил отметили
    """.split()
)


@dataclass(frozen=True, slots=True)
class Token:
    """Слово с позицией в исходном тексте. `norm` — нижний регистр, ё→е."""

    norm: str
    start: int
    end: int


def normalize_word(word: str) -> str:
    return word.lower().replace("ё", "е")


def clean(text: str) -> str:
    """Унификация символов без сдвига позиций нам не нужна — NFKC только для хеша."""
    return unicodedata.normalize("NFKC", text)


def tokenize(text: str) -> list[Token]:
    """Слова (буквы и цифры) с позициями. Ссылки пропускаем: они не текст новости."""
    url_spans = [(m.start(), m.end()) for m in _URL_RE.finditer(text)]
    tokens: list[Token] = []
    span_i = 0
    for m in _TOKEN_RE.finditer(text):
        while span_i < len(url_spans) and url_spans[span_i][1] <= m.start():
            span_i += 1
        if span_i < len(url_spans) and url_spans[span_i][0] <= m.start() < url_spans[span_i][1]:
            continue
        tokens.append(Token(normalize_word(m.group()), m.start(), m.end()))
    return tokens


def normalized_text(text: str) -> str:
    """Текст для точного сравнения: слова через пробел, без регистра, ё, пунктуации и ссылок."""
    return " ".join(t.norm for t in tokenize(clean(text)))


def text_hash(text: str) -> str:
    """Хеш нормализованного текста (ТЗ-Ф30): одинаков для текстов, отличающихся
    только регистром, пробелами, пунктуацией, ё/е и ссылками."""
    return hashlib.blake2b(normalized_text(text).encode("utf-8"), digest_size=16).hexdigest()


def stem(word: str) -> str:
    """Грубая основа слова для сравнения пересказов: первые 5 букв."""
    return word[:5]


def content_stems(tokens: list[Token]) -> set[str]:
    return {stem(t.norm) for t in tokens if len(t.norm) > 2 and t.norm not in STOPWORDS}


def split_paragraphs(text: str) -> list[TextRange]:
    """Абзацы — непустые строки (перенос строки = граница абзаца)."""
    out: list[TextRange] = []
    for m in _PARAGRAPH_RE.finditer(text):
        start, end = _strip_span(text, m.start(), m.end())
        if end > start:
            out.append(TextRange(start, end))
    return out


def split_sentences(text: str) -> list[Sentence]:
    """Предложения с позициями. Границы: конец абзаца и razdel внутри абзаца."""
    return list(_split_sentences_cached(text))


@lru_cache(maxsize=4096)
def _split_sentences_cached(text: str) -> tuple[Sentence, ...]:
    out: list[Sentence] = []
    for para in split_paragraphs(text):
        chunk = text[para.start : para.end]
        for s in sentenize(chunk):
            start, end = _strip_span(text, para.start + int(s.start), para.start + int(s.stop))
            if end > start:
                out.append(Sentence(len(out), start, end))
    return tuple(out)


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def merge_ranges(ranges: list[TextRange], text: str, max_gap: int = 3) -> list[TextRange]:
    """Склеивает соседние отрезки, если между ними только пробелы и знаки препинания."""
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda r: (r.start, r.end))
    out = [ordered[0]]
    for r in ordered[1:]:
        last = out[-1]
        gap = text[last.end : r.start]
        if r.start <= last.end or (len(gap) <= max_gap and not _TOKEN_RE.search(gap)):
            out[-1] = TextRange(last.start, max(last.end, r.end))
        else:
            out.append(r)
    return out
