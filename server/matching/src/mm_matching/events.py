"""Шаг 3 воронки: признаки события — кто, где, когда, какие числа (Natasha и правила).

Нужен, чтобы отсечь «другое событие на ту же тему»: два ДТП или два пожара в крае
эмбеддинги считают похожими, а место, дата и числа у них разные.
"""

from __future__ import annotations

import inspect
import re
import threading
from dataclasses import dataclass
from typing import Any

from mm_matching.text import normalize_word
from mm_matching.types import EventSigns

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}  # fmt: skip
_MONTH_RE = (
    r"(январ[ья]|феврал[ья]|марта?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|августа?|"
    r"сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])"
)
_DATE_WORDS_RE = re.compile(
    rf"\b(\d{{1,2}})(?:\s*[-–—]\s*\d{{1,2}})?\s+{_MONTH_RE}(?:\s+(\d{{4}}))?", re.IGNORECASE
)
_DATE_DOTS_RE = re.compile(r"\b(\d{1,2})[.-](\d{1,2})[.-](\d{2,4})\b")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
# Номера статей закона («ч. 1 ст. 238 УК РФ») одинаковы у разных дел — это не признак события.
_LAW_REF_RE = re.compile(r"(?:\bст|стать[яиеюй]|\bч|част[ьиюя]|\bп|пункт[аеу]?)\.?\s*$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![\w])")
_YEAR_RE = re.compile(r"^(19|20)\d\d$")

# Места, которые есть почти в каждой новости края: совпадение ничего не доказывает.
_GENERIC_PLACES = frozenset(
    {
        "красноярский край", "край", "россия", "рф", "российская федерация", "сибирь",
        "красноярье", "регион", "енисейская сибирь", "сфо", "хакасия", "республика хакасия",
    }
)  # fmt: skip
# Места, которые есть в большинстве новостей края: не подтверждают «то же событие»,
# но разные места по-прежнему считаются противоречием. Основы по 5 букв.
_FREQUENT_PLACE_STEMS = frozenset({"красн"})


def _patch_inspect() -> None:
    """pymorphy2 (зависимость Natasha) зовёт inspect.getargspec, которого нет в Python 3.11+."""
    if not hasattr(inspect, "getargspec"):

        def getargspec(func: Any) -> tuple[Any, Any, Any, Any]:
            spec = inspect.getfullargspec(func)
            return spec.args, spec.varargs, spec.varkw, spec.defaults

        inspect.getargspec = getargspec  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class _Signs:
    """Признаки в виде для сравнения (основы слов) плюс читаемый вид для показа."""

    places: frozenset[str]
    persons: frozenset[str]
    orgs: frozenset[str]
    dates: frozenset[tuple[int, int]]
    numbers: frozenset[str]
    shown: EventSigns


@dataclass(frozen=True, slots=True)
class EventComparison:
    support: int  # сколько видов признаков совпало (место, дата, люди, числа)
    conflict: int  # сколько видов признаков противоречат
    shared: tuple[str, ...]  # что совпало — для пояснения «совпадают: Канск, 14.10»
    differs: tuple[str, ...]  # что не совпало — «другая дата и место»


