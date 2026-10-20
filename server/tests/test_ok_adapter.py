"""Адаптер Одноклассников на сохранённых страницах ok.ru (без сети).

Образцы в `tests/ok_pages/` — настоящие страницы ok.ru от 20.10.2026 (около 10:05 UTC):
- `group_avangard.html` — шапка и лента группы «Авангард-online» (правая колонка с участниками
  убрана: личные данные);
- `topic_avangard.html` — страница поста той же группы (скрипты, кроме JSON-LD, убраны).
Пустая и закрытая группа, капча — производные от настоящей страницы или короткие
искусственные страницы: живых образцов у команды нет (помечено в тестах).
"""

from __future__ import annotations

import asyncio
import itertools
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from mediamonitor.adapters import AdapterRegistry, FixtureAdapter, build_adapters
from mediamonitor.adapters.base import (
    AdapterError,
    AdapterEvent,
    AdapterQuery,
    Capped,
    Partial,
    Posts,
    Progress,
    RawPost,
    SourceInfo,
)
from mediamonitor.adapters.ok_live import (
    OkAdapter,
    OkGroup,
    is_captcha,
    load_catalog_groups,
    parse_feed_time,
    parse_group_page,
    parse_topic_page,
)
from mediamonitor.main import create_app
from mediamonitor.normalize.urls import PostRef
from mediamonitor.settings import Settings
from tests.conftest import fixture_store, make_settings, new_workspace, open_client, read_stream

PAGES = Path(__file__).parent / "ok_pages"
GROUP = (PAGES / "group_avangard.html").read_text("utf-8")
TOPIC = (PAGES / "topic_avangard.html").read_text("utf-8")
GID = "56158715707477"
SAMPLE_TOPIC = "158542578844501"
NOW = datetime(2026, 10, 20, 10, 5, tzinfo=UTC)
AVANGARD = OkGroup(
    name="Авангард",
    gid=GID,
    slug=None,
    district="Козульский муниципальный округ",
    subscribers=2114,
    in_catalog=True,
    regional=True,
)
# Без ленты: шапка настоящей страницы (пустая группа) и она же с отметкой «закрытая».
HEADER = GROUP.split('<div class="feed-w"')[0] + "</body></html>"
CLOSED = HEADER.replace("</body>", "<div class='group-closed'>Это закрытая группа</div></body>")
# Искусственная страница проверки «я не робот»: настоящей у команды нет.
CAPTCHA = (
    "<html><head><title>OK</title></head><body><form action='/dk' method='post'>"
    "<p>Подтвердите, что вы не робот</p><img src='/captcha?id=1'>"
    "<input name='st.ccode'></form></body></html>"
)


def topic_page(topic_id: str) -> str:
    """Страница поста: настоящая, а для других топиков — с подменённым номером."""
    return TOPIC.replace(SAMPLE_TOPIC, topic_id)


class Ok:
    """ok.ru на сохранённых страницах: путь → (код, страница); считает запросы."""

    def __init__(self) -> None:
        self.pages: dict[str, tuple[int, str]] = {f"/group/{GID}": (200, GROUP)}
        self.requests: list[httpx.Request] = []
        self.fail: Callable[[httpx.Request], None] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail is not None:
            self.fail(request)
        path = request.url.path
        if path in self.pages:
            status, body = self.pages[path]
            return httpx.Response(status, text=body)
        topic = re.fullmatch(r"/group/(\d+)/topic/(\d+)", path)
        if topic:
            page = topic_page(topic.group(2)).replace(GID, topic.group(1))
            return httpx.Response(200, text=page)
        return httpx.Response(404, text="<html><body>Страница не найдена</body></html>")


def make_adapter(
    tmp_path: Path, ok: Ok, groups: list[OkGroup] | None = None, **kwargs: object
) -> OkAdapter:
    settings: Settings = make_settings(tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(ok.handler))
    return OkAdapter(
        settings,
        client,
        groups=[AVANGARD] if groups is None else groups,
        min_interval_sec=0.0,
        now=lambda: NOW,
        **kwargs,  # type: ignore[arg-type]
    )


