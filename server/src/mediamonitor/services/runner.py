"""Фоновое выполнение поиска (НТ-2, НТ-6, ТЗ-Ф42–Ф44).

Поиск идёт задачей asyncio в процессе сервера, а его состояние — в базе: статусы
площадок, записи подборки, журнал событий. Поэтому ход можно читать потоком SSE с
любого места, а после перезапуска сервера найденное не теряется (SC-51).

Порядок событий: `queued`* → `started` → (`ai-unavailable`) → `topic` →
(`platform` | `items`)* → `finished`; при остановке — `stopped`, при общей ошибке — `failed`.

Проверка постов на ИИ идёт фоном по мере сбора и не задерживает выдачу: записи уходят в
поток сразу, без `aiCheck`; когда детектор оценил их тексты, те же записи приходят ещё раз
событием `items` (интерфейс заменяет их по id). Перед `finished` сервер ждёт фоновую
проверку не дольше AI_DETECT_FINISH_WAIT_SEC; что не успело — досчитается и будет в подборке.

Каждая площадка идёт своей задачей; сбой одной не роняет остальные (ТЗ-Ф42), её
можно повторить отдельно (ТЗ-Ф44). На рабочее место — один активный поиск, на весь
сервер — MAX_RUNNING_SEARCHES, остальные ждут в очереди с понятным «перед вами N» (НТ-6).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.adapters import enabled_platforms
from mediamonitor.adapters.base import (
    AdapterError,
    AdapterQuery,
    Capped,
    Partial,
    Posts,
    Progress,
    RawPost,
    SourceInfo,
)
from mediamonitor.contract import (
    KRASNOYARSK_KRAI,
    AiUnavailableEvent,
    ApiError,
    ApiModel,
    CutExample,
    Evidence,
    FailedEvent,
    FinishedEvent,
    ItemsEvent,
    PlatformEvent,
    PlatformId,
    PlatformStatus,
    QueuedEvent,
    RegionReason,
    RunTicket,
    SearchConditions,
    SearchRequest,
    SelectionNotice,
    StartedEvent,
    StoppedEvent,
    TextRange,
    TopicEvent,
    TopicUnderstanding,
)
from mediamonitor.db.models import (
    PlatformRunRow,
    PublicationRow,
    SearchGroupRow,
    SearchItemRow,
    SearchRow,
    WorkspaceRow,
)
from mediamonitor.errors import ApiProblem, required
from mediamonitor.labels import PLATFORM_NAME, status_summary
from mediamonitor.matcher import Candidate, Decision, MatchSession, QueryContext
from mediamonitor.normalize.query import (
    ReleaseText,
    conditions_label,
    detect_kind,
    is_other_region,
    meaning_label,
    release_of,
)
from mediamonitor.normalize.text import excerpt_bounds, headline
from mediamonitor.normalize.urls import source_id
from mediamonitor.services import sources as source_service
from mediamonitor.services.context import AppContext
from mediamonitor.services.events import append_event
from mediamonitor.services.normalize_post import NormPost, normalize, upsert_publication
from mediamonitor.services.selection import build_selection, load_runs, platform_status
from mediamonitor.services.vectors import DbVectorStore
from mediamonitor.timeutil import day_end, day_start, iso, parse_iso, utcnow

log = logging.getLogger(__name__)

OTHER_REGION_NOTICE = SelectionNotice(
    code="other-region",
    tone="info",
    message="Поиск ограничен Красноярским краем. Публикации о другом регионе попадают в подборку, "
    "только если в них упоминается край или их опубликовал краевой источник.",
)
AI_NOTICE = SelectionNotice(
    code="ai-unavailable",
    tone="warning",
    message="Смысловая проверка недоступна: нейросеть не отвечает. Публикации найдены "
    "по совпадению "
    "слов; спорные помечены «не проверено ИИ».",
)
INTERRUPTED = {
    "code": "unavailable",
    "message": "Поиск прервался: сервер перезапускался. Найденное сохранено — повторите площадку.",
    "retryable": True,
}
PROGRESS_EVENT_INTERVAL = 0.25
MAX_CUT_EXAMPLES = 6


def _subject(platform: PlatformId, *, genitive: bool = False) -> str:
    """Название площадки в сообщении: «ответ сайтов СМИ», «ответ ВКонтакте»."""
    if platform == "site":
        return "сайтов СМИ" if genitive else "Сайты СМИ"
    if platform == "dzen" and genitive:
        return "Дзена"
    return PLATFORM_NAME[platform]


def busy_message(label: str) -> str:
    return (
        f"Уже идёт поиск «{label}». Дождитесь, пока он закончится, или остановите его — "
        "одновременно идёт один поиск."
    )


# ---------------------------------------------------------------- очередь (НТ-6)


class SlotQueue:
    """Не больше `limit` поисков одновременно; остальные ждут по очереди (FIFO)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.running = 0
        self.waiting: list[str] = []
        self._version = 0
        self._condition = asyncio.Condition()

    async def acquire(self, key: str, on_wait: Callable[[int], Awaitable[None]]) -> None:
        async with self._condition:
            self.waiting.append(key)
            self._version += 1
        reported = -1
        try:
            while True:
                async with self._condition:
                    if self.running < self.limit and self.waiting[0] == key:
                        self.waiting.pop(0)
                        self.running += 1
                        self._version += 1
                        self._condition.notify_all()
                        return
                    ahead = self.waiting.index(key) + 1
                    seen = self._version
                if ahead != reported:
                    reported = ahead
                    await on_wait(ahead)

                def changed(seen: int = seen) -> bool:
                    return self._version != seen

                async with self._condition:
                    await self._condition.wait_for(changed)
        except BaseException:
            async with self._condition:
                if key in self.waiting:
                    self.waiting.remove(key)
                    self._version += 1
                    self._condition.notify_all()
            raise

    async def release(self) -> None:
        async with self._condition:
            self.running = max(0, self.running - 1)
            self._version += 1
            self._condition.notify_all()


