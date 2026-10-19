"""Кэш векторов смысла в базе (Р7: своя база — кэш, поиск всё равно идёт в момент запроса).

Вектор поста хранится по ключу «пост × модель с версией × задача» вместе с хешем текста,
по которому он посчитан. Пост, который уже встречался в любом поиске, повторно не
считается (~0,5 с на пост на CPU) — если текст не поменялся.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from mediamonitor.db.models import PostEmbeddingRow
from mediamonitor.db.session import SessionMaker
from mediamonitor.timeutil import utcnow


def _as_list(vector: Any) -> list[float]:
    """pgvector отдаёт numpy-массив, SQLite (JSON) — список."""
    return [float(x) for x in vector]


class DbVectorStore:
    def __init__(self, sessions: SessionMaker) -> None:
        self.sessions = sessions

    async def load(self, model: str, kind: str, keys: Mapping[str, str]) -> dict[str, list[float]]:
        if not keys:
            return {}
        async with self.sessions() as session:
            rows = await session.scalars(
                select(PostEmbeddingRow).where(
                    PostEmbeddingRow.model == model,
                    PostEmbeddingRow.kind == kind,
                    PostEmbeddingRow.publication_id.in_(list(keys)),
                )
            )
            return {
                row.publication_id: _as_list(row.vector)
                for row in rows
                if keys.get(row.publication_id) == row.text_key
            }

    async def save(
        self, model: str, kind: str, rows: Sequence[tuple[str, str, Sequence[float]]]
    ) -> None:
        if not rows:
            return
        now = utcnow()
        values = [
            {
                "publication_id": pid,
                "model": model,
                "kind": kind,
                "text_key": key,
                "vector": [float(x) for x in vector],
                "created_at": now,
            }
            for pid, key, vector in rows
        ]
        async with self.sessions.begin() as session:
            dialect = session.get_bind().dialect.name
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            statement = insert(PostEmbeddingRow).values(values)
            statement = statement.on_conflict_do_update(
                index_elements=["publication_id", "model", "kind"],
                set_={
                    "text_key": statement.excluded.text_key,
                    "vector": statement.excluded.vector,
                    "created_at": statement.excluded.created_at,
                },
            )
            await session.execute(statement)
