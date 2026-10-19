"""События хода поиска: журнал в базе + уведомления в процессе + поток SSE (НТ-2, НТ-23).

Каждое событие сначала записывается в `search_events` с номером `seq`, потом
читатели потока получают уведомление. Поэтому поток можно читать с любого места:
после обрыва связи клиент переподключается с `Last-Event-ID` и получает пропущенное.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.contract import TERMINAL_EVENTS, ApiModel
from mediamonitor.db.models import SearchEventRow, SearchRow
from mediamonitor.timeutil import utcnow

HEARTBEAT_SEC = 15.0


class EventBus:
    """Будильник для читателей потока: «у поиска X появились новые события»."""

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}
        self._condition = asyncio.Condition()

    def version(self, search_id: str) -> int:
        return self._versions.get(search_id, 0)

    async def notify(self, search_id: str) -> None:
        async with self._condition:
            self._versions[search_id] = self._versions.get(search_id, 0) + 1
            self._condition.notify_all()

    async def wait(self, search_id: str, seen: int, seconds: float) -> bool:
        """Ждать нового события поиска. False — истёк таймаут."""
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self.version(search_id) != seen), seconds
                )
            except TimeoutError:
                return False
            return True


def append_event(session: AsyncSession, search: SearchRow, event: ApiModel) -> int:
    """Записать событие в журнал поиска (в текущей транзакции). Возвращает его номер."""
    payload = event.dump()
    search.event_seq += 1
    session.add(
        SearchEventRow(
            search_id=search.id,
            seq=search.event_seq,
            type=str(payload["type"]),
            payload=payload,
            created_at=utcnow(),
        )
    )
    return search.event_seq


def encode_sse(seq: int, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {seq}\nevent: {payload['type']}\ndata: {data}\n\n".encode()


async def read_events(
    session: AsyncSession, search_id: str, after: int, limit: int = 200
) -> list[SearchEventRow]:
    rows = await session.scalars(
        select(SearchEventRow)
        .where(SearchEventRow.search_id == search_id, SearchEventRow.seq > after)
        .order_by(SearchEventRow.seq)
        .limit(limit)
    )
    return list(rows)


def is_terminal(row: SearchEventRow) -> bool:
    return row.type in TERMINAL_EVENTS


async def heartbeat_or_event(bus: EventBus, search_id: str, seen: int) -> AsyncIterator[bytes]:
    """Ждать события; если долго ничего — отправить комментарий, чтобы прокси не рвал связь."""
    if not await bus.wait(search_id, seen, HEARTBEAT_SEC):
        yield b": ping\n\n"
