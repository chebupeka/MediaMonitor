"""Приложение FastAPI: сборка зависимостей, жизненный цикл, маршруты.

Запуск: `uv run uvicorn mediamonitor.main:create_app --factory` (см. server/README.md).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from mediamonitor.adapters import AdapterRegistry, FixtureAdapter, build_adapters
from mediamonitor.ai.judge import AiJudge, build_judge
from mediamonitor.aicheck import AiCheckService, AiDetector, build_detector
from mediamonitor.api.middleware import (
    BodyLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from mediamonitor.api.routes import router
from mediamonitor.contract import Health
from mediamonitor.db.session import create_all, create_engine, create_sessions
from mediamonitor.errors import install_error_handlers
from mediamonitor.matcher import Matcher, load_matcher
from mediamonitor.services.context import AppContext
from mediamonitor.services.events import EventBus
from mediamonitor.services.runner import SearchRunner
from mediamonitor.services.sources import seed_catalog
from mediamonitor.services.stand import log_event
from mediamonitor.services.topic import TopicService
from mediamonitor.settings import Settings, get_settings
from mediamonitor.timeutil import utcnow

log = logging.getLogger("mediamonitor")

AdapterFactory = Callable[[Settings, httpx.AsyncClient], AdapterRegistry]
JudgeFactory = Callable[[Settings, httpx.AsyncClient], AiJudge]
MatcherFactory = Callable[[Settings], Matcher]
DetectorFactory = Callable[[Settings], AiDetector | None]


async def _warm_matcher(ctx: AppContext) -> None:
    try:
        await ctx.matcher.warmup()
    except Exception as error:  # прогрев не должен ронять сервер
        log.exception("Прогрев воронки не удался")
        async with ctx.sessions.begin() as session:
            await log_event(session, "error", f"Воронка не прогрелась: {type(error).__name__}.")


def create_app(
    settings: Settings | None = None,
    *,
    adapter_factory: AdapterFactory | None = None,
    judge_factory: JudgeFactory | None = None,
    matcher_factory: MatcherFactory | None = None,
    detector_factory: DetectorFactory | None = None,
) -> FastAPI:
    """Собрать приложение. Фабрики площадок, нейросети и детектора подменяются в тестах."""
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        if settings.is_sqlite:
            await create_all(engine)  # SQLite — только тесты; PostgreSQL — через миграции Alembic
        sessions = create_sessions(engine)
        http = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": f"MediaMonitor/{settings.app_version}"},
            follow_redirects=False,
        )
        adapters = (adapter_factory or build_adapters)(settings, http)
        judge = (judge_factory or build_judge)(settings, http)
        matcher = (
            matcher_factory(settings)
            if matcher_factory
            else load_matcher(settings.matcher, settings)
        )
        ctx = AppContext(
            settings=settings,
            sessions=sessions,
            adapters=adapters,
            judge=judge,
            matcher=matcher,
            http=http,
            bus=EventBus(),
            topics=TopicService(judge, matcher),
            ai_checks=AiCheckService(
                settings, sessions, (detector_factory or build_detector)(settings)
            ),
            started_at=utcnow(),
        )
        ctx.runner = SearchRunner(ctx)
        extra = [
            s for a in adapters.values() if isinstance(a, FixtureAdapter) for s in a.store.catalog()
        ]
        async with sessions.begin() as session:
            catalog_size = await seed_catalog(
                session, list({(s.platform, s.owner_id): s for s in extra}.values())
            )
            await log_event(
                session,
                "info",
                f"Сервер запущен, версия {settings.app_version}; данные: {settings.data_source}; "
                f"каталог края: {catalog_size} источников.",
            )
        await ctx.ai_checks.load_identity()
        recovered = await ctx.runner.recover()
        if recovered:
            log.warning("Закрыто поисков, прерванных перезапуском: %s", recovered)
        warmups: list[asyncio.Task[None]] = []
        if settings.llm_warmup:
            warmups.append(asyncio.create_task(judge.warmup(), name="llm-warmup"))
        if settings.matcher_warmup:
            # Модель смысла и признаки события грузятся в фоне: сервер отвечает сразу (НТ-18).
            warmups.append(asyncio.create_task(_warm_matcher(ctx), name="matcher-warmup"))
        # Сервис детектора ИИ: доступен ли и какая версия модели (в фоне, не задерживает старт).
        warmups.append(asyncio.create_task(ctx.ai_checks.probe(), name="ai-detect-probe"))
        app.state.ctx = ctx
        try:
            yield
        finally:
            for task in warmups:
                if not task.done():
                    task.cancel()
            await ctx.runner.shutdown()
            await ctx.ai_checks.aclose()
            await http.aclose()
            await engine.dispose()

    production = settings.environment == "production"
    app = FastAPI(
        title="Медиамонитор — API",
        version=settings.app_version,
        description="Поиск публикаций VK, OK и MAX по Красноярскому краю. "
        "Контракт: web/src/api/types.ts.",
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    install_error_handlers(app)
    app.include_router(router)

    @app.get("/health", response_model=Health, tags=["служебное"])
    async def health() -> Health:
        ctx: AppContext = app.state.ctx
        try:
            async with ctx.sessions() as session:
                await session.execute(text("SELECT 1"))
            database = "ok"
        except Exception:  # база недоступна — отвечаем, а не падаем
            database = "down"
        return Health(
            status="ok" if database == "ok" else "degraded",
            database="ok" if database == "ok" else "down",
            version=settings.app_version,
        )

    # Порядок: внешние обёртки — последними.
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(BodyLimitMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Workspace-Key", "Last-Event-ID"],
        expose_headers=["Retry-After", "Content-Disposition", "X-Export-Rows"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    return app
