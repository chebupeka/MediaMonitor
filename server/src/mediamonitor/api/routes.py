"""HTTP API: каждый метод MonitorApi (web/src/api/client.ts) — один запрос.

Таблица соответствия — docs/12-tech-design.md, «API». Ответы — модели contract.py
(та же форма, что types.ts). Ключ рабочего места — заголовок `X-Workspace-Key`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.aicheck import normalize_text
from mediamonitor.contract import (
    KRASNOYARSK_KRAI,
    AiCheck,
    ApiModel,
    CatalogSource,
    ExcludeSourceResult,
    ExclusionsBody,
    ExportOptions,
    ExportPreview,
    FinishedEvent,
    IdsBody,
    ImportPreview,
    ImportReport,
    ItemsEvent,
    KeyBody,
    LinkRecheckReport,
    PlatformId,
    QueryAnalysis,
    RecentSearch,
    Relevance,
    ResultItem,
    RunTicket,
    SearchConditions,
    SearchMode,
    SearchRequest,
    Selection,
    SelectionCounts,
    Source,
    SourceCheck,
    SourceIdBody,
    SourceInput,
    SourcePatch,
    SourcesRecheckReport,
    SpreadReport,
    StandStatus,
    StartedEvent,
    StartState,
    StoppedEvent,
    TextBody,
    TopicBody,
    TopicEvent,
    TopicUnderstanding,
    UrlBody,
    Workspace,
    WorkspaceLink,
)
from mediamonitor.db.models import ExportRow, SearchRow, WorkspaceRow, WorkspaceSourceRow
from mediamonitor.errors import ApiProblem, required
from mediamonitor.normalize.query import analyze, preset_period
from mediamonitor.services import curation, imports
from mediamonitor.services import sources as source_service
from mediamonitor.services import workspace as workspace_service
from mediamonitor.services.context import AppContext
from mediamonitor.services.events import encode_sse, heartbeat_or_event, is_terminal, read_events
from mediamonitor.services.export import build_preview, build_xlsx, export_items, file_name
from mediamonitor.services.selection import build_selection
from mediamonitor.services.spread import build_spread
from mediamonitor.services.stand import platform_infos, stand_status
from mediamonitor.timeutil import krsk_today, utcnow

router = APIRouter(prefix="/api")

WorkspaceKey = Annotated[
    str | None,
    Header(alias="X-Workspace-Key", description="Ключ рабочего места (Р8) из ссылки-ключа"),
]
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FIXTURE_DATA_NOTE = (
    "Записанные примеры (режим разработки): источники вымышлены, это не живые данные."
)
LIVE_DATA_NOTE = (
    "Получены с площадок в момент поиска. Ссылки построены сервисом по ключу поста, тексты и "
    "даты — из записи поста."
)


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


@asynccontextmanager
async def workspace_tx(
    ctx: AppContext, key: str | None
) -> AsyncIterator[tuple[AsyncSession, WorkspaceRow]]:
    """Транзакция от имени рабочего места: всё внутри видит только его данные (НТ-7)."""
    async with ctx.sessions.begin() as session:
        workspace = await workspace_service.require_workspace(session, key)
        now = utcnow()
        if now - workspace.last_seen_at > timedelta(minutes=5):
            workspace.last_seen_at = now
        yield session, workspace


def _data_note(ctx: AppContext) -> str:
    base = FIXTURE_DATA_NOTE if ctx.settings.data_source == "fixtures" else LIVE_DATA_NOTE
    media = {"site": ctx.settings.sites_source, "dzen": ctx.settings.dzen_source}
    shown = {p: mode for p, mode in media.items() if p in ctx.adapters and mode != "off"}
    if not shown:
        return base
    # Сайты СМИ и Дзен включаются отдельно от VK, OK, MAX — говорим про каждую часть.
    names = {"site": "сайты СМИ", "dzen": "Дзен"}
    live = [names[p] for p, mode in shown.items() if mode == "live"]
    recorded = [names[p] for p, mode in shown.items() if mode == "fixtures"]
    parts = [f"VK, OK и MAX: {base[0].lower()}{base[1:]}"]
    if live:
        what = " и ".join(live)
        parts.append(f"{what[0].upper()}{what[1:]}: получены с публичных страниц в момент поиска.")
    if recorded:
        what = " и ".join(recorded)
        parts.append(f"{what[0].upper()}{what[1:]}: записанные образцы ответов.")
    return " ".join(parts)


# ---------------------------------------------------------------- старт и запрос


@router.get("/start", response_model=StartState, summary="getStartState")
async def get_start_state(ctx: Ctx, key: WorkspaceKey = None) -> StartState:
    async with workspace_tx(ctx, key) as (session, workspace):
        count = await session.scalar(
            select(func.count())
            .select_from(WorkspaceSourceRow)
            .where(
                WorkspaceSourceRow.workspace_id == workspace.id,
                WorkspaceSourceRow.removed_at.is_(None),
            )
        )
    sources = int(count or 0)
    # Первый запуск — «Везде»; дальше — последний выбор человека (п. 47). Пустой список
    # источников — снова «Везде»: искать «по моим» нечему (НТ-14).
    remembered = (
        workspace.last_mode if workspace.last_mode in ("my-sources", "everywhere") else None
    )
    default_mode: SearchMode = "everywhere"
    if remembered == "my-sources" and sources > 0:
        default_mode = "my-sources"
    return StartState(
        first_run=sources == 0,
        sources_count=sources,
        default_mode=default_mode,
        example_query="Например: безопасность дорожного движения",
        default_period=preset_period("7d", krsk_today()),
        region=KRASNOYARSK_KRAI,
        platforms=platform_infos(ctx),
    )


@router.post("/query/analyze", response_model=QueryAnalysis, summary="analyzeQuery")
async def analyze_query(ctx: Ctx, body: TextBody) -> QueryAnalysis:
    return analyze(body.text, max_length=ctx.settings.max_query_length, today=krsk_today())


@router.post("/query/topic", response_model=TopicUnderstanding, summary="understandTopic")
async def understand_topic(ctx: Ctx, body: TopicBody) -> TopicUnderstanding:
    if len(body.text.strip()) > ctx.settings.max_query_length:
        raise ApiProblem(
            "too-long", "Текст запроса длиннее 20 000 знаков. Оставьте заголовок и первые абзацы."
        )
    status = await ctx.judge.status()
    return await ctx.topics.understand(
        status.available, body.text, meaning_id=body.meaning_id, correction=body.correction
    )


# ---------------------------------------------------------------- проверка текста на ИИ


@router.post("/ai-check", response_model=AiCheck, summary="checkAiText")
async def check_ai_text(ctx: Ctx, body: TextBody) -> AiCheck:
    """Отдельная проверка (правый клик, экран вставки): тот же метод и кэш, что у подборки.

    Короче 40 слов — «мало текста» без модели; сервис недоступен — «проверка недоступна».
    """
    limit = ctx.settings.max_query_length
    # Сначала грубо по сырому тексту (не нормализуем мегабайт пробелов), потом точно.
    if len(body.text) > limit * 4 or len(normalize_text(body.text)) > limit:
        raise ApiProblem(
            "too-long",
            "Текст длиннее 20 000 знаков. Выделите статью или её часть.",
        )
    return await ctx.ai_checks.check_text(body.text)


# ---------------------------------------------------------------- поиск


@router.post("/searches", status_code=202, response_model=RunTicket, summary="startSearch")
async def start_search(ctx: Ctx, request: SearchRequest, key: WorkspaceKey = None) -> RunTicket:
    async with workspace_tx(ctx, key) as (_, workspace):
        pass
    return await ctx.runner.start(workspace, request)


@router.get("/searches/{search_id}/events", summary="поток событий хода поиска (SSE)")
async def search_events(
    ctx: Ctx,
    search_id: str,
    request: Request,
    *,
    key: WorkspaceKey = None,
    after: Annotated[int, Query(ge=0)] = 0,
    snapshot: bool = False,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    async with workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
    if last_event_id and last_event_id.isdigit():
        after, snapshot = int(last_event_id), False

    async def stream() -> AsyncIterator[bytes]:
        position = after
        if snapshot:
            async with ctx.sessions() as session:
                row = await session.get(SearchRow, search.id)
                row = required(row, "row")
                selection = await build_selection(session, row, ctx.adapters, ctx.ai_checks)
                position = row.event_seq
            for event in _snapshot_events(selection):
                yield encode_sse(position, event)
            if selection.phase != "running":
                return
        while True:
            if await request.is_disconnected():
                return
            seen = ctx.bus.version(search.id)
            async with ctx.sessions() as session:
                rows = await read_events(session, search.id, position)
                phase = await session.scalar(
                    select(SearchRow.phase).where(SearchRow.id == search.id)
                )
            for event_row in rows:
                yield encode_sse(event_row.seq, event_row.payload)
                position = event_row.seq
                if is_terminal(event_row):
                    return
            if rows:
                continue
            if phase != "running":
                return
            async for ping in heartbeat_or_event(ctx.bus, search.id, seen):
                yield ping

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _snapshot_events(selection: Selection) -> list[dict[str, Any]]:
    """attachSearch: снимок подборки — `started`, `topic`, `items`, затем итог (если есть)."""
    events: list[ApiModel] = [
        StartedEvent(conditions=selection.conditions, statuses=selection.statuses)
    ]
    if selection.topic is not None:
        events.append(TopicEvent(topic=selection.topic))
    if selection.items:
        events.append(
            ItemsEvent(items=selection.items, groups=selection.groups, counts=selection.counts)
        )
    if selection.phase == "done":
        events.append(FinishedEvent(selection=selection))
    elif selection.phase == "stopped":
        events.append(StoppedEvent(selection=selection))
    return [event.dump() for event in events]


@router.post("/searches/{search_id}/stop", status_code=204, summary="stopSearch")
async def stop_search(ctx: Ctx, search_id: str, key: WorkspaceKey = None) -> Response:
    async with workspace_tx(ctx, key) as (_, workspace):
        pass
    await ctx.runner.stop(workspace, search_id)
    return Response(status_code=204)


@router.post(
    "/searches/{search_id}/platforms/{platform}/retry",
    status_code=202,
    response_model=RunTicket,
    summary="retryPlatform",
)
async def retry_platform(
    ctx: Ctx, search_id: str, platform: PlatformId, key: WorkspaceKey = None
) -> RunTicket:
    async with workspace_tx(ctx, key) as (_, workspace):
        pass
    return await ctx.runner.retry(workspace, search_id, platform)


@router.get("/searches/{search_id}", response_model=Selection, summary="getSelection")
async def get_selection(ctx: Ctx, search_id: str, key: WorkspaceKey = None) -> Selection:
    async with workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
        return await build_selection(session, search, ctx.adapters, ctx.ai_checks)


@router.post(
    "/searches/{search_id}/exclusions", response_model=SelectionCounts, summary="setExcluded"
)
async def set_excluded(
    ctx: Ctx, search_id: str, body: ExclusionsBody, key: WorkspaceKey = None
) -> SelectionCounts:
    async with ctx.runner.lock_for(search_id), workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
        return await curation.set_excluded(
            session, ctx.adapters, search, body.item_ids, body.excluded, ai=ctx.ai_checks
        )


@router.post(
    "/searches/{search_id}/exclusions/source",
    response_model=ExcludeSourceResult,
    summary="excludeSource",
)
async def exclude_source(
    ctx: Ctx, search_id: str, body: SourceIdBody, key: WorkspaceKey = None
) -> ExcludeSourceResult:
    async with ctx.runner.lock_for(search_id), workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
        return await curation.exclude_source(
            session, ctx.adapters, search, body.source_id, ai=ctx.ai_checks
        )


@router.post(
    "/searches/{search_id}/items", status_code=201, response_model=ResultItem, summary="addByUrl"
)
async def add_by_url(
    ctx: Ctx, search_id: str, body: UrlBody, key: WorkspaceKey = None
) -> ResultItem:
    async with ctx.runner.lock_for(search_id), workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
        item = await curation.add_by_url(
            session, ctx.adapters, search, body.url, ctx.matcher.split_sentences
        )
    # Проверка на ИИ — после записи, без открытой транзакции; результат идёт в общий кэш,
    # поэтому подборка потом покажет то же самое.
    text = item.publication.text
    if text is None:
        return item
    return item.model_copy(update={"ai_check": await ctx.ai_checks.check_text(text)})


@router.post(
    "/searches/{search_id}/links/recheck", response_model=LinkRecheckReport, summary="recheckLinks"
)
async def recheck_links(ctx: Ctx, search_id: str, key: WorkspaceKey = None) -> LinkRecheckReport:
    async with workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
        return await curation.recheck_links(session, ctx.adapters, search)


@router.get("/searches/{search_id}/spread", response_model=SpreadReport, summary="getSpread")
async def get_spread(
    ctx: Ctx,
    search_id: str,
    key: WorkspaceKey = None,
    group_id: Annotated[str | None, Query(alias="groupId")] = None,
) -> SpreadReport:
    async with workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
        selection = await build_selection(session, search, ctx.adapters, ctx.ai_checks)
        return build_spread(selection, search.release, group_id, ai_enabled=ctx.ai_checks.enabled)


def _export_options(
    only_relevance: list[Relevance] | None, only_undated: bool | None
) -> ExportOptions:
    return ExportOptions(
        only_relevance=list(dict.fromkeys(only_relevance)) if only_relevance else None,
        only_undated=True if only_undated else None,
    )


OnlyRelevance = Annotated[list[Relevance] | None, Query(alias="onlyRelevance")]
OnlyUndated = Annotated[bool | None, Query(alias="onlyUndated")]


@router.get(
    "/searches/{search_id}/export/preview", response_model=ExportPreview, summary="getExportPreview"
)
async def export_preview(
    ctx: Ctx,
    search_id: str,
    key: WorkspaceKey = None,
    only_relevance: OnlyRelevance = None,
    only_undated: OnlyUndated = None,
) -> ExportPreview:
    async with workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
        selection = await build_selection(session, search, ctx.adapters, ctx.ai_checks)
    return build_preview(selection, _export_options(only_relevance, only_undated), _data_note(ctx))


@router.get(
    "/searches/{search_id}/export.xlsx", summary="скачать XLSX (тот же состав, что в предпросмотре)"
)
async def export_xlsx(
    ctx: Ctx,
    search_id: str,
    key: WorkspaceKey = None,
    only_relevance: OnlyRelevance = None,
    only_undated: OnlyUndated = None,
) -> Response:
    options = _export_options(only_relevance, only_undated)
    async with workspace_tx(ctx, key) as (session, workspace):
        search = await curation.own_search(session, workspace, search_id)
        selection = await build_selection(session, search, ctx.adapters, ctx.ai_checks)
        content = build_xlsx(selection, options, _data_note(ctx))
        name = file_name(selection)
        # Столько строк в листе «Публикации» — то же число, что в предпросмотре (rowCount).
        rows = len(export_items(selection, options))
        session.add(
            ExportRow(
                search_id=search.id,
                workspace_id=workspace.id,
                options=options.dump(),
                row_count=rows,
                file_name=name,
                created_at=utcnow(),
            )
        )
    disposition = f"attachment; filename=\"mediamonitor.xlsx\"; filename*=UTF-8''{quote(name)}"
    # `X-Export-Rows` — `ExportFile.rowCount` для getExportFile интерфейса.
    return Response(
        content=content,
        media_type=XLSX_TYPE,
        headers={"Content-Disposition": disposition, "X-Export-Rows": str(rows)},
    )


# ---------------------------------------------------------------- источники


@router.get("/sources", response_model=list[Source], summary="listSources")
async def list_sources(ctx: Ctx, key: WorkspaceKey = None) -> list[Source]:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await source_service.list_sources(session, workspace)


@router.post("/sources/check", response_model=SourceCheck, summary="checkSource")
async def check_source(ctx: Ctx, body: UrlBody, key: WorkspaceKey = None) -> SourceCheck:
    async with workspace_tx(ctx, key) as (session, workspace):
        check, _ = await source_service.check_url(session, ctx.adapters, workspace, body.url)
        return check


@router.post("/sources", status_code=201, response_model=Source, summary="addSource")
async def add_source(ctx: Ctx, body: SourceInput, key: WorkspaceKey = None) -> Source:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await source_service.add_source(session, ctx.adapters, workspace, body)


@router.post("/sources/recheck", response_model=SourcesRecheckReport, summary="recheckSources")
async def recheck_sources(ctx: Ctx, key: WorkspaceKey = None) -> SourcesRecheckReport:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await source_service.recheck_sources(session, ctx.adapters, workspace)


@router.post("/sources/import/preview", response_model=ImportPreview, summary="previewImport")
async def preview_import(
    ctx: Ctx,
    file: Annotated[UploadFile, File(description="Excel (.xlsx) или CSV")],
    key: WorkspaceKey = None,
) -> ImportPreview:
    content = await file.read(ctx.settings.max_import_bytes + 1)
    if len(content) > ctx.settings.max_import_bytes:
        raise ApiProblem("too-long", "Файл больше 5 МБ. Оставьте в нём только список источников.")
    async with workspace_tx(ctx, key) as (session, workspace):
        return await imports.preview_import(
            session,
            adapters=ctx.adapters,
            workspace=workspace,
            file_name=(file.filename or "файл").strip()[:200],
            content=content,
            max_rows=ctx.settings.max_import_rows,
        )


@router.post("/sources/import/{preview_id}", response_model=ImportReport, summary="importSources")
async def import_sources(ctx: Ctx, preview_id: str, key: WorkspaceKey = None) -> ImportReport:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await imports.run_import(session, workspace, preview_id)


@router.post("/sources/from-catalog", response_model=list[Source], summary="addFromCatalog")
async def add_from_catalog(ctx: Ctx, body: IdsBody, key: WorkspaceKey = None) -> list[Source]:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await source_service.add_from_catalog(session, workspace, body.ids)


@router.patch("/sources/{source_id}", response_model=Source, summary="updateSource")
async def update_source(
    ctx: Ctx, source_id: str, body: SourcePatch, key: WorkspaceKey = None
) -> Source:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await source_service.update_source(session, workspace, source_id, body)


@router.delete("/sources/{source_id}", status_code=204, summary="removeSource")
async def remove_source(ctx: Ctx, source_id: str, key: WorkspaceKey = None) -> Response:
    async with workspace_tx(ctx, key) as (session, workspace):
        await source_service.remove_source(session, workspace, source_id)
    return Response(status_code=204)


@router.post("/sources/{source_id}/restore", response_model=Source, summary="restoreSource")
async def restore_source(ctx: Ctx, source_id: str, key: WorkspaceKey = None) -> Source:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await source_service.restore_source(
            session, workspace, source_id, ctx.settings.source_restore_minutes
        )


@router.get("/catalog", response_model=list[CatalogSource], summary="getCatalog")
async def get_catalog(ctx: Ctx, key: WorkspaceKey = None) -> list[CatalogSource]:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await source_service.catalog(session, workspace)


# ---------------------------------------------------------------- рабочее место (Р8)


@router.post(
    "/workspaces", status_code=201, response_model=WorkspaceLink, summary="новое рабочее место"
)
async def create_workspace(ctx: Ctx, request: Request) -> WorkspaceLink:
    # Предел новых рабочих мест с одного адреса за сутки (НТ-6); частота — RateLimitMiddleware.
    await ctx.new_workspaces.admit(request.client.host if request.client else None)
    async with ctx.sessions.begin() as session:
        row, key = await workspace_service.create_workspace(session)
    return workspace_service.link_of(row, key, ctx.settings.public_app_url)


@router.get("/workspace", response_model=Workspace, summary="getWorkspace")
async def get_workspace(ctx: Ctx, key: WorkspaceKey = None) -> Workspace:
    async with workspace_tx(ctx, key) as (session, workspace):
        return await workspace_service.to_contract(session, workspace)


@router.get("/workspace/link", response_model=WorkspaceLink, summary="getWorkspaceLink")
async def get_workspace_link(ctx: Ctx, key: WorkspaceKey = None) -> WorkspaceLink:
    async with workspace_tx(ctx, key) as (_, workspace):
        pass
    key = required(key, "key")
    return workspace_service.link_of(
        workspace, workspace_service.clean_key(key), ctx.settings.public_app_url
    )


@router.post("/workspace/open", response_model=Workspace, summary="openWorkspace")
async def open_workspace(ctx: Ctx, body: KeyBody) -> Workspace:
    async with ctx.sessions.begin() as session:
        workspace = await workspace_service.find_workspace(
            session, workspace_service.clean_key(body.key)
        )
        if workspace is None:
            raise ApiProblem("not-found", workspace_service.NOT_FOUND)
        workspace.last_seen_at = utcnow()
        return await workspace_service.to_contract(session, workspace)


# ---------------------------------------------------------------- недавние, стенд


@router.get("/recent", response_model=list[RecentSearch], summary="listRecent")
async def list_recent(ctx: Ctx, key: WorkspaceKey = None) -> list[RecentSearch]:
    async with workspace_tx(ctx, key) as (session, workspace):
        rows = await session.scalars(
            select(SearchRow)
            .where(
                SearchRow.workspace_id == workspace.id,
                SearchRow.in_recent.is_(True),
                SearchRow.phase != "running",
            )
            .order_by(SearchRow.created_at.desc())
            .limit(20)
        )
        return [
            RecentSearch(
                search_id=row.id,
                conditions=SearchConditions.model_validate(row.conditions),
                total=row.result_total,
                status_summary=row.status_summary,
                request=SearchRequest.model_validate(row.request),
            )
            for row in rows
        ]


@router.get("/stand", response_model=StandStatus, summary="getStandStatus")
async def get_stand_status(ctx: Ctx) -> StandStatus:
    return await stand_status(ctx)