def query(sources: list[SourceInfo] | None = None) -> AdapterQuery:
    return AdapterQuery(
        text="",
        kind="topic",
        start=datetime(2026, 10, 19, tzinfo=UTC),
        end=NOW,
        sources=sources,
    )


async def collect(adapter: OkAdapter, q: AdapterQuery) -> list[AdapterEvent]:
    return [event async for event in adapter.search(q)]


def posts_of(events: list[AdapterEvent]) -> list[RawPost]:
    return [post for event in events if isinstance(event, Posts) for post in event.posts]


# ---------------------------------------------------------------- каталог и разбор


def test_catalog_has_only_groups() -> None:
    groups = load_catalog_groups()
    assert len(groups) == 38  # 47 ссылок OK в каталоге, 9 из них — личные профили
    assert all(g.gid or g.slug for g in groups)
    assert all(g.in_catalog and g.regional for g in groups)
    assert not any(g.slug and g.slug.startswith("profile") for g in groups)
    assert len({g.key for g in groups}) == len(groups)


def test_group_feed_is_parsed() -> None:
    page = parse_group_page(GROUP, NOW)
    assert (page.gid, page.name, page.members, page.closed) == (GID, "Авангард-online", 2391, False)
    assert len(page.posts) == 10
    first = page.posts[0]
    assert first.topic_id == "158544454419285"
    assert first.shown_at == datetime(2026, 10, 20, 6, 41, tzinfo=UTC)  # «09:41» по Москве
    assert first.precision == "minute"
    assert first.snippet.startswith("20 ОКТЯБРЯ - ДЕНЬ ВОЕННОГО СВЯЗИСТА")
    sample = next(p for p in page.posts if p.topic_id == SAMPLE_TOPIC)
    assert sample.reactions == 18
    assert sample.has_media
    assert page.posts[-2].precision == "day"  # «18 окт» — время не показано


def test_topic_page_is_parsed() -> None:
    topic = parse_topic_page(TOPIC)
    assert (topic.owner_id, topic.topic_id) == (GID, SAMPLE_TOPIC)
    assert topic.published_at == datetime(2026, 10, 19, 4, 17, 36, tzinfo=UTC)
    assert "Шадрин" in topic.text
    assert len(topic.text) > 200
    assert topic.author_name == "Авангард-online"


@pytest.mark.parametrize(
    ("shown", "expected", "precision"),
    [
        ("10:31", datetime(2026, 10, 20, 7, 31, tzinfo=UTC), "minute"),
        ("вчера 07:30", datetime(2026, 10, 19, 4, 30, tzinfo=UTC), "minute"),
        ("18 окт", datetime(2026, 10, 17, 21, 0, tzinfo=UTC), "day"),
        ("3 мар 2025", datetime(2025, 3, 2, 21, 0, tzinfo=UTC), "day"),
        ("28 дек", datetime(2025, 12, 27, 21, 0, tzinfo=UTC), "day"),
        ("недавно", None, "day"),
    ],
)
def test_feed_time(shown: str, expected: datetime | None, precision: str) -> None:
    assert parse_feed_time(shown, NOW) == (expected, precision)


# ---------------------------------------------------------------- поиск


async def test_search_reads_feed_and_post_pages(tmp_path: Path) -> None:
    ok = Ok()
    adapter = make_adapter(tmp_path, ok)
    events = await collect(adapter, query())
    posts = posts_of(events)
    # В периоде с 19.10 — 8 постов ленты; «18 окт» и «17 окт» — раньше.
    assert len(posts) == 8
    assert all(p.time_reliability == "exact" for p in posts)
    assert all(p.ref.url.startswith(f"https://ok.ru/group/{GID}/topic/") for p in posts)
    assert all(p.views is None for p in posts)  # просмотров постов OK без входа не показывает
    sample = next(p for p in posts if p.ref.post_id == SAMPLE_TOPIC)
    assert sample.reactions == 18
    assert sample.text is not None
    assert "Шадрин" in sample.text
    assert sample.source.subscribers == 2391
    assert sample.source.in_catalog
    assert sample.source.district == "Козульский муниципальный округ"
    progress = [e for e in events if isinstance(e, Progress)]
    assert progress[0].current_source == "Авангард"
    assert progress[-1].done == progress[-1].total == 1
    assert not [e for e in events if isinstance(e, Partial | Capped)]
    # Ни одного запроса в закрытые robots.txt разделы.
    assert all("/dk" not in r.url.path and "/search" not in r.url.path for r in ok.requests)
    assert all(r.headers["user-agent"].startswith("MediaMonitor/") for r in ok.requests)
    assert len(ok.requests) == 1 + 8


