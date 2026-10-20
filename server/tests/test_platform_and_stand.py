"""Стенд (НТ-18), квоты, большая подборка и потолок площадки (К26, SC-16), перезапуск (SC-51),
подключение своей воронки через MATCHER и проверка её ответов сервером (К14)."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

import httpx
from sqlalchemy import delete, select

from mediamonitor.ai.judge import AiJudge
from mediamonitor.db.models import QuotaUsageRow, SearchRow, StandEventRow
from mediamonitor.matcher import (
    Candidate,
    Decision,
    EvidenceDraft,
    MatchSession,
    QueryContext,
    VectorStore,
    load_matcher,
)
from mediamonitor.matcher.simple import SimpleMatcher
from tests.conftest import Harness, make_app, make_settings, new_workspace, open_client, run_search


async def test_stand_status(harness: Harness, client: httpx.AsyncClient) -> None:
    stand = (await client.get("/api/stand")).json()
    assert [p["platform"] for p in stand["platforms"]] == ["vk", "ok", "max"]
    assert all("Фикстуры" in p["via"] for p in stand["platforms"])
    assert stand["platforms"][2]["freshness"]["delayHours"] == 24
    assert stand["queue"] == {"running": 0, "waiting": 0, "perClientLimit": 1}
    assert 0 < stand["memory"]["usedMb"] <= stand["memory"]["totalMb"]
    assert stand["version"] == "0.1.0"
    assert any("Сервер запущен" in e["message"] for e in stand["events"])
    # Ни ключей, ни внутренних адресов на странице стенда (НТ-15).
    assert "http" not in str(stand)
    assert "sqlite" not in str(stand).lower()


async def test_quota_warning_at_80_percent(tmp_path: Path) -> None:
    # Только месячный предел (суточный 0 — выключен): одно предупреждение на 80%.
    settings = make_settings(tmp_path, vk_monthly_quota=100, vk_daily_calls=0)
    harness = make_app(settings)
    async with open_client(harness.app) as client:
        ctx = harness.app.state.ctx
        async with ctx.sessions.begin() as session:
            # База может быть общей для прогонов (TEST_DATABASE_URL) — с чистого счётчика.
            await session.execute(delete(QuotaUsageRow).where(QuotaUsageRow.platform == "vk"))
            await session.execute(delete(StandEventRow).where(StandEventRow.message.like("VK:%")))
        await ctx.budget.spend("vk", 79)
        await ctx.budget.spend("vk", 1)
        await ctx.budget.spend("vk", 5)
        stand = (await client.get("/api/stand")).json()
    warnings = [e for e in stand["events"] if "лимита" in e["message"]]
    assert len(warnings) == 1  # предупреждение одно, а не на каждый вызов
    assert warnings[0]["level"] == "warning"
    assert "80%" in warnings[0]["message"]
    assert "80 из 100 вызовов за месяц" in warnings[0]["message"]


async def test_large_selection_and_platform_cap(client: httpx.AsyncClient) -> None:
    headers = await new_workspace(client)
    started = time.perf_counter()
    search_id, events = await run_search(client, headers, "нагрузочный набор 500")
    elapsed = time.perf_counter() - started
    selection = events[-1]["data"]["selection"]
    statuses = {s["platform"]: s for s in selection["statuses"]}
    assert statuses["ok"]["cap"] == {
        "limit": 100,
        "note": "Одноклассники отдают не больше 100 результатов на запрос",
    }
    assert any(n["code"] == "platform-cap" for n in selection["notices"])
    assert selection["counts"]["total"] > 300
    response = await client.get(f"/api/searches/{search_id}/export.xlsx", headers=headers)
    assert response.status_code == 200
    assert elapsed < 60, f"500 результатов искались {elapsed:.1f} с"


async def test_interrupted_search_is_closed_on_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    harness = make_app(settings, step_delay_sec=0.5)
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        body = {
            "text": "ДТП",
            "period": {"preset": "custom", "from": "2026-09-20", "to": "2026-10-19"},
            "mode": "everywhere",
        }
        search_id = (await client.post("/api/searches", json=body, headers=headers)).json()[
            "searchId"
        ]
        ctx = harness.app.state.ctx
        # «Сервер упал»: задачу поиска снимаем, в базе поиск остаётся «идёт».
        live = ctx.runner._live[search_id]
        assert live.task is not None
        live.task.cancel()
        for task in live.platform_tasks.values():
            task.cancel()
        ctx.runner._live.clear()
        async with ctx.sessions.begin() as session:
            row = await session.get(SearchRow, search_id)
            assert row is not None
            row.phase = "running"
    restarted = make_app(settings)
    async with open_client(restarted.app) as client:
        selection = (await client.get(f"/api/searches/{search_id}", headers=headers)).json()
        assert selection["phase"] == "done"
        problems = [s["problem"] for s in selection["statuses"] if s["state"] == "error"]
        assert problems
        assert all(p["code"] == "unavailable" and p["retryable"] for p in problems)
        async with restarted.app.state.ctx.sessions() as session:
            running = list(
                await session.scalars(select(SearchRow).where(SearchRow.phase == "running"))
            )
        assert running == []


# ---------------------------------------------------------------- своя воронка через MATCHER


class _LyingSession:
    """Воронка, которая ошибается: чужой id, несуществующее предложение, отрезки вне текста."""

    ai_failed = False

    async def classify(self, candidates: Sequence[Candidate]) -> list[Decision]:
        result = [Decision("vk:-1_1", keep=True, relevance="direct")]
        for c in candidates:
            result.append(
                Decision(
                    c.id,
                    keep=True,
                    relevance="direct",
                    method="semantic",
                    evidence=EvidenceDraft(10_000, [(-5, 10**6)], "semantic", "выдумка"),
                )
            )
        return result


class LyingMatcher(SimpleMatcher):
    name = "lying"

    def start(  # type: ignore[override]
        self, query: QueryContext, judge: AiJudge, ai_available: bool, vectors: VectorStore
    ) -> MatchSession:
        del query, judge, ai_available, vectors
        return _LyingSession()


def create_lying_matcher() -> LyingMatcher:
    return LyingMatcher()


def test_load_matcher() -> None:
    matcher = load_matcher("tests.test_platform_and_stand:create_lying_matcher")
    assert matcher.name == "lying"
    simple = load_matcher("mediamonitor.matcher.simple:create_matcher")
    assert simple.name == "simple"


async def test_server_checks_matcher_output(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, matcher="tests.test_platform_and_stand:create_lying_matcher")
    harness = make_app(settings)
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        _, events = await run_search(client, headers)
        items = events[-1]["data"]["selection"]["items"]
        assert items
        assert "vk:-1_1" not in {i["id"] for i in items}  # чужой id воронки не попал в подборку
        for item in items:
            publication = item["publication"]
            if publication["text"] is None:
                continue
            assert 0 <= item["evidence"]["sentenceIndex"] < len(publication["sentences"])
            for r in item["evidence"]["ranges"]:
                assert 0 <= r["start"] < r["end"] <= len(publication["text"])
            excerpt = item["excerpt"]
            assert publication["text"][excerpt["start"] : excerpt["end"]] == excerpt["text"]
