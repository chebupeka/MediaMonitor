"""Сайты СМИ и Дзен (ТЗ-Ф17, вариант Б разведки): разбор, вежливость, сбои, поиск целиком.

Сайты края из-за рубежа не открываются, поэтому всё — на записанных образцах ответов
(`mediamonitor/fixtures/sources`, разметка как в живых ответах 20.10.2026) и на подменённом
транспорте httpx. Живые сайты проверяет лид на стенде после выкатки.
"""

from __future__ import annotations

import asyncio
import io
import itertools
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from openpyxl import load_workbook

from mediamonitor.adapters import AdapterRegistry, FixtureAdapter, media_adapters
from mediamonitor.adapters.base import (
    AdapterError,
    AdapterEvent,
    AdapterQuery,
    Partial,
    Posts,
    Progress,
    RawPost,
    SourceInfo,
)
from mediamonitor.adapters.dzen import DzenAdapter, DzenConfig, parse_publication_page
from mediamonitor.adapters.replay import replay_catalog, replay_response, sample
from mediamonitor.adapters.site_parse import (
    ParseError,
    html_to_text,
    parse_article,
    parse_cards,
    parse_feed,
    parse_ru_date,
    search_found,
)
from mediamonitor.adapters.sites import SitesAdapter, SitesConfig, search_phrase
from mediamonitor.adapters.web import HostLimiter, PoliteFetcher, TtlCache, user_agent
from mediamonitor.ai.judge import NullJudge
from mediamonitor.contract import REQUIRED_PLATFORMS
from mediamonitor.main import create_app
from mediamonitor.media import load_media_catalog
from mediamonitor.normalize.urls import (
    is_safe_post_url,
    parse_address,
    parse_post_url,
    post_url,
    source_url,
)
from mediamonitor.settings import Settings
from mediamonitor.timeutil import day_end, day_start, iso
from tests.conftest import fixture_store, make_settings, new_workspace, open_client, run_search
from tests.contract.test_contract_schema import assert_contract

NOW = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)  # 20.10.2026 10:00 по Красноярску
RELEASE = (
    "Эскроу-счёт поможет воплотить мечту о своём доме\n"
    "Жители Красноярского края могут построить частный дом с использованием эскроу-счёта. "
    "Деньги на счёте хранятся в банке и переходят к подрядчику только после того, как дом "
    "построен и принят. Так семья защищена от недобросовестных строителей."
)
VTRUDA_PUBLISHER = "647edcf397f79c2656d02daf"
ANGARKA_PUBLISHER = "611c742476e1862f7f85ab3a"


def query(
    text: str = "медведи",
    *,
    start: date = date(2026, 10, 1),
    end: date = date(2026, 10, 20),
    kind: Any = "topic",
    sources: list[SourceInfo] | None = None,
) -> AdapterQuery:
    return AdapterQuery(
        text=text, kind=kind, start=day_start(start), end=day_end(end), sources=sources
    )


Handler = Callable[[httpx.Request], httpx.Response]


def fetcher(
    handler: Handler | None = None, *, interval: float = 0.0, per_ip: int = 4, cache: float = 600
) -> PoliteFetcher:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler or (lambda r: replay_response(str(r.url)))),
        headers={"User-Agent": user_agent("0.1.0", "https://monitor.example/app/")},
    )
    return PoliteFetcher(
        client, HostLimiter(interval, per_ip), TtlCache(cache), timeout=5, max_bytes=2_000_000
    )


def sites(handler: Handler | None = None, **config: Any) -> SitesAdapter:
    catalog = replay_catalog(load_media_catalog())
    return SitesAdapter(catalog, fetcher(handler), SitesConfig(**config), now=lambda: NOW)


def dzen(handler: Handler | None = None, **config: Any) -> DzenAdapter:
    catalog = replay_catalog(load_media_catalog())
    return DzenAdapter(catalog, fetcher(handler), DzenConfig(**config), now=lambda: NOW)


async def collect(events: Any) -> tuple[list[RawPost], list[AdapterEvent]]:
    posts: list[RawPost] = []
    rest: list[AdapterEvent] = []
    async for event in events:
        if isinstance(event, Posts):
            posts.extend(event.posts)
        else:
            rest.append(event)
    return posts, rest


# ---------------------------------------------------------------- каталог СМИ края


