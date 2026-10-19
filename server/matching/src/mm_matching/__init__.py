"""MediaMonitor: воронка смыслового отбора публикаций (решения Р5–Р6).

Сервер работает с интерфейсом `Matcher`; реализация — `FunnelMatcher`.

    from mm_matching import Candidate, create_matcher
    matcher = create_matcher()          # модели и OLLAMA_URL — из окружения
    matcher.warmup()                    # при старте сервера
    report = matcher.match_news(release_text, candidates)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from mm_matching.config import LlmSettings, MatcherConfig
from mm_matching.funnel import FunnelMatcher, OnResult
from mm_matching.types import (
    Candidate,
    Citation,
    EventSigns,
    Evidence,
    Excerpt,
    LlmStatus,
    MatchReport,
    MatchResult,
    PlacementType,
    QueryKind,
    ReleaseFragmentInfo,
    Relevance,
    Scores,
    SelectionMethod,
    Sentence,
    TextRange,
    TopicCard,
    TopicFacet,
)


@runtime_checkable
class Matcher(Protocol):
    """Что сервер получает от отбора. Все методы синхронные и потокобезопасные;
    в FastAPI вызывайте их через `run_in_threadpool` (CPU и сеть до Ollama)."""

    def warmup(self) -> None: ...

    def prefetch(self, candidates: Sequence[Candidate], kind: QueryKind) -> None: ...

    def split_sentences(self, text: str) -> list[Sentence]: ...

    def text_hash(self, text: str) -> str: ...

    def find_repeats(self, candidates: Sequence[Candidate]) -> dict[str, str]: ...

    def group_copies(self, candidates: Sequence[Candidate], threshold: float = 0.8) -> list[list[str]]: ...

    def event_signs(self, text: str) -> EventSigns: ...

    def topic_card(self, query: str, kind: QueryKind = "topic") -> TopicCard: ...

    def correct_topic_card(
        self,
        card: TopicCard,
        *,
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        add_includes: Sequence[str] = (),
        add_excludes: Sequence[str] = (),
    ) -> TopicCard: ...

    def match_news(
        self, release_text: str, candidates: Sequence[Candidate], *, on_result: OnResult | None = None
    ) -> MatchReport: ...

    def match_topic(
        self,
        query: str | TopicCard,
        candidates: Sequence[Candidate],
        *,
        kind: QueryKind = "topic",
        on_result: OnResult | None = None,
    ) -> MatchReport: ...


def create_matcher(config: MatcherConfig | None = None) -> Matcher:
    """Воронка с настройками из окружения: `EMBEDDING_MODEL`, `OLLAMA_URL`, `OLLAMA_MODEL`…"""
    return FunnelMatcher(config)


__all__ = [
    "Candidate",
    "Citation",
    "EventSigns",
    "Evidence",
    "Excerpt",
    "FunnelMatcher",
    "LlmSettings",
    "LlmStatus",
    "MatchReport",
    "MatchResult",
    "Matcher",
    "MatcherConfig",
    "OnResult",
    "PlacementType",
    "QueryKind",
    "ReleaseFragmentInfo",
    "Relevance",
    "Scores",
    "SelectionMethod",
    "Sentence",
    "TextRange",
    "TopicCard",
    "TopicFacet",
    "create_matcher",
]