# ---------------------------------------------------------------- состояние идущего поиска


@dataclass(frozen=True)
class _PostsJob:
    platform: PlatformId
    posts: Sequence[RawPost]


@dataclass(frozen=True)
class _CapJob:
    platform: PlatformId
    capped: Capped


@dataclass(frozen=True)
class _DoneJob:
    platform: PlatformId
    final: str | None
    problem: dict[str, Any] | None


_Job = _PostsJob | _CapJob | _DoneJob


@dataclass(frozen=True)
class _AiJob:
    """Записи, ждущие проверки на ИИ: (id записи, текст поста) и отметки «ждут» в сервисе."""

    items: Sequence[tuple[str, str]]
    keys: Sequence[str]


@dataclass
class _Live:
    search_id: str
    workspace_id: str
    request: SearchRequest
    conditions: SearchConditions
    start: datetime
    end: datetime
    sources: list[SourceInfo] | None
    ai_available: bool
    previous_ids: set[str] | None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    match_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    session: MatchSession | None = None
    task: asyncio.Task[None] | None = None
    platform_tasks: dict[PlatformId, asyncio.Task[None]] = field(default_factory=dict)
    # Сбор и отбор идут параллельно: площадки кладут порции в очередь, один обработчик
    # поиска отбирает их по мере прихода и отдаёт результаты в поток (НТ-2).
    jobs: asyncio.Queue[_Job] = field(default_factory=asyncio.Queue)
    worker: asyncio.Task[None] | None = None
    # Проверка на ИИ — своя очередь и свой обработчик: отбор её не ждёт.
    ai_jobs: asyncio.Queue[_AiJob | None] = field(default_factory=asyncio.Queue)
    ai_worker: asyncio.Task[None] | None = None
    # Итог записан: дальше фоновая проверка только пишет кэш, событий не шлёт.
    finished: bool = False
    failed_batches: set[PlatformId] = field(default_factory=set)
    last_progress_event: dict[PlatformId, float] = field(default_factory=dict)
    progress: dict[PlatformId, Progress] = field(default_factory=dict)
    ai_notice_sent: bool = False
    topic_changed: bool = False


def _period_bounds(conditions: SearchConditions) -> tuple[datetime, datetime]:
    """Период поиска: календарные дни по Красноярску; «24 часа» — от момента запуска."""
    if conditions.period.preset == "24h":
        end = parse_iso(conditions.started_at)
        return end - timedelta(hours=24), end
    return day_start(date.fromisoformat(conditions.period.from_)), day_end(
        date.fromisoformat(conditions.period.to)
    )


def same_search(a: SearchRequest, b: SearchRequest) -> bool:
    """Один и тот же запрос — одна запись в «Недавних» (П12)."""
    return (
        a.text.strip() == b.text.strip()
        and a.mode == b.mode
        and a.period.preset == b.period.preset
        and (
            a.period.preset != "custom"
            or (a.period.from_, a.period.to) == (b.period.from_, b.period.to)
        )
        and (a.meaning_id or None) == (b.meaning_id or None)
    )