def test_media_catalog_from_table() -> None:
    catalog = load_media_catalog()
    assert len(catalog.sites) == 48
    assert len(catalog.polled_sites) == 43
    off = {s.name: s.off_reason for s in catalog.sites if not s.polled}
    assert off == {
        "Ачинская газета": "сайт не открывается",
        "Маяк Севера": "сайт не открывается",
        "Наш Красноярский край": "пока не подключён: другой движок сайта",
        "Огни Енисея": "лента закрыта в robots.txt",
        "Сельский труженик": "сайт заброшен, последние новости — 2021 год",
    }
    modes = [s.mode for s in catalog.polled_sites]
    assert modes.count("rss") == 39
    assert modes.count("news-list") == 4
    note = catalog.sites_note()
    assert note.startswith("Подключено 43 сайта из 48.")
    assert "«Огни Енисея» — лента закрыта в robots.txt" in note
    # Защита «Енисея»: только лента, без поиска и проверки ссылок.
    enisey = catalog.site_by_owner("enisey.tv")
    assert enisey is not None
    assert enisey.search_url is None
    assert not enisey.article_check
    assert enisey.link_host == "www.enisey.tv"
    # Каналы Дзена: 25 пишут, 3 давно молчат, 1 не найден.
    states = [c.state for c in catalog.channels]
    assert states.count("ok") == 25
    assert states.count("inactive") == 3
    assert catalog.channel(None, "vtruda") is catalog.channel(VTRUDA_PUBLISHER)


def test_catalog_json_has_only_communities_groups_and_channels() -> None:
    import json
    from importlib import resources

    raw = json.loads(
        resources.files("mediamonitor.data").joinpath("catalog.json").read_text("utf-8")
    )
    entries = raw["sources"]
    by_platform = {p: [e for e in entries if e["platform"] == p] for p in ("vk", "ok", "max")}
    assert {p: len(v) for p, v in by_platform.items()} == {"vk": 45, "ok": 38, "max": 45}
    ids = {(e["platform"], e["ownerId"]) for e in entries}
    # Личные страницы VK, профили OK и приглашения MAX не переносим (catalog-issues.md).
    assert ("vk", "id586913986") not in ids
    assert ("vk", "586913986") not in ids
    assert not any("profile" in str(e) or "join" in str(e) for e in entries)
    assert ("vk", "-184237411") in ids  # public184237411 → числовой id сообщества
    assert all(e["type"] == "media" for e in entries)


# ---------------------------------------------------------------- адреса и ключи (НТ-13)


def test_site_and_dzen_addresses() -> None:
    article = parse_address("https://www.vtruda.ru/news/batka-ataman/?sphrase_id=4885")
    assert article is not None
    assert article.post is not None
    assert article.post.id == "site:vtruda.ru_news/batka-ataman/"
    # Без «/» на конце и с кириллическим доменом — тот же ключ.
    same = parse_post_url("https://vtruda.ru/news/batka-ataman")
    assert same == article.post
    rabochiy = parse_post_url("https://газетарабочий.рф/news/x-y/")
    assert rabochiy is not None
    assert rabochiy.owner_id == "xn--80aaaegnnmj2ctw4e.xn--p1ai"
    assert post_url(rabochiy) == "https://газетарабочий.рф/news/x-y/"
    assert is_safe_post_url(post_url(article.post))
    home = parse_address("газетарабочий.рф")
    assert home is not None
    assert home.kind == "group"
    assert home.platform == "site"
    assert source_url("site", "enisey.tv", None) == "https://www.enisey.tv/"
    # Сайт не из каталога края — не поддерживается; путь с «..» — не ключ.
    assert parse_address("https://example.ru/news/x/") is None
    assert parse_post_url("https://vtruda.ru/news/../admin/") is None

    channel = parse_address("https://zen.yandex.ru/vtruda?share_to=link")
    assert channel is not None
    assert channel.platform == "dzen"
    assert channel.slug == "vtruda"
    by_id = parse_address(f"https://dzen.ru/id/{ANGARKA_PUBLISHER}")
    assert by_id is not None
    assert by_id.owner_id == ANGARKA_PUBLISHER
    editor = parse_address(f"https://dzen.ru/profile/editor/id/{ANGARKA_PUBLISHER}/publications")
    assert editor is not None
    assert editor.owner_id == ANGARKA_PUBLISHER
    post = parse_post_url("https://dzen.ru/a/atcLQPnEs1M6TU2d?from=channel")
    assert post is not None
    assert post.post_id == "a-atcLQPnEs1M6TU2d"
    assert post.owner_id == ""
    assert post_url(post) == "https://dzen.ru/a/atcLQPnEs1M6TU2d"
    assert parse_address("https://dzen.ru/search?query=x") is None
    assert source_url("ok", "achgzt24", "achgzt24") == "https://ok.ru/achgzt24"


