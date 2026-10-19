"""Разбор поля запроса (НТ-21, П14, НТ-26) — правила те же, что в имитации мокапа.

Сервер текст сам не меняет — только предлагает подсказки. Тут же: вид запроса
(тема / событие / текст новости), готовые периоды, слова запроса для сравнения,
абзацы релиза для поиска перепечаток.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from importlib import resources
from typing import Any, cast

from mediamonitor.contract import (
    Ambiguity,
    Period,
    PeriodPreset,
    QueryAnalysis,
    QueryHint,
    QueryKind,
    QueryMeaning,
    ReplaceTextFix,
    SetPeriodFix,
)
from mediamonitor.labels import format_number, truncate_text
from mediamonitor.normalize.text import split_sentences, words
from mediamonitor.timeutil import add_days

_I = re.IGNORECASE
LINK_RE = re.compile(r"^\s*(https?://|www\.|vk\.com/|ok\.ru/|max\.ru/)\S*\s*$", _I)
REGION_RE = re.compile(
    r"\s*(?:в|по)\s+(?:красноярском\s+крае|красноярскому\s+краю|нашем\s+крае|крае)(?=[\s,.!?]|$)",
    _I,
)
CONVERSATIONAL_RE = re.compile(
    r"^\s*(?:пожалуйста[,\s]+)?(?:подбери|найди|покажи|собери|поищи|нужны|нужно найти)(?:те)?"
    r"(?:[,\s]+пожалуйста)?[,:\s]+(?:мне\s+)?(?:все\s+)?(?:публикации|посты|новости)?\s*"
    r"(?:про|о|об|по)?\s*",
    _I,
)
TIME_RE = re.compile(
    r"\s*(?:за\s+)?(?:на\s+прошлой\s+неделе|последн(?:юю|ие)\s+(?:неделю|7\s+дней)|за\s+неделю"
    r"|за\s+месяц|последний\s+месяц|сегодня|вчера)",
    _I,
)
OTHER_REGION_RE = re.compile(
    r"(новосибирск|иркутск|омск|томск|кемеров|москв|петербург|барнаул|абакан|хакаси|тыв[аеуы]"
    r"|кузбасс|якут|бурят)",
    _I,
)
KRAI_PLACE_RE = re.compile(
    r"(красноярск|норильск|ачинск|канск|минусинск|лесосибирск|железногорск|зеленогорск|шарыпов"
    r"|дивногорск|енисейск|дудинк|таймыр|эвенки|богучан|назаров|боготол|сосновоборск|край)",
    _I,
)
EVENT_RE = re.compile(r"(енисе|ледостав|навигаци|северн\w*\s+завоз)", _I)

STOP_WORDS = frozenset(
    [
        "и",
        "в",
        "во",
        "на",
        "по",
        "о",
        "об",
        "обо",
        "для",
        "с",
        "со",
        "к",
        "ко",
        "за",
        "от",
        "до",
        "из",
        "у",
        "не",
        "ни",
        "что",
        "это",
        "как",
        "а",
        "но",
        "или",
        "ли",
        "же",
        "бы",
        "при",
        "про",
        "над",
        "под",
        "без",
        "через",
        "после",
        "между",
        "его",
        "ее",
        "их",
        "мы",
        "вы",
        "он",
        "она",
        "они",
        "все",
        "так",
        "там",
        "тут",
        "уже",
        "еще",
        "ещё",
        "пожалуйста",
        "подбери",
        "найди",
        "покажи",
        "собери",
        "поищи",
        "нужны",
        "нужно",
        "мне",
        "новости",
        "публикации",
        "посты",
        "край",
        "крае",
        "краю",
        "края",
        "красноярском",
        "красноярскому",
        "красноярский",
        "красноярского",
        "наш",
        "нашем",
        "который",
        "которая",
        "которые",
        "этот",
        "эта",
        "эти",
        "тот",
        "та",
        "те",
        "свой",
        "своя",
        "свои",
        "был",
        "была",
        "были",
        "будет",
        "быть",
        "год",
        "года",
        "году",
        "лет",
    ]
)


def is_other_region(text: str) -> bool:
    """Запрос про другой регион (НТ-26): упомянут другой регион и не упомянут край."""
    return bool(OTHER_REGION_RE.search(text)) and not KRAI_PLACE_RE.search(text)


def detect_kind(text: str) -> QueryKind:
    trimmed = text.strip()
    sentences = [s for s in re.split(r"[.!?…]+\s", trimmed) if s]
    if len(trimmed) > 240 or len(sentences) >= 3:
        return "news-text"
    if EVENT_RE.search(trimmed):
        return "event"
    return "topic"


def stem(word: str) -> str:
    """Грубая основа слова для сравнения без морфологии: «дорожного» → «дорожно»."""
    if len(word) <= 4:
        return word
    return word[: min(8, max(4, len(word) - 2))]


def query_stems(text: str) -> list[str]:
    """Значимые слова запроса (основы), в порядке появления, без повторов."""
    result: list[str] = []
    for word in words(text):
        if word in STOP_WORDS or len(word) < 3 or word.isdigit():
            continue
        s = stem(word)
        if s not in result:
            result.append(s)
    return result


def preset_period(preset: PeriodPreset, today: date) -> Period:
    match preset:
        case "today":
            return Period(preset=preset, from_=today.isoformat(), to=today.isoformat())
        case "24h":
            return Period(
                preset=preset, from_=add_days(today, -1).isoformat(), to=today.isoformat()
            )
        case "7d":
            return Period(
                preset=preset, from_=add_days(today, -6).isoformat(), to=today.isoformat()
            )
        case _:
            return Period(
                preset=preset, from_=add_days(today, -29).isoformat(), to=today.isoformat()
            )


@dataclass(frozen=True)
class AmbiguousTerm:
    pattern: re.Pattern[str]
    question: str
    options: list[QueryMeaning]


@lru_cache(maxsize=1)
def ambiguous_terms() -> tuple[AmbiguousTerm, ...]:
    raw = cast(
        dict[str, Any],
        json.loads(
            resources.files("mediamonitor.data").joinpath("ambiguous.json").read_text("utf-8")
        ),
    )
    return tuple(
        AmbiguousTerm(
            pattern=re.compile(term["pattern"], _I),
            question=term["question"],
            options=[QueryMeaning.model_validate(o) for o in term["options"]],
        )
        for term in raw["terms"]
    )


def meaning_label(meaning_id: str | None) -> str | None:
    if not meaning_id:
        return None
    for term in ambiguous_terms():
        for option in term.options:
            if option.id == meaning_id:
                return option.label
    return None


def analyze(text: str, *, max_length: int, today: date) -> QueryAnalysis:
    """Подсказки к полю запроса. Порядок и тексты — как в мокапе."""
    trimmed = text.strip()
    hints: list[QueryHint] = []
    if len(trimmed) > max_length:
        hints.append(
            QueryHint(
                code="too-long",
                message=f"Текст длиннее {format_number(max_length)} знаков. Оставьте главное: "
                "заголовок и первые абзацы.",
            )
        )
    if LINK_RE.match(trimmed):
        hints.append(
            QueryHint(
                code="looks-like-link",
                message="Похоже, это ссылка. Вставьте текст новости или опишите тему словами.",
            )
        )
    elif 0 < len(trimmed) < 3:
        hints.append(
            QueryHint(
                code="too-short", message="Слишком короткий запрос. Добавьте пару слов о теме."
            )
        )

    without_region = re.sub(r"\s{2,}", " ", REGION_RE.sub("", trimmed)).strip()
    if without_region != trimmed and without_region:
        hints.append(
            QueryHint(
                code="region-in-text",
                message="Регион уже выбран: Красноярский край. Слова «в Красноярском крае» искать "
                "не нужно — без них найдётся больше.",
                fix=ReplaceTextFix(
                    type="replace-text", label="Убрать из запроса", text=without_region
                ),
            )
        )

    if CONVERSATIONAL_RE.match(trimmed):
        cleaned = CONVERSATIONAL_RE.sub("", trimmed, count=1).strip()
        if cleaned and cleaned != trimmed:
            hints.append(
                QueryHint(
                    code="conversational",
                    message="Достаточно написать тему: просьбы вроде «подбери, пожалуйста» можно "
                    "опустить.",
                    fix=ReplaceTextFix(
                        type="replace-text", label=f"Оставить «{cleaned}»", text=cleaned
                    ),
                )
            )

    time_match = TIME_RE.search(trimmed)
    if time_match:
        phrase = time_match.group(0).strip()
        lowered = phrase.lower()
        preset: PeriodPreset = (
            "today"
            if "сегодня" in lowered
            else "24h"
            if "вчера" in lowered
            else "30d"
            if "месяц" in lowered
            else "7d"
        )
        hints.append(
            QueryHint(
                code="time-words",
                message="Период лучше задать кнопками ниже — так поиск будет точнее.",
                fix=SetPeriodFix(
                    type="set-period",
                    label=f"Поставить период «{phrase}»",
                    period=preset_period(preset, today),
                ),
            )
        )

    if is_other_region(trimmed):
        hints.append(
            QueryHint(
                code="other-region",
                message="Поиск ограничен Красноярским краем. Публикации о другом регионе найдутся, "
                "только если в них упоминается край.",
            )
        )

    ambiguity = None
    for term in ambiguous_terms():
        if term.pattern.match(trimmed):
            ambiguity = Ambiguity(question=term.question, options=list(term.options))
            break
    return QueryAnalysis(text=text, kind=detect_kind(trimmed), hints=hints, ambiguity=ambiguity)


# ---------------------------------------------------------------- релиз (П1)


@dataclass(frozen=True)
class ReleaseFragmentText:
    id: str
    index: int
    text: str


@dataclass(frozen=True)
class ReleaseText:
    title: str
    text: str
    fragments: tuple[ReleaseFragmentText, ...]


def release_of(text: str) -> ReleaseText:
    """Текст новости → заголовок и абзацы (фрагменты для «карты фрагментов», П1)."""
    clean = text.strip().replace("\r\n", "\n")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", clean) if p.strip()]
    title_source = paragraphs[0] if paragraphs else clean
    first_line_is_title = (
        len(paragraphs) > 1
        and len(title_source) <= 120
        and not title_source.endswith((".", "!", "?"))
    )
    if first_line_is_title:
        body = paragraphs[1:]
        title = title_source
    else:
        body = paragraphs
        spans = split_sentences(title_source)
        first = title_source[spans[0].start : spans[0].end] if spans else title_source
        title = truncate_text(first.rstrip("."), 80)
    fragments = tuple(
        ReleaseFragmentText(id=f"p{i + 1}", index=i, text=p)
        for i, p in enumerate(body or paragraphs)
    )
    return ReleaseText(title=title, text=clean, fragments=fragments)


def conditions_label(text: str, kind: QueryKind, release: ReleaseText | None) -> str:
    """Короткая подпись запроса для строки состояния (SearchConditions.label)."""
    if kind == "news-text" and release is not None:
        return release.title
    trimmed = " ".join(text.split())
    return f"{trimmed[:48]}…" if len(trimmed) > 48 else trimmed
