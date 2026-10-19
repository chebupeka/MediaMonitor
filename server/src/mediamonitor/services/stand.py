"""Состояние стенда для дежурного (НТ-18): площадки, квоты, нейросеть, очередь, память.

Квоты считаем сами: каждый платный вызов адаптер отмечает в `quota_usage`; при 80%
квоты в журнал стенда пишется предупреждение (решения из матрицы, п. 5).
Ни ключей, ни адресов внутренних сервисов страница не показывает (НТ-15).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal, cast

import psutil
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.adapters.base import QuotaInfo
from mediamonitor.contract import (
    PLATFORM_ORDER,
    HealthState,
    PlatformId,
    Quota,
    StandAi,
    StandEvent,
    StandMemory,
    StandPlatform,
    StandQueue,
    StandStatus,
)
from mediamonitor.db.models import PlatformRunRow, QuotaUsageRow, StandEventRow
from mediamonitor.labels import PLATFORM_SHORT, format_number
from mediamonitor.services.context import AppContext
from mediamonitor.timeutil import iso, iso_or_none, utcnow

EventLevel = Literal["info", "warning", "error"]


async def log_event(session: AsyncSession, level: EventLevel, message: str) -> None:
    session.add(StandEventRow(at=utcnow(), level=level, message=message[:1000]))


def _period(info: QuotaInfo, now: datetime) -> tuple[str, datetime | None]:
    if info.period == "month":
        start_next = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=UTC)
        return now.strftime("%Y-%m"), start_next
    if info.period == "day":
        return now.strftime("%Y-%m-%d"), None
    return "total", None


async def spend_quota(
    session: AsyncSession, platform: PlatformId, info: QuotaInfo, amount: int, warn_ratio: float
) -> None:
    """Учесть расход квоты площадки; на 80% — предупреждение дежурному."""
    now = utcnow()
    period, resets = _period(info, now)
    row = await session.get(QuotaUsageRow, (platform, period))
    if row is None:
        row = QuotaUsageRow(
            platform=platform,
            period=period,
            used=0,
            limit=info.limit,
            unit=info.unit,
            resets_at=resets,
            warned=False,
        )
        session.add(row)
    row.used += amount
    row.limit = info.limit
    if not row.warned and row.used >= row.limit * warn_ratio:
        row.warned = True
        percent = round(row.used / row.limit * 100) if row.limit else 100
        level: EventLevel = "error" if row.used >= row.limit else "warning"
        await log_event(
            session,
            level,
            f"{PLATFORM_SHORT[platform]}: израсходовано {percent}% квоты "
            f"({format_number(row.used)} из {format_number(row.limit)} {row.unit}).",
        )


async def _quota(
    session: AsyncSession, platform: PlatformId, info: QuotaInfo | None
) -> Quota | None:
    if info is None:
        return None
    period, resets = _period(info, utcnow())
    row = await session.get(QuotaUsageRow, (platform, period))
    return Quota(
        used=row.used if row else 0,
        limit=info.limit,
        unit=info.unit,
        resets_at=iso_or_none(row.resets_at if row else resets),
    )


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
                    quota=await _quota(session, platform, adapter.description.quota),
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
