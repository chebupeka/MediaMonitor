"""Интерфейс адаптера площадки (Р2, `07-plan.md`: «отдельный адаптер на каждую площадку»).

Адаптер только получает данные площадки: кандидатов поиска, пост по ключу,
сведения об источнике. Нормализует, отбирает и хранит — остальной сервер.

Сбой площадки — исключение `AdapterError` с кодом из контракта (НТ-3). Ответ, который
не удалось разобрать, — это `bad-response`, а не «ничего не найдено» (НТ-5).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from mediamonitor.contract import (
    DataFreshness,
    HealthState,
    PlatformId,
    PlatformState,
    ProblemCode,
    SourceType,
    TimeReliability,
)
from mediamonitor.normalize.urls import PostRef


@dataclass(frozen=True)
class SourceInfo:
    """Источник, как его знает площадка (группа, сообщество, канал)."""

    platform: PlatformId
    owner_id: str
    slug: str | None
    name: str
    url: str
    subscribers: int | None
    type: SourceType = "community"
    district: str | None = None
    # В каталоге краевых источников (основание «краевой источник», Р4).
    regional: bool = False
    in_catalog: bool = False
    closed: bool = False
    description: str = ""
    last_post_at: datetime | None = None


@dataclass(frozen=True)
class RawPost:
    """Пост, как его отдала площадка. Все поля — только из ответа площадки (К14)."""

    ref: PostRef
    source: SourceInfo
    text: str | None
    title: str | None
    published_at: datetime | None
    time_reliability: TimeReliability
    edited: bool
    repost_of: tuple[str, str] | None  # (название источника, ссылка на оригинал)
    has_media: bool
    views: int | None
    reactions: int | None
    alt_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterQuery:
    """Что ищем на площадке."""

    text: str
    kind: Literal["topic", "event", "news-text"]
    start: datetime  # начало периода, UTC
    end: datetime  # конец периода, UTC
    # Режим «мои источники» — только эти; None — режим «везде».
    sources: Sequence[SourceInfo] | None
    meaning_id: str | None = None
    # 1 — первый запуск, 2+ — повтор площадки (ТЗ-Ф44).
    attempt: int = 1


@dataclass(frozen=True)
class Progress:
    done: int
    total: int
    unit: Literal["sources", "pages"]
    current_source: str | None = None


@dataclass(frozen=True)
class Posts:
    posts: Sequence[RawPost]


@dataclass(frozen=True)
class Partial:
    """Поиск идёт дальше, но итог будет «частично» (закрытые группы, ограничение частоты)."""

    code: ProblemCode
    message: str
    retryable: bool


@dataclass(frozen=True)
class Capped:
    """Площадка отдала не больше `limit` результатов (SC-16)."""

    limit: int
    note: str


AdapterEvent = Progress | Posts | Partial | Capped


class AdapterError(Exception):
    """Сбой площадки: найденное до сбоя сохраняется, статус — по коду (НТ-3)."""

    def __init__(
        self,
        code: ProblemCode,
        message: str,
        *,
        retryable: bool,
        state: PlatformState = "error",
    ) -> None:
        super().__init__(message)
        self.code: ProblemCode = code
        self.message = message
        self.retryable = retryable
        self.state: PlatformState = state


@dataclass(frozen=True)
class SourceProbe:
    """Итог проверки ссылки на источник (П9)."""

    state: Literal["ok", "not-found", "closed", "not-supported", "post-link"]
    source: SourceInfo | None
    # Для ссылки на пост: где он опубликован (если удалось узнать).
    post: PostRef | None = None


@dataclass(frozen=True)
class QuotaInfo:
    """Площадка платит вызовами: такую площадку стенд показывает с расходом бюджета.

    Учёт и пределы (сутки и месяц) — `services/budget.py` (`CallBudget`), здесь — справка.
    """

    limit: int
    unit: str
    period: Literal["month", "day", "total"]


class CallMeter(Protocol):
    """Бюджет вызовов внешней площадки (НТ-6): адаптер списывает вызов до обращения.

    Предел исчерпан — `AdapterError` с кодом `quota-exhausted` (вызов не делается).
    Реализация — `services.budget.CallBudget`.
    """

    async def spend(self, platform: PlatformId, amount: int = 1) -> None: ...


@dataclass(frozen=True)
class AdapterHealth:
    state: HealthState
    message: str


@dataclass
class AdapterDescription:
    """Что показать о площадке на странице стенда и в статусах."""

    platform: PlatformId
    via: str
    freshness: DataFreshness | None = None
    quota: QuotaInfo | None = None
    tags: list[str] = field(default_factory=list)


class PlatformAdapter(Protocol):
    platform: PlatformId
    description: AdapterDescription

    def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        """Кандидаты по запросу: ход (Progress), порции постов (Posts), предупреждения."""
        ...

    async def fetch_post(self, ref: PostRef) -> RawPost | None:
        """Пост по ключу: живая проверка ссылки и «добавить по ссылке». None — поста нет."""
        ...

    async def probe_source(self, url: str) -> SourceProbe:
        """Проверить ссылку на группу или канал (П9)."""
        ...

    async def health(self) -> AdapterHealth:
        """Работает ли площадка сейчас (для страницы стенда, НТ-18)."""
        ...
