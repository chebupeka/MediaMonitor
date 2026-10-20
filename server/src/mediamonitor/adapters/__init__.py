"""Адаптеры площадок: общий интерфейс, записанные примеры и настоящие VK, OK, MAX."""

from __future__ import annotations

import httpx

from mediamonitor.adapters.base import CallMeter, PlatformAdapter
from mediamonitor.adapters.fixture import (
    FixtureAdapter,
    FixtureStore,
    is_demo_post,
    parse_failures,
)
from mediamonitor.adapters.live import MaxAdapter, OkAdapter, VkAdapter
from mediamonitor.adapters.vk_live import PostCache
from mediamonitor.contract import PLATFORM_ORDER, PlatformId
from mediamonitor.settings import Settings

AdapterRegistry = dict[PlatformId, PlatformAdapter]


def live_adapter(
    platform: PlatformId,
    settings: Settings,
    client: httpx.AsyncClient,
    budget: CallMeter | None,
    cache: PostCache | None,
) -> PlatformAdapter:
    """Настоящий адаптер площадки — по строке на площадку."""
    if platform == "vk":
        return VkAdapter(settings, client, budget, cache=cache)
    if platform == "ok":
        return OkAdapter(settings, client, budget)
    return MaxAdapter(settings, client, budget)


def build_adapters(
    settings: Settings,
    client: httpx.AsyncClient,
    budget: CallMeter | None = None,
    cache: PostCache | None = None,
) -> AdapterRegistry:
    """Адаптеры по площадкам: `DATA_SOURCE_<ПЛОЩАДКА>` (или общий `DATA_SOURCE`).

    fixtures — записанные примеры (их публикации помечаются `demo`), live — площадка.
    `budget` — суточный и месячный предел вызовов платных площадок (НТ-6): настоящие
    адаптеры списывают из него каждый вызов. `cache` — кэш публикаций в базе (Р7).
    """
    registry: AdapterRegistry = {}
    store: FixtureStore | None = None
    failures = parse_failures(settings.fixture_failures)
    delay = settings.fixture_step_delay_ms / 1000
    for platform in PLATFORM_ORDER:
        if settings.source_of(platform) == "live":
            registry[platform] = live_adapter(platform, settings, client, budget, cache)
            continue
        if store is None:
            store = FixtureStore.load(shift_to_now=settings.fixture_shift_to_now)
        registry[platform] = FixtureAdapter(
            platform, store, failure=failures.get(platform), step_delay_sec=delay
        )
    return registry


def demo_platforms(adapters: AdapterRegistry) -> list[PlatformId]:
    """Площадки, которые сейчас отвечают записанными примерами."""
    return [p for p in PLATFORM_ORDER if isinstance(adapters.get(p), FixtureAdapter)]


__all__ = [
    "AdapterRegistry",
    "FixtureAdapter",
    "FixtureStore",
    "PlatformAdapter",
    "build_adapters",
    "demo_platforms",
    "is_demo_post",
]