# ---------------------------------------------------------------- разбор ответов


def test_parse_bitrix_feed_article_and_cards() -> None:
    items = parse_feed(sample("vtruda-rss.xml"))
    assert len(items) == 5
    first = items[0]
    assert first.link == "https://vtruda.ru/news/medvedi-ne-ukhodyat/"
    assert first.full_text
    assert first.has_media
    assert first.published_at == datetime(2026, 10, 19, 6, 59, 24, tzinfo=UTC)
    assert "<" not in first.text
    assert "охотнадзор" in first.text
    article = parse_article(sample("vtruda-article-medvedi.html").decode(), NOW)
    assert article.title == "Медведи не уходят"
    assert article.views == 52
    assert article.exact_time
    assert article.published_at == datetime(2026, 10, 19, 6, 59, 24, tzinfo=UTC)
    assert article.text.startswith("С августа")
    assert "Поделиться" not in article.text
    found = parse_cards(sample("vtruda-search.html").decode(), NOW)
    assert [c.href.split("?")[0] for c in found][:2] == [
        "/news/medvedi-ne-ukhodyat/",
        "/news/medved-za-okolitsey/",
    ]
    assert found[1].title == "Медведь за околицей"
    assert found[1].date is not None
    assert not found[1].date.exact
    assert search_found(sample("vtruda-search.html").decode()) == 4
    listed = parse_cards(sample("angarka-news.html").decode(), NOW)
    assert len(listed) == 4
    assert listed[0].date is not None
    assert listed[0].date.exact


def test_parse_double_escaped_feed_and_dates() -> None:
    items = parse_feed(sample("enisey-rss.xml"))
    assert len(items) == 3
    art = items[0]
    assert "<p>" not in art.text
    assert "&laquo;" not in art.text
    assert "«Рыбы Енисея»" in art.text
    assert "&hellip;" not in art.summary
    with pytest.raises(ParseError):
        parse_feed(b"<html><body>captcha</body></html>")
    with pytest.raises(ParseError):
        parse_feed(b"not xml at all")
    assert html_to_text("По­-своему <b>прекрасны</b><br>октября") == "По-своему прекрасны\nоктября"

    def at(value: str) -> str | None:
        parsed = parse_ru_date(value, NOW)
        return iso(parsed.moment) if parsed else None

    assert at("19.10.2026 13:59:24") == "2026-10-19T13:59:24+07:00"
    assert at("20 октября 2026 09:48") == "2026-10-20T09:48:00+07:00"
    assert at("вчера, 12:09") == "2026-10-19T12:09:00+07:00"
    assert at("15.10.2026") == "2026-10-15T00:00:00+07:00"
    assert at("19 дек") == "2025-12-19T00:00:00+07:00"  # без года — прошлый декабрь
    assert at("без даты") is None


def test_parse_dzen_publication_page() -> None:
    page = parse_publication_page(sample("dzen-article-medvedi.html").decode())
    assert page.publisher_id == VTRUDA_PUBLISHER
    assert page.publisher_name == "О Сибири с любовью!"
    assert page.title == "Медведи: карантин и новые меры"
    assert page.views == 46
    assert page.text.startswith("В Минусинском округе")
    assert "\n" in page.text


def test_search_phrase() -> None:
    assert search_phrase("медведи в Красноярском крае", "topic") == "медведи"
    # Буква «ё» приводится к «е» — поиск сайтов понимает обе.
    assert search_phrase(RELEASE, "news-text") == "эскроу счет поможет воплотить мечту"


# ---------------------------------------------------------------- сайты: поиск