class SearchRunner:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
        self.slots = SlotQueue(ctx.settings.max_running_searches)
        self.vectors = DbVectorStore(ctx.sessions)
        self._live: dict[str, _Live] = {}
        self._durations: list[float] = []
        self._ai_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ для страницы стенда

    @property
    def running(self) -> int:
        return self.slots.running

    @property
    def waiting(self) -> int:
        return len(self.slots.waiting)

    def lock_for(self, search_id: str) -> asyncio.Lock:
        """Замок идущего поиска: правки подборки не перемешиваются с записью хода."""
        live = self._live.get(search_id)
        return live.lock if live is not None else asyncio.Lock()

    def _eta(self, ahead: int) -> int:
        average = sum(self._durations) / len(self._durations) if self._durations else 20.0
        return max(5, round(average * ahead))

    # ------------------------------------------------------------ запуск

    async def start(self, workspace: WorkspaceRow, request: SearchRequest) -> RunTicket:
        settings = self.settings
        text = request.text
        if not text.strip():
            raise ApiProblem("invalid", "Введите тему, событие или текст новости.")
        if len(text.strip()) > settings.max_query_length:
            raise ApiProblem(
                "too-long",
                "Текст запроса длиннее 20 000 знаков. Оставьте заголовок и первые абзацы.",
            )
        try:
            first, last = (
                date.fromisoformat(request.period.from_),
                date.fromisoformat(request.period.to),
            )
        except ValueError as error:
            raise ApiProblem(
                "invalid", "Период указан неверно: нужны даты вида 2026-10-19."
            ) from error
        if first > last:
            raise ApiProblem("invalid", "Начало периода позже его конца. Поменяйте даты местами.")
        if (last - first).days + 1 > settings.max_period_days:
            raise ApiProblem(
                "invalid",
                "Период длиннее 6 месяцев: на открытом стенде так искать нельзя. Сократите период.",
            )
        # По умолчанию — все площадки этого сервера; выключенные из запроса молча убираем.
        available = enabled_platforms(self.ctx.adapters)
        wanted = request.platforms or available
        platforms = [p for p in available if p in wanted]
        if not platforms:
            raise ApiProblem("invalid", "Выбранные площадки на этом сервере выключены.")

        async with self.ctx.sessions.begin() as session:
            await self._ensure_free(session, workspace.id)
            owner = required(await session.get(WorkspaceRow, workspace.id), "workspace")
            owner.last_mode = request.mode  # режим по умолчанию в следующий раз (п. 47)
            infos = None
            if request.mode == "my-sources":
                infos = await source_service.active_infos(session, workspace.id, request.source_ids)
            previous_ids = await self._previous_ids(session, workspace.id, request.repeat_of)
            status = await self.ctx.judge.status()
            kind = detect_kind(text)
            release = self._release(text) if kind == "news-text" else None
            search_id = f"s_{secrets.token_hex(10)}"
            now = utcnow()
            conditions = SearchConditions(
                search_id=search_id,
                text=text,
                label=conditions_label(text, kind, release),
                kind=kind,
                period=request.period,
                region=KRASNOYARSK_KRAI,
                mode=request.mode,
                source_count=len(infos) if infos is not None else None,
                platforms=platforms,
                meaning_label=meaning_label(request.meaning_id),
                started_at=iso(now),
                finished_at=None,
                repeat_of=request.repeat_of,
            )
            notices = [OTHER_REGION_NOTICE.dump()] if is_other_region(text) else []
            session.add(
                SearchRow(
                    id=search_id,
                    workspace_id=workspace.id,
                    request=request.dump(),
                    conditions=conditions.dump(),
                    kind=kind,
                    phase="running",
                    topic=None,
                    release={
                        "title": release.title,
                        "text": release.text,
                        "fragments": [
                            {"id": f.id, "index": f.index, "text": f.text}
                            for f in release.fragments
                        ],
                    }
                    if release
                    else None,
                    ai_available=status.available,
                    notices=notices,
                    stop_requested=False,
                    arrival_seq=0,
                    event_seq=0,
                    in_recent=True,
                    result_total=0,
                    status_summary="",
                    error=None,
                    created_at=now,
                    finished_at=None,
                )
            )
            await session.flush()  # сначала поиск, потом его площадки (внешний ключ)
            for platform in platforms:
                session.add(
                    PlatformRunRow(
                        search_id=search_id,
                        platform=platform,
                        state="waiting",
                        done=0.0,
                        total=0,
                        unit="sources",
                        problem=None,
                        cap=None,
                        current_source=None,
                        attempt=1,
                        updated_at=None,
                    )
                )
        start, end = _period_bounds(conditions)
        live = _Live(
            search_id=search_id,
            workspace_id=workspace.id,
            request=request,
            conditions=conditions,
            start=start,
            end=end,
            sources=infos,
            ai_available=status.available,
            previous_ids=previous_ids,
        )
        live.ai_notice_sent = not status.available
        self._spawn(live, platforms, initial=True, ai_reason=status.reason)
        return RunTicket(search_id=search_id, after=0)

    async def _ensure_free(self, session: AsyncSession, workspace_id: str) -> None:
        running = list(
            await session.scalars(
                select(SearchRow).where(
                    SearchRow.workspace_id == workspace_id, SearchRow.phase == "running"
                )
            )
        )
        if len(running) >= self.settings.active_searches_per_workspace:
            label = str(running[0].conditions.get("label", ""))
            raise ApiProblem("too-many-requests", busy_message(label), retry_after_sec=10)

    async def _previous_ids(
        self, session: AsyncSession, workspace_id: str, repeat_of: str | None
    ) -> set[str] | None:
        if not repeat_of:
            return None
        previous = await session.scalar(
            select(SearchRow.id).where(
                SearchRow.id == repeat_of, SearchRow.workspace_id == workspace_id
            )
        )
        if previous is None:
            return None
        rows = await session.scalars(
            select(SearchItemRow.publication_id).where(SearchItemRow.search_id == previous)
        )
        return set(rows)

    @staticmethod
    def _cancel(live: _Live) -> None:
        """Остановить сбор и отбор. Найденное до остановки уже в базе."""
        if live.platform_tasks:
            for task in live.platform_tasks.values():
                task.cancel()
            if live.worker is not None:
                live.worker.cancel()
        elif live.task is not None:
            live.task.cancel()

    def _release(self, text: str) -> ReleaseText:
        """Релиз: заголовок — сервер, абзацы — воронка (на их id ссылается цитирование, П1)."""
        release = release_of(text)
        return replace(release, fragments=self.ctx.matcher.release_fragments(release.text))

    def _spawn(
        self,
        live: _Live,
        platforms: Sequence[PlatformId],
        *,
        initial: bool,
        ai_reason: str | None = None,
    ) -> None:
        self._live[live.search_id] = live
        live.task = asyncio.create_task(
            self._main(live, list(platforms), initial=initial, ai_reason=ai_reason),
            name=f"search-{live.search_id}",
        )

    # ------------------------------------------------------------ остановка и повтор

    async def stop(self, workspace: WorkspaceRow, search_id: str) -> None:
        async with self.ctx.sessions.begin() as session:
            search = await self._own(session, workspace, search_id)
            if search.phase != "running":
                return
            search.stop_requested = True
        live = self._live.get(search_id)
        if live is None:
            # Поиск «идёт» в базе, но не в этом процессе — закрываем как остановленный.
            await self._close_orphan(search_id, stopped=True)
            return
        live.stop.set()
        self._cancel(live)

    async def retry(
        self, workspace: WorkspaceRow, search_id: str, platform: PlatformId
    ) -> RunTicket:
        async with self.ctx.sessions.begin() as session:
            search = await self._own(session, workspace, search_id)
            if search.phase == "running":
                raise ApiProblem(
                    "too-many-requests",
                    "Поиск ещё идёт: повторить площадку можно, когда он закончится.",
                    retry_after_sec=5,
                )
            await self._ensure_free(session, workspace.id)
            conditions = SearchConditions.model_validate(search.conditions)
            if platform not in conditions.platforms:
                raise ApiProblem("invalid", "Эта площадка не участвовала в поиске.")
            if platform not in self.ctx.adapters:
                raise ApiProblem("invalid", "Эта площадка сейчас выключена на сервере.")
            run = await session.get(PlatformRunRow, (search_id, platform))
            run = required(run, "run")
            run.state = "waiting"
            run.problem = None
            run.current_source = None
            run.attempt += 1
            run.updated_at = utcnow()
            search.phase = "running"
            search.stop_requested = False
            search.finished_at = None
            search.conditions = {**search.conditions, "finishedAt": None}
            after = search.event_seq
            request = SearchRequest.model_validate(search.request)
            infos = None
            if request.mode == "my-sources":
                infos = await source_service.active_infos(session, workspace.id, request.source_ids)
            previous_ids = await self._previous_ids(session, workspace.id, request.repeat_of)
            ai_available = search.ai_available
        start, end = _period_bounds(conditions)
        old = self._live.get(search_id)
        live = _Live(
            search_id=search_id,
            workspace_id=workspace.id,
            request=request,
            conditions=conditions,
            start=start,
            end=end,
            sources=infos,
            ai_available=ai_available,
            previous_ids=previous_ids,
            session=old.session if old else None,
        )
        live.ai_notice_sent = not ai_available
        self._spawn(live, [platform], initial=False)
        return RunTicket(search_id=search_id, after=after)

    async def _own(
        self, session: AsyncSession, workspace: WorkspaceRow, search_id: str
    ) -> SearchRow:
        search = await session.get(SearchRow, search_id)
        if search is None or search.workspace_id != workspace.id:
            raise ApiProblem("not-found", "Поиск не найден. Запустите его заново.")
        return search

    # ------------------------------------------------------------ ход поиска

    async def _main(
        self, live: _Live, platforms: list[PlatformId], *, initial: bool, ai_reason: str | None
    ) -> None:
        acquired = False
        began = time.monotonic()
        try:
            await self.slots.acquire(live.search_id, lambda ahead: self._queued(live, ahead))
            acquired = True
            if initial:
                await self._begin(live, ai_reason)
            if not live.stop.is_set():
                self._start_ai_worker(live)
                live.worker = asyncio.create_task(self._worker(live, set(platforms)))
                tasks = {p: asyncio.create_task(self._platform(live, p)) for p in platforms}
                live.platform_tasks = tasks
                await asyncio.gather(*tasks.values(), return_exceptions=True)
                await asyncio.gather(live.worker, return_exceptions=True)
            await self._finish(live)
        except asyncio.CancelledError:
            # Остановили в очереди или пока составлялась карточка темы.
            await self._finish(live)
        except Exception:
            log.exception("Поиск %s прервался ошибкой", live.search_id)
            await self._fail(live)
        finally:
            if acquired:
                await self.slots.release()
                self._durations = [*self._durations[-19:], time.monotonic() - began]
            if self._live.get(live.search_id) is live:
                del self._live[live.search_id]

    async def _queued(self, live: _Live, ahead: int) -> None:
        await self._emit(live, QueuedEvent(ahead=ahead, eta_sec=self._eta(ahead)))

    async def _begin(self, live: _Live, ai_reason: str | None) -> None:
        async with live.lock, self.ctx.sessions.begin() as session:
            search = await self._search(session, live)
            runs = await load_runs(session, live.search_id)
            statuses = [platform_status(r, 0, self.ctx.adapters, "running") for r in runs]
            append_event(
                session, search, StartedEvent(conditions=live.conditions, statuses=statuses)
            )
            if not live.ai_available:
                message = ai_reason or "Смысловая проверка недоступна: нейросеть не отвечает."
                append_event(
                    session, search, AiUnavailableEvent(message=f"{message} Поиск идёт без неё.")
                )
                search.notices = [*search.notices, AI_NOTICE.dump()]
        await self.ctx.bus.notify(live.search_id)
        topic = await self.ctx.topics.understand(
            live.ai_available,
            live.request.text,
            meaning_id=live.request.meaning_id,
            correction=live.request.topic,
        )
        async with live.lock, self.ctx.sessions.begin() as session:
            search = await self._search(session, live)
            search.topic = topic.dump()
            append_event(session, search, TopicEvent(topic=topic))
        await self.ctx.bus.notify(live.search_id)
        live.session = self._match_session(live, topic)

    def _match_session(self, live: _Live, topic: TopicUnderstanding | None) -> MatchSession:
        news = live.conditions.kind == "news-text"
        return self.ctx.matcher.start(
            QueryContext(
                text=live.request.text,
                kind=live.conditions.kind,
                label=live.conditions.label,
                meaning_id=live.request.meaning_id,
                topic=topic,
                release=self._release(live.request.text) if news else None,
            ),
            self.ctx.judge,
            live.ai_available,
            self.vectors,
        )

    async def _ensure_session(self, live: _Live) -> MatchSession:
        if live.session is None:
            async with self.ctx.sessions() as session:
                search = await self._search(session, live)
                topic = TopicUnderstanding.model_validate(search.topic) if search.topic else None
            live.session = self._match_session(live, topic)
        return live.session

    async def _platform(self, live: _Live, platform: PlatformId) -> None:
        adapter = self.ctx.adapters[platform]
        name = PLATFORM_NAME[platform]
        async with self.ctx.sessions() as session:
            run = await session.get(PlatformRunRow, (live.search_id, platform))
            attempt = run.attempt if run else 1
        query = AdapterQuery(
            text=live.request.text,
            kind=live.conditions.kind,
            start=live.start,
            end=live.end,
            sources=live.sources,
            meaning_id=live.request.meaning_id,
            attempt=attempt,
        )
        final: str | None = None
        problem: dict[str, Any] | None = None
        try:
            # Предел вызовов площадки на сутки или месяц исчерпан — обход не начинаем (НТ-6).
            await self.ctx.budget.ensure_available(platform)
            async with asyncio.timeout(self.settings.platform_timeout_sec):
                async for event in adapter.search(query):
                    if live.stop.is_set():
                        break
                    if isinstance(event, Progress):
                        await self._progress(live, platform, event)
                    elif isinstance(event, Posts):
                        await live.jobs.put(_PostsJob(platform, event.posts))
                    elif isinstance(event, Partial):
                        final = "partial"
                        problem = {
                            "code": event.code,
                            "message": event.message,
                            "retryable": event.retryable,
                        }
                    elif isinstance(event, Capped):
                        await live.jobs.put(_CapJob(platform, event))
            if live.stop.is_set():
                final, problem = "stopped", None
        except AdapterError as error:
            final = error.state
            problem = {"code": error.code, "message": error.message, "retryable": error.retryable}
        except TimeoutError:
            final = "error"
            problem = {
                "code": "timeout",
                "message": f"{_subject(platform)} не уложились во время. Найденное сохранено — "
                "повторите поиск по площадке."
                if platform == "site"
                else f"{name} не уложился во время. Найденное сохранено — повторите "
                "поиск по площадке.",
                "retryable": True,
            }
        except asyncio.CancelledError:
            final, problem = "stopped", None
        except Exception:
            log.exception("Площадка %s: сбой обработки", platform)
            final = "error"
            problem = {
                "code": "bad-response",
                "message": f"Ответ {_subject(platform, genitive=True)} не удалось обработать. "
                "Это ошибка, "
                "а не «ничего не найдено» — "
                "повторите позже.",
                "retryable": True,
            }
        # Итог площадки — после её порций: обработчик идёт по очереди.
        live.jobs.put_nowait(_DoneJob(platform, final, problem))

    async def _worker(self, live: _Live, platforms: set[PlatformId]) -> None:
        """Отбор порций по мере сбора: результаты уходят в поток сразу после каждой (НТ-2)."""
        pending = set(platforms)
        step = self.settings.match_batch_size
        while pending:
            job = await live.jobs.get()
            try:
                if isinstance(job, _PostsJob):
                    for start in range(0, len(job.posts), step):
                        await self._ingest(live, job.platform, job.posts[start : start + step])
                elif isinstance(job, _CapJob):
                    await self._capped(live, job.platform, job.capped)
                else:
                    pending.discard(job.platform)
                    await self._platform_done(live, job.platform, job.final, job.problem)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Поиск %s: сбой обработки порции %s", live.search_id, job.platform)
                live.failed_batches.add(job.platform)

    async def _status(
        self, session: AsyncSession, search: SearchRow, run: PlatformRunRow
    ) -> PlatformStatus:
        found = await session.scalar(
            select(func.count())
            .select_from(SearchItemRow)
            .join(PublicationRow, PublicationRow.id == SearchItemRow.publication_id)
            .where(
                SearchItemRow.search_id == search.id,
                SearchItemRow.excluded.is_(False),
                PublicationRow.platform == run.platform,
            )
        )
        return platform_status(run, int(found or 0), self.ctx.adapters, search.phase)

    async def _progress(self, live: _Live, platform: PlatformId, progress: Progress) -> None:
        now = time.monotonic()
        emit = (
            progress.done in (0, progress.total)
            or now - live.last_progress_event.get(platform, 0.0) >= PROGRESS_EVENT_INTERVAL
        )
        # Ход держим в памяти; в базу и в поток — не чаще раза в 0,25 с (и первый/последний шаг).
        live.progress[platform] = progress
        if not emit:
            return
        async with live.lock, self.ctx.sessions.begin() as session:
            run = required(await session.get(PlatformRunRow, (live.search_id, platform)), "run")
            _apply_progress(run, progress)
            search = await self._search(session, live)
            status = await self._status(session, search, run)
            append_event(
                session,
                search,
                PlatformEvent(status=status, current_source=progress.current_source),
            )
        live.last_progress_event[platform] = now
        await self.ctx.bus.notify(live.search_id)

    async def _capped(self, live: _Live, platform: PlatformId, capped: Capped) -> None:
        async with live.lock, self.ctx.sessions.begin() as session:
            run = await session.get(PlatformRunRow, (live.search_id, platform))
            run = required(run, "run")
            run.cap = {"limit": capped.limit, "note": capped.note}
            search = await self._search(session, live)
            if not any(n.get("code") == "platform-cap" for n in search.notices):
                notice = SelectionNotice(
                    code="platform-cap",
                    tone="warning",
                    message=f"{capped.note}. Чтобы увидеть всё, уточните запрос "
                    "или сократите период.",
                )
                search.notices = [*search.notices, notice.dump()]

    async def _ingest(self, live: _Live, platform: PlatformId, raws: Sequence[RawPost]) -> None:
        # 1. Нормализация и кэш публикаций.
        posts: dict[str, NormPost] = {}
        for raw in raws:
            post = normalize(raw, self.ctx.matcher.split_sentences)
            if post is not None and post.id not in posts:
                posts[post.id] = post
        if not posts:
            return
        candidates: list[Candidate] = []
        meta: dict[str, tuple[NormPost, RegionReason]] = {}
        async with live.lock, self.ctx.sessions.begin() as session:
            existing = set(
                await session.scalars(
                    select(SearchItemRow.publication_id).where(
                        SearchItemRow.search_id == live.search_id,
                        SearchItemRow.publication_id.in_(list(posts)),
                    )
                )
            )
            mine = (
                {source_id(s.platform, s.owner_id) for s in live.sources}
                if live.sources is not None
                else set()
            )
            for post in posts.values():
                directory = await source_service.upsert_source(session, post.source)
                await upsert_publication(session, post, directory.id)
                if post.id in existing:
                    continue
                # Привязка к краю (Р4): «Мои источники» — регион не проверяем, человек сам
                # выбрал источники; «Везде» — краевой источник или упомянуто место края.
                in_my_list = directory.id in mine
                if not in_my_list and not directory.regional and not post.places:
                    continue
                meta[post.id] = (
                    post,
                    RegionReason(
                        regional_source=directory.regional,
                        in_my_sources=in_my_list,
                        places=list(post.places),
                    ),
                )
                candidates.append(
                    Candidate(
                        id=post.id,
                        platform=post.ref.platform,
                        source_id=directory.id,
                        title=post.title,
                        text=post.text,
                        sentences=post.spans,
                        source_name=directory.name,
                        source_regional=directory.regional,
                        places=post.places,
                        published_at=post.published_at,
                        is_repost=post.repost_of is not None,
                        has_media=post.has_media,
                        content_hash=post.content_hash,
                    )
                )
        if not candidates:
            return
        # 2. Отбор — без открытой транзакции: нейросеть может думать долго.
        session_matcher = await self._ensure_session(live)
        async with live.match_lock:
            decisions = await session_matcher.classify(candidates)
        # 3. Записи подборки, группы, события.
        async with live.lock, self.ctx.sessions.begin() as session:
            search = await self._search(session, live)
            if session_matcher.ai_failed and not live.ai_notice_sent:
                live.ai_notice_sent = True
                search.ai_available = False
                search.notices = [*search.notices, AI_NOTICE.dump()]
                append_event(
                    session,
                    search,
                    AiUnavailableEvent(
                        message="Смысловая проверка недоступна: нейросеть не ответила. "
                        "Спорные получат «не проверено ИИ»."
                    ),
                )
            new_ids = await self._store(session, search, live, decisions, meta)
            if new_ids:
                run = required(await session.get(PlatformRunRow, (live.search_id, platform)), "run")
                _apply_progress(run, live.progress.get(platform))
                await session.flush()
                # Тексты новых записей — «ждут проверки на ИИ» до сборки события: запись
                # уходит без `aiCheck`, оценка придёт следующим событием.
                keys = self.ctx.ai_checks.reserve(
                    text for text in (meta[i][0].text for i in new_ids) if text is not None
                )
                waiting: list[tuple[str, str]] = []
                try:
                    selection = await build_selection(
                        session, search, self.ctx.adapters, self.ctx.ai_checks
                    )
                    fresh = set(new_ids)
                    items = [i for i in selection.items if i.id in fresh]
                    append_event(
                        session,
                        search,
                        ItemsEvent(items=items, groups=selection.groups, counts=selection.counts),
                    )
                    status = next(s for s in selection.statuses if s.platform == platform)
                    append_event(
                        session,
                        search,
                        PlatformEvent(status=status, current_source=run.current_source),
                    )
                    waiting = [
                        (i.id, i.publication.text)
                        for i in items
                        if i.ai_check is None and i.publication.text is not None
                    ]
                finally:
                    # Не ушло в очередь (сбой, остановка, всё уже в кэше) — отметки снимаются.
                    self._queue_ai(live, waiting, keys)
        await self.ctx.bus.notify(live.search_id)

    # ------------------------------------------------------------ проверка на ИИ (фоном)

    def _start_ai_worker(self, live: _Live) -> None:
        task = asyncio.create_task(self._ai_worker(live), name=f"ai-check-{live.search_id}")
        live.ai_worker = task
        self._ai_tasks.add(task)
        task.add_done_callback(self._ai_tasks.discard)

    def _queue_ai(self, live: _Live, items: list[tuple[str, str]], keys: list[str]) -> None:
        worker = live.ai_worker
        if not items or worker is None or worker.done() or live.finished:
            self.ctx.ai_checks.release(keys)
            return
        live.ai_jobs.put_nowait(_AiJob(items, keys))

    async def _ai_worker(self, live: _Live) -> None:
        """Проверяет тексты новых записей и шлёт эти записи ещё раз — уже с оценкой."""
        ai = self.ctx.ai_checks
        try:
            while True:
                job = await live.ai_jobs.get()
                if job is None:
                    return
                try:
                    await ai.check_many([text for _, text in job.items])
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Поиск %s: сбой проверки на ИИ", live.search_id)
                finally:
                    ai.release(job.keys)
                if not live.finished:
                    try:
                        await self._emit_ai(live, [item_id for item_id, _ in job.items])
                    except Exception:
                        log.exception("Поиск %s: не удалось отправить оценки ИИ", live.search_id)
        finally:
            # Остановили — отметки «ждут проверки» у оставшихся снимаем.
            while not live.ai_jobs.empty():
                rest = live.ai_jobs.get_nowait()
                if rest is not None:
                    ai.release(rest.keys)

    async def _emit_ai(self, live: _Live, item_ids: Sequence[str]) -> None:
        async with live.lock, self.ctx.sessions.begin() as session:
            if live.finished:
                return
            search = await self._search(session, live)
            selection = await build_selection(
                session, search, self.ctx.adapters, self.ctx.ai_checks
            )
            wanted = set(item_ids)
            items = [i for i in selection.items if i.id in wanted]
            if not items:
                return
            append_event(
                session,
                search,
                ItemsEvent(items=items, groups=selection.groups, counts=selection.counts),
            )
        await self.ctx.bus.notify(live.search_id)

    async def _drain_ai(self, live: _Live, *, wait: bool) -> None:
        """Закрыть очередь проверки; при обычном конце — подождать её, но не дольше лимита."""
        worker = live.ai_worker
        if worker is None:
            return
        live.ai_jobs.put_nowait(None)
        if not wait or worker.done():
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(worker), timeout=self.settings.ai_detect_finish_wait_sec
            )
        except TimeoutError:
            log.info("Поиск %s: проверка на ИИ досчитается после итога", live.search_id)
        except Exception:
            log.exception("Поиск %s: сбой фоновой проверки на ИИ", live.search_id)

    async def _store(
        self,
        session: AsyncSession,
        search: SearchRow,
        live: _Live,
        decisions: Sequence[Decision],
        meta: dict[str, tuple[NormPost, RegionReason]],
    ) -> list[str]:
        new_ids: list[str] = []
        clusters: dict[str, tuple[str, str]] = {}
        topic = TopicUnderstanding.model_validate(search.topic) if search.topic else None
        now = utcnow()
        for decision in decisions:
            if decision.id not in meta:
                continue  # воронка вернула чужой id — не верим
            post, region = meta[decision.id]
            if not decision.keep:
                if topic is not None and decision.cut_facet:
                    topic = _count_cut(topic, decision, post)
                    live.topic_changed = True
                continue
            evidence, excerpt = _explain(post, decision)
            is_new = live.previous_ids is not None and post.id not in live.previous_ids
            search.arrival_seq += 1
            session.add(
                SearchItemRow(
                    search_id=search.id,
                    publication_id=post.id,
                    relevance=decision.relevance,
                    method=decision.method,
                    method_note=decision.method_note,
                    region_reason=region.dump(),
                    excerpt=excerpt,
                    evidence=evidence.dump() if evidence else None,
                    placement_type=decision.placement_type,
                    is_original=False,
                    citation={
                        "share": decision.citation[0],
                        "fragmentIds": list(decision.citation[1]),
                    }
                    if decision.citation
                    else None,
                    group_id=None,
                    cluster=decision.cluster,
                    excluded=False,
                    excluded_at=None,
                    is_new=is_new,
                    arrival=search.arrival_seq,
                    created_at=now,
                )
            )
            new_ids.append(post.id)
            if decision.cluster:
                clusters[decision.cluster] = (
                    decision.cluster_kind or "copies",
                    decision.cluster_title or "Копии одного сообщения",
                )
        await session.flush()
        for cluster, (kind, title) in clusters.items():
            await _regroup(session, search.id, cluster, kind, title)
        if topic is not None and live.topic_changed:
            search.topic = topic.dump()
        return new_ids

    async def _platform_done(
        self, live: _Live, platform: PlatformId, final: str | None, problem: dict[str, Any] | None
    ) -> None:
        async with live.lock, self.ctx.sessions.begin() as session:
            search = await self._search(session, live)
            run = required(await session.get(PlatformRunRow, (live.search_id, platform)), "run")
            progress = live.progress.get(platform)
            if progress is not None:
                _apply_progress(run, progress)
            status = await self._status(session, search, run)
            if platform in live.failed_batches and final in (None, "partial"):
                final = "partial"
                problem = problem or {
                    "code": "bad-response",
                    "message": f"Часть ответа {_subject(platform, genitive=True)} не удалось "
                    "обработать: "
                    "найденное сохранено, повторите поиск по площадке.",
                    "retryable": True,
                }
            state = final or ("found" if status.found > 0 else "nothing")
            if state in ("found", "nothing"):
                run.done = float(run.total)
            run.state = state
            run.problem = problem
            run.current_source = None
            run.updated_at = utcnow()
            status = await self._status(session, search, run)
            append_event(session, search, PlatformEvent(status=status, current_source=None))
        await self.ctx.bus.notify(live.search_id)

    async def _finish(self, live: _Live) -> None:
        await self._drain_ai(live, wait=not live.stop.is_set())
        async with live.lock, self.ctx.sessions.begin() as session:
            live.finished = True
            search = await self._search(session, live)
            if search.phase != "running":
                return
            stopped = live.stop.is_set() or search.stop_requested
            for run in await load_runs(session, live.search_id):
                if run.state in ("waiting", "searching"):
                    run.state = "stopped"
                    run.current_source = None
            now = utcnow()
            search.phase = "stopped" if stopped else "done"
            search.finished_at = now
            search.conditions = {**search.conditions, "finishedAt": iso(now)}
            await self._update_recent(session, search)
            if live.topic_changed and search.topic:
                append_event(
                    session,
                    search,
                    TopicEvent(topic=TopicUnderstanding.model_validate(search.topic)),
                )
            selection = await build_selection(
                session, search, self.ctx.adapters, self.ctx.ai_checks
            )
            search.result_total = selection.counts.total
            search.status_summary = status_summary(selection.statuses, selection.counts.total)
            event: ApiModel = (
                StoppedEvent(selection=selection) if stopped else FinishedEvent(selection=selection)
            )
            append_event(session, search, event)
        await self.ctx.bus.notify(live.search_id)

    async def _fail(self, live: _Live) -> None:
        live.finished = True
        await self._drain_ai(live, wait=False)
        try:
            async with live.lock, self.ctx.sessions.begin() as session:
                search = await self._search(session, live)
                now = utcnow()
                search.phase = "done"
                search.finished_at = now
                search.conditions = {**search.conditions, "finishedAt": iso(now)}
                error = ApiError(
                    code="server",
                    message="Поиск прервался из-за ошибки на сервере. Найденное сохранено — "
                    "запустите "
                    "поиск ещё раз.",
                )
                search.error = error.dump()
                append_event(session, search, FailedEvent(error=error))
            await self.ctx.bus.notify(live.search_id)
        except Exception:
            log.exception("Не удалось записать сбой поиска %s", live.search_id)

    async def _update_recent(self, session: AsyncSession, search: SearchRow) -> None:
        """Повтор заменяет запись, которую повторили; тот же запрос — одна запись (П12)."""
        request = SearchRequest.model_validate(search.request)
        others = await session.scalars(
            select(SearchRow).where(
                SearchRow.workspace_id == search.workspace_id,
                SearchRow.id != search.id,
                SearchRow.in_recent.is_(True),
            )
        )
        for other in others:
            if other.id == request.repeat_of or same_search(
                SearchRequest.model_validate(other.request), request
            ):
                other.in_recent = False

    async def _emit(self, live: _Live, event: ApiModel) -> None:
        async with live.lock, self.ctx.sessions.begin() as session:
            search = await self._search(session, live)
            append_event(session, search, event)
        await self.ctx.bus.notify(live.search_id)

    async def _search(self, session: AsyncSession, live: _Live) -> SearchRow:
        return required(await session.get(SearchRow, live.search_id), "search")

    # ------------------------------------------------------------ перезапуск сервера (SC-51)

    async def _close_orphan(self, search_id: str, *, stopped: bool) -> None:
        async with self.ctx.sessions.begin() as session:
            search = await session.get(SearchRow, search_id)
            if search is None or search.phase != "running":
                return
            for run in await load_runs(session, search_id):
                if run.state in ("waiting", "searching"):
                    if stopped:
                        run.state = "stopped"
                    else:
                        run.state = "error"
                        run.problem = dict(INTERRUPTED)
                    run.current_source = None
                    run.updated_at = utcnow()
            now = utcnow()
            search.phase = "stopped" if stopped else "done"
            search.finished_at = now
            search.conditions = {**search.conditions, "finishedAt": iso(now)}
            selection = await build_selection(
                session, search, self.ctx.adapters, self.ctx.ai_checks
            )
            search.result_total = selection.counts.total
            search.status_summary = status_summary(selection.statuses, selection.counts.total)
            event: ApiModel = (
                StoppedEvent(selection=selection) if stopped else FinishedEvent(selection=selection)
            )
            append_event(session, search, event)
        await self.ctx.bus.notify(search_id)

    async def recover(self) -> int:
        """При старте: поиски, прерванные перезапуском, закрыть с «Повторить» по площадкам."""
        async with self.ctx.sessions() as session:
            ids = list(
                await session.scalars(select(SearchRow.id).where(SearchRow.phase == "running"))
            )
        for search_id in ids:
            await self._close_orphan(search_id, stopped=False)
        return len(ids)

    async def shutdown(self) -> None:
        tasks = []
        for live in list(self._live.values()):
            live.stop.set()
            self._cancel(live)
            if live.task is not None:
                tasks.append(live.task)
        if tasks:
            await asyncio.wait(tasks, timeout=10)
        background = list(self._ai_tasks)
        for task in background:
            task.cancel()
        if background:
            await asyncio.wait(background, timeout=5)


