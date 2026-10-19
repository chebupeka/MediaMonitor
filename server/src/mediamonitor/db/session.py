"""Подключение к базе: PostgreSQL на стенде, SQLite — только в тестах."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from mediamonitor.db.models import Base

SessionMaker = async_sessionmaker[AsyncSession]


def create_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        engine = create_async_engine(url, connect_args={"timeout": 30})

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection: DBAPIConnection, _: ConnectionPoolEntry) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    return create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


def create_sessions(engine: AsyncEngine) -> SessionMaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    """Создать таблицы без миграций — только для тестов на SQLite."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