async def test_sites_search_on_recorded_samples() -> None:
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return replay_response(str(request.url))

    adapter = sites(handler)
    posts, events = await collect(adapter.search(query()))
    by_id = {p.ref.id: p for p in posts}
    # Лента, раздел новостей (без RSS), добор поиском по сайту и «Енисей» (своя лента).
    assert "site:vtruda.ru_news/medvedi-ne-ukhodyat/" in by_id
    assert "site:angarka.info_news/eskrou-schyet-pomozhet-voplotit-mechtu-o-svoyem-dome/" in by_id
    assert "site:enisey.tv_news/post-96801/" in by_id
    okolitsa = by_id["site:vtruda.ru_news/medved-za-okolitsey/"]
    assert okolitsa.views == 120
    assert okolitsa.time_reliability == "exact"
    dachi = by_id["site:vtruda.ru_news/medved-vyshel-k-dacham/"]
    assert dachi.time_reliability == "approximate"
    assert dachi.views is None
    assert "site:vtruda.ru_news/kak-vesti-sebya-pri-vstreche-s-medvedem/" not in by_id  # август
    assert all(p.source.regional and p.source.type == "media" for p in posts)
    assert by_id["site:vtruda.ru_news/medvedi-ne-ukhodyat/"].source.name == "Власть труда"
    progress = [e for e in events if isinstance(e, Progress)]
    assert progress[0] == Progress(0, 4, "sources")
    assert progress[-1].done == 4
    assert not [e for e in events if isinstance(e, Partial)]
    # Повтор с коротким периодом: ленты и разделы — из кэша ответов (Р7: только экономия),
    # поиск по сайту не нужен — лента покрывает период.
    first = list(asked)
    short, _ = await collect(adapter.search(query(start=date(2026, 10, 18))))
    assert all(p.published_at and p.published_at >= day_start(date(2026, 10, 18)) for p in short)
    again = asked[len(first) :]
    assert not [u for u in again if u.endswith(("/rss/", "/rss.xml", "/news/"))]
    assert not [u for u in again if "/search/" in u]
    await adapter.aclose()


async def test_sites_partial_and_error_are_honest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host in ("www.kvgazeta.ru", "angarka.info"):
            raise httpx.ConnectTimeout("geo filter", request=request)
        if request.url.host == "www.enisey.tv":
            return httpx.Response(307, headers={"location": "https://variti.example/check"})
        return replay_response(str(request.url))

    adapter = sites(handler)
    posts, events = await collect(adapter.search(query()))
    assert posts
    assert all(p.ref.owner_id == "vtruda.ru" for p in posts)
    partial = [e for e in events if isinstance(e, Partial)]
    assert len(partial) == 1
    assert partial[0].code == "unavailable"
    assert partial[0].retryable
    message = partial[0].message
    assert message.startswith("Не ответили 3 сайта из 4:")
    assert "«Енисей» — сайт переадресует на чужой адрес" in message
    assert "«Канские ведомости» — не ответил вовремя" in message
    health = await adapter.health()
    assert health.state == "degraded"
    assert "не ответили 3 сайта" in health.message

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("blocked", request=request)

    with pytest.raises(AdapterError) as error:
        await collect(sites(down).search(query()))
    assert error.value.code == "unavailable"
    assert error.value.retryable
    assert "Сайты СМИ не ответили" in error.value.message


async def test_sites_deadline_and_bad_markup() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.kvgazeta.ru":
            await asyncio.sleep(5)
        if request.url.host == "angarka.info" and request.url.path == "/news/":
            return httpx.Response(200, text="<html><body>Сайт на обслуживании</body></html>")
        return replay_response(str(request.url))

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    adapter = SitesAdapter(
        replay_catalog(load_media_catalog()),
        PoliteFetcher(client, HostLimiter(0, 4), TtlCache(0), timeout=10, max_bytes=10**6),
        SitesConfig(deadline_sec=0.5),
        now=lambda: NOW,
    )
    started = time.monotonic()
    _, events = await collect(adapter.search(query()))
    assert time.monotonic() - started < 3
    message = next(e for e in events if isinstance(e, Partial)).message
    assert "«Канские ведомости» — не успел ответить" in message
    assert "«Ангарская правда» — ответ не удалось разобрать" in message


