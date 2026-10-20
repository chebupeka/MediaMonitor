"""Скорость поиска (стенд 20.10): отбор не душит сбор с площадок.

Пять площадок вживую давали сотни порций; после каждой подборка собиралась заново по всем
записям поиска прямо в цикле событий, и процесс api грузил процессор на 96 %. Теперь записи
уходят в поток пачками (не чаще ITEMS_EVENT_INTERVAL), а разбор текста идёт в потоке.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from mediamonitor.services import runner as runner_module
from mediamonitor.services.normalize_post import normalize
from tests.conftest import make_app, make_settings, new_workspace, open_client, run_search

# Цикл событий не должен замирать дольше этого — иначе запросы площадок ждут.
MAX_LOOP_STALL_SEC = 0.3


class _LoopProbe:
    """Тикает каждые 10 мс и запоминает самую долгую задержку тика."""

    def __init__(self) -> None:
        self.worst = 0.0
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        while True:
            began = time.perf_counter()
            await asyncio.sleep(0.01)
            self.worst = max(self.worst, time.perf_counter() - began - 0.01)

    def __enter__(self) -> _LoopProbe:
        self._task = asyncio.get_running_loop().create_task(self._run())
        return self

    def __exit__(self, *exc: object) -> None:
        if self._task is not None:
            self._task.cancel()


async def test_slow_normalization_does_not_block_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow_normalize(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.05)  # разбор длинного текста: синхронная работа на каждый пост
        return normalize(*args, **kwargs)

    monkeypatch.setattr(runner_module, "normalize", slow_normalize)
    harness = make_app(make_settings(tmp_path, match_batch_size=32))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        with _LoopProbe() as probe:
            _, events = await run_search(client, headers)
    assert events[-1]["event"] == "finished"
    assert events[-1]["data"]["selection"]["counts"]["total"] > 10
    # В цикле событий порция из 32 постов держала бы его 1,6 с.
    assert probe.worst < MAX_LOOP_STALL_SEC


async def test_items_are_sent_in_batches_and_none_is_lost(tmp_path: Path) -> None:
    # Порция по одному посту — сотни порций, как у пяти площадок вживую.
    harness = make_app(make_settings(tmp_path, match_batch_size=1))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        _, events = await run_search(client, headers)
    finished = events[-1]["data"]["selection"]
    total = finished["counts"]["total"]
    assert total > 10
    items_events = [e for e in events if e["event"] == "items"]
    # Не событие на каждую порцию: первые записи сразу, остальные пачками и перед итогом площадки.
    assert len(items_events) <= len(finished["statuses"]) + 2 < total
    sent = {i["id"] for e in items_events for i in e["data"]["items"]}
    assert sent == {i["id"] for i in finished["items"]}
    # Записи площадки приходят раньше её итога.
    position: dict[str, int] = {}
    for index, event in enumerate(events):
        if event["event"] == "items":
            for item in event["data"]["items"]:
                position.setdefault(item["id"], index)
    for index, event in enumerate(events):
        status = event["data"].get("status") if event["event"] == "platform" else None
        if status and status["state"] == "found":
            platform = status["platform"]
            mine = [i["id"] for i in finished["items"] if i["publication"]["platform"] == platform]
            assert all(position[i] < index for i in mine)