async def test_post_pages_limit_falls_back_to_feed(tmp_path: Path) -> None:
    ok = Ok()
    adapter = make_adapter(tmp_path, ok, topic_pages_per_search=2)
    posts = posts_of(await collect(adapter, query()))
    assert len(posts) == 8
    exact = [p for p in posts if p.time_reliability == "exact"]
    approx = [p for p in posts if p.time_reliability == "approximate"]
    assert (len(exact), len(approx)) == (2, 6)
    assert approx[0].text
    assert not approx[0].text.endswith("...")
    assert len(ok.requests) == 1 + 2


async def test_cache_saves_requests(tmp_path: Path) -> None:
    ok = Ok()
    adapter = make_adapter(tmp_path, ok)
    first = posts_of(await collect(adapter, query()))
    count = len(ok.requests)
    second = posts_of(await collect(adapter, query()))
    assert [p.ref for p in second] == [p.ref for p in first]
    assert len(ok.requests) == count  # лента и посты — из кэша (Р7)
    post = await adapter.fetch_post(PostRef("ok", GID, SAMPLE_TOPIC))
    assert post is not None
    assert post.reactions == 18
    assert len(ok.requests) == count


async def test_period_deeper_than_feed_is_capped(tmp_path: Path) -> None:
    ok = Ok()
    adapter = make_adapter(tmp_path, ok)
    q = query()
    q = AdapterQuery(q.text, q.kind, datetime(2026, 10, 1, tzinfo=UTC), q.end, None)
    events = await collect(adapter, q)
    capped = [e for e in events if isinstance(e, Capped)]
    assert len(capped) == 1
    assert "10 последних постов" in capped[0].note


async def test_my_sources_closed_missing_and_other_platforms(tmp_path: Path) -> None:
    ok = Ok()
    ok.pages["/group/111"] = (200, CLOSED.replace(GID, "111"))
    adapter = make_adapter(tmp_path, ok, groups=[])
    sources = [
        SourceInfo("ok", GID, None, "Авангард", f"https://ok.ru/group/{GID}", None),
        SourceInfo("ok", "111", None, "Закрытая", "https://ok.ru/group/111", None),
        SourceInfo("ok", "222", None, "Удалённая", "https://ok.ru/group/222", None),
        SourceInfo("vk", "-1", "club1", "Группа VK", "https://vk.com/club1", None),
    ]
    events = await collect(adapter, query(sources))
    assert len(posts_of(events)) == 8
    partial = [e for e in events if isinstance(e, Partial)]
    assert len(partial) == 1
    assert partial[0].code == "sources-closed"
    assert "«Закрытая»" in partial[0].message
    assert "«Удалённая»" in partial[0].message
    assert all(r.url.host == "ok.ru" for r in ok.requests)


async def test_empty_group(tmp_path: Path) -> None:
    ok = Ok()
    ok.pages[f"/group/{GID}"] = (200, HEADER)
    adapter = make_adapter(tmp_path, ok)
    events = await collect(adapter, query())
    assert posts_of(events) == []
    assert not [e for e in events if isinstance(e, Partial)]
    assert (await adapter.probe_source(f"https://ok.ru/group/{GID}")).state == "ok"


async def test_closed_group_probe(tmp_path: Path) -> None:
    ok = Ok()
    ok.pages[f"/group/{GID}"] = (200, CLOSED)
    adapter = make_adapter(tmp_path, ok)
    probe = await adapter.probe_source(f"https://ok.ru/group/{GID}")
    assert probe.state == "closed"
    assert probe.source is not None
    assert probe.source.closed