async def test_sites_politeness_rate_and_user_agent() -> None:
    starts: dict[str, list[float]] = {}
    agents: set[str] = set()
    active = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        starts.setdefault(request.url.host.removeprefix("www."), []).append(time.monotonic())
        agents.add(request.headers["user-agent"])
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return replay_response(str(request.url))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": user_agent("0.1.0", "https://monitor.example/app/")},
    )
    adapter = SitesAdapter(
        replay_catalog(load_media_catalog()),
        PoliteFetcher(client, HostLimiter(0.15, 2), TtlCache(0), timeout=5, max_bytes=10**6),
        now=lambda: NOW,
    )
    await collect(adapter.search(query()))
    vtruda = starts["vtruda.ru"]
    assert len(vtruda) >= 3  # лента, поиск, страницы статей
    gaps = [b - a for a, b in itertools.pairwise(vtruda)]
    assert min(gaps) >= 0.12  # не чаще раза в интервал на сайт (с запасом на таймер Windows)
    assert peak <= 2 + 1  # 3 сайта платформы на одном адресе: не больше 2 сразу (+«Енисей»)
    assert agents == {
        "Mediaradar/0.1.0 (prototype media monitor for Krasnoyarsk Krai news; +https://monitor.example/)"
    }


async def test_sites_my_sources_fetch_and_probe() -> None:
    # Весь каталог края: опрашиваются только сайты из списка пользователя.
    adapter = SitesAdapter(load_media_catalog(), fetcher(), now=lambda: NOW)
    site = adapter.catalog.site_by_owner("vtruda.ru")
    assert site is not None
    vtruda = adapter.source_info(site)
    achinsk = load_media_catalog().site_by_owner("pv-press.ru")
    assert achinsk is not None
    posts, events = await collect(
        adapter.search(query(sources=[vtruda, adapter.source_info(achinsk)]))
    )
    assert {p.ref.owner_id for p in posts} == {vtruda.owner_id}
    partial = next(e for e in events if isinstance(e, Partial))
    assert partial.code == "sources-closed"
    assert "«Ачинская газета» — сайт не открывается" in partial.message
    ref = parse_post_url("https://vtruda.ru/news/medvedi-ne-ukhodyat/")
    assert ref is not None
    found = await adapter.fetch_post(ref)
    assert found is not None
    assert found.views == 52
    gone = parse_post_url("https://vtruda.ru/news/udalena/")
    assert gone is not None
    assert await adapter.fetch_post(gone) is None
    enisey = parse_post_url("https://www.enisey.tv/news/post-96801/")
    assert enisey is not None
    with pytest.raises(AdapterError, match="защитой от программ"):
        await adapter.fetch_post(enisey)
    assert (await adapter.probe_source("https://vtruda.ru/")).state == "ok"
    assert (await adapter.probe_source("https://example.ru/")).state == "not-supported"
    link = await adapter.probe_source("https://vtruda.ru/news/medvedi-ne-ukhodyat/")
    assert link.state == "post-link"
    assert link.source is not None


# ---------------------------------------------------------------- Дзен


async def test_dzen_channels_paging_and_skip() -> None:
    adapter = dzen()
    posts, events = await collect(adapter.search(query()))
    ids = {p.ref.id for p in posts}
    assert f"dzen:{VTRUDA_PUBLISHER}_a-aTdzMedvedi01aBc" in ids
    assert f"dzen:{VTRUDA_PUBLISHER}_b-bTdzPerehod01xYz" in ids  # короткий пост — весь текст
    assert f"dzen:{VTRUDA_PUBLISHER}_a-aTdzOldOne01ZzZz" in ids  # со второй страницы
    assert f"dzen:{VTRUDA_PUBLISHER}_a-aTdzOldTwo01YyYy" not in ids  # 28.09 — вне периода
    medvedi = next(p for p in posts if p.ref.post_id == "a-aTdzMedvedi01aBc")
    assert medvedi.views == 46
    assert medvedi.reactions == 1
    assert medvedi.title
    assert medvedi.source.subscribers == 2823
    assert medvedi.source.name == "Власть труда"
    brief = next(p for p in posts if p.ref.post_id.startswith("b-"))
    assert brief.title is None
    assert brief.text
    assert "светофоры" in brief.text
    assert not [e for e in events if isinstance(e, Partial)]
    # Неделя целиком на первой странице: листать не нужно.
    before = adapter.fetcher.requests
    await collect(dzen().search(query(start=date(2026, 10, 14))))
    assert before == 3  # два канала и одна страница листания
    await adapter.aclose()