class EventExtractor:
    """Извлекает признаки события. Модели Natasha грузятся один раз (≈1 с)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = False
        self._segmenter: Any = None
        self._ner: Any = None
        self._morph: Any = None
        self._cache: dict[str, _Signs] = {}

    def _load(self) -> None:
        if self._ready:
            return
        _patch_inspect()
        import pymorphy2
        import pymorphy2_dicts_ru
        from natasha import NewsEmbedding, NewsNERTagger, Segmenter

        self._segmenter = Segmenter()
        self._ner = NewsNERTagger(NewsEmbedding())
        # Словарь задаём путём: поиск через pkg_resources в новых setuptools не работает.
        self._morph = pymorphy2.MorphAnalyzer(path=pymorphy2_dicts_ru.get_path())
        self._ready = True

    def signs(self, text: str) -> EventSigns:
        return self._extract(text).shown

    def _extract(self, text: str) -> _Signs:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        with self._lock:
            self._load()
            result = self._extract_locked(text)
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[text] = result
        return result

    def _extract_locked(self, text: str) -> _Signs:
        from natasha import Doc

        doc = Doc(text)
        doc.segment(self._segmenter)
        doc.tag_ner(self._ner)
        places: dict[str, str] = {}
        persons: dict[str, str] = {}
        orgs: dict[str, str] = {}
        for span in doc.spans:
            lemma = self._lemmatize(span.text)
            if not lemma:
                continue
            if span.type == "LOC":
                if lemma not in _GENERIC_PLACES:
                    places.setdefault(lemma, lemma[:1].upper() + lemma[1:])
            elif span.type == "PER":
                persons.setdefault(lemma, _title(lemma))
            elif span.type == "ORG":
                orgs.setdefault(lemma, span.text)
        dates, date_spans = _dates(text)
        date_spans += [(m.start(), m.end()) for m in _TIME_RE.finditer(text)]
        numbers = _numbers(text, date_spans)
        shown = EventSigns(
            who=tuple(list(persons.values()) + list(orgs.values()))[:8],
            where=tuple(places.values())[:8],
            when=tuple(f"{d:02d}.{m:02d}" for d, m in sorted(dates, key=lambda x: (x[1], x[0])))[:8],
            numbers=tuple(sorted(numbers, key=_num_key))[:12],
        )
        return _Signs(
            places=frozenset(_place_stems(places)),
            persons=frozenset(_person_stems(persons)),
            orgs=frozenset(orgs),
            dates=frozenset(dates),
            numbers=frozenset(numbers),
            shown=shown,
        )

    def _lemmatize(self, phrase: str) -> str:
        words = re.findall(r"[^\W_]+", phrase)
        lemmas = []
        for w in words:
            parses = self._morph.parse(w)
            lemmas.append(normalize_word(str(parses[0].normal_form)) if parses else normalize_word(w))
        return " ".join(lemmas)

    def compare(self, a: str, b: str) -> EventComparison:
        return compare_signs(self._extract(a), self._extract(b))


def _title(lemma: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in lemma.split())


def _place_stems(places: dict[str, str]) -> set[str]:
    # «Ачинский район» и «Ачинск» должны совпасть: сравниваем основы из 5 букв.
    out = set()
    for lemma in places:
        for w in lemma.split():
            if w not in {"район", "город", "поселок", "село", "улица", "область", "округ", "муниципальный"}:
                out.add(w[:5])
    return out


def _person_stems(persons: dict[str, str]) -> set[str]:
    # Фамилия — последнее слово; «Иван Петров» и «Петров» совпадают.
    return {lemma.split()[-1][:6] for lemma in persons if lemma}


def _dates(text: str) -> tuple[set[tuple[int, int]], list[tuple[int, int]]]:
    out: set[tuple[int, int]] = set()
    spans: list[tuple[int, int]] = []
    for m in _DATE_WORDS_RE.finditer(text):
        day = int(m.group(1))
        word = m.group(2).lower()
        month = next((v for k, v in _MONTHS.items() if word.startswith(k)), 0)
        if 1 <= day <= 31 and month:
            out.add((day, month))
            spans.append((m.start(), m.end()))
    for m in _DATE_DOTS_RE.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        if 1 <= day <= 31 and 1 <= month <= 12:
            out.add((day, month))
            spans.append((m.start(), m.end()))
    return out, spans


def _numbers(text: str, skip: list[tuple[int, int]]) -> set[str]:
    out: set[str] = set()
    for m in _NUMBER_RE.finditer(text):
        if any(s <= m.start() < e for s, e in skip):
            continue
        if _LAW_REF_RE.search(text[max(0, m.start() - 12) : m.start()]):
            continue
        value = m.group().replace(",", ".")
        if _YEAR_RE.match(value):
            continue  # год есть почти в каждой новости
        out.add(value)
    return out


def _num_key(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _specific_numbers(numbers: frozenset[str]) -> set[str]:
    """Числа, совпадение которых что-то значит: не 1–9 (их слишком много в любом тексте)."""
    return {n for n in numbers if "." in n or _num_key(n) >= 10}


def compare_signs(a: _Signs, b: _Signs) -> EventComparison:
    shared: list[str] = []
    differs: list[str] = []
    support = 0
    conflict = 0

    if a.places and b.places:
        common = a.places & b.places
        specific = common - _FREQUENT_PLACE_STEMS
        if specific:
            support += 1
            shared.extend(p for p in b.shown.where if p.lower()[:5] in specific)
        elif not common:
            conflict += 1
            differs.append("место")
    if a.dates and b.dates:
        common_d = a.dates & b.dates
        if common_d:
            support += 1
            shared.extend(f"{d:02d}.{m:02d}" for d, m in sorted(common_d))
        else:
            conflict += 1
            differs.append("дата")
    # Разные люди в двух текстах — не противоречие: в пересказе часть имён опускают.
    if a.persons and b.persons and a.persons & b.persons:
        support += 1
        shared.extend(p for p in b.shown.who if p.lower().split()[-1][:6] in a.persons)
    na, nb = _specific_numbers(a.numbers), _specific_numbers(b.numbers)
    if na and nb:
        common_n = na & nb
        if common_n:
            support += 1
            shared.extend(sorted(common_n, key=_num_key)[:3])
        elif len(na) >= 2 and len(nb) >= 2:
            conflict += 1
            differs.append("числа")
    return EventComparison(support, conflict, tuple(dict.fromkeys(shared))[:6], tuple(differs))
