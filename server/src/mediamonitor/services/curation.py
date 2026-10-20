"""Работа с готовой подборкой: исключить «не то» (ТЗ-Ф48, НТ-25), добавить пост по
ссылке (П8), перепроверить ссылки перед выгрузкой (НТ-19)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.adapters import AdapterRegistry
from mediamonitor.adapters.base import AdapterError, RawPost
from mediamonitor.contract import (
    Evidence,
    ExcludeSourceResult,
    LinkRecheckReport,
    PlatformId,
    RegionReason,
    ResultItem,
    SelectionCounts,
    TextRange,
)
from mediamonitor.db.models import PublicationRow, SearchItemRow, SearchRow, WorkspaceRow
from mediamonitor.errors import ApiProblem
from mediamonitor.normalize.text import Span, excerpt_bounds, split_sentences
from mediamonitor.normalize.urls import PostRef, parse_post_url
from mediamonitor.services import sources as source_service
from mediamonitor.services.normalize_post import normalize, upsert_publication
from mediamonitor.services.selection import (
    build_selection,
    load_bundles,
    my_source_ids,
    result_item,
)
from mediamonitor.timeutil import iso, utcnow

if TYPE_CHECKING:
    from mediamonitor.aicheck import AiCheckService

SEARCH_NOT_FOUND = "Поиск не найден. Запустите его заново."


async def own_search(session: AsyncSession, workspace: WorkspaceRow, search_id: str) -> SearchRow:
    """Поиск этого рабочего места. Чужой поиск неотличим от несуществующего (НТ-7)."""
    search = await session.get(SearchRow, search_id)
    if search is None or search.workspace_id != workspace.id:
        raise ApiProblem("not-found", SEARCH_NOT_FOUND)
    return search


async def set_excluded(
    session: AsyncSession,
    adapters: AdapterRegistry,
    search: SearchRow,
    item_ids: Sequence[str],
    excluded: bool,
    *,
    ai: AiCheckService | None = None,
) -> SelectionCounts:
    if item_ids:
        await session.execute(
            update(SearchItemRow)
            .where(
                SearchItemRow.search_id == search.id,
                SearchItemRow.publication_id.in_(list(set(item_ids))),
            )
            .values(excluded=excluded, excluded_at=utcnow() if excluded else None)
        )
    return (await build_selection(session, search, adapters, ai)).counts


async def exclude_source(
    session: AsyncSession,
    adapters: AdapterRegistry,
    search: SearchRow,
    source_id: str,
    *,
    ai: AiCheckService | None = None,
) -> ExcludeSourceResult:
    rows = await session.execute(
        select(SearchItemRow)
        .join(PublicationRow, PublicationRow.id == SearchItemRow.publication_id)
        .where(
            SearchItemRow.search_id == search.id,
            SearchItemRow.excluded.is_(False),
            PublicationRow.source_id == source_id,
        )
    )
    ids = []
    now = utcnow()
    for (item,) in rows:
        item.excluded = True
        item.excluded_at = now
        ids.append(item.publication_id)
    await session.flush()
    counts = (await build_selection(session, search, adapters, ai)).counts
    return ExcludeSourceResult(item_ids=ids, counts=counts)


async def _fetch(adapters: AdapterRegistry, ref: PostRef) -> RawPost | None:
    adapter = adapters.get(ref.platform)
    if adapter is None:
        raise ApiProblem("invalid", "Эта площадка сейчас выключена на сервере.")
    try:
        return await adapter.fetch_post(ref)
    except AdapterError as error:
        raise ApiProblem("server", error.message) from error


async def add_by_url(
    session: AsyncSession,
    adapters: AdapterRegistry,
    search: SearchRow,
    url: str,
    split: Callable[[str], list[Span]] = split_sentences,
) -> ResultItem:
    ref = parse_post_url(url)
    if ref is None:
        raise ApiProblem(
            "invalid",
            "Это не ссылка на пост ВКонтакте, Одноклассников, MAX, Дзена или статью сайта СМИ "
            "края.",
        )
    raw: RawPost | None = None
    if not ref.owner_id:
        # В ссылке на публикацию Дзена нет владельца: ключ узнаём со страницы публикации.
        raw = await _fetch(adapters, ref)
        if raw is not None:
            ref = raw.ref
    existing = await session.get(SearchItemRow, (search.id, ref.id))
    if existing is not None:
        if not existing.excluded:
            raise ApiProblem("invalid", "Эта публикация уже есть в подборке.")
        existing.excluded = False
        existing.excluded_at = None
        await session.flush()
    else:
        if raw is None:
            raw = await _fetch(adapters, ref)
        post = normalize(raw, split) if raw is not None else None
        if post is None:
            raise ApiProblem(
                "not-found", "Пост по ссылке не найден: он удалён, закрыт или ссылка с ошибкой."
            )
        directory = await source_service.upsert_source(session, post.source)
        await upsert_publication(session, post, directory.id)
        mode = search.request.get("mode")
        in_my_list = mode == "my-sources" and directory.id in await my_source_ids(
            session, search.workspace_id
        )
        evidence = None
        excerpt = None
        if post.text and post.spans:
            span = post.spans[0]
            evidence = Evidence(
                sentence_index=0,
                ranges=[TextRange(start=span.start, end=span.end)],
                basis="semantic",
                note=None,
            ).dump()
            start, end = excerpt_bounds(list(post.spans), 0, len(post.text))
            excerpt = {"start": start, "end": end}
        search.arrival_seq += 1
        session.add(
            SearchItemRow(
                search_id=search.id,
                publication_id=post.id,
                relevance="direct",
                method="manual",
                method_note="Вы добавили публикацию по ссылке",
                region_reason=RegionReason(
                    regional_source=directory.regional,
                    in_my_sources=in_my_list,
                    places=list(post.places),
                ).dump(),
                excerpt=excerpt,
                evidence=evidence,
                placement_type=None,
                is_original=False,
                citation=None,
                group_id=None,
                cluster=None,
                excluded=False,
                excluded_at=None,
                is_new=False,
                arrival=search.arrival_seq,
                created_at=utcnow(),
            )
        )
        await session.flush()
    mine = await my_source_ids(session, search.workspace_id)
    bundles = await load_bundles(session, search.id, [ref.id])
    return result_item(bundles[0], mine, search.kind)


async def recheck_links(
    session: AsyncSession, adapters: AdapterRegistry, search: SearchRow
) -> LinkRecheckReport:
    result = await session.execute(
        select(PublicationRow)
        .join(SearchItemRow, SearchItemRow.publication_id == PublicationRow.id)
        .where(SearchItemRow.search_id == search.id, SearchItemRow.excluded.is_(False))
    )
    publications = [row for (row,) in result]
    gate = asyncio.Semaphore(4)
    now = utcnow()

    async def check(pub: PublicationRow) -> str:
        ref = PostRef(cast(PlatformId, pub.platform), pub.owner_id, pub.post_id)
        adapter = adapters.get(ref.platform)
        if adapter is None:
            return "not-checked"  # площадка выключена на сервере
        async with gate:
            try:
                found = await adapter.fetch_post(ref)
            except AdapterError:
                return "not-checked"
        return "ok" if found is not None else "deleted"

    states = await asyncio.gather(*(check(p) for p in publications))
    deleted: list[str] = []
    for pub, state in zip(publications, states, strict=True):
        if state == "not-checked":
            continue
        pub.link_state = state
        pub.link_checked_at = now
        if state == "deleted":
            deleted.append(pub.id)
    checked = sum(1 for s in states if s != "not-checked")
    return LinkRecheckReport(
        checked=checked, ok=checked - len(deleted), deleted_item_ids=deleted, checked_at=iso(now)
    )