async def test_dzen_login_check_redirects_stay_on_dzen() -> None:
    hosts: list[str] = []
    cookies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        cookies.append(request.headers.get("cookie", ""))
        if "zen_sso_checked" not in request.headers.get("cookie", ""):
            return httpx.Response(
                302,
                headers=[
                    ("location", "https://sso.passport.yandex.ru/push?retpath=x"),
                    ("set-cookie", "zen_sso_checked=1; Domain=.dzen.ru; Path=/"),
                    ("set-cookie", "zen_vk_sso_checked=1; Domain=.dzen.ru; Path=/"),
                ],
            )
        return replay_response(str(request.url))

    adapter = dzen(handler)
    ref = parse_post_url("https://dzen.ru/a/aTdzMedvedi01aBc")
    assert ref is not None
    post = await adapter.fetch_post(ref)
    assert post is not None
    assert post.ref.owner_id == VTRUDA_PUBLISHER
    assert post.views == 46
    assert set(hosts) == {"dzen.ru"}  # на вход Яндекса и VK не ходим
    assert len(hosts) == 2
    assert "zen_sso_checked=1" in cookies[1]


async def test_dzen_format_change_is_an_error_not_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"something": "else"})

    with pytest.raises(AdapterError) as error:
        await collect(dzen(handler).search(query()))
    assert error.value.code == "bad-response"
    adapter = dzen()
    assert (await adapter.probe_source("https://dzen.ru/vtruda")).state == "ok"
    assert (await adapter.probe_source("https://dzen.ru/some_blogger")).state == "not-supported"
    gone = parse_post_url("https://dzen.ru/a/aTdzGoneGone0000")
    assert gone is not None
    assert await adapter.fetch_post(gone) is None


# ---------------------------------------------------------------- поиск целиком через сервер


def media_app(tmp_path: Path, **overrides: Any) -> FastAPI:
    values: dict[str, Any] = {"sites_source": "fixtures", "dzen_source": "fixtures", **overrides}
    settings = make_settings(tmp_path, **values)
    store = fixture_store()

    def adapter_factory(s: Settings, _: httpx.AsyncClient) -> AdapterRegistry:
        registry: AdapterRegistry = {p: FixtureAdapter(p, store) for p in REQUIRED_PLATFORMS}
        registry.update(media_adapters(s))
        return registry

    return create_app(
        settings,
        adapter_factory=adapter_factory,
        judge_factory=lambda s, _: NullJudge(s.llm_model_label),
    )


async def test_release_spread_over_sites_and_dzen(tmp_path: Path) -> None:
    async with open_client(media_app(tmp_path)) as client:
        headers = await new_workspace(client)
        start = (await client.get("/api/start", headers=headers)).json()
        assert_contract("StartState", start)
        platforms = {p["id"]: p for p in start["platforms"]}
        assert list(platforms) == ["vk", "ok", "max", "site", "dzen"]
        assert platforms["site"]["enabled"]
        assert not platforms["site"]["required"]
        assert platforms["site"]["note"].startswith("Подключено 4 сайта из 4")
        assert "серая зона" in platforms["dzen"]["note"]

        search_id, events = await run_search(client, headers, RELEASE)
        selection = events[-1]["data"]["selection"]
        assert_contract("Selection", selection)
        assert selection["conditions"]["platforms"] == ["vk", "ok", "max", "site", "dzen"]
        statuses = {s["platform"]: s for s in selection["statuses"]}
        assert statuses["site"]["state"] == "found"
        assert statuses["site"]["note"].startswith("Подключено")
        assert statuses["dzen"]["state"] == "found"
        assert "note" not in statuses["vk"]
        on_sites = [i for i in selection["items"] if i["publication"]["platform"] == "site"]
        hosts = {i["publication"]["key"]["ownerId"] for i in on_sites}
        assert {"vtruda.ru", "kvgazeta.ru", "angarka.info", "enisey.tv"} <= hosts
        assert selection["counts"]["byPlatform"]["site"] == len(on_sites)
        assert all(i["regionReason"]["regionalSource"] for i in on_sites)
        assert all(i["publication"]["url"].startswith("https://") for i in on_sites)

        group = next(g for g in selection["groups"] if g["countsByPlatform"]["site"] >= 3)
        spread = (
            await client.get(
                f"/api/searches/{search_id}/spread",
                params={"groupId": group["id"]},
                headers=headers,
            )
        ).json()
        assert_contract("SpreadReport", spread)
        assert spread["totals"]["byPlatform"]["site"] >= 3
        assert any(p["platform"] == "site" for p in spread["placements"])
        # Первоисточник среди найденного — самая ранняя копия (лента «Енисея», 10:05).
        assert spread["original"]["sourceName"] == "Енисей"

        response = await client.get(f"/api/searches/{search_id}/export.xlsx", headers=headers)
        assert response.status_code == 200
        sheet = load_workbook(io.BytesIO(response.content))["Публикации"]
        platforms_column = {row[1] for row in sheet.iter_rows(min_row=2, values_only=True)}
        assert "Сайт СМИ" in platforms_column
        summary = load_workbook(io.BytesIO(response.content))["Сводка"]
        texts = " ".join(str(c) for row in summary.iter_rows(values_only=True) for c in row)
        assert "Сайты СМИ: найдено" in texts
        assert "записанные образцы ответов" in texts

        stand = (await client.get("/api/stand")).json()
        assert [p["platform"] for p in stand["platforms"]] == ["vk", "ok", "max", "site", "dzen"]
        assert "http" not in str(stand)


