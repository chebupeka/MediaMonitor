"""Состояние стенда для дежурного (НТ-18): площадки, квоты, нейросеть, очередь, память.

Квоты считаем сами: каждый платный вызов адаптер списывает из бюджета (`services/budget.py`,
предел на сутки и месяц); при 80% в журнал стенда пишется предупреждение (решения из
матрицы, п. 5). Страница показывает самый напряжённый из периодов.
Ни ключей, ни адресов внутренних сервисов страница не показывает (НТ-15).
"""

from __future__ import annotations

import asyncio
from typing import Literal, cast

import psutil
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.contract import (
    PLATFORM_ORDER,
    HealthState,
    PlatformId,
    StandAi,
    StandEvent,
    StandMemory,
    StandPlatform,
    StandQueue,
    StandStatus,
)
from mediamonitor.db.models import PlatformRunRow, StandEventRow
from mediamonitor.services.context import AppContext
from mediamonitor.timeutil import iso, iso_or_none, utcnow

EventLevel = Literal["info", "warning", "error"]


async def log_event(session: AsyncSession, level: EventLevel, message: str) -> None:
    session.add(StandEventRow(at=utcnow(), level=level, message=message[:1000]))


async def _last_success(session: AsyncSession, platform: PlatformId) -> str | None:
    moment = await session.scalar(
        select(func.max(PlatformRunRow.updated_at)).where(
            PlatformRunRow.platform == platform, PlatformRunRow.state.in_(("found", "nothing"))
        )
    )
    return iso_or_none(moment)


def _memory() -> StandMemory:
    memory = psutil.virtual_memory()
    return StandMemory(
        used_mb=int((memory.total - memory.available) / 2**20), total_mb=int(memory.total / 2**20)
    )


async def stand_status(ctx: AppContext) -> StandStatus:
    healths = await asyncio.gather(*(ctx.adapters[p].health() for p in PLATFORM_ORDER))
    ai_status = await ctx.judge.status()
    stats = ctx.judge.stats
    async with ctx.sessions() as session:
        platforms = []
        for platform, health in zip(PLATFORM_ORDER, healths, strict=True):
            adapter = ctx.adapters[platform]
            platforms.append(
                StandPlatform(
                    platform=platform,
                    state=health.state,
                    message=health.message,
                    via=adapter.description.via,
                    freshness=adapter.description.freshness,
                    # Расход бюджета — у площадок, которые платят вызовами (VK, MaxStat).
                    quota=await ctx.budget.quota(session, platform)
                    if adapter.description.quota is not None
                    else None,
                    last_success_at=await _last_success(session, platform),
                )
            )
        rows = await session.scalars(
            select(StandEventRow).order_by(StandEventRow.at.desc()).limit(20)
        )
        history = [
            StandEvent(at=iso(r.at), level=cast(EventLevel, r.level), message=r.message)
            for r in rows
        ]
    # Текущее состояние воронки (модель смысла: CPU, видеокарта или откат) и проверки на ИИ
    # (детектор недоступен — предупреждение) — первыми строками.
    notes = [*ctx.matcher.stand_notes(), *ctx.ai_checks.stand_notes()]
    now = iso(utcnow())
    events = [StandEvent(at=now, level=n.level, message=n.message) for n in notes] + history
    if not ai_status.available:
        ai_state: HealthState = "down"
    elif not stats.warm:
        ai_state = "degraded"
    else:
        ai_state = "ok"
    states = [p.state for p in platforms] + [ai_state]
    healthy = all(s == "ok" for s in states) and all(n.level == "info" for n in notes)
    overall: HealthState = "ok" if healthy else "degraded"
    return StandStatus(
        checked_at=iso(utcnow()),
        overall=overall,
        platforms=platforms,
        ai=StandAi(
            state=ai_state,
            model=ctx.judge.model_label,
            warm=stats.warm,
            queue_length=stats.queue_length,
            avg_seconds_per_post=stats.avg_seconds_per_post,
        ),
        queue=StandQueue(
            running=ctx.runner.running,
            waiting=ctx.runner.waiting,
            per_client_limit=ctx.settings.active_searches_per_workspace,
        ),
        memory=_memory(),
        events=events,
        version=ctx.settings.app_version,
    )