async def test_probe_links(tmp_path: Path) -> None:
    ok = Ok()
    ok.pages["/avangardonline"] = (200, GROUP)
    adapter = make_adapter(tmp_path, ok)
    probe = await adapter.probe_source("https://ok.ru/avangardonline/")
    assert probe.state == "ok"
    assert probe.source is not None
    assert (probe.source.owner_id, probe.source.name) == (GID, "Авангард-online")
    assert (await adapter.probe_source("https://ok.ru/profile/583268521789")).state == (
        "not-supported"
    )
    post = await adapter.probe_source(f"https://ok.ru/group/{GID}/topic/{SAMPLE_TOPIC}")
    assert post.state == "post-link"
    assert (await adapter.probe_source("https://ok.ru/nosuchgroup")).state == "not-found"
    assert len(ok.requests) == 2


async def test_deleted_post_is_none(tmp_path: Path) -> None:
    ok = Ok()
    ok.pages[f"/group/{GID}/topic/1"] = (404, "<html><body>Не найдено</body></html>")
    adapter = make_adapter(tmp_path, ok)
    assert await adapter.fetch_post(PostRef("ok", GID, "1")) is None
    post = await adapter.fetch_post(PostRef("ok", GID, SAMPLE_TOPIC))
    assert post is not None
    assert post.time_reliability == "exact"
    assert post.ref.url == f"https://ok.ru/group/{GID}/topic/{SAMPLE_TOPIC}"


async def test_captcha_makes_ok_unavailable_and_pauses(tmp_path: Path) -> None:
    ok = Ok()
    ok.pages[f"/group/{GID}"] = (200, CAPTCHA)
    adapter = make_adapter(tmp_path, ok)
    with pytest.raises(AdapterError) as error:
        await collect(adapter, query())
    assert error.value.code == "unavailable"
    assert error.value.retryable
    count = len(ok.requests)
    # Пауза: капчу не обходим и ok.ru не трогаем.
    with pytest.raises(AdapterError):
        await adapter.fetch_post(PostRef("ok", GID, SAMPLE_TOPIC))
    assert len(ok.requests) == count
    assert (await adapter.health()).state == "down"


def test_captcha_markers() -> None:
    assert is_captcha(CAPTCHA)
    assert not is_captcha(GROUP)
    assert not is_captcha(TOPIC)
    # Слова из текста поста — не капча.
    assert not is_captcha(GROUP.replace("ПОГОДА В КОЗУЛЬКЕ", "Подтвердите, что вы не робот"))


async def test_too_many_requests(tmp_path: Path) -> None:
    ok = Ok()
    ok.pages[f"/group/{GID}"] = (429, "")
    adapter = make_adapter(tmp_path, ok)
    with pytest.raises(AdapterError) as error:
        await collect(adapter, query())
    assert error.value.code == "rate-limited"


async def test_network_error_and_timeout(tmp_path: Path) -> None:
    ok = Ok()

    def offline(request: httpx.Request) -> None:
        raise httpx.ConnectError("нет сети", request=request)

    ok.fail = offline
    adapter = make_adapter(tmp_path, ok)
    with pytest.raises(AdapterError) as error:
        await collect(adapter, query())
    assert (error.value.code, error.value.retryable) == ("unavailable", True)
    assert (await adapter.health()).state == "degraded"

    def slow(request: httpx.Request) -> None:
        raise httpx.ReadTimeout("долго", request=request)

    ok.fail = slow
    with pytest.raises(AdapterError) as error:
        await adapter.fetch_post(PostRef("ok", GID, SAMPLE_TOPIC))
    assert error.value.code == "timeout"


async def test_changed_format_is_an_error_not_empty(tmp_path: Path) -> None:
    ok = Ok()
    ok.pages[f"/group/{GID}"] = (200, GROUP.replace('class="feed-w"', 'class="feed-x"'))
    adapter = make_adapter(tmp_path, ok)
    with pytest.raises(AdapterError) as error:
        await collect(adapter, query())
    assert error.value.code == "bad-response"
    ok.pages[f"/group/{GID}/topic/5"] = (200, "<html><body>что-то другое</body></html>")
    with pytest.raises(AdapterError) as error:
        await adapter.fetch_post(PostRef("ok", GID, "5"))
    assert error.value.code == "bad-response"


