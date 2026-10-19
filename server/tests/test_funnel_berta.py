"""Медленный интеграционный тест: настоящая модель BERTA на CPU (≈0,5 ГБ, грузится ~30 с).

Запуск: uv run pytest -m slow   (модель берётся из кэша Hugging Face или скачивается).
Обычный прогон pytest его пропускает.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediamonitor.matcher.funnel import FunnelMatcher, create_matcher
from mediamonitor.settings import Settings
from tests.conftest import (
    Harness,
    make_app,
    make_settings,
    new_workspace,
    open_client,
    run_search,
    unique,
)
from tests.fakes import shared_events
from tests.test_funnel import check_item, release_text

pytestmark = pytest.mark.slow


def berta_app(tmp_path: Path, version: str) -> tuple[Harness, list[FunnelMatcher]]:
    built: list[FunnelMatcher] = []

    def factory(settings: Settings) -> FunnelMatcher:
        matcher = create_matcher(settings)
        matcher.events = shared_events()
        matcher.core = matcher.make_core(matcher.llm_settings)
        built.append(matcher)
        return matcher

    settings = make_settings(tmp_path, embedding_model="sergeyzh/BERTA", embedding_version=version)
    return make_app(settings, matcher_factory=factory), built


async def test_release_search_with_real_berta(tmp_path: Path) -> None:
    version = unique()  # база может быть общей для прогонов (TEST_DATABASE_URL)
    harness, built = berta_app(tmp_path, version)
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        search_id, events = await run_search(client, headers, release_text())
        selection = events[-1]["data"]["selection"]
        groups = [g for g in selection["groups"] if g["kind"] == "release"]
        assert len(groups) == 1
        assert len(groups[0]["itemIds"]) >= 5, "перепечатки и пересказы релиза найдены"
        methods = {i["method"] for i in selection["items"]}
        assert "copy" in methods
        for item in selection["items"]:
            check_item(item)
        assert sum(s["found"] for s in selection["statuses"]) == selection["counts"]["total"]
        spread = (await client.get(f"/api/searches/{search_id}/spread", headers=headers)).json()
        assert spread["totals"]["placements"] == len(groups[0]["itemIds"])
    first = built[0].embedder.computed
    assert first > 10

    # Тот же поиск в новом процессе: векторы постов — из базы, модель считает только запрос.
    harness2, built2 = berta_app(tmp_path, version)
    async with open_client(harness2.app) as client:
        headers = await new_workspace(client)
        _, events = await run_search(client, headers, release_text())
        again = events[-1]["data"]["selection"]
        assert again["counts"] == selection["counts"]
    assert built2[0].embedder.computed <= 1
