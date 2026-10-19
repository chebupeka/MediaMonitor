"""Типы колонок, одинаково работающие в PostgreSQL (стенд) и SQLite (только тесты)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Dialect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator, TypeEngine

# JSON: в PostgreSQL — JSONB.
JsonType: TypeEngine[Any] = JSON(none_as_null=True).with_variant(
    JSONB(none_as_null=True), "postgresql"
)

# Вектор смысла (Р5, шаг 2 воронки): в PostgreSQL — pgvector без фиксированной длины
# (BERTA даёт 768, другая модель может дать иную), в SQLite — JSON.
VectorType: TypeEngine[Any] = JSON(none_as_null=True).with_variant(Vector(), "postgresql")


class UtcDateTime(TypeDecorator[datetime]):
    """Момент времени: в базе — UTC, в Python — всегда с поясом (UTC).

    SQLite пояс не хранит, поэтому приводим явно и при записи, и при чтении.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Время без пояса: передайте datetime с tzinfo")
        moment = value.astimezone(UTC)
        return moment.replace(tzinfo=None) if dialect.name == "sqlite" else moment

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