async def test_site_sources_in_catalog_and_my_sources(tmp_path: Path) -> None:
    async with open_client(media_app(tmp_path)) as client:
        headers = await new_workspace(client)
        catalog = (await client.get("/api/catalog", headers=headers)).json()
        site_ids = {c["id"] for c in catalog if c["platform"] == "site"}
        assert site_ids == {
            "site:vtruda.ru",
            "site:kvgazeta.ru",
            "site:angarka.info",
            "site:enisey.tv",
        }
        assert {c["id"] for c in catalog if c["platform"] == "dzen"} == {
            f"dzen:{VTRUDA_PUBLISHER}",
            f"dzen:{ANGARKA_PUBLISHER}",
        }
        assert any(c["platform"] == "vk" and c["name"] == "Авангард" for c in catalog)
        check = (
            await client.post("/api/sources/check", json={"url": "www.vtruda.ru"}, headers=headers)
        ).json()
        assert check["state"] == "ok"
        assert "сайт СМИ" in check["message"]
        assert check["preview"]["url"] == "https://vtruda.ru/"
        foreign = (
            await client.post(
                "/api/sources/check", json={"url": "https://example.ru/"}, headers=headers
            )
        ).json()
        assert foreign["state"] == "not-supported"
        added = await client.post(
            "/api/sources", json={"url": "https://vtruda.ru/"}, headers=headers
        )
        assert added.status_code == 201, added.text
        _, events = await run_search(client, headers, "медведи", mode="my-sources")
        selection = events[-1]["data"]["selection"]
        statuses = {s["platform"]: s for s in selection["statuses"]}
        assert statuses["site"]["state"] == "found"
        assert statuses["vk"]["progress"]["total"] == 0  # в списке только сайт
        items = selection["items"]
        assert items
        assert all(i["publication"]["source"]["id"] == "site:vtruda.ru" for i in items)
        assert all(i["regionReason"]["inMySources"] for i in items)


async def test_add_dzen_post_by_link(tmp_path: Path) -> None:
    async with open_client(media_app(tmp_path)) as client:
        headers = await new_workspace(client)
        # Поиск только по VK: публикации Дзена в подборке нет, её добавляют по ссылке.
        search_id, _ = await run_search(client, headers, "медведи", platforms=["vk"])
        response = await client.post(
            f"/api/searches/{search_id}/items",
            json={"url": "https://dzen.ru/a/aTdzMedvedi01aBc?from=channel"},
            headers=headers,
        )
        assert response.status_code in (200, 201), response.text
        item = response.json()
        assert item["publication"]["id"] == f"dzen:{VTRUDA_PUBLISHER}_a-aTdzMedvedi01aBc"
        assert item["publication"]["url"] == "https://dzen.ru/a/aTdzMedvedi01aBc"


async def test_switches_turn_platforms_off(tmp_path: Path) -> None:
    app = media_app(tmp_path, dzen_source="off")
    async with open_client(app) as client:
        headers = await new_workspace(client)
        start = (await client.get("/api/start", headers=headers)).json()
        dzen_info = next(p for p in start["platforms"] if p["id"] == "dzen")
        assert dzen_info["enabled"] is False
        _, events = await run_search(client, headers, "медведи", platforms=["vk", "dzen", "site"])
        selection = events[-1]["data"]["selection"]
        assert selection["conditions"]["platforms"] == ["vk", "site"]
        assert {s["platform"] for s in selection["statuses"]} == {"vk", "site"}
