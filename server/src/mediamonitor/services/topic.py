"""«Как система поняла тему» (ТЗ-Ф7, Р5, П14, SC-14).

Карточку составляет нейросеть один раз на запрос. Если она недоступна — карточка
по словам запроса с пометкой «смысловая проверка недоступна». Примеров формулировок
нейросеть не пишет: пример должен быть дословно из поста (К14), поэтому `example`
появляется только из настоящих публикаций, а «что отсекли» — из отсечённых постов поиска.
"""

from __future__ import annotations

import re
from collections import OrderedDict

from mediamonitor.ai.judge import AiJudge
from mediamonitor.contract import (
    EventSigns,
    QueryKind,
    TopicCorrection,
    TopicFacet,
    TopicUnderstanding,
)
from mediamonitor.labels import truncate_text
from mediamonitor.matcher.base import Matcher
from mediamonitor.normalize.query import detect_kind, meaning_label
from mediamonitor.normalize.region import find_places

RULES_NOTE = (
    "Смысловая проверка недоступна: нейросеть не отвечает, карточка составлена по словам "
    "запроса. Спорные публикации будут помечены «не проверено ИИ»."
)
_NUMBERS = re.compile(
    r"\b\d[\d\s]{0,12}(?:[.,]\d+)?\s*(?:%|руб\w*|тыс\w*|млн|человек|мест|класс\w*)?", re.UNICODE
)
_DATES = re.compile(
    r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
    r"|\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b",
    re.IGNORECASE,
)


def _rules_signs(text: str) -> EventSigns:
    numbers = [m.group(0).strip() for m in _NUMBERS.finditer(text) if m.group(0).strip()][:5]
    return EventSigns(
        who=[],
        where=find_places(text)[:5],
        when=[m.group(0) for m in _DATES.finditer(text)][:5],
        numbers=list(dict.fromkeys(numbers)),
    )


def rules_topic(text: str, kind: QueryKind, meaning_id: str | None) -> TopicUnderstanding:
    label = truncate_text(" ".join(text.split()), 80) or "Запрос"
    meaning = meaning_label(meaning_id)
    summary_subject = f"{label} ({meaning})" if meaning else label
    return TopicUnderstanding(
        summary=f"Публикации по запросу «{summary_subject}» в соцсетях Красноярского края.",
        includes=[TopicFacet(id="main", label=meaning or label, origin="system")],
        excludes=[],
        signs=_rules_signs(text) if kind != "topic" else None,
        made_by="rules",
        note=RULES_NOTE,
        cut_examples=[],
    )


class TopicService:
    """Карточка темы с кэшем: одна и та же карточка до поиска и в поиске (id граней совпадают)."""

    CACHE_SIZE = 256

    def __init__(self, judge: AiJudge, matcher: Matcher | None = None) -> None:
        self.judge = judge
        self.matcher = matcher
        self._cache: OrderedDict[tuple[str, str | None], TopicUnderstanding] = OrderedDict()

    async def _base(
        self, text: str, kind: QueryKind, meaning_id: str | None
    ) -> TopicUnderstanding | None:
        meaning = meaning_label(meaning_id)
        query = f"{text}\n(значение: {meaning})" if meaning else text
        draft = await self.judge.topic_card(query, None)
        if draft is None:
            return None
        signs = None
        if kind != "topic":
            signs = EventSigns(
                who=draft.who, where=draft.where, when=draft.when, numbers=draft.numbers
            )
        return TopicUnderstanding(
            summary=draft.summary,
            includes=[
                TopicFacet(id=f"in-{i + 1}", label=label, origin="system")
                for i, label in enumerate(draft.includes)
            ],
            excludes=[
                TopicFacet(id=f"ex-{i + 1}", label=label, origin="system")
                for i, label in enumerate(draft.excludes)
            ],
            signs=signs,
            made_by="ai",
            note=None,
            cut_examples=[],
        )

    async def understand(
        self,
        ai_available: bool,
        text: str,
        *,
        meaning_id: str | None = None,
        correction: TopicCorrection | None = None,
    ) -> TopicUnderstanding:
        kind = detect_kind(text)
        key = (text.strip(), meaning_id)
        topic = self._cache.get(key)
        if topic is None and self.matcher is not None:
            # Карточку составляет воронка — по ней же она и отбирает (Р5).
            topic = await self.matcher.topic_card(text, kind, meaning_label(meaning_id))
        if topic is None and ai_available:
            topic = await self._base(text, kind, meaning_id)
        if topic is not None and topic.made_by == "ai":
            # Карточку нейросети запоминаем: id граней до поиска и в поиске совпадают.
            self._cache[key] = topic
            while len(self._cache) > self.CACHE_SIZE:
                self._cache.popitem(last=False)
        if topic is None:
            topic = rules_topic(text, kind, meaning_id)
        if correction is not None:
            topic = apply_correction(topic, correction)
        return topic


def apply_correction(topic: TopicUnderstanding, correction: TopicCorrection) -> TopicUnderstanding:
    """Перенос граней между «входит» и «не то» (как в мокапе) + уточнение пользователя."""
    include, exclude = set(correction.include), set(correction.exclude)
    facets = [*topic.includes, *topic.excludes]
    was_included = {f.id for f in topic.includes}

    def moved(facet: TopicFacet, to_user: bool) -> TopicFacet:
        return facet.model_copy(update={"origin": "user"}) if to_user else facet

    includes = [
        moved(f, f.id in include)
        for f in facets
        if f.id in include or (f.id not in exclude and f.id in was_included)
    ]
    excludes = [
        moved(f, f.id in exclude)
        for f in facets
        if f.id in exclude or (f.id not in include and f.id not in was_included)
    ]
    notes = (correction.notes or "").strip()
    if notes:
        includes.append(TopicFacet(id="user-note", label=truncate_text(notes, 80), origin="user"))
    kept = {f.id for f in excludes}
    return topic.model_copy(
        update={
            "includes": includes,
            "excludes": excludes,
            "cut_examples": [
                c for c in topic.cut_examples if c.facet_id is None or c.facet_id in kept
            ],
        }
    )
