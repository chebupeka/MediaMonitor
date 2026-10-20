"""Бюджет вызовов внешних площадок на открытом стенде (НТ-6): сутки и месяц, 80%, исчерпание.

Настоящие адаптеры пока заготовки, поэтому вызовы площадки изображает адаптер на записанных
примерах, который списывает по вызову на каждый шаг обхода — как будет делать VK
(`wall.get` по сообществу) и MaxStat (страница поиска).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from mediamonitor.adapters import FixtureAdapter
from mediamonitor.adapters.base import (
    AdapterEvent,
    AdapterQuery,
    CallMeter,
    Progress,
    QuotaInfo,
)
from mediamonitor.contract import PlatformId
from mediamonitor.db.models import QuotaUsageRow, StandEventRow
from mediamonitor.db.session import SessionMaker
from mediamonitor.services.budget import BudgetExhaustedError, CallBudget, window
from tests.conftest import fixture_store, make_app, make_settings, new_workspace, open_client
from tests.conftest import run_search as run

# Полдень 30.10.2031 по Красноярску: далеко от сегодняшних счётчиков общей базы.
NOON = datetime(2031, 10, 30, 5, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class MeteredAdapter(FixtureAdapter):
    """Записанные примеры, но каждый шаг обхода — платный вызов площадки."""

    def __init__(self, platform: PlatformId) -> None:
        super().__init__(platform, fixture_store())
        self.description.quota = QuotaInfo(limit=0, unit="вызовов", period="day")
        self.budget: CallMeter | None = None
        self.calls = 0

    async def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        async for event in super().search(query):
            if isinstance(event, Progress) and event.done < event.total:
                if self.budget is not None:
                    await self.budget.spend(self.platform)
                self.calls += 1
            yield event


async def _clean(sessions: SessionMaker, platform: PlatformId) -> None:
    async with sessions.begin() as session:
        await session.execute(delete(QuotaUsageRow).where(QuotaUsageRow.platform == platform))
        await session.execute(
            delete(StandEventRow).where(StandEventRow.message.like(f"{platform.upper()}:%"))
        )


async def _events(sessions: SessionMaker, prefix: str) -> list[StandEventRow]:
    async with sessions() as session:
        rows = await session.scalars(
            select(StandEventRow)
            .where(StandEventRow.message.like(f"{prefix}%"))
            .order_by(StandEventRow.id)
        )
        return list(rows)


def test_windows_follow_krasnoyarsk_calendar() -> None:
    # 23:30 30 ноября по Красноярску — это ещё ноябрь, хотя в UTC уже 16:30 того же дня.
    late = datetime(2031, 11, 30, 16, 30, tzinfo=UTC)
    day, month = window("day", late), window("month", late)
    assert day.key == "2031-11-30"
    assert day.resets_at == datetime(2031, 11, 30, 17, 0, tzinfo=UTC)  # 00:00 1 декабря
    assert month.key == "2031-11"
    assert month.resets_at == datetime(2031, 11, 30, 17, 0, tzinfo=UTC)
    december = window("month", datetime(2031, 12, 10, tzinfo=UTC))
    assert december.key == "2031-12"
    assert december.resets_at == datetime(2031, 12, 31, 17, 0, tzinfo=UTC)  # 1 января 2032


async def test_daily_limit_warns_at_80_percent_and_stops(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, vk_daily_calls=10, vk_monthly_quota=100)
    harness = make_app(settings)
    clock = Clock(NOON)
    async with open_client(harness.app):
        sessions = harness.app.state.ctx.sessions
        await _clean(sessions, "vk")
        budget = CallBudget(settings, sessions, clock=clock)
        for _ in range(7):
            await budget.spend("vk")
        assert await _events(sessions, "VK:") == []
        await budget.spend("vk")  # 8 из 10 — 80%
        await budget.spend("vk")
        warnings = await _events(sessions, "VK:")
        assert [e.level for e in warnings] == ["warning"]
        assert "80% суточного лимита (8 из 10 вызовов за сутки)" in warnings[0].message

        await budget.spend("vk")  # 10 из 10 — исчерпан
        events = await _events(sessions, "VK:")
        assert [e.level for e in events] == ["warning", "error"]
        assert "суточный лимит открытого стенда исчерпан" in events[1].message

        with pytest.raises(BudgetExhaustedError) as exhausted:
            await budget.spend("vk")
        error = exhausted.value
        assert error.code == "quota-exhausted"
        assert error.state == "no-access"
        assert not error.retryable
        assert "на сегодня исчерпан" in error.message
        assert "после 00:00 по красноярскому времени" in error.message
        with pytest.raises(BudgetExhaustedError):
            await budget.ensure_available("vk")
        # Отказ ничего не списал и не написал в журнал второй раз.
        async with sessions() as session:
            row = await session.get(QuotaUsageRow, ("vk", "2031-10-30"))
            assert row is not None
            assert row.used == 10
        assert len(await _events(sessions, "VK:")) == 2

        # Наступили следующие сутки — снова можно; месячный счётчик продолжается.
        clock.now = NOON + timedelta(days=1)
        await budget.ensure_available("vk")
        await budget.spend("vk")
        async with sessions() as session:
            month = await session.get(QuotaUsageRow, ("vk", "2031-10"))
            assert month is not None
            assert month.used == 11


async def test_monthly_limit_and_call_that_does_not_fit(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, maxstat_daily_credits=0, maxstat_credits=10)
    harness = make_app(settings)
    async with open_client(harness.app):
        sessions = harness.app.state.ctx.sessions
        await _clean(sessions, "max")
        budget = CallBudget(settings, sessions, clock=Clock(NOON))
        await budget.spend("max", 3)
        await budget.spend("max", 6)  # 9 из 10
        # Поиск MaxStat стоит 3 кредита: в оставшийся 1 не помещается — не списываем.
        with pytest.raises(BudgetExhaustedError) as exhausted:
            await budget.spend("max", 3)
        assert "на этот месяц исчерпан" in exhausted.value.message
        assert "1 ноября" in exhausted.value.message
        await budget.spend("max", 1)  # а один кредит — помещается
        async with sessions() as session:
            row = await session.get(QuotaUsageRow, ("max", "2031-10"))
            assert row is not None
            assert row.used == 10
        # Одноклассники — без ключа и без бюджета.
        assert not budget.covers("ok")
        await budget.spend("ok", 1_000_000)


async def test_zero_means_no_limit(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, vk_daily_calls=0, vk_monthly_quota=0)
    harness = make_app(settings)
    async with open_client(harness.app):
        budget = CallBudget(settings, harness.app.state.ctx.sessions, clock=Clock(NOON))
        assert not budget.covers("vk")
        await budget.spend("vk", 50_000)
        await budget.ensure_available("vk", 50_000)


async def test_search_stops_with_clear_status_when_limit_is_spent(tmp_path: Path) -> None:
    pool = fixture_store().everywhere_pool.get("vk", 10)
    assert pool > 4
    settings = make_settings(tmp_path, vk_daily_calls=4, vk_monthly_quota=10_000)
    harness = make_app(settings)
    vk = MeteredAdapter("vk")
    harness.adapters["vk"] = vk
    async with open_client(harness.app) as client:
        ctx = harness.app.state.ctx
        await _clean(ctx.sessions, "vk")
        vk.budget = ctx.budget
        headers = await new_workspace(client)

        # Обход VK упирается в предел на середине: найденное до этого — в подборке.
        _, events = await run(client, headers)
        assert events[-1]["event"] == "finished"
        statuses = {s["platform"]: s for s in events[-1]["data"]["selection"]["statuses"]}
        assert statuses["vk"]["state"] == "no-access"
        problem = statuses["vk"]["problem"]
        assert problem["code"] == "quota-exhausted"
        assert problem["retryable"] is False
        assert "Лимит запросов к ВКонтакте на сегодня исчерпан" in problem["message"]
        assert statuses["ok"]["state"] == "found"  # другие площадки ищут дальше
        assert vk.calls == 4

        # Следующий поиск: обход VK даже не начинается.
        _, again = await run(client, headers)
        statuses = {s["platform"]: s for s in again[-1]["data"]["selection"]["statuses"]}
        assert statuses["vk"]["state"] == "no-access"
        assert statuses["vk"]["problem"]["code"] == "quota-exhausted"
        assert vk.calls == 4

        # Дежурный видит расход и запись в журнале стенда.
        stand = (await client.get("/api/stand")).json()
        quota = next(p["quota"] for p in stand["platforms"] if p["platform"] == "vk")
        assert quota["used"] == 4
        assert quota["limit"] == 4
        assert quota["unit"] == "вызовов за сутки"
        assert quota["resetsAt"].endswith("T00:00:00+07:00")
        messages = [e["message"] for e in stand["events"]]
        assert any("VK: суточный лимит открытого стенда исчерпан" in m for m in messages)
        # Площадки на записанных примерах не платят вызовами — квоты у них нет.
        assert next(p["quota"] for p in stand["platforms"] if p["platform"] == "ok") is None
