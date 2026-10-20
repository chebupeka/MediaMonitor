"""Адаптеры площадок: общий интерфейс, записанные примеры, VK, OK, MAX, сайты СМИ и Дзен."""

from __future__ import annotations

import httpx

from mediamonitor.adapters.base import CallMeter, CatalogProvider, PlatformAdapter
from mediamonitor.adapters.dzen import DzenAdapter, DzenConfig
from mediamonitor.adapters.fixture import (
    FixtureAdapter,
    FixtureStore,
    is_demo_post,
    parse_failures,
)
from mediamonitor.adapters.max_live import MaxAdapter
from mediamonitor.adapters.ok_live import OkAdapter
from mediamonitor.adapters.replay import replay_catalog, replay_transport
from mediamonitor.adapters.sites import SitesAdapter, SitesConfig
from mediamonitor.adapters.vk_live import PostCache, VkAdapter
from mediamonitor.adapters.web import HostLimiter, PoliteFetcher, TtlCache, user_agent
from mediamonitor.contract import PLATFORM_ORDER, REQUIRED_PLATFORMS, PlatformId
from mediamonitor.media import load_media_catalog
from mediamonitor.settings import Settings

AdapterRegistry = dict[PlatformId, PlatformAdapter]


def enabled_platforms(adapters: AdapterRegistry) -> list[PlatformId]:
    """Площадки этого сервера в обычном порядке: VK, OK, MAX, сайты СМИ, Дзен."""
    return [p for p in PLATFORM_ORDER if p in adapters]


def live_adapter(
    platform: PlatformId,
    settings: Settings,
    client: httpx.AsyncClient,
    budget: CallMeter | None,
    cache: PostCache | None,
) -> PlatformAdapter:
    """Настоящий адаптер обязательной площадки — по строке на площадку.

    VK — `vk_live.py` (VK API), OK — `ok_live.py` (публичные страницы групп),
    MAX — `max_live.py` (индекс MaxStat).
    """
    if platform == "vk":
        return VkAdapter(settings, client, budget, cache=cache)
    if platform == "ok":
        return OkAdapter(settings, client, budget)
    if platform == "max":
        return MaxAdapter(settings, client, budget)
    raise ValueError(f"нет настоящего адаптера для площадки {platform}")


def build_adapters(
    settings: Settings,
    client: httpx.AsyncClient,
    budget: CallMeter | None = None,
    cache: PostCache | None = None,
) -> AdapterRegistry:
    """Адаптеры по настройкам.

    VK, OK, MAX — по `DATA_SOURCE_<ПЛОЩАДКА>` (или общему `DATA_SOURCE`): fixtures — записанные
    примеры (их публикации помечаются `demo`), live — площадка.
    `budget` — суточный и месячный предел вызовов платных площадок (НТ-6): настоящие
    адаптеры списывают из него каждый вызов. `cache` — кэш публикаций в базе (Р7).
    Сайты СМИ и Дзен — по SITES_SOURCE и DZEN_SOURCE (от DATA_SOURCE не зависят).
    """
    registry: AdapterRegistry = {}
    store: FixtureStore | None = None
    failures = parse_failures(settings.fixture_failures)
    delay = settings.fixture_step_delay_ms / 1000
    for platform in REQUIRED_PLATFORMS:
        if settings.source_of(platform) == "live":
            registry[platform] = live_adapter(platform, settings, client, budget, cache)
            continue
        if store is None:
            store = FixtureStore.load(shift_to_now=settings.fixture_shift_to_now)
        registry[platform] = FixtureAdapter(
            platform, store, failure=failures.get(platform), step_delay_sec=delay
        )
    registry.update(media_adapters(settings))
    return registry


def _fetcher(settings: Settings, *, replay: bool) -> PoliteFetcher:
    agent = settings.sources_user_agent or user_agent(settings.app_version, settings.public_app_url)
    client = httpx.AsyncClient(
        transport=replay_transport() if replay else None,
        headers={"User-Agent": agent, "Accept-Language": "ru-RU,ru;q=0.9"},
        follow_redirects=False,
        timeout=settings.sources_request_timeout_sec,
        limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
    )
    limiter = HostLimiter(
        0.0 if replay else settings.sources_min_interval_sec, settings.sources_per_ip
    )
    return PoliteFetcher(
        client,
        limiter,
        TtlCache(settings.sources_cache_sec),
        timeout=settings.sources_request_timeout_sec,
        max_bytes=settings.sources_max_bytes,
    )


def media_adapters(settings: Settings) -> AdapterRegistry:
    """Сайты СМИ и Дзен из каталога края (`data/krai-media.json`)."""
    registry: AdapterRegistry = {}
    catalog = load_media_catalog()
    if settings.sites_source != "off":
        replay = settings.sites_source == "fixtures"
        registry["site"] = SitesAdapter(
            replay_catalog(catalog) if replay else catalog,
            _fetcher(settings, replay=replay),
            SitesConfig(
                deadline_sec=settings.sites_deadline_sec,
                articles_per_site=settings.sites_articles_per_site,
                max_articles=settings.sites_max_articles,
            ),
            via=(
                "Записанные образцы ответов сайтов СМИ (не живые данные)"
                if replay
                else "Ленты RSS, разделы новостей и поиск на сайтах СМИ края"
            ),
        )
    if settings.dzen_source != "off":
        replay = settings.dzen_source == "fixtures"
        registry["dzen"] = DzenAdapter(
            replay_catalog(catalog) if replay else catalog,
            _fetcher(settings, replay=replay),
            DzenConfig(deadline_sec=settings.dzen_deadline_sec, max_pages=settings.dzen_max_pages),
            via=(
                "Записанные образцы ответов Дзена (не живые данные)"
                if replay
                else "Страницы каналов редакций края на Дзене"
            ),
        )
    return registry


def demo_platforms(adapters: AdapterRegistry) -> list[PlatformId]:
    """Площадки, которые сейчас отвечают записанными примерами."""
    return [p for p in PLATFORM_ORDER if isinstance(adapters.get(p), FixtureAdapter)]


__all__ = [
    "AdapterRegistry",
    "CatalogProvider",
    "DzenAdapter",
    "FixtureAdapter",
    "FixtureStore",
    "PlatformAdapter",
    "SitesAdapter",
    "build_adapters",
    "demo_platforms",
    "enabled_platforms",
    "is_demo_post",
    "live_adapter",
    "media_adapters",
]
