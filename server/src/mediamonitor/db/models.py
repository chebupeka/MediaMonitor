"""Модель данных (docs/12-tech-design.md, «Модель данных»).

Сущности: рабочее место → источники пользователя; справочник источников площадок;
поиск → ход по площадкам → записи подборки (размещения) ↔ публикации; группы;
события хода; выгрузки; разборы импорта; события стенда; расход квот и счётчики клиентов
открытого стенда; кэши векторов и проверок на ИИ.

Публикации — общий кэш (Р7): одна запись на пост (ключ НТ-13). Всё, что принадлежит
пользователю, привязано к рабочему месту (НТ-7).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mediamonitor.db.types import JsonType, UtcDateTime, VectorType

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Целочисленный автоключ: BIGINT в PostgreSQL, INTEGER в SQLite (иначе нет автоинкремента).
AutoId = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: UtcDateTime(),
        dict[str, Any]: JsonType,
        list[Any]: JsonType,
    }


# ---------------------------------------------------------------- рабочее место (Р8)


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    # Храним только SHA-256 ключа: ключ из базы не восстановить.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    # Последний выбранный режим поиска — режим по умолчанию при следующем входе (бэклог п. 47).
    last_mode: Mapped[str | None] = mapped_column(String(16))


# ---------------------------------------------------------------- источники


class PlatformSourceRow(Base):
    """Справочник источников площадок: каталог края + всё, что встретилось в поиске."""

    __tablename__ = "platform_sources"
    __table_args__ = (UniqueConstraint("platform", "owner_id"),)

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    platform: Mapped[str] = mapped_column(String(8))
    owner_id: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str | None] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000))
    type: Mapped[str] = mapped_column(String(20))
    district: Mapped[str | None] = mapped_column(String(200))
    subscribers: Mapped[int | None]
    # Источник из каталога краевых источников — основание «краевой источник» (Р4).
    regional: Mapped[bool] = mapped_column(Boolean, default=False)
    in_catalog: Mapped[bool] = mapped_column(Boolean, default=False)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    last_post_at: Mapped[datetime | None]
    checked_at: Mapped[datetime | None]
    updated_at: Mapped[datetime]


class WorkspaceSourceRow(Base):
    """Источник в списке пользователя. Удаление мягкое: `removed_at`, можно вернуть (НТ-7)."""

    __tablename__ = "workspace_sources"
    __table_args__ = (UniqueConstraint("workspace_id", "source_id"),)

    id: Mapped[int] = mapped_column(AutoId, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("platform_sources.id"))
    name: Mapped[str] = mapped_column(String(500))
    type: Mapped[str] = mapped_column(String(20))
    district: Mapped[str | None] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(String(10))
    added_at: Mapped[datetime]
    removed_at: Mapped[datetime | None]
    check: Mapped[dict[str, Any]]


# ---------------------------------------------------------------- поиск


class SearchRow(Base):
    __tablename__ = "searches"
    __table_args__ = (Index("ix_searches_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    request: Mapped[dict[str, Any]]
    # Условия выполненного поиска (НТ-1) — снимок SearchConditions.
    conditions: Mapped[dict[str, Any]]
    kind: Mapped[str] = mapped_column(String(16))
    # running / done / stopped (как Selection.phase)
    phase: Mapped[str] = mapped_column(String(16), index=True)
    topic: Mapped[dict[str, Any] | None]
    # Для поиска по тексту новости: заголовок, текст и абзацы релиза (П1).
    release: Mapped[dict[str, Any] | None]
    ai_available: Mapped[bool] = mapped_column(Boolean, default=False)
    notices: Mapped[list[Any]]
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    arrival_seq: Mapped[int] = mapped_column(Integer, default=0)
    event_seq: Mapped[int] = mapped_column(Integer, default=0)
    in_recent: Mapped[bool] = mapped_column(Boolean, default=True)
    # Итог на момент окончания — для «Недавних» (П12): сколько нашли тогда и как прошли площадки.
    result_total: Mapped[int] = mapped_column(Integer, default=0)
    status_summary: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[dict[str, Any] | None]
    created_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]


class PlatformRunRow(Base):
    """Ход поиска по одной площадке: статус, счётчик, проблема (НТ-2, НТ-3)."""

    __tablename__ = "platform_runs"

    search_id: Mapped[str] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), primary_key=True
    )
    platform: Mapped[str] = mapped_column(String(8), primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
    done: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(10), default="sources")
    problem: Mapped[dict[str, Any] | None]
    cap: Mapped[dict[str, Any] | None]
    current_source: Mapped[str | None] = mapped_column(String(500))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime | None]


class PublicationRow(Base):
    """Пост площадки — общий кэш (Р7). Ключ — `vk:-100123_4567` (НТ-13)."""

    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("platform", "owner_id", "post_id"),)

    id: Mapped[str] = mapped_column(String(300), primary_key=True)
    platform: Mapped[str] = mapped_column(String(8))
    owner_id: Mapped[str] = mapped_column(String(200))
    post_id: Mapped[str] = mapped_column(String(300))  # путь статьи сайта СМИ — длинный
    source_id: Mapped[str | None] = mapped_column(ForeignKey("platform_sources.id"))
    url: Mapped[str] = mapped_column(String(1000))
    merged_urls: Mapped[list[Any]]
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    sentences: Mapped[list[Any]]
    published_at: Mapped[datetime | None] = mapped_column(index=True)
    time_reliability: Mapped[str] = mapped_column(String(12))
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    repost_of: Mapped[dict[str, Any] | None]
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    views: Mapped[int | None]
    reactions: Mapped[int | None]
    fetched_at: Mapped[datetime]
    link_state: Mapped[str] = mapped_column(String(12), default="not-checked")
    link_checked_at: Mapped[datetime | None]
    # Хеш нормализованного текста: точные копии (шаг 1 воронки, ТЗ-Ф30).
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    updated_at: Mapped[datetime]


class PostEmbeddingRow(Base):
    """Кэш векторов смысла (Р7: база — кэш): пост × версия модели × задача.

    Вектор годен, пока совпадает `text_key` — хеш текста, по которому он посчитан.
    Уже посчитанные посты повторно не считаются (~0,5 с на пост на CPU).
    """

    __tablename__ = "post_embeddings"

    publication_id: Mapped[str] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), primary_key=True
    )
    # Модель и версия: «sergeyzh/BERTA#1».
    model: Mapped[str] = mapped_column(String(200), primary_key=True)
    # Задача модели: paraphrase (текст новости) или topic (тема) — у них разные префиксы.
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    text_key: Mapped[str] = mapped_column(String(64))
    vector: Mapped[Any] = mapped_column(VectorType)
    created_at: Mapped[datetime]


class AiCheckRow(Base):
    """Кэш проверки текста на ИИ: SHA-256 нормализованного текста × модель × версия модели.

    Первый посчитанный результат сохраняется и дальше переиспользуется — в отдельной
    проверке, в подборке и в «Распространении» (один текст — один результат). Смена модели
    или версии даёт новый ключ — текст считается заново. «Мало текста» и «недоступно» сюда
    не пишутся: первое считается без модели, второе — не результат.
    """

    __tablename__ = "ai_checks"

    text_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(200), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(100), primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    # Уровень по порогам на момент проверки (наружу уровень считается из score).
    level: Mapped[str] = mapped_column(String(16))
    checked_at: Mapped[datetime]


class SearchItemRow(Base):
    """Запись подборки — размещение публикации в поиске (ТЗ-Ф29) и почему она здесь."""

    __tablename__ = "search_items"
    __table_args__ = (Index("ix_search_items_search_arrival", "search_id", "arrival"),)

    search_id: Mapped[str] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), primary_key=True
    )
    publication_id: Mapped[str] = mapped_column(ForeignKey("publications.id"), primary_key=True)
    relevance: Mapped[str] = mapped_column(String(10))
    method: Mapped[str] = mapped_column(String(14))
    method_note: Mapped[str | None] = mapped_column(Text)
    region_reason: Mapped[dict[str, Any]]
    excerpt: Mapped[dict[str, Any] | None]
    evidence: Mapped[dict[str, Any] | None]
    placement_type: Mapped[str | None] = mapped_column(String(10))
    is_original: Mapped[bool] = mapped_column(Boolean, default=False)
    citation: Mapped[dict[str, Any] | None]
    group_id: Mapped[str | None] = mapped_column(String(64))
    # Ключ кластера копий от воронки: одинаковый ключ — одна группа (Р9).
    cluster: Mapped[str | None] = mapped_column(String(100))
    # Исключение «не то» (ТЗ-Ф48): исключённые не идут в счётчики и XLSX.
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_at: Mapped[datetime | None]
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    arrival: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime]


class SearchGroupRow(Base):
    """Группа размещений (Р9): релиз или копии одного сообщения."""

    __tablename__ = "search_groups"
    __table_args__ = (UniqueConstraint("search_id", "cluster"),)

    search_id: Mapped[str] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cluster: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime]


class SearchEventRow(Base):
    """Журнал событий хода поиска: из него читает поток SSE (и после переподключения)."""

    __tablename__ = "search_events"
    __table_args__ = (UniqueConstraint("search_id", "seq"),)

    id: Mapped[int] = mapped_column(AutoId, primary_key=True, autoincrement=True)
    search_id: Mapped[str] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime]


# ---------------------------------------------------------------- выгрузки, импорт


class ExportRow(Base):
    """Журнал выгрузок XLSX: какой поиск, с какими условиями, сколько строк."""

    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(AutoId, primary_key=True, autoincrement=True)
    search_id: Mapped[str] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    options: Mapped[dict[str, Any]]
    row_count: Mapped[int]
    file_name: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime]


class ImportPreviewRow(Base):
    __tablename__ = "import_previews"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    payload: Mapped[dict[str, Any]]
    created_at: Mapped[datetime]


# ---------------------------------------------------------------- стенд (НТ-18)


class StandEventRow(Base):
    __tablename__ = "stand_events"

    id: Mapped[int] = mapped_column(AutoId, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(index=True)
    level: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)


class QuotaUsageRow(Base):
    """Расход бюджета площадок по периодам: сутки «2026-10-20», месяц «2026-10» (НТ-6).

    `warned` — дежурный уже получил предупреждение 80% (или «исчерпан») за этот период.
    """

    __tablename__ = "quota_usage"

    platform: Mapped[str] = mapped_column(String(8), primary_key=True)
    period: Mapped[str] = mapped_column(String(10), primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)
    limit: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(40))
    resets_at: Mapped[datetime | None]
    warned: Mapped[bool] = mapped_column(Boolean, default=False)


class ClientDailyUsageRow(Base):
    """Счётчики открытого стенда на клиента за сутки (НТ-6): новые рабочие места с одного IP.

    Сам адрес не храним — только SHA-256 от него; строки старше вчерашнего дня удаляются.
    """

    __tablename__ = "client_daily_usage"

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    client_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Сутки по красноярскому времени: «2026-10-20».
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
