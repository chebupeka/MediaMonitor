"""Общие заготовки тестов: приложение на временной базе, клиент httpx, чтение потока SSE.

База — временный файл SQLite (только для тестов). Если задана переменная
TEST_DATABASE_URL (PostgreSQL), тесты идут на ней — так их гоняют на стенде.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from mediamonitor.adapters import AdapterRegistry, FixtureAdapter, FixtureStore
from mediamonitor.adapters.fixture import FailureMode
from mediamonitor.ai.judge import AiJudge, NullJudge
from mediamonitor.contract import PLATFORM_ORDER, PlatformId
from mediamonitor.main import DetectorFactory, JudgeFactory, MatcherFactory, create_app
from mediamonitor.settings import Settings

if sys.platform == "win32":
    # Асинхронный psycopg (PostgreSQL) не работает с ProactorEventLoop Windows.
    def pytest_asyncio_loop_factories(
        config: pytest.Config, item: pytest.Item
    ) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
        del config, item
        return {"selector": asyncio.SelectorEventLoop}


# Период, в который попадают записанные примеры (их «сегодня» — 19.10.2026).
PERIOD = {"preset": "custom", "from": "2026-09-20", "to": "2026-10-19"}
BDD = "Безопасность дорожного движения"
_STORE: FixtureStore | None = None


def fixture_store() -> FixtureStore:
    global _STORE  # noqa: PLW0603 — фикстуры читаем один раз на прогон
    if _STORE is None:
        _STORE = FixtureStore.load()
    return _STORE


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    values: dict[str, Any] = {
        "database_url": url,
        "environment": "test",
        "fixture_step_delay_ms": 0,
        "llm_warmup": False,
        "ollama_url": None,
        "rate_limit_per_minute": 100_000,
        "search_rate_limit_per_minute": 10_000,
        "workspace_rate_limit_per_minute": 10_000,
        "ai_check_rate_limit_per_minute": 10_000,
        # Общая база PostgreSQL (TEST_DATABASE_URL) копит счётчик за сутки между прогонами.
        "workspaces_per_ip_per_day": 1_000_000,
        "public_app_url": "https://monitor.example/",
        # Большинство тестов — на простой заглушке отбора (быстро и предсказуемо);
        # воронка «Э-Отбор» — в test_funnel.py с лёгкой моделью смысла.
        "matcher": "mediamonitor.matcher.simple:create_matcher",
        "matcher_warmup": False,
        "embedding_model": "fake-berta",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@dataclass
class Harness:
    """Приложение и его площадки: тест может включить сбой или «удалить» пост."""

    app: FastAPI
    adapters: dict[PlatformId, FixtureAdapter]


def make_app(
    settings: Settings,
    *,
    failures: dict[PlatformId, FailureMode] | None = None,
    judge: AiJudge | None = None,
    judge_factory: JudgeFactory | None = None,
    matcher_factory: MatcherFactory | None = None,
    detector_factory: DetectorFactory | None = None,
    step_delay_sec: float = 0.0,
    store: FixtureStore | None = None,
) -> Harness:
    adapters = {
        p: FixtureAdapter(
            p,
            store or fixture_store(),
            failure=(failures or {}).get(p),
            step_delay_sec=step_delay_sec,
        )
        for p in PLATFORM_ORDER
    }

    def adapter_factory(_: Settings, __: httpx.AsyncClient) -> AdapterRegistry:
        return dict(adapters)

    def default_judge_factory(s: Settings, _: httpx.AsyncClient) -> AiJudge:
        return judge or NullJudge(s.llm_model_label)

    app = create_app(
        settings,
        adapter_factory=adapter_factory,
        judge_factory=judge_factory or default_judge_factory,
        matcher_factory=matcher_factory,
        detector_factory=detector_factory,
    )
    return Harness(app=app, adapters=adapters)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def harness(settings: Settings) -> Harness:
    return make_app(settings)


@pytest.fixture
async def client(harness: Harness) -> AsyncIterator[httpx.AsyncClient]:
    async with open_client(harness.app) as c:
        yield c


class open_client:  # noqa: N801 — читается как функция в `async with`
    """Клиент httpx к приложению с запущенным жизненным циклом (lifespan)."""

    def __init__(self, app: FastAPI, client_ip: str = "127.0.0.1") -> None:
        self.app = app
        self.client_ip = client_ip
        self._manager: LifespanManager | None = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        self._manager = LifespanManager(self.app, startup_timeout=30, shutdown_timeout=30)
        await self._manager.__aenter__()
        transport = httpx.ASGITransport(app=self._manager.app, client=(self.client_ip, 50000))
        self._client = httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60)
        return self._client

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
        if self._manager is not None:
            await self._manager.__aexit__(None, None, None)


# ---------------------------------------------------------------- помощники


async def new_workspace(client: httpx.AsyncClient) -> dict[str, str]:
    """Новое рабочее место → заголовки с его ключом."""
    response = await client.post("/api/workspaces")
    assert response.status_code == 201, response.text
    return {"X-Workspace-Key": response.json()["key"]}


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Поток SSE → список событий: {id, event, data}."""
    events = []
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if not line or line.startswith(":"):
                continue
            name, _, value = line.partition(": ")
            fields[name] = value
        if "data" in fields:
            events.append(
                {
                    "id": int(fields["id"]),
                    "event": fields["event"],
                    "data": json.loads(fields["data"]),
                }
            )
    return events


async def read_stream(
    client: httpx.AsyncClient, headers: dict[str, str], search_id: str, **params: Any
) -> list[dict[str, Any]]:
    response = await client.get(f"/api/searches/{search_id}/events", headers=headers, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


async def run_search(
    client: httpx.AsyncClient, headers: dict[str, str], text: str = BDD, **request: Any
) -> tuple[str, list[dict[str, Any]]]:
    body: dict[str, Any] = {"text": text, "period": PERIOD, "mode": "everywhere", **request}
    response = await client.post("/api/searches", json=body, headers=headers)
    assert response.status_code == 202, response.text
    search_id = str(response.json()["searchId"])
    return search_id, await read_stream(client, headers, search_id)


def unique() -> str:
    return uuid.uuid4().hex[:8]


Factory = Callable[..., Harness]
