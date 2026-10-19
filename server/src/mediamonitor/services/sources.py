"""Источники: справочник площадок, список пользователя, проверка ссылок, каталог края.

Список источников принадлежит рабочему месту (НТ-7). Каталог краевых источников
общий и только для чтения (Р8). Тексты сообщений — как в мокапе.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import timedelta
from importlib import resources
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.adapters import AdapterRegistry
from mediamonitor.adapters.base import AdapterError, SourceInfo, SourceProbe
from mediamonitor.contract import (
    CatalogSource,
    PlatformId,
    Source,
    SourceCheck,
    SourceCheckState,
    SourceInput,
    SourcePatch,
    SourcePreview,
    SourcesRecheckProblem,
    SourcesRecheckReport,
    source_type,
)
from mediamonitor.db.models import PlatformSourceRow, WorkspaceRow, WorkspaceSourceRow
from mediamonitor.errors import ApiProblem, required
from mediamonitor.normalize.urls import parse_address, source_id, source_url
from mediamonitor.timeutil import iso, iso_or_none, utcnow

NOT_SUPPORTED = "Это не ссылка на группу или канал ВКонтакте, Одноклассников или MAX."
OK_MESSAGE = "Источник доступен: открытая группа, посты читаются."
CLOSED_MESSAGE = "Группа закрыта: её посты не видны, поиск по ней невозможен."
NOT_REGIONAL = "Пишет не только о крае: в подборку попадут посты, где упоминается край."
NOT_IN_LIST = "Источник не найден в вашем списке."


# ---------------------------------------------------------------- справочник


async def upsert_source(
    session: AsyncSession, info: SourceInfo, *, catalog: bool = False
) -> PlatformSourceRow:
    """Записать сведения площадки об источнике в общий справочник.

    Отметку «в каталоге края» ставит только сам каталог (`catalog=True`): ответ площадки
    или поиска сделать источник каталожным не может.
    """
    sid = source_id(info.platform, info.owner_id)
    row = await session.get(PlatformSourceRow, sid)
    now = utcnow()
    if row is None:
        row = PlatformSourceRow(
            id=sid,
            platform=info.platform,
            owner_id=info.owner_id,
            slug=info.slug,
            name=info.name,
            url=source_url(info.platform, info.owner_id, info.slug),
            type=info.type,
            district=info.district,
            subscribers=info.subscribers,
            regional=info.regional,
            in_catalog=catalog and info.in_catalog,
            closed=info.closed,
            description=info.description,
            last_post_at=info.last_post_at,
            checked_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row
    row.name = info.name or row.name
    row.slug = info.slug or row.slug
    row.subscribers = info.subscribers if info.subscribers is not None else row.subscribers
    row.closed = info.closed
    # Каталог края ведём мы: площадка не может снять отметку «краевой».
    row.regional = row.regional or info.regional
    if catalog:
        row.in_catalog = info.in_catalog
    if info.district and not row.district:
        row.district = info.district
    if info.last_post_at is not None:
        row.last_post_at = info.last_post_at
    row.checked_at = now
    row.updated_at = now
    return row


def _catalog_file() -> list[SourceInfo]:
    raw = json.loads(
        resources.files("mediamonitor.data").joinpath("catalog.json").read_text("utf-8")
    )
    result = []
    for entry in raw["sources"]:
        platform = cast(PlatformId, entry["platform"])
        owner = str(entry["ownerId"])
        slug = entry.get("slug")
        result.append(
            SourceInfo(
                platform=platform,
                owner_id=owner,
                slug=slug,
                name=entry["name"],
                url=source_url(platform, owner, slug),
                subscribers=entry.get("subscribers"),
                type=source_type(entry.get("type")),
                district=entry.get("district"),
                regional=True,
                in_catalog=True,
                description=entry.get("description", ""),
            )
        )
    return result


async def seed_catalog(session: AsyncSession, extra: Sequence[SourceInfo]) -> int:
    """Каталог краевых источников при старте: файл data/catalog.json + записанные примеры."""
    infos = [*_catalog_file(), *extra]
    ids = []
    for info in infos:
        row = await upsert_source(session, info, catalog=True)
        ids.append(row.id)
    # Каталог — ровно то, что в файле: прежние отметки снимаем.
    await session.execute(
        update(PlatformSourceRow)
        .where(PlatformSourceRow.in_catalog.is_(True), PlatformSourceRow.id.not_in(ids))
        .values(in_catalog=False)
    )
    return sum(1 for info in infos if info.in_catalog)


# ---------------------------------------------------------------- в форме контракта


def _preview(row: PlatformSourceRow) -> SourcePreview:
    return SourcePreview(
        platform=cast(PlatformId, row.platform),
        name=row.name,
        url=row.url,
        subscribers=row.subscribers,
        last_post_at=iso_or_none(row.last_post_at),
        suggested_type=source_type(row.type),
        suggested_district=row.district,
    )


def to_source(entry: WorkspaceSourceRow, directory: PlatformSourceRow) -> Source:
    return Source(
        id=directory.id,
        platform=cast(PlatformId, directory.platform),
        name=entry.name,
        url=directory.url,
        type=source_type(entry.type),
        district=entry.district,
        subscribers=directory.subscribers,
        in_my_sources=entry.removed_at is None,
        regional=directory.regional,
        origin=cast(Any, entry.origin),
        added_at=iso(entry.added_at),
        check=SourceCheck.model_validate(entry.check),
    )


async def _entries(
    session: AsyncSession, workspace_id: str, *, active: bool = True
) -> list[tuple[WorkspaceSourceRow, PlatformSourceRow]]:
    query = (
        select(WorkspaceSourceRow, PlatformSourceRow)
        .join(PlatformSourceRow, PlatformSourceRow.id == WorkspaceSourceRow.source_id)
        .where(WorkspaceSourceRow.workspace_id == workspace_id)
    )
    if active:
        query = query.where(WorkspaceSourceRow.removed_at.is_(None))
    result = await session.execute(query)
    return list(result)


async def list_sources(session: AsyncSession, workspace: WorkspaceRow) -> list[Source]:
    sources = [to_source(e, d) for e, d in await _entries(session, workspace.id)]
    return sorted(sources, key=lambda s: s.name.casefold().replace("ё", "е"))


async def active_infos(
    session: AsyncSession, workspace_id: str, ids: Sequence[str] | None
) -> list[SourceInfo]:
    """Источники пользователя для поиска «по моим источникам»."""
    wanted = set(ids) if ids else None
    infos = []
    for entry, directory in await _entries(session, workspace_id):
        if wanted is not None and directory.id not in wanted:
            continue
        infos.append(
            SourceInfo(
                platform=cast(PlatformId, directory.platform),
                owner_id=directory.owner_id,
                slug=directory.slug,
                name=entry.name,
                url=directory.url,
                subscribers=directory.subscribers,
                type=source_type(entry.type),
                district=entry.district,
                regional=directory.regional,
                in_catalog=directory.in_catalog,
                closed=directory.closed,
            )
        )
    return infos


# ---------------------------------------------------------------- проверка ссылки (П9)


async def probe(adapters: AdapterRegistry, url: str) -> SourceProbe:
    address = parse_address(url)
    if address is None:
        return SourceProbe("not-supported", None)
    try:
        return await adapters[address.platform].probe_source(url)
    except AdapterError as error:
        raise ApiProblem("server", error.message) from error


async def check_url(
    session: AsyncSession, adapters: AdapterRegistry, workspace: WorkspaceRow, url: str
) -> tuple[SourceCheck, PlatformSourceRow | None]:
    checked_at = iso(utcnow())
    result = await probe(adapters, url)
    if result.state == "not-supported":
        return SourceCheck(
            state="not-supported", message=NOT_SUPPORTED, preview=None, checked_at=checked_at
        ), None
    if result.state == "post-link":
        owner = result.source
        if owner is not None:
            row = await upsert_source(session, owner)
            what = "этот канал" if owner.platform == "max" else "эту группу"
            return SourceCheck(
                state="post-link",
                message=f"Это ссылка на пост. Он опубликован в «{owner.name}» — можно проверить "
                f"и добавить {what}.",
                preview=None if owner.closed else _preview(row),
                checked_at=checked_at,
            ), None
        return SourceCheck(
            state="post-link",
            message="Это ссылка на пост, а не на группу. Откройте группу или канал, где он вышел, "
            "и скопируйте их адрес.",
            preview=None,
            checked_at=checked_at,
        ), None
    if result.state == "not-found" or result.source is None:
        return SourceCheck(
            state="not-found",
            message="По этой ссылке ничего нет: группа удалена или ссылка с ошибкой.",
            preview=None,
            checked_at=checked_at,
        ), None
    row = await upsert_source(session, result.source)
    entry = await session.scalar(
        select(WorkspaceSourceRow).where(
            WorkspaceSourceRow.workspace_id == workspace.id,
            WorkspaceSourceRow.source_id == row.id,
            WorkspaceSourceRow.removed_at.is_(None),
        )
    )
    if entry is not None:
        message = (
            f"«{row.name}» уже есть в вашем списке, но группа закрыта: по ней не ищем."
            if row.closed
            else f"«{row.name}» уже есть в вашем списке."
        )
        return SourceCheck(
            state="duplicate", message=message, preview=_preview(row), checked_at=checked_at
        ), row
    if result.state == "closed":
        return SourceCheck(
            state="closed",
            message=f"«{row.name}» — закрытая группа: её посты не видны, искать в ней нельзя.",
            preview=None,
            checked_at=checked_at,
        ), row
    if not row.regional:
        return SourceCheck(
            state="not-regional",
            message=f"«{row.name}» пишет не только о крае. Добавить можно: "
            "в подборку попадут посты, "
            "где упоминается край.",
            preview=_preview(row),
            checked_at=checked_at,
        ), row
    return SourceCheck(
        state="ok",
        message=f"«{row.name}» доступен: открытая группа, посты читаются.",
        preview=_preview(row),
        checked_at=checked_at,
    ), row


# ---------------------------------------------------------------- список пользователя


async def _entry(session: AsyncSession, workspace_id: str, sid: str) -> WorkspaceSourceRow | None:
    return await session.scalar(
        select(WorkspaceSourceRow).where(
            WorkspaceSourceRow.workspace_id == workspace_id, WorkspaceSourceRow.source_id == sid
        )
    )


def ok_check() -> dict[str, Any]:
    return SourceCheck(
        state="ok", message=OK_MESSAGE, preview=None, checked_at=iso(utcnow())
    ).dump()


async def attach(
    session: AsyncSession,
    workspace_id: str,
    directory: PlatformSourceRow,
    origin: str,
    check: dict[str, Any],
    *,
    name: str | None = None,
    type_: str | None = None,
    district: str | None = None,
    district_set: bool = False,
) -> WorkspaceSourceRow:
    """Добавить источник в список (или вернуть удалённый) — одна запись на источник."""
    entry = await _entry(session, workspace_id, directory.id)
    now = utcnow()
    if entry is None:
        entry = WorkspaceSourceRow(
            workspace_id=workspace_id,
            source_id=directory.id,
            name=name or directory.name,
            type=type_ or directory.type,
            district=district if district_set else directory.district,
            origin=origin,
            added_at=now,
            removed_at=None,
            check=check,
        )
        session.add(entry)
    else:
        entry.removed_at = None
        entry.origin = origin
        entry.added_at = now
        entry.name = name or directory.name
        entry.type = type_ or directory.type
        entry.district = district if district_set else directory.district
        entry.check = check
    await session.flush()
    return entry


async def add_source(
    session: AsyncSession, adapters: AdapterRegistry, workspace: WorkspaceRow, data: SourceInput
) -> Source:
    check, directory = await check_url(session, adapters, workspace, data.url)
    if check.state not in ("ok", "not-regional") or directory is None:
        raise ApiProblem("invalid", check.message)
    name = (data.name or "").strip() or None
    entry = await attach(
        session,
        workspace.id,
        directory,
        "manual",
        check.dump(),
        name=name,
        type_=data.type,
        district=data.district,
        district_set="district" in data.model_fields_set,
    )
    return to_source(entry, directory)


async def update_source(
    session: AsyncSession, workspace: WorkspaceRow, sid: str, patch: SourcePatch
) -> Source:
    entry = await _entry(session, workspace.id, sid)
    if entry is None or entry.removed_at is not None:
        raise ApiProblem("not-found", NOT_IN_LIST)
    fields = patch.model_fields_set
    if "name" in fields and patch.name is not None and patch.name.strip():
        entry.name = patch.name.strip()[:500]
    if "type" in fields and patch.type is not None:
        entry.type = patch.type
    if "district" in fields:
        entry.district = patch.district.strip()[:200] if patch.district else None
    directory = await session.get(PlatformSourceRow, sid)
    directory = required(directory, "directory")
    return to_source(entry, directory)


async def remove_source(session: AsyncSession, workspace: WorkspaceRow, sid: str) -> None:
    entry = await _entry(session, workspace.id, sid)
    if entry is None or entry.removed_at is not None:
        raise ApiProblem("not-found", NOT_IN_LIST)
    entry.removed_at = utcnow()


async def restore_source(
    session: AsyncSession, workspace: WorkspaceRow, sid: str, window_minutes: int
) -> Source:
    entry = await _entry(session, workspace.id, sid)
    if (
        entry is None
        or entry.removed_at is None
        or utcnow() - entry.removed_at > timedelta(minutes=window_minutes)
    ):
        raise ApiProblem("not-found", "Источник уже нельзя вернуть.")
    entry.removed_at = None
    directory = await session.get(PlatformSourceRow, sid)
    directory = required(directory, "directory")
    return to_source(entry, directory)


async def recheck_sources(
    session: AsyncSession, adapters: AdapterRegistry, workspace: WorkspaceRow
) -> SourcesRecheckReport:
    checked_at = iso(utcnow())
    entries = await _entries(session, workspace.id)
    gate = asyncio.Semaphore(4)

    async def one(directory: PlatformSourceRow) -> SourceProbe | None:
        async with gate:
            try:
                return await adapters[cast(PlatformId, directory.platform)].probe_source(
                    directory.url
                )
            except AdapterError:
                return None

    probes = await asyncio.gather(*(one(d) for _, d in entries))
    problems: list[SourcesRecheckProblem] = []
    for (entry, directory), result in zip(entries, probes, strict=True):
        if result is None:
            check = SourceCheck(
                state="not-found",
                message="Проверить не удалось: площадка не ответила. Повторите позже.",
                preview=None,
                checked_at=checked_at,
            )
        elif result.state == "closed":
            directory.closed = True
            check = SourceCheck(
                state="closed", message=CLOSED_MESSAGE, preview=None, checked_at=checked_at
            )
        elif result.state == "ok" and result.source is not None:
            await upsert_source(session, result.source)
            state: SourceCheckState = "ok" if directory.regional else "not-regional"
            check = SourceCheck(
                state=state,
                message=OK_MESSAGE if state == "ok" else NOT_REGIONAL,
                preview=None,
                checked_at=checked_at,
            )
        else:
            check = SourceCheck(
                state="not-found",
                message="По этой ссылке ничего нет: группа удалена или ссылка с ошибкой.",
                preview=None,
                checked_at=checked_at,
            )
        entry.check = check.dump()
        if check.state != "ok":
            problems.append(
                SourcesRecheckProblem(
                    source_id=directory.id,
                    name=entry.name,
                    state=check.state,
                    message=check.message,
                )
            )
    sources = await list_sources(session, workspace)
    return SourcesRecheckReport(
        checked_at=checked_at,
        checked=len(sources),
        ok=sum(1 for s in sources if s.check.state == "ok"),
        problems=problems,
        sources=sources,
    )


# ---------------------------------------------------------------- каталог (НТ-14)


async def catalog(session: AsyncSession, workspace: WorkspaceRow) -> list[CatalogSource]:
    mine = {e.source_id for e, _ in await _entries(session, workspace.id)}
    rows = await session.scalars(
        select(PlatformSourceRow)
        .where(PlatformSourceRow.in_catalog.is_(True), PlatformSourceRow.closed.is_(False))
        .order_by(PlatformSourceRow.platform, PlatformSourceRow.name)
    )
    return [
        CatalogSource(
            id=row.id,
            platform=cast(PlatformId, row.platform),
            name=row.name,
            url=row.url,
            type=source_type(row.type),
            district=row.district,
            subscribers=row.subscribers,
            in_my_sources=row.id in mine,
            regional=row.regional,
            description=row.description,
        )
        for row in rows
    ]


async def add_from_catalog(
    session: AsyncSession, workspace: WorkspaceRow, ids: Sequence[str]
) -> list[Source]:
    added: list[Source] = []
    active = {e.source_id for e, _ in await _entries(session, workspace.id)}
    for sid in dict.fromkeys(ids):
        directory = await session.get(PlatformSourceRow, sid)
        if directory is None or not directory.in_catalog or directory.closed or sid in active:
            continue
        entry = await attach(session, workspace.id, directory, "catalog", ok_check())
        added.append(to_source(entry, directory))
    return added