# ---------------------------------------------------------------- помощники


def _apply_progress(run: PlatformRunRow, progress: Progress | None) -> None:
    run.state = "searching"
    run.updated_at = utcnow()
    if progress is None:
        return
    run.done = float(progress.done)
    run.total = progress.total
    run.unit = progress.unit
    run.current_source = progress.current_source


def _explain(post: NormPost, decision: Decision) -> tuple[Evidence | None, dict[str, int] | None]:
    """Доказательство и выдержка только по границам настоящего текста (Р5, НТ-8)."""
    text = post.text
    if text is None or not post.spans:
        return None, None
    draft = decision.evidence
    index = draft.sentence_index if draft and 0 <= draft.sentence_index < len(post.spans) else 0
    ranges = [
        TextRange(start=a, end=b)
        for a, b in (draft.ranges if draft else [])
        if 0 <= a < b <= len(text)
    ]
    if not ranges:
        span = post.spans[index]
        ranges = [TextRange(start=span.start, end=span.end)]
    evidence = Evidence(
        sentence_index=index,
        ranges=ranges,
        basis=draft.basis if draft else "semantic",
        note=draft.note if draft else None,
    )
    start, end = excerpt_bounds(list(post.spans), index, len(text))
    return evidence, {"start": start, "end": end}


