"""Рабочее место без регистрации (Р8) и изоляция данных (НТ-7).

Ключ — 32 случайных символа (192 бита), неугадываемый. В базе храним только его
SHA-256: по базе ключ не восстановить. Клиент передаёт ключ в заголовке
`X-Workspace-Key`; ссылка «Открыть на другом компьютере» несёт ключ во фрагменте
адреса (`#workspace=…`), который браузер не отправляет на сервер.
"""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.contract import Workspace, WorkspaceLink
from mediamonitor.db.models import SearchRow, WorkspaceRow, WorkspaceSourceRow
from mediamonitor.errors import ApiProblem
from mediamonitor.timeutil import iso, utcnow

KEY_HEADER = "X-Workspace-Key"
NOT_FOUND = "Рабочее место по этой ссылке не найдено. Проверьте, что ссылка скопирована целиком."


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


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
