"""Рабочее место без регистрации (Р8) и изоляция данных (НТ-7).

Ключ — 32 случайных символа (192 бита), неугадываемый. В базе храним только его
SHA-256: по базе ключ не восстановить. Клиент передаёт ключ в заголовке
`X-Workspace-Key`; ссылка «Открыть на другом компьютере» несёт ключ во фрагменте
адреса (`#workspace=…`), который браузер не отправляет на сервер.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.contract import Workspace, WorkspaceLink
from mediamonitor.db.models import (
    ClientDailyUsageRow,
    SearchRow,
    WorkspaceRow,
    WorkspaceSourceRow,
)
from mediamonitor.db.session import SessionMaker
from mediamonitor.errors import ApiProblem
from mediamonitor.labels import format_number
from mediamonitor.timeutil import day_start, iso, krsk_today, utcnow

KEY_HEADER = "X-Workspace-Key"
NOT_FOUND = "Рабочее место по этой ссылке не найдено. Проверьте, что ссылка скопирована целиком."


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def client_hash(ip: str | None) -> str:
    """Адрес клиента для счётчиков стенда: храним только хеш, не сам IP."""
    return hashlib.sha256(f"mediamonitor-client:{ip or 'unknown'}".encode()).hexdigest()


class NewWorkspaceLimit:
    """Не больше `limit` новых рабочих мест с одного IP за сутки по Красноярску (НТ-6).

    Ссылка на стенд публичная: без предела скрипт засорил бы базу пустыми рабочими местами.
    Частоту в минуту ограничивает RateLimitMiddleware, это — предел на сутки; счётчик в базе
    (`client_daily_usage`) переживает перезапуск сервера. Сервер — один процесс, поэтому
    «проверить и увеличить» защищены замком процесса.
    """

    KIND = "workspace"

    def __init__(
        self, sessions: SessionMaker, limit: int, *, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._sessions = sessions
        self._limit = limit
        self._clock = clock
        self._lock = asyncio.Lock()

    async def admit(self, client_ip: str | None) -> None:
        """Учесть новое рабочее место с этого адреса или ответить 429 до завтра."""
        now = self._clock()
        today = krsk_today(now)
        key = (self.KIND, client_hash(client_ip), today.isoformat())
        async with self._lock, self._sessions.begin() as session:
            row = await session.get(ClientDailyUsageRow, key, with_for_update=True)
            if row is None:
                # Первое за сутки с этого адреса — заодно убрать позавчерашние и старше.
                yesterday = (today - timedelta(days=1)).isoformat()
                await session.execute(
                    delete(ClientDailyUsageRow).where(ClientDailyUsageRow.day < yesterday)
                )
                row = ClientDailyUsageRow(kind=key[0], client_hash=key[1], day=key[2], count=0)
                session.add(row)
            if row.count >= self._limit:
                tomorrow = day_start(today + timedelta(days=1))
                raise ApiProblem(
                    "too-many-requests",
                    f"С вашего адреса сегодня создано уже {format_number(self._limit)} "
                    "рабочих мест — это предел открытого стенда. Откройте прежнее рабочее место "
                    "по ссылке-ключу или попробуйте завтра.",
                    retry_after_sec=max(1, int((tomorrow - now).total_seconds()) + 1),
                )
            row.count += 1


def clean_key(raw: str) -> str:
    """Ключ из ссылки или как есть: «https://…/#workspace=abc» → «abc»."""
    value = raw.strip()
    marker = "#workspace="
    if marker in value:
        value = value.split(marker, 1)[1]
    return value.split("&", 1)[0].strip()


async def create_workspace(session: AsyncSession) -> tuple[WorkspaceRow, str]:
    key = secrets.token_urlsafe(24)
    now = utcnow()
    row = WorkspaceRow(
        id=f"ws_{secrets.token_hex(8)}", key_hash=hash_key(key), created_at=now, last_seen_at=now
    )
    session.add(row)
    await session.flush()
    return row, key


async def find_workspace(session: AsyncSession, key: str) -> WorkspaceRow | None:
    if not key or len(key) > 200:
        return None
    return await session.scalar(select(WorkspaceRow).where(WorkspaceRow.key_hash == hash_key(key)))


async def require_workspace(session: AsyncSession, key: str | None) -> WorkspaceRow:
    if not key:
        raise ApiProblem(
            "not-found",
            "Рабочее место не выбрано: откройте сайт заново, оно создастся само.",
        )
    row = await find_workspace(session, clean_key(key))
    if row is None:
        raise ApiProblem("not-found", NOT_FOUND)
    return row


async def to_contract(session: AsyncSession, row: WorkspaceRow) -> Workspace:
    sources = await session.scalar(
        select(func.count())
        .select_from(WorkspaceSourceRow)
        .where(WorkspaceSourceRow.workspace_id == row.id, WorkspaceSourceRow.removed_at.is_(None))
    )
    recent = await session.scalar(
        select(func.count())
        .select_from(SearchRow)
        .where(
            SearchRow.workspace_id == row.id,
            SearchRow.in_recent.is_(True),
            SearchRow.phase != "running",
        )
    )
    return Workspace(
        id=row.id,
        created_at=iso(row.created_at),
        sources_count=int(sources or 0),
        recent_count=min(int(recent or 0), 20),
    )


def link_of(row: WorkspaceRow, key: str, public_app_url: str) -> WorkspaceLink:
    base = public_app_url.split("#", 1)[0]
    return WorkspaceLink(
        workspace_id=row.id, key=key, url=f"{base}#workspace={key}", created_at=iso(utcnow())
    )
