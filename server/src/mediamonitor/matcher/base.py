"""Интерфейс воронки отбора `Matcher` (Р5, `docs/12-tech-design.md`, «Отбор»).

Сервер отдаёт воронке нормализованных кандидатов и получает решение по каждому:
оставить или нет, метка, метод, доказательство, тип размещения, кластер копий.
Воронка НЕ пишет ссылок, дат, заголовков и выдержек: их сервер берёт только из
записи поста (К14). Номер предложения-доказательства сервер ещё раз проверяет.

Настоящую воронку (MinHash → эмбеддинги → признаки события → нейросеть) делает
«Э-Отбор» в `server/matching/`; подключается настройкой MATCHER=«модуль:функция».
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from mediamonitor.ai.judge import AiJudge
from mediamonitor.contract import (
    PlacementType,
    PlatformId,
    QueryKind,
    Relevance,
    SelectionMethod,
    TopicUnderstanding,
)
from mediamonitor.normalize.query import ReleaseFragmentText, ReleaseText
from mediamonitor.normalize.text import Span


@dataclass(frozen=True)
class QueryContext:
    """Что ищем: запрос, вид, карточка темы, релиз (для поиска перепечаток)."""

    text: str
    kind: QueryKind
    label: str
    meaning_id: str | None
    topic: TopicUnderstanding | None
    release: ReleaseText | None


@dataclass(frozen=True)
class Candidate:
    """Нормализованный пост-кандидат. `id` — ключ публикации (`vk:-100123_4567`)."""

    id: str
    platform: PlatformId
    source_id: str
    title: str | None
    text: str | None
    sentences: Sequence[Span]
    source_name: str
    source_regional: bool
    places: Sequence[str]
    published_at: datetime | None
    is_repost: bool
    has_media: bool
    content_hash: str | None


@dataclass(frozen=True)
class EvidenceDraft:
    """Доказательство: номер предложения и отрезки подсветки в координатах текста поста."""

    sentence_index: int
    ranges: Sequence[tuple[int, int]]
    basis: Literal["ai", "release-match", "semantic"]
    note: str | None = None


@dataclass(frozen=True)
class Decision:
    id: str
    keep: bool
    relevance: Relevance = "disputed"
    method: SelectionMethod = "semantic"
    method_note: str | None = None
    evidence: EvidenceDraft | None = None
    placement_type: PlacementType | None = None
    # Доля релиза, вошедшая дословно, и id абзацев (П1) — только для текста новости.
    citation: tuple[float, tuple[str, ...]] | None = None
    # Кластер копий: одинаковый ключ — одна группа (Р9). Название группы — подсказка.
    cluster: str | None = None
    cluster_title: str | None = None
    cluster_kind: Literal["release", "copies"] | None = None
    # Для отсечённых: какая грань «не то» отсекла и почему (карточка темы, SC-14).
    cut_facet: str | None = None
    cut_reason: str | None = None


@dataclass(frozen=True)
class StandNote:
    """Строка для страницы стенда (НТ-18): состояние моделей воронки."""

    level: Literal["info", "warning", "error"]
    message: str


class VectorStore(Protocol):
    """Кэш векторов смысла в базе (Р7): ключ — пост, модель с версией и задача."""

    async def load(self, model: str, kind: str, keys: Mapping[str, str]) -> dict[str, list[float]]:
        """`keys`: id публикации → хеш текста. Отдаёт векторы, посчитанные по этому тексту."""
        ...

    async def save(
        self, model: str, kind: str, rows: Sequence[tuple[str, str, Sequence[float]]]
    ) -> None:
        """Строки (id публикации, хеш текста, вектор): новые записываются, старые заменяются."""
        ...


class MatchSession(Protocol):
    """Отбор в рамках одного поиска. Может помнить кластеры между порциями."""

    @property
    def ai_failed(self) -> bool:
        """Нейросеть была нужна, но не ответила: спорные получили «не проверено ИИ»."""
        ...

    async def classify(self, candidates: Sequence[Candidate]) -> list[Decision]:
        """Решение по каждому кандидату — в том же порядке."""
        ...


class Matcher(Protocol):
    name: str

    def split_sentences(self, text: str) -> list[Span]:
        """Разбиение на предложения: номер доказательства воронки ссылается на него."""
        ...

    def release_fragments(self, text: str) -> tuple[ReleaseFragmentText, ...]:
        """Абзацы релиза (П1): на их id ссылается цитирование `Decision.citation`."""
        ...

    async def topic_card(
        self, text: str, kind: QueryKind, meaning: str | None
    ) -> TopicUnderstanding | None:
        """Карточка «как система поняла тему». None — пусть сервер составит свою."""
        ...

    async def warmup(self) -> None:
        """Загрузить модели при старте сервера, чтобы первый поиск не ждал (НТ-18)."""
        ...

    def stand_notes(self) -> list[StandNote]:
        """Состояние моделей для страницы стенда."""
        ...

    def start(
        self, query: QueryContext, judge: AiJudge, ai_available: bool, vectors: VectorStore
    ) -> MatchSession: ...
