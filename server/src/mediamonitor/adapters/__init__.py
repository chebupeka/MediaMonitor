"""Адаптеры площадок: общий интерфейс, записанные примеры и настоящие VK, OK, MAX."""

from __future__ import annotations

import httpx

from mediamonitor.adapters.base import CallMeter, PlatformAdapter
from mediamonitor.adapters.fixture import FixtureAdapter, FixtureStore, parse_failures
from mediamonitor.adapters.live import MaxAdapter, OkAdapter, VkAdapter
from mediamonitor.contract import PLATFORM_ORDER, PlatformId
from mediamonitor.settings import Settings

AdapterRegistry = dict[PlatformId, PlatformAdapter]


def build_adapters(
    settings: Settings, client: httpx.AsyncClient, budget: CallMeter | None = None
) -> AdapterRegistry:
    """Адаптеры по настройке DATA_SOURCE: fixtures — записанные примеры, live — площадки.

    `budget` — суточный и месячный предел вызовов платных площадок (НТ-6): настоящие
    адаптеры списывают из него каждый вызов. Записанные примеры площадок не вызывают.
    """
    if settings.data_source == "live":
        return {
            "vk": VkAdapter(settings, client, budget),
            "ok": OkAdapter(settings, client, budget),
            "max": MaxAdapter(settings, client, budget),
        }
    store = FixtureStore.load(shift_to_now=settings.fixture_shift_to_now)
    failures = parse_failures(settings.fixture_failures)
    delay = settings.fixture_step_delay_ms / 1000
    return {
        platform: FixtureAdapter(
            platform, store, failure=failures.get(platform), step_delay_sec=delay
        )
        for platform in PLATFORM_ORDER
    }


__all__ = ["AdapterRegistry", "FixtureAdapter", "FixtureStore", "PlatformAdapter", "build_adapters"]
