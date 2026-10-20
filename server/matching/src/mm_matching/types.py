"""Типы результата отбора. Повторяют контракт интерфейса `web/src/api/types.ts`.

Соответствие полей (Python → TypeScript):
- `MatchResult.relevance` → `ResultItem.relevance` ('direct' | 'indirect' | 'disputed');
- `MatchResult.method` / `method_note` → `ResultItem.method` / `methodNote`;
- `MatchResult.evidence` → `ResultItem.evidence` (`sentence_index` → `sentenceIndex`);
- `MatchResult.excerpt` → `ResultItem.excerpt` (`cut_start` → `cutStart` …);
- `MatchResult.placement_type` → `ResultItem.placementType`;
- `MatchResult.citation` → `ResultItem.citation` (`fragment_ids` → `fragmentIds`);
- `MatchResult.sentences` → `Publication.sentences`;
- `ReleaseFragmentInfo` → `ReleaseFragment` (`taken_by` → `takenBy`);
- `TopicCard` → `TopicUnderstanding`, `EventSigns` → `EventSigns`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Relevance = Literal["direct", "indirect", "disputed"]
SelectionMethod = Literal["copy", "semantic", "ai-confirmed", "ai-unchecked", "manual"]
PlacementType = Literal["verbatim", "shortened", "retold", "repost"]
EvidenceBasis = Literal["ai", "release-match", "semantic"]
QueryKind = Literal["topic", "event", "news-text"]

# Какой шаг воронки принял решение — для оценки и отладки, в интерфейс не идёт.
Stage = Literal["hash", "shingles", "embeddings", "events", "rules", "llm", "no-text"]
# Зона правил: явно да / явно нет / серая.
Zone = Literal["yes", "no", "gray"]


@dataclass(frozen=True, slots=True)
class TextRange:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Sentence:
    index: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Candidate:
    """Публикация-кандидат. Все поля — из записи поста, нейросеть их не видит, кроме `text`.

    - `id` — ключ публикации на сервере (`vk:-100123_4567`);
    - `source_id` — источник (группа, канал): нужен для поиска повторов одного поста;
    - `is_repost` — площадка отдала пост как репост (тип размещения «репост», П2).
    """

    id: str
    text: str | None
    source_id: str | None = None
    title: str | None = None
    published_at: datetime | None = None
    is_repost: bool = False


@dataclass(frozen=True, slots=True)
class Evidence:
    sentence_index: int
    ranges: tuple[TextRange, ...]
    basis: EvidenceBasis
    note: str | None


@dataclass(frozen=True, slots=True)
class Excerpt:
    start: int
    end: int
    text: str
    cut_start: bool
    cut_end: bool


@dataclass(frozen=True, slots=True)
class Citation:
    """Полнота цитирования (П1): доля текста релиза, вошедшая дословно, и абзацы релиза."""

    share: float
    fragment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventSigns:
    """Признаки события (шаг 3): кто, где, когда, какие числа. Только из текста, кодом."""

    who: tuple[str, ...] = ()
    where: tuple[str, ...] = ()
    when: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Scores:
    """Числа, по которым решала воронка. `None` — шаг не выполнялся."""

    release_share: float | None = None  # доля релиза, вошедшая дословно
    post_share: float | None = None  # доля поста, взятая из релиза дословно
    jaccard: float | None = None  # оценка MinHash
    cosine: float | None = None  # смысловая близость к запросу
    anti_cosine: float | None = None  # близость к «не то» карточки темы
    event_support: int | None = None  # совпавшие признаки события
    event_conflict: int | None = None  # противоречащие признаки события
    evidence_cosine: float | None = None  # близость предложения-доказательства ИИ к запросу


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Решение по одному кандидату. `included=False` — в подборку не идёт, `reason` объясняет."""

    candidate_id: str
    included: bool
    relevance: Relevance | None
    method: SelectionMethod
    method_note: str | None
    reason: str
    stage: Stage
    zone: Zone
    sentences: tuple[Sentence, ...]
    evidence: Evidence | None
    excerpt: Excerpt | None
    placement_type: PlacementType | None = None
    citation: Citation | None = None
    text_hash: str | None = None
    scores: Scores = field(default_factory=Scores)
    # Поиск по теме: грань карточки, из-за которой пост отсечён («не то») или найден.
    facet_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReleaseFragmentInfo:
    """Абзац релиза для карты фрагментов (П1)."""

    id: str
    index: int
    text: str
    start: int
    end: int
    taken_by: int
    of: int


LlmState = Literal["used", "unavailable", "not-configured", "not-needed", "partial"]


@dataclass(frozen=True, slots=True)
class LlmStatus:
    """Что было с нейросетью в этом поиске. Для пометки `ai-unavailable` (SC-08)."""

    state: LlmState
    checked: int = 0
    unchecked: int = 0
    message: str | None = None


@dataclass(frozen=True, slots=True)
class MatchReport:
    results: tuple[MatchResult, ...]
    llm: LlmStatus
    fragments: tuple[ReleaseFragmentInfo, ...] = ()
    timings: dict[str, float] = field(default_factory=dict)


FacetOrigin = Literal["system", "user"]


@dataclass(frozen=True, slots=True)
class TopicFacet:
    id: str
    label: str
    origin: FacetOrigin = "system"


@dataclass(frozen=True, slots=True)
class TopicCard:
    """«Как система поняла тему» (ТЗ-Ф7). `made_by='rules'` — нейросеть недоступна."""

    query: str
    summary: str
    includes: tuple[TopicFacet, ...]
    excludes: tuple[TopicFacet, ...]
    made_by: Literal["ai", "rules"]
    note: str | None = None
    signs: EventSigns | None = None
