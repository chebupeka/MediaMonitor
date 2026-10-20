"""Контракт API — зеркало `web/src/api/types.ts` на Pydantic v2.

Правила:
- имена полей в JSON те же, что в types.ts (camelCase); в Python — snake_case;
- поле `x: T | null` в TS — обязательное и может быть `None` (в JSON будет `null`);
- поле `x?: T` в TS — `absent()`: если значения нет, ключа в JSON нет совсем;
- менять файл можно только вместе с types.ts; соответствие проверяет
  tests/contract/test_contract_schema.py по JSON Schema, собранной из types.ts;
- `server_only()` — поле, которое сервер считает для себя (XLSX, проверки, будущие
  экраны), но в JSON не отдаёт: в контракте ветки интерфейса его нет
  (docs/04-decisions.md, «Основа фронтенда — ветка команды»).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _is_none(value: object) -> bool:
    return value is None


def absent(**kwargs: Any) -> Any:
    """Необязательное поле (`x?: T` в TS): None не попадает в JSON."""
    return Field(default=None, exclude_if=_is_none, **kwargs)


def server_only(default: Any) -> Any:
    """Поле только для сервера: в JSON не попадает, при чтении ответа без него — `default`."""
    if isinstance(default, list):
        return Field(default_factory=list, exclude=True)
    return Field(default=default, exclude=True)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
    )

    def dump(self) -> dict[str, Any]:
        """JSON-совместимый словарь в форме контракта (camelCase)."""
        return self.model_dump(mode="json", by_alias=True)


# ============================================================================
# Базовые обозначения
# ============================================================================

IsoDateTime = str
IsoDate = str
PlatformId = Literal["vk", "ok", "max", "site", "dzen"]
PLATFORM_ORDER: tuple[PlatformId, ...] = ("vk", "ok", "max", "site", "dzen")
# Обязательные площадки ТЗ (ТЗ-Ф18); сайты СМИ края и Дзен — дополнительные (ТЗ-Ф17).
REQUIRED_PLATFORMS: tuple[PlatformId, ...] = ("vk", "ok", "max")
QueryKind = Literal["topic", "event", "news-text"]
SearchMode = Literal["my-sources", "everywhere"]
PeriodPreset = Literal["today", "24h", "7d", "30d", "custom"]
PlatformState = Literal[
    "waiting", "searching", "found", "nothing", "partial", "error", "no-access", "stopped"
]
SourceType = Literal["media", "authority", "municipal", "institution", "community", "blogger"]
SOURCE_TYPES: frozenset[str] = frozenset(
    ("media", "authority", "municipal", "institution", "community", "blogger")
)
# Типы прежнего контракта (до ветки интерфейса) — в базе и в старых записях.
_LEGACY_SOURCE_TYPES: dict[str, SourceType] = {
    "krai-media": "media",
    "local-media": "media",
    "gov": "authority",
    "other": "media",
}
TimeReliability = Literal["exact", "approximate", "unknown"]
Relevance = Literal["direct", "indirect", "disputed"]
RELEVANCE_ORDER: tuple[Relevance, ...] = ("direct", "indirect", "disputed")
SelectionMethod = Literal["copy", "semantic", "ai-confirmed", "ai-unchecked", "manual"]
PlacementType = Literal["verbatim", "shortened", "retold", "repost"]
PLACEMENT_ORDER: tuple[PlacementType, ...] = ("verbatim", "shortened", "retold", "repost")
HealthState = Literal["ok", "degraded", "down"]
ProblemCode = Literal[
    "unavailable",
    "timeout",
    "bad-response",
    "rate-limited",
    "key-invalid",
    "quota-exhausted",
    "sources-closed",
]
SourceCheckState = Literal[
    "ok", "not-found", "closed", "not-supported", "duplicate", "not-regional", "post-link"
]
ApiErrorCode = Literal["offline", "too-many-requests", "too-long", "not-found", "invalid", "server"]
WHOLE_KRAI = "весь край"


def source_type(value: str | None) -> SourceType:
    """Тип источника в форме контракта: прежние значения переводятся, неизвестное — сообщество."""
    if value in SOURCE_TYPES:
        return value  # type: ignore[return-value]
    return _LEGACY_SOURCE_TYPES.get(value or "", "community")


class Region(ApiModel):
    id: Literal["krasnoyarsk-krai"]
    name: str
    time_zone: Literal["Asia/Krasnoyarsk"]


KRASNOYARSK_KRAI = Region(
    id="krasnoyarsk-krai", name="Красноярский край", time_zone="Asia/Krasnoyarsk"
)


# ============================================================================
# Запрос и условия поиска
# ============================================================================


class Period(ApiModel):
    preset: PeriodPreset
    from_: IsoDate = Field(alias="from")
    to: IsoDate


class TopicCorrection(ApiModel):
    include: list[str]
    exclude: list[str]
    notes: str | None = absent()


class SearchRequest(ApiModel):
    text: str
    period: Period
    mode: SearchMode
    source_ids: list[str] | None = absent()
    platforms: list[PlatformId] | None = absent()
    meaning_id: str | None = absent()
    topic: TopicCorrection | None = absent()
    repeat_of: str | None = absent()


class SearchConditions(ApiModel):
    search_id: str
    text: str
    label: str
    kind: QueryKind
    period: Period
    region: Region
    mode: SearchMode
    source_count: int | None
    platforms: list[PlatformId]
    meaning_label: str | None
    started_at: IsoDateTime
    finished_at: IsoDateTime | None
    repeat_of: str | None


# ============================================================================
# Разбор поля запроса и «как система поняла тему»
# ============================================================================


class ReplaceTextFix(ApiModel):
    type: Literal["replace-text"]
    label: str
    text: str


class SetPeriodFix(ApiModel):
    type: Literal["set-period"]
    label: str
    period: Period


QueryHintFix = Annotated[ReplaceTextFix | SetPeriodFix, Field(discriminator="type")]


class QueryHint(ApiModel):
    code: Literal[
        "looks-like-link",
        "too-short",
        "too-long",
        "region-in-text",
        "conversational",
        "time-words",
        "other-region",
    ]
    message: str
    fix: QueryHintFix | None = absent()


class QueryMeaning(ApiModel):
    id: str
    label: str
    description: str


class Ambiguity(ApiModel):
    question: str
    options: list[QueryMeaning]


class QueryAnalysis(ApiModel):
    text: str
    kind: QueryKind
    hints: list[QueryHint]
    ambiguity: Ambiguity | None


class TopicFacet(ApiModel):
    id: str
    label: str
    example: str | None = absent()
    cut_count: int | None = absent()
    origin: Literal["system", "user"]


class EventSigns(ApiModel):
    who: list[str]
    where: list[str]
    when: list[str]
    numbers: list[str]


class CutExample(ApiModel):
    headline: str
    reason: str
    # Грань «не то», которая отсекла пост: перенос грани в «входит» убирает её примеры.
    facet_id: str | None = server_only(None)


class TopicUnderstanding(ApiModel):
    summary: str
    includes: list[TopicFacet]
    excludes: list[TopicFacet]
    signs: EventSigns | None
    made_by: Literal["ai", "rules"]
    note: str | None
    cut_examples: list[CutExample]


# ============================================================================
# Площадки: статусы и свежесть (НТ-3, НТ-4, НТ-5)
# ============================================================================


class ProgressCounter(ApiModel):
    done: int
    total: int
    unit: Literal["sources", "pages"]


class DataFreshness(ApiModel):
    delay_hours: int
    note: str


class PlatformCap(ApiModel):
    limit: int
    note: str


class PlatformProblem(ApiModel):
    code: ProblemCode
    message: str
    retryable: bool


class PlatformStatus(ApiModel):
    platform: PlatformId
    state: PlatformState
    found: int
    progress: ProgressCounter | None
    problem: PlatformProblem | None
    freshness: DataFreshness | None
    cap: PlatformCap | None
    updated_at: IsoDateTime | None
    # Постоянная оговорка о покрытии: «Подключено 43 сайта из 48: …».
    note: str | None = absent()
    # Площадка отвечает записанными примерами (демо): её публикации вымышлены, ссылок нет.
    demo: bool | None = absent()


class PlatformInfo(ApiModel):
    """Площадка, как её описывает сервер: интерфейс не держит список жёстко."""

    id: PlatformId
    name: str
    short: str
    required: bool
    enabled: bool
    via: str
    note: str | None


# ============================================================================
# Источники
# ============================================================================


class SourceRef(ApiModel):
    id: str
    platform: PlatformId
    name: str
    url: str
    type: SourceType
    district: str | None
    subscribers: int | None
    in_my_sources: bool
    regional: bool


class SourcePreview(ApiModel):
    platform: PlatformId
    name: str
    url: str
    subscribers: int | None
    last_post_at: IsoDateTime | None
    suggested_type: SourceType
    suggested_district: str | None


class SourceCheck(ApiModel):
    state: SourceCheckState
    message: str
    preview: SourcePreview | None
    checked_at: IsoDateTime


class Source(SourceRef):
    origin: Literal["manual", "catalog", "import"]
    added_at: IsoDateTime
    check: SourceCheck


class SourceInput(ApiModel):
    url: str
    name: str | None = absent()
    type: SourceType | None = absent()
    district: str | None = None


class ImportColumn(ApiModel):
    letter: str
    title: str
    role: Literal["url", "name", "ignored"]
    note: str


class ImportOutcomeAdd(ApiModel):
    kind: Literal["add"]
    source: SourceRef
    note: str | None


class ImportOutcomeDuplicate(ApiModel):
    kind: Literal["duplicate"]
    source: SourceRef


class ImportOutcomeSkip(ApiModel):
    kind: Literal["skip"]
    reason: str


class ImportOutcomeEmpty(ApiModel):
    kind: Literal["empty"]


ImportRowOutcome = Annotated[
    ImportOutcomeAdd | ImportOutcomeDuplicate | ImportOutcomeSkip | ImportOutcomeEmpty,
    Field(discriminator="kind"),
]


class ImportRow(ApiModel):
    row: int
    value: str
    title: str
    outcome: ImportRowOutcome


class ImportCounts(ApiModel):
    add: int
    duplicate: int
    skip: int
    empty: int


class ImportPreview(ApiModel):
    preview_id: str
    file_name: str
    sheet_name: str
    total_rows: int
    header_row: int | None
    columns: list[ImportColumn]
    rows: list[ImportRow]
    counts: ImportCounts


class ImportDuplicate(ApiModel):
    row: int
    value: str
    name: str


class ImportSkipped(ApiModel):
    row: int
    value: str
    reason: str


class ImportReport(ApiModel):
    added: list[Source]
    duplicates: list[ImportDuplicate]
    skipped: list[ImportSkipped]


class SourcesRecheckProblem(ApiModel):
    source_id: str
    name: str
    state: SourceCheckState
    message: str


class SourcesRecheckReport(ApiModel):
    checked_at: IsoDateTime
    checked: int
    ok: int
    problems: list[SourcesRecheckProblem]
    sources: list[Source]


class CatalogSource(SourceRef):
    description: str


class StartState(ApiModel):
    first_run: bool
    sources_count: int
    default_mode: SearchMode
    example_query: str
    default_period: Period
    region: Region
    platforms: list[PlatformInfo]


# ============================================================================
# Рабочее место (Р8)
# ============================================================================


class Workspace(ApiModel):
    id: str
    created_at: IsoDateTime
    sources_count: int
    recent_count: int


class WorkspaceLink(ApiModel):
    workspace_id: str
    key: str
    url: str
    created_at: IsoDateTime


# ============================================================================
# Публикация и запись подборки
# ============================================================================


class PostKey(ApiModel):
    platform: PlatformId
    owner_id: str
    post_id: str


class Sentence(ApiModel):
    index: int
    start: int
    end: int


class TextRange(ApiModel):
    start: int
    end: int


class LinkCheck(ApiModel):
    state: Literal["ok", "deleted", "not-checked"]
    checked_at: IsoDateTime | None


class RepostOf(ApiModel):
    source_name: str
    url: str


class Publication(ApiModel):
    id: str
    key: PostKey
    platform: PlatformId
    source: SourceRef
    url: str
    merged_urls: list[str]
    title: str | None
    headline: str
    headline_from: Literal["title", "text"]
    text: str | None
    sentences: list[Sentence]
    published_at: IsoDateTime | None
    time_reliability: TimeReliability
    edited: bool
    repost_of: RepostOf | None
    has_media: bool
    views: int | None
    reactions: int | None
    fetched_at: IsoDateTime
    link_check: LinkCheck
    # Публикация из записанных примеров (демо): источник вымышлен, ссылки на пост нет.
    # У живых публикаций поля нет.
    demo: bool | None = absent()


class RegionReason(ApiModel):
    regional_source: bool
    # Источник из списка пользователя в режиме «Мои источники» (Р4, п. 48): регион не
    # проверяем, причина «в вашем списке». По умолчанию False — для записей до п. 48.
    in_my_sources: bool = False
    places: list[str]


class Evidence(ApiModel):
    sentence_index: int
    ranges: list[TextRange]
    basis: Literal["ai", "release-match", "semantic"]
    note: str | None


class Excerpt(ApiModel):
    start: int
    end: int
    text: str
    cut_start: bool
    cut_end: bool


class Citation(ApiModel):
    share: float
    fragment_ids: list[str]


# ============================================================================
# Проверка текста на ИИ (04-decisions.md, «Проверка текста на ИИ»)
# ============================================================================

AiLevel = Literal["likely-ai", "signs", "unlikely", "too-short", "unavailable"]


class AiCheck(ApiModel):
    """Оценка модели, не доказательство. Один текст — один результат во всех местах."""

    level: AiLevel
    # Вероятность класса «ai» от модели; null — «мало текста» или «проверка недоступна».
    score: float | None
    model: str
    # SHA-256 нормализованного текста (aicheck/text.py) — ключ общего кэша результатов.
    text_hash: str
    words: int
    checked_at: IsoDateTime


class ResultItem(ApiModel):
    id: str
    publication: Publication
    relevance: Relevance
    method: SelectionMethod
    method_note: str | None
    region_reason: RegionReason
    excerpt: Excerpt | None
    evidence: Evidence | None
    placement_type: PlacementType | None
    is_original: bool
    citation: Citation | None
    group_id: str | None
    excluded: bool
    is_new: bool
    arrival: int
    # Нет поля — текст поста ещё проверяется (фоном, по мере сбора) или текста нет.
    ai_check: AiCheck | None = absent()


class ByPlatform(ApiModel):
    vk: int = 0
    ok: int = 0
    max: int = 0
    site: int = 0
    dzen: int = 0

    def add(self, platform: PlatformId, value: int = 1) -> None:
        setattr(self, platform, getattr(self, platform) + value)


class ByRelevance(ApiModel):
    direct: int = 0
    indirect: int = 0
    disputed: int = 0

    def add(self, relevance: Relevance, value: int = 1) -> None:
        setattr(self, relevance, getattr(self, relevance) + value)


class ByPlacementType(ApiModel):
    verbatim: int = 0
    shortened: int = 0
    retold: int = 0
    repost: int = 0

    def add(self, placement: PlacementType, value: int = 1) -> None:
        setattr(self, placement, getattr(self, placement) + value)


class ResultGroup(ApiModel):
    id: str
    title: str
    kind: Literal["release", "copies"]
    item_ids: list[str]
    original_item_id: str | None
    counts_by_platform: ByPlatform
    counts_by_type: ByPlacementType


class SelectionCounts(ApiModel):
    total: int
    excluded: int
    by_relevance: ByRelevance
    by_platform: ByPlatform
    by_placement_type: ByPlacementType
    new: int
    # Без исключённых: «похоже на ИИ» и «есть признаки» (фильтр «Похоже на ИИ»).
    ai_likely: int = 0
    ai_signs: int = 0
    # Записи без даты (ТЗ-Ф36): лист «Сводка» в XLSX и выгрузка «только без даты».
    undated: int = server_only(0)


class SelectionNotice(ApiModel):
    code: Literal[
        "other-region", "platform-cap", "ai-unavailable", "images-not-analyzed", "undated-included"
    ]
    tone: Literal["info", "warning"]
    message: str


class Selection(ApiModel):
    search_id: str
    conditions: SearchConditions
    statuses: list[PlatformStatus]
    items: list[ResultItem]
    groups: list[ResultGroup]
    counts: SelectionCounts
    topic: TopicUnderstanding | None
    notices: list[SelectionNotice]
    ai_available: bool
    phase: Literal["running", "done", "stopped"]


# ============================================================================
# Ход поиска — события (НТ-2, НТ-6, НТ-23)
# ============================================================================


class ApiError(ApiModel):
    code: ApiErrorCode
    message: str
    retry_after_sec: int | None = absent()
    # Отказ «уже идёт поиск»: id того поиска — клиент подключится к нему (attachSearch).
    running_search_id: str | None = absent()


class QueuedEvent(ApiModel):
    type: Literal["queued"] = "queued"
    ahead: int
    eta_sec: int


class StartedEvent(ApiModel):
    type: Literal["started"] = "started"
    conditions: SearchConditions
    statuses: list[PlatformStatus]


class TopicEvent(ApiModel):
    type: Literal["topic"] = "topic"
    topic: TopicUnderstanding


class PlatformEvent(ApiModel):
    type: Literal["platform"] = "platform"
    status: PlatformStatus
    current_source: str | None


class ItemsEvent(ApiModel):
    type: Literal["items"] = "items"
    items: list[ResultItem]
    groups: list[ResultGroup]
    counts: SelectionCounts


class AiUnavailableEvent(ApiModel):
    type: Literal["ai-unavailable"] = "ai-unavailable"
    message: str


class ConnectionLostEvent(ApiModel):
    """Событие интерфейса (НТ-23): сервер его не отправляет, клиент создаёт сам."""

    type: Literal["connection-lost"] = "connection-lost"
    message: str


class ConnectionRestoredEvent(ApiModel):
    """Событие интерфейса (НТ-23): сервер его не отправляет, клиент создаёт сам."""

    type: Literal["connection-restored"] = "connection-restored"
    message: str


class FinishedEvent(ApiModel):
    type: Literal["finished"] = "finished"
    selection: Selection


class StoppedEvent(ApiModel):
    type: Literal["stopped"] = "stopped"
    selection: Selection


class FailedEvent(ApiModel):
    type: Literal["failed"] = "failed"
    error: ApiError


SearchEvent = Annotated[
    QueuedEvent
    | StartedEvent
    | TopicEvent
    | PlatformEvent
    | ItemsEvent
    | AiUnavailableEvent
    | ConnectionLostEvent
    | ConnectionRestoredEvent
    | FinishedEvent
    | StoppedEvent
    | FailedEvent,
    Field(discriminator="type"),
]
TERMINAL_EVENTS = frozenset({"finished", "stopped", "failed"})


# ============================================================================
# Распространение новости (Р10, П1, П4, П5, П6)
# ============================================================================


class ReleaseFragment(ApiModel):
    id: str
    index: int
    text: str
    taken_by: int
    of: int = server_only(0)


class ReachAnomaly(ApiModel):
    code: Literal["views-above-subscribers", "few-reactions"]
    message: str


class OriginNote(ApiModel):
    code: Literal["approximate-time", "edited", "first-among-found"]
    message: str


class SpreadPlacement(ApiModel):
    item_id: str
    platform: PlatformId
    source_name: str
    published_at: IsoDateTime | None
    time_reliability: TimeReliability
    subscribers: int | None
    views: int | None
    placement_type: PlacementType
    is_original: bool
    citation_share: float
    url: str
    ai_check: AiCheck | None = absent()
    # Публикация из записанных примеров (демо): ссылки на пост нет — «Распространение»
    # её не показывает. У живых публикаций поля нет.
    demo: bool | None = absent()
    # Сверх контракта ветки: район источника для точек, аномалии охвата (НТ-24) и т.п.
    source_id: str = server_only("")
    source_type: SourceType = server_only("community")
    source_district: str | None = server_only(None)
    in_my_sources: bool = server_only(False)
    places: list[str] = server_only([])
    edited: bool = server_only(False)
    reactions: int | None = server_only(None)
    anomalies: list[ReachAnomaly] = server_only([])
    fragment_ids: list[str] = server_only([])
    repost_of: RepostOf | None = server_only(None)


class WavePoint(ApiModel):
    start: IsoDateTime
    count: int
    by_platform: ByPlatform


class ReachMetric(ApiModel):
    value: int | None
    with_data: int
    of: int
    how_counted: str


class SpreadSelection(ApiModel):
    total: int
    outside_group: int


class SpreadRelease(ApiModel):
    text: str
    fragments: list[ReleaseFragment]


class SpreadOriginal(ApiModel):
    item_id: str
    source_name: str
    platform: PlatformId
    published_at: IsoDateTime | None
    time_reliability: TimeReliability
    notes: list[OriginNote]


class SpreadTotals(ApiModel):
    placements: int
    by_platform: ByPlatform
    by_type: ByPlacementType


class SpreadWave(ApiModel):
    hourly: list[WavePoint]
    daily: list[WavePoint]


class SpreadAiSummary(ApiModel):
    """«Похожи на ИИ: N из M» — только пересказы, без исходного (копии повторяют оценку
    релиза). `likely_ai` — уровень «похоже на ИИ»."""

    likely_ai: int
    retold: int


class SpreadReport(ApiModel):
    search_id: str
    group_id: str
    # Сверх контракта ветки: экран «Распространение» берёт их из `getSelection`.
    conditions: SearchConditions | None = server_only(None)
    statuses: list[PlatformStatus] = server_only([])
    selection: SpreadSelection | None = server_only(None)
    title: str
    release: SpreadRelease
    original: SpreadOriginal
    totals: SpreadTotals
    audience: ReachMetric
    views: ReachMetric
    wave: SpreadWave
    placements: list[SpreadPlacement]
    # Нет поля — проверка на ИИ не подключена: строку не показываем.
    ai_retold: SpreadAiSummary | None = absent()
    computed_at: IsoDateTime


# ============================================================================
# Выгрузка XLSX (ТЗ-Ф37, Ф38; НТ-10, НТ-11, НТ-20)
# ============================================================================


class ExportOptions(ApiModel):
    only_relevance: list[Relevance] | None = absent()
    # Сверх контракта ветки: параметр запроса `onlyUndated` (фильтр «дата неизвестна»).
    only_undated: bool | None = absent()


class ExportColumn(ApiModel):
    id: str
    title: str


ExportCell = str | int | float | None


class ExportSheetTable(ApiModel):
    name: str
    columns: list[ExportColumn]
    rows: list[list[ExportCell]]
    total_rows: int


class SummaryEntry(ApiModel):
    label: str
    value: str


class ExportSummarySheet(ApiModel):
    name: str
    entries: list[SummaryEntry]


class ExportPreview(ApiModel):
    search_id: str
    file_name: str
    row_count: int
    excluded_count: int
    rule: str
    applied_filter: list[Relevance] | None
    only_undated: bool = server_only(False)
    summary: ExportSummarySheet
    publications: ExportSheetTable
    time_zone_note: str


# ============================================================================
# Недавние поиски, проверка ссылок
# ============================================================================


class RecentSearch(ApiModel):
    search_id: str
    conditions: SearchConditions
    total: int
    status_summary: str
    request: SearchRequest


class LinkRecheckReport(ApiModel):
    checked: int
    ok: int
    deleted_item_ids: list[str]
    checked_at: IsoDateTime


# ============================================================================
# Состояние стенда (НТ-18)
# ============================================================================


class Quota(ApiModel):
    used: int
    limit: int
    unit: str
    resets_at: IsoDateTime | None


class StandPlatform(ApiModel):
    platform: PlatformId
    state: HealthState
    message: str
    via: str
    freshness: DataFreshness | None
    quota: Quota | None
    last_success_at: IsoDateTime | None


class StandAi(ApiModel):
    state: HealthState
    model: str
    warm: bool
    queue_length: int
    avg_seconds_per_post: float | None


class StandQueue(ApiModel):
    running: int
    waiting: int
    per_client_limit: int


class StandMemory(ApiModel):
    used_mb: int
    total_mb: int


class StandEvent(ApiModel):
    at: IsoDateTime
    level: Literal["info", "warning", "error"]
    message: str


class StandStatus(ApiModel):
    checked_at: IsoDateTime
    overall: HealthState
    platforms: list[StandPlatform]
    ai: StandAi
    queue: StandQueue
    memory: StandMemory
    events: list[StandEvent]
    version: str


# ============================================================================
# Тела запросов и служебные ответы HTTP (не входят в types.ts)
# ============================================================================


class RunTicket(ApiModel):
    """Ответ на запуск поиска или повтор площадки: откуда читать поток событий."""

    search_id: str
    after: int


class ExcludeSourceResult(ApiModel):
    item_ids: list[str]
    counts: SelectionCounts


class TextBody(ApiModel):
    text: str


class TopicBody(ApiModel):
    text: str
    meaning_id: str | None = absent()
    correction: TopicCorrection | None = absent()


class ExclusionsBody(ApiModel):
    item_ids: list[str] = Field(max_length=10_000)
    excluded: bool


class SourceIdBody(ApiModel):
    source_id: str


class UrlBody(ApiModel):
    url: str = Field(max_length=2_000)


class SourcePatch(ApiModel):
    """`Partial<Omit<SourceInput, 'url'>>`: передано только то, что меняем."""

    name: str | None = None
    type: SourceType | None = None
    district: str | None = None


class IdsBody(ApiModel):
    ids: list[str] = Field(max_length=1_000)


class KeyBody(ApiModel):
    key: str = Field(max_length=500)


class Health(ApiModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "down"]
    version: str
