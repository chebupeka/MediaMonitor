"""Подборка из базы в форме контракта: записи, группы, счётчики, статусы площадок.

Одни и те же функции собирают ответ getSelection, события потока, XLSX и
«Распространение» — поэтому числа везде совпадают (ТЗ-Ф38, правило «числа совпадают»).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.adapters import AdapterRegistry
from mediamonitor.contract import (
    PLATFORM_ORDER,
    AiCheck,
    ByPlacementType,
    ByPlatform,
    ByRelevance,
    Citation,
    Evidence,
    Excerpt,
    LinkCheck,
    PlacementType,
    PlatformCap,
    PlatformId,
    PlatformProblem,
    PlatformState,
    PlatformStatus,
    PostKey,
    ProgressCounter,
    Publication,
    RegionReason,
    RepostOf,
    ResultGroup,
    ResultItem,
    SearchConditions,
    Selection,
    SelectionCounts,
    SelectionNotice,
    Sentence,
    SourceRef,
    TimeReliability,
    TopicUnderstanding,
    source_type,
)
from mediamonitor.db.models import (
    PlatformRunRow,
    PlatformSourceRow,
    PublicationRow,
    SearchGroupRow,
    SearchItemRow,
    SearchRow,
    WorkspaceSourceRow,
)
from mediamonitor.normalize.text import Span, headline
from mediamonitor.timeutil import iso, iso_or_none

if TYPE_CHECKING:
    from mediamonitor.aicheck import AiCheckService

UNDATED_NOTICE = SelectionNotice(
    code="undated-included",
    tone="info",
    message="Публикации без даты показаны с пометкой «дата неизвестна»: проверить, что они "
    "попадают в период, нельзя.",
)
MEDIA_NOTICE = SelectionNotice(
    code="images-not-analyzed",
    tone="info",
    message="Текст на картинках и в видео не анализируется.",
)


@dataclass(frozen=True)
class ItemBundle:
    item: SearchItemRow
    publication: PublicationRow
    source: PlatformSourceRow | None


async def my_source_ids(session: AsyncSession, workspace_id: str) -> set[str]:
    rows = await session.scalars(
        select(WorkspaceSourceRow.source_id).where(
            WorkspaceSourceRow.workspace_id == workspace_id,
            WorkspaceSourceRow.removed_at.is_(None),
        )
    )
    return set(rows)


async def load_bundles(
    session: AsyncSession, search_id: str, item_ids: Iterable[str] | None = None
) -> list[ItemBundle]:
    query = (
        select(SearchItemRow, PublicationRow, PlatformSourceRow)
        .join(PublicationRow, PublicationRow.id == SearchItemRow.publication_id)
        .outerjoin(PlatformSourceRow, PlatformSourceRow.id == PublicationRow.source_id)
        .where(SearchItemRow.search_id == search_id)
        .order_by(SearchItemRow.arrival)
    )
    if item_ids is not None:
        ids = list(item_ids)
        if not ids:
            return []
        query = query.where(SearchItemRow.publication_id.in_(ids))
    result = await session.execute(query)
    return [ItemBundle(item, pub, src) for item, pub, src in result]


def source_ref(
    source: PlatformSourceRow | None, publication: PublicationRow, mine: set[str]
) -> SourceRef:
    if source is None:
        return SourceRef(
            id=f"{publication.platform}:{publication.owner_id}",
            platform=cast(PlatformId, publication.platform),
            name="Источник не определён",
            url=publication.url,
            type="community",
            district=None,
            subscribers=None,
            in_my_sources=False,
            regional=False,
        )
    return SourceRef(
        id=source.id,
        platform=cast(PlatformId, source.platform),
        name=source.name,
        url=source.url,
        type=source_type(source.type),
        district=source.district,
        subscribers=source.subscribers,
        in_my_sources=source.id in mine,
        regional=source.regional,
    )


def publication_model(bundle: ItemBundle, mine: set[str]) -> Publication:
    pub = bundle.publication
    spans = [Span(int(s[0]), int(s[1])) for s in pub.sentences]
    title_text, from_title = headline(pub.title, pub.text, spans)
    repost = pub.repost_of
    return Publication(
        id=pub.id,
        key=PostKey(
            platform=cast(PlatformId, pub.platform), owner_id=pub.owner_id, post_id=pub.post_id
        ),
        platform=cast(PlatformId, pub.platform),
        source=source_ref(bundle.source, pub, mine),
        url=pub.url,
        merged_urls=[str(u) for u in pub.merged_urls],
        title=pub.title,
        headline=title_text,
        headline_from="title" if from_title else "text",
        text=pub.text,
        sentences=[Sentence(index=i, start=s.start, end=s.end) for i, s in enumerate(spans)],
        published_at=iso_or_none(pub.published_at),
        time_reliability=cast(TimeReliability, pub.time_reliability),
        edited=pub.edited,
        repost_of=RepostOf(source_name=repost["sourceName"], url=repost["url"]) if repost else None,
        has_media=pub.has_media,
        views=pub.views,
        reactions=pub.reactions,
        fetched_at=iso(pub.fetched_at),
        link_check=LinkCheck(
            state=cast(Any, pub.link_state), checked_at=iso_or_none(pub.link_checked_at)
        ),
    )


def output_placement(row: SearchItemRow, kind: str) -> PlacementType | None:
    """Тип размещения показываем при поиске по тексту новости и внутри групп копий (П2)."""
    if row.placement_type is None:
        return None
    if kind != "news-text" and row.group_id is None:
        return None
    return cast(PlacementType, row.placement_type)


def result_item(
    bundle: ItemBundle, mine: set[str], kind: str, ai_check: AiCheck | None = None
) -> ResultItem:
    row = bundle.item
    publication = publication_model(bundle, mine)
    text = publication.text
    excerpt = None
    if text is not None and row.excerpt is not None:
        start, end = int(row.excerpt["start"]), int(row.excerpt["end"])
        excerpt = Excerpt(
            start=start,
            end=end,
            text=text[start:end],
            cut_start=start > 0,
            cut_end=end < len(text),
        )
    citation = None
    if row.citation is not None and kind == "news-text":
        citation = Citation.model_validate(row.citation)
    return ResultItem(
        id=row.publication_id,
        publication=publication,
        relevance=cast(Any, row.relevance),
        method=cast(Any, row.method),
        method_note=row.method_note,
        region_reason=RegionReason.model_validate(row.region_reason),
        excerpt=excerpt,
        evidence=Evidence.model_validate(row.evidence)
        if row.evidence and text is not None
        else None,
        placement_type=output_placement(row, kind),
        is_original=row.is_original,
        citation=citation,
        group_id=row.group_id,
        excluded=row.excluded,
        is_new=row.is_new,
        arrival=row.arrival,
        ai_check=ai_check,
    )


async def ai_checks_of(
    session: AsyncSession, bundles: Sequence[ItemBundle], ai: AiCheckService | None
) -> dict[str, AiCheck]:
    """Проверка на ИИ для записей — из общего кэша по тексту поста (тот же, что у отдельной
    проверки). Пока текст проверяется фоном, результата нет."""
    if ai is None:
        return {}
    return await ai.lookup(session, {b.item.publication_id: b.publication.text for b in bundles})


def compute_counts(items: Sequence[ResultItem]) -> SelectionCounts:
    counts = SelectionCounts(
        total=0,
        excluded=0,
        by_relevance=ByRelevance(),
        by_platform=ByPlatform(),
        by_placement_type=ByPlacementType(),
        new=0,
        ai_likely=0,
        ai_signs=0,
        undated=0,
    )
    for item in items:
        if item.excluded:
            counts.excluded += 1
            continue
        if item.ai_check is not None:
            if item.ai_check.level == "likely-ai":
                counts.ai_likely += 1
            elif item.ai_check.level == "signs":
                counts.ai_signs += 1
        counts.total += 1
        counts.by_relevance.add(item.relevance)
        counts.by_platform.add(item.publication.platform)
        if item.placement_type is not None:
            counts.by_placement_type.add(item.placement_type)
        if item.is_new:
            counts.new += 1
        if item.publication.published_at is None:
            counts.undated += 1
    return counts


def _published_key(item: ResultItem) -> str:
    return item.publication.published_at or "9"


def compute_groups(
    group_rows: Sequence[SearchGroupRow], items: Sequence[ResultItem]
) -> list[ResultGroup]:
    groups: list[ResultGroup] = []
    for row in group_rows:
        members = sorted((i for i in items if i.group_id == row.id), key=_published_key)
        if not members:
            continue
        by_platform = ByPlatform()
        by_type = ByPlacementType()
        for member in members:
            if member.excluded:
                continue
            by_platform.add(member.publication.platform)
            if member.placement_type is not None:
                by_type.add(member.placement_type)
        original = next((m.id for m in members if m.is_original), None)
        groups.append(
            ResultGroup(
                id=row.id,
                title=row.title,
                kind=cast(Any, row.kind),
                item_ids=[m.id for m in members],
                original_item_id=original,
                counts_by_platform=by_platform,
                counts_by_type=by_type,
            )
        )
    return groups


def platform_status(
    run: PlatformRunRow, found: int, adapters: AdapterRegistry, phase: str
) -> PlatformStatus:
    platform = cast(PlatformId, run.platform)
    state = cast(PlatformState, run.state)
    if phase == "stopped" and state in ("waiting", "searching"):
        state = "stopped"
    show_progress = state in ("searching", "partial", "stopped") or run.total == 0
    adapter = adapters.get(platform)
    return PlatformStatus(
        platform=platform,
        state=state,
        found=found,
        progress=ProgressCounter(
            done=int(run.done + 1e-6), total=run.total, unit=cast(Any, run.unit)
        )
        if show_progress
        else None,
        problem=PlatformProblem.model_validate(run.problem) if run.problem else None,
        freshness=adapter.description.freshness if adapter else None,
        cap=PlatformCap.model_validate(run.cap) if run.cap else None,
        updated_at=iso_or_none(run.updated_at),
    )


async def load_runs(session: AsyncSession, search_id: str) -> list[PlatformRunRow]:
    rows = list(
        await session.scalars(select(PlatformRunRow).where(PlatformRunRow.search_id == search_id))
    )
    rows.sort(key=lambda r: PLATFORM_ORDER.index(cast(PlatformId, r.platform)))
    return rows


def statuses_of(
    runs: Sequence[PlatformRunRow],
    items: Sequence[ResultItem],
    adapters: AdapterRegistry,
    phase: str,
) -> list[PlatformStatus]:
    found: dict[str, int] = {}
    for item in items:
        if not item.excluded:
            found[item.publication.platform] = found.get(item.publication.platform, 0) + 1
    return [platform_status(run, found.get(run.platform, 0), adapters, phase) for run in runs]


def notices_of(search: SearchRow, items: Sequence[ResultItem]) -> list[SelectionNotice]:
    notices = [SelectionNotice.model_validate(n) for n in search.notices]
    codes = {n.code for n in notices}
    if "undated-included" not in codes and any(i.publication.published_at is None for i in items):
        notices.append(UNDATED_NOTICE)
    if "images-not-analyzed" not in codes and any(i.publication.has_media for i in items):
        notices.append(MEDIA_NOTICE)
    return notices


def conditions_of(search: SearchRow) -> SearchConditions:
    return SearchConditions.model_validate(search.conditions)


def phase_of(search: SearchRow) -> str:
    return search.phase if search.phase in ("running", "done", "stopped") else "done"


async def build_selection(
    session: AsyncSession,
    search: SearchRow,
    adapters: AdapterRegistry,
    ai: AiCheckService | None = None,
) -> Selection:
    mine = await my_source_ids(session, search.workspace_id)
    bundles = await load_bundles(session, search.id)
    checks = await ai_checks_of(session, bundles, ai)
    items = [result_item(b, mine, search.kind, checks.get(b.item.publication_id)) for b in bundles]
    group_rows = list(
        await session.scalars(
            select(SearchGroupRow)
            .where(SearchGroupRow.search_id == search.id)
            .order_by(SearchGroupRow.created_at)
        )
    )
    runs = await load_runs(session, search.id)
    phase = phase_of(search)
    return Selection(
        search_id=search.id,
        conditions=conditions_of(search),
        statuses=statuses_of(runs, items, adapters, phase),
        items=items,
        groups=compute_groups(group_rows, items),
        counts=compute_counts(items),
        topic=TopicUnderstanding.model_validate(search.topic) if search.topic else None,
        notices=notices_of(search, items),
        ai_available=search.ai_available,
        phase=cast(Any, phase),
    )