async def test_one_request_per_interval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Запросы идут не чаще одного в интервал, даже если их просят одновременно."""
    ok = Ok()
    clock = [0.0]
    stamps: list[float] = []

    async def sleep(delay: float) -> None:
        clock[0] += delay  # часы адаптера идут ровно на паузу троттлинга

    def stamp(_: httpx.Request) -> None:
        stamps.append(clock[0])

    monkeypatch.setattr("mediamonitor.adapters.ok_live.asyncio.sleep", sleep)
    ok.fail = stamp
    settings = make_settings(tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(ok.handler))
    adapter = OkAdapter(
        settings, client, groups=[AVANGARD], min_interval_sec=1.1, clock=lambda: clock[0]
    )
    refs = [PostRef("ok", GID, str(n)) for n in (11, 12, 13)]
    await asyncio.gather(*(adapter.fetch_post(ref) for ref in refs))
    assert stamps == pytest.approx([0.0, 1.1, 2.2])
    assert all(b - a >= 1.1 - 1e-9 for a, b in itertools.pairwise(stamps))


async def test_post_pages_are_shared_between_groups(tmp_path: Path) -> None:
    """Время на страницы постов делится между группами, а не уходит на первую."""
    ok = Ok()
    clock = [0.0]

    def tick(_: httpx.Request) -> None:
        clock[0] += 1.0  # каждый запрос к ok.ru — секунда

    ok.fail = tick
    gids = [GID, "56158715707478", "56158715707479"]
    for gid in gids[1:]:
        ok.pages[f"/group/{gid}"] = (200, GROUP.replace(GID, gid))
    groups = [OkGroup(name=f"Группа {n}", gid=gid, slug=None) for n, gid in enumerate(gids)]
    settings = make_settings(tmp_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(ok.handler))
    adapter = OkAdapter(
        settings,
        client,
        groups=groups,
        min_interval_sec=1.0,
        search_budget_sec=14.0,
        clock=lambda: clock[0],
        now=lambda: NOW,
    )
    posts = posts_of(await collect(adapter, query()))
    exact = dict.fromkeys(gids, 0)
    for post in posts:
        if post.time_reliability == "exact":
            exact[post.ref.owner_id] += 1
    assert len(posts) == 24
    assert exact == {gids[0]: 3, gids[1]: 4, gids[2]: 4}
    assert clock[0] <= 14.0


def test_registry_uses_live_ok(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, data_source="live")
    adapters = build_adapters(settings, httpx.AsyncClient())
    assert isinstance(adapters["ok"], OkAdapter)


async def test_search_through_api_with_live_ok(tmp_path: Path) -> None:
    """Сквозной поиск: настоящий адаптер OK на сохранённых страницах → подборка."""
    ok = Ok()
    settings = make_settings(tmp_path, data_source="live")

    def adapters(s: Settings, _: httpx.AsyncClient) -> AdapterRegistry:
        client = httpx.AsyncClient(transport=httpx.MockTransport(ok.handler))
        return {
            "vk": FixtureAdapter("vk", fixture_store()),
            "ok": OkAdapter(s, client, groups=[AVANGARD], min_interval_sec=0.0),
            "max": FixtureAdapter("max", fixture_store()),
        }

    app = create_app(settings, adapter_factory=adapters)
    async with open_client(app) as client:
        headers = await new_workspace(client)
        today = datetime.now(UTC).date()
        body = {
            "text": "День отца в Шадрино",
            "period": {"preset": "custom", "from": "2026-10-19", "to": today.isoformat()},
            "mode": "everywhere",
            "platforms": ["ok"],
        }
        response = await client.post("/api/searches", json=body, headers=headers)
        assert response.status_code == 202, response.text
        events = await read_stream(client, headers, response.json()["searchId"])
    selection = events[-1]["data"]["selection"]
    status = next(s for s in selection["statuses"] if s["platform"] == "ok")
    assert status["state"] in ("found", "partial"), status
    urls = [i["publication"]["url"] for i in selection["items"]]
    assert f"https://ok.ru/group/{GID}/topic/{SAMPLE_TOPIC}" in urls