def _count_cut(topic: TopicUnderstanding, decision: Decision, post: NormPost) -> TopicUnderstanding:
    """Отсечённый гранью «не то» пост: счётчик грани и пример — дословно начало поста."""
    excludes = [
        f.model_copy(update={"cut_count": (f.cut_count or 0) + 1})
        if f.id == decision.cut_facet
        else f
        for f in topic.excludes
    ]
    examples = list(topic.cut_examples)
    if len(examples) < MAX_CUT_EXAMPLES:
        title, _ = headline(post.title, post.text, list(post.spans))
        examples.append(
            CutExample(
                headline=title,
                reason=decision.cut_reason or "Не относится к теме",
                facet_id=decision.cut_facet,
            )
        )
    return topic.model_copy(update={"excludes": excludes, "cut_examples": examples})


async def _regroup(
    session: AsyncSession, search_id: str, cluster: str, kind: str, title: str
) -> None:
    """Собрать группу кластера (Р9): релиз — всегда, копии — от двух размещений."""
    result = await session.execute(
        select(SearchItemRow, PublicationRow.published_at)
        .join(PublicationRow, PublicationRow.id == SearchItemRow.publication_id)
        .where(SearchItemRow.search_id == search_id, SearchItemRow.cluster == cluster)
    )
    members = list(result)
    if kind == "copies" and len(members) < 2:
        return
    group = await session.scalar(
        select(SearchGroupRow).where(
            SearchGroupRow.search_id == search_id, SearchGroupRow.cluster == cluster
        )
    )
    if group is None:
        count = await session.scalar(
            select(func.count())
            .select_from(SearchGroupRow)
            .where(SearchGroupRow.search_id == search_id)
        )
        group = SearchGroupRow(
            search_id=search_id,
            id=f"g-{int(count or 0) + 1}",
            cluster=cluster,
            title=title,
            kind=kind,
            created_at=utcnow(),
        )
        session.add(group)
    members.sort(key=lambda m: (m[1] is None, m[1].timestamp() if m[1] else 0.0, m[0].arrival))
    for index, (item, _) in enumerate(members):
        item.group_id = group.id
        item.is_original = index == 0
    await session.flush()
