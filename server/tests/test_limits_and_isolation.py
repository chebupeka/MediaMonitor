"""Лимиты открытого стенда (НТ-6) и изоляция рабочих мест (НТ-7, Р8)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from mediamonitor.api.middleware import RateLimiter
from tests.conftest import (
    BDD,
    PERIOD,
    Harness,
    make_app,
    make_settings,
    new_workspace,
    open_client,
    run_search,
)

# ---------------------------------------------------------------- лимиты (НТ-6)


async def test_query_longer_than_limit(client: httpx.AsyncClient) -> None:
    headers = await new_workspace(client)
    body = {"text": "а" * 20_001, "period": PERIOD, "mode": "everywhere"}
    response = await client.post("/api/searches", json=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["code"] == "too-long"
    ok = {"text": "а" * 20_000, "period": PERIOD, "mode": "everywhere"}
    assert (await client.post("/api/searches", json=ok, headers=headers)).status_code == 202


async def test_period_longer_than_six_months(client: httpx.AsyncClient) -> None:
    headers = await new_workspace(client)
    period = {"preset": "custom", "from": "2026-01-01", "to": "2026-10-19"}
    response = await client.post(
        "/api/searches", json={"text": BDD, "period": period, "mode": "everywhere"}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid"
    assert "6 месяцев" in response.json()["message"]
    reversed_period = {"preset": "custom", "from": "2026-10-19", "to": "2026-10-01"}
    response = await client.post(
        "/api/searches",
        json={"text": BDD, "period": reversed_period, "mode": "everywhere"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_one_active_search_per_workspace(tmp_path: Path) -> None:
    harness = make_app(make_settings(tmp_path), step_delay_sec=0.05)
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        body = {"text": BDD, "period": PERIOD, "mode": "everywhere"}
        first = await client.post("/api/searches", json=body, headers=headers)
        assert first.status_code == 202
        second = await client.post("/api/searches", json=body, headers=headers)
        assert second.status_code == 429
        error = second.json()
        assert error["code"] == "too-many-requests"
        assert error["retryAfterSec"] == 10
        assert second.headers["retry-after"] == "10"
        assert "Уже идёт поиск" in error["message"]
        # Другое рабочее место может искать в это же время (НТ-7).
        other = await new_workspace(client)
        assert (await client.post("/api/searches", json=body, headers=other)).status_code == 202
        await client.post(f"/api/searches/{first.json()['searchId']}/stop", headers=headers)


async def test_rate_limit_by_ip(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, rate_limit_per_minute=5)
    harness = make_app(settings)
    async with open_client(harness.app, client_ip="10.0.0.1") as client:
        statuses = [(await client.get("/api/stand")).status_code for _ in range(7)]
        assert statuses[:5] == [200] * 5
        assert statuses[5:] == [429, 429]
        limited = await client.get("/api/stand")
        assert limited.json()["code"] == "too-many-requests"
        assert int(limited.headers["retry-after"]) > 0
        assert (await client.get("/health")).status_code == 200  # проверка живости не ограничена


async def test_search_start_rate_limit(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, search_rate_limit_per_minute=2)
    harness = make_app(settings)
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        body = {"text": "", "period": PERIOD, "mode": "everywhere"}
        codes = [
            (await client.post("/api/searches", json=body, headers=headers)).status_code
            for _ in range(3)
        ]
        assert codes == [422, 422, 429]


def test_rate_limiter_window() -> None:
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])
    assert limiter.hit("all", "ip", 2) is None
    assert limiter.hit("all", "ip", 2) is None
    assert limiter.hit("all", "ip", 2) == 61
    assert limiter.hit("all", "other-ip", 2) is None
    now[0] = 60.5
    assert limiter.hit("all", "ip", 2) is None


async def test_body_size_limit(tmp_path: Path) -> None:
    harness = make_app(make_settings(tmp_path, max_body_bytes=1_000))
    async with open_client(harness.app) as client:
        response = await client.post("/api/query/analyze", json={"text": "я" * 2_000})
        assert response.status_code == 413
        assert response.json()["code"] == "too-long"


async def test_queue_when_server_is_busy(tmp_path: Path) -> None:
    """Сверх MAX_RUNNING_SEARCHES поиск ждёт в очереди: «перед вами N» (НТ-6)."""
    harness = make_app(make_settings(tmp_path, max_running_searches=1), step_delay_sec=0.02)
    async with open_client(harness.app) as client:
        first, second = await new_workspace(client), await new_workspace(client)
        body = {"text": BDD, "period": PERIOD, "mode": "everywhere"}
        await client.post("/api/searches", json=body, headers=first)
        await asyncio.sleep(0.05)
        _, events = await run_search(client, second)
        assert events[0]["event"] == "queued"
        assert events[0]["data"]["ahead"] == 1
        assert events[0]["data"]["etaSec"] > 0
        assert [e["event"] for e in events].index("started") > 0
        assert events[-1]["event"] == "finished"


# ---------------------------------------------------------------- изоляция (НТ-7)


async def test_workspaces_do_not_see_each_other(client: httpx.AsyncClient) -> None:
    alice, bob = await new_workspace(client), await new_workspace(client)
    search_id, _ = await run_search(client, alice)
    for method, url in (
        ("GET", f"/api/searches/{search_id}"),
        ("GET", f"/api/searches/{search_id}/events"),
        ("GET", f"/api/searches/{search_id}/export/preview"),
        ("GET", f"/api/searches/{search_id}/export.xlsx"),
        ("GET", f"/api/searches/{search_id}/spread"),
        ("POST", f"/api/searches/{search_id}/stop"),
        ("POST", f"/api/searches/{search_id}/links/recheck"),
        ("POST", f"/api/searches/{search_id}/platforms/vk/retry"),
    ):
        response = await client.request(method, url, headers=bob)
        assert response.status_code == 404, (method, url, response.status_code)
        assert response.json()["code"] == "not-found"
    excluded = await client.post(
        f"/api/searches/{search_id}/exclusions",
        json={"itemIds": ["x"], "excluded": True},
        headers=bob,
    )
    assert excluded.status_code == 404
    assert (await client.get("/api/recent", headers=bob)).json() == []
    assert len((await client.get("/api/recent", headers=alice)).json()) == 1


async def test_source_lists_are_separate(client: httpx.AsyncClient) -> None:
    alice, bob = await new_workspace(client), await new_workspace(client)
    catalog = (await client.get("/api/catalog", headers=alice)).json()
    assert catalog, "каталог края общий и не пустой"
    await client.post("/api/sources/from-catalog", json={"ids": [catalog[0]["id"]]}, headers=alice)
    assert len((await client.get("/api/sources", headers=alice)).json()) == 1
    assert (await client.get("/api/sources", headers=bob)).json() == []
    bob_catalog = (await client.get("/api/catalog", headers=bob)).json()
    assert not any(c["inMySources"] for c in bob_catalog)
    # Удалить чужой источник нельзя.
    response = await client.delete(f"/api/sources/{catalog[0]['id']}", headers=bob)
    assert response.status_code == 404
    assert len((await client.get("/api/sources", headers=alice)).json()) == 1


async def test_workspace_key_required_and_link(harness: Harness, client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/sources")
    assert missing.status_code == 404
    assert missing.json()["code"] == "not-found"
    wrong = await client.get("/api/sources", headers={"X-Workspace-Key": "guess"})
    assert wrong.status_code == 404
    created = (await client.post("/api/workspaces")).json()
    assert len(created["key"]) >= 32
    assert created["url"] == f"https://monitor.example/#workspace={created['key']}"
    headers = {"X-Workspace-Key": created["key"]}
    link = (await client.get("/api/workspace/link", headers=headers)).json()
    assert link["key"] == created["key"]
    assert link["workspaceId"] == created["workspaceId"]
    opened = await client.post("/api/workspace/open", json={"key": link["url"]})
    assert opened.status_code == 200
    assert opened.json()["id"] == created["workspaceId"]
    unknown = await client.post("/api/workspace/open", json={"key": "nope"})
    assert unknown.status_code == 404
    assert "ссылке не найдено" in unknown.json()["message"]
    # Ключ хранится только как хеш: в базе его нет.
    from sqlalchemy import select

    from mediamonitor.db.models import WorkspaceRow

    ctx = harness.app.state.ctx
    async with ctx.sessions() as session:
        rows = list(await session.scalars(select(WorkspaceRow)))
    assert all(created["key"] not in (r.key_hash, r.id) for r in rows)


async def test_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/stand")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("application/json")
