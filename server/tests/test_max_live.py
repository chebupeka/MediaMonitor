"""Настоящий MAX через индекс MaxStat (`adapters/max_live.py`) на записанных ответах API.

Ответы повторяют форму живой пробы 20.10.2026 (поля, типы, формат ссылок и времени),
тексты и каналы — вымышленные. Сеть не нужна: запросы принимает `httpx.MockTransport`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from mediamonitor.adapters import FixtureAdapter, build_adapters
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
from mediamonitor.adapters.max_live import (
    COST_SEARCH,
    PAGES_MAX_ITEMS,
    MaxAdapter,
    TtlCache,
    channel_slug,
    max_catalog,
    maxstat_post_id,
    post_ref,
    search_terms,
    time_from_post_id,
)
from mediamonitor.contract import PlatformId
from mediamonitor.normalize.urls import PostRef, parse_post_url, post_url
from mediamonitor.services.budget import BudgetExhaustedError
from mediamonitor.settings import Settings
from tests.conftest import make_settings

START = datetime(2026, 10, 10, tzinfo=UTC)
END = datetime(2026, 10, 20, 12, tzinfo=UTC)


def _post(
    post_id: str,
    number: str,
    *,
    slug: str,
    channel_id: str,
    text: str,
    published: str = "2026-10-20T06:21:12Z",
    **extra: Any,
) -> dict[str, Any]:
    """Пост в форме ответа MaxStat (`PostSearchResult`, проба 20.10.2026)."""
    post: dict[str, Any] = {
        "id": number,
        "channel_id": channel_id,
        "type": "photo",
        "url": f"https://max.ru/{slug}/{post_id}",
        "text": text,
        "text_links": [],
        "views": 10,
        "likes": 2,
        "likes_detailed": {},
        "attachments": [{"attachment_type": "image", "attachment_url": "https://i.oneme.ru/i?r=x"}],
        "forwarded_from_id": None,
        "forward_type": None,
        "published_at": published,
        "updated_at": "2026-10-20T09:21:16.037408+03:00",
        "is_deleted": False,
        "deleted_at": None,
        "score": None,
    }
    post.update(extra)
    return post


# Настоящие пары «id в ссылке — id MaxStat» из пробы: id MaxStat — тот же int64.
FOREIGN = _post(
    "AaFX-JoMRWE",
    "117471790536344929",
    slug="channel_demoX",
    channel_id="-78391094417442",
    text="Речные маршруты закрывают на ледостав.",
)
KRAI = _post(
    "AaFX6wlMIlc",
    "117471732273259095",
    slug="eniseytv",
    channel_id="-75496399637769",
    text="Ледостав на Енисее: паромы встали.",
    published="2026-10-20T06:06:23Z",
)
PRIVATE = _post(
    "AaFXX2VwfBs", "117471132523723803", slug="c", channel_id="-1", text="Пост без ника"
)
PRIVATE["url"] = "https://max.ru/c/-76901987009858/AaFXX2VwfBs"
OLD = _post(
    "AaFYK3M0MWo",
    "117472008927981930",
    slug="channel_demoX",
    channel_id="-78391094417442",
    text="Ледостав прошлого года",
    published="2026-09-01T07:16:44Z",
)
CHANNEL = {
    "id": "-78391094417442",
    "name": "Демо Новости",
    "description": "Новости демо-города",
    "avatar": "https://i.oneme.ru/i?r=y",
    "url": "https://max.ru/channel_demoX",
    "access": "public",
    "subscribers": 109,
    "posts": 207,
    "categories": ["Новости и СМИ", "Блоги"],
    "rkn_status": "skipped",
    "created_at": "1970-01-01T03:00:00+03:00",
    "updated_at": "2026-10-20T06:37:42+03:00",
}
LIMITS = {
    "plan_credits": 1000,
    "addon_credits": 0,
    "used_credits": 25,
    "remaining_credits": 975,
    "period_ends_at": "2026-11-18T14:47:23.366089Z",
}


def page(posts: list[dict[str, Any]], total: int | None = None, offset: int = 0) -> dict[str, Any]:
    count = len(posts) if total is None else total
    return {"total": count, "posts": posts, "limit": 100, "offset": offset}


def error(status: int, code: str) -> httpx.Response:
    body = {"code": code, "message": code, "request_id": "6f9619ff-8b86-4d01-b42d-00cf4fc964ff"}
    return httpx.Response(status, json=body)


def _copy(response: httpx.Response) -> httpx.Response:
    """Свежий ответ на каждый запрос: один записанный ответ можно отдать несколько раз."""
    return httpx.Response(response.status_code, headers=response.headers, content=response.content)


class Api:
    """Записанные ответы MaxStat: по пути и параметру `search`; журнал запросов."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.search: dict[str, list[httpx.Response] | httpx.Response] = {}
        self.other: dict[str, httpx.Response] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api")
        if path == "/v1/posts":
            term = request.url.params.get("search", "")
            answer = (
                self.search.get(f"{term}@{request.url.params.get('offset')}") or self.search[term]
            )
            if isinstance(answer, list):
                return _copy(answer.pop(0) if len(answer) > 1 else answer[0])
            return _copy(answer)
        return _copy(self.other.get(path) or error(404, "not_found"))

    def paths(self) -> list[str]:
        return [r.url.path.removeprefix("/api") for r in self.requests]

    def terms(self) -> list[tuple[str, str]]:
        return [
            (r.url.params.get("search", ""), r.url.params.get("offset", ""))
            for r in self.requests
            if r.url.path.endswith("/v1/posts")
        ]


class Meter:
    """Бюджет вызовов: записывает списания; `left` — сколько кредитов осталось."""

    def __init__(self, left: int = 10_000) -> None:
        self.left = left
        self.spent: list[int] = []

    async def spend(self, platform: PlatformId, amount: int = 1) -> None:
        if amount > self.left:
            raise BudgetExhaustedError(platform, "day", END)
        self.left -= amount
        self.spent.append(amount)


async def no_sleep(_: float) -> None:
    return None


def adapter(
    tmp_path: Path, api: Api, meter: Meter | None = None, **overrides: Any
) -> tuple[MaxAdapter, Meter]:
    values: dict[str, Any] = {"maxstat_token": SecretStr("test-key-not-real")}
    values.update(overrides)
    settings = make_settings(tmp_path, **values)
    client = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
    meter = meter or Meter()
    return MaxAdapter(settings, client, meter, sleep=no_sleep), meter


def query(
    text: str = "ледостав на Енисее", sources: list[SourceInfo] | None = None
) -> AdapterQuery:
    return AdapterQuery(text=text, kind="topic", start=START, end=END, sources=sources)


async def collect(adapter: MaxAdapter, q: AdapterQuery) -> list[AdapterEvent]:
    return [event async for event in adapter.search(q)]


def posts_of(events: list[AdapterEvent]) -> list[RawPost]:
    return [p for e in events if isinstance(e, Posts) for p in e.posts]


# ---------------------------------------------------------------- поиск «везде»


async def test_everywhere_search_parses_posts_and_spends_real_cost(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав енисее"] = httpx.Response(200, json=page([], total=0))
    api.search["ледостав"] = httpx.Response(
        200, json=page([FOREIGN, KRAI, PRIVATE, OLD]), headers={"X-Credits-Cost": "3"}
    )
    api.other["/v1/channels/-78391094417442"] = httpx.Response(200, json=CHANNEL)
    max_adapter, meter = adapter(tmp_path, api)

    events = await collect(max_adapter, query())

    # Узкий запрос пуст — расширяем до одного слова (MaxStat ищет слова вместе).
    assert api.terms() == [("ледостав енисее", "0"), ("ледостав", "0")]
    request = api.requests[0]
    assert request.headers["X-API-Token"] == "test-key-not-real"
    params = request.url.params
    assert params["date_from"] == "2026-10-10"
    assert params["date_to"] == "2026-10-20"
    assert params["is_deleted"] == "false"
    assert params["limit"] == "100"
    posts = posts_of(events)
    # Канал без ника (`/c/-…`) пропущен, пост вне периода отсечён.
    assert [p.ref.url for p in posts] == [
        "https://max.ru/channel_demox/AaFX-JoMRWE",
        "https://max.ru/eniseytv/AaFX6wlMIlc",
    ]
    foreign, krai = posts
    assert foreign.text == "Речные маршруты закрывают на ледостав."
    assert foreign.published_at == datetime(2026, 10, 20, 6, 21, 12, tzinfo=UTC)
    assert foreign.time_reliability == "exact"
    assert (foreign.views, foreign.reactions, foreign.has_media) == (10, 2, True)
    assert foreign.source.name == "Демо Новости"
    assert foreign.source.subscribers == 109
    assert foreign.source.type == "media"
    assert not foreign.source.regional
    # Канал краевого СМИ — из каталога, без платного запроса канала.
    assert krai.source.in_catalog
    assert krai.source.regional
    assert "/v1/channels/-75496399637769" not in api.paths()
    # Два поиска по 3 кредита и один канал за 1 кредит.
    assert meter.spent == [COST_SEARCH, COST_SEARCH, 1]
    assert max_adapter.credits_reported == 3
    progress = [e for e in events if isinstance(e, Progress)]
    assert progress[0] == Progress(0, 3, "pages")
    assert progress[-1] == Progress(3, 3, "pages")


async def test_paging_stops_at_stand_limit_and_says_so(tmp_path: Path) -> None:
    api = Api()
    many = [
        _post(
            f"AaFX-JoMRW{c}",
            str(117471790536344929 + i),
            slug="channel_demox",
            channel_id="-1",
            text="ледостав",
        )
        for i, c in enumerate("ABCDEFGHIJ")
    ]
    api.search["ледостав"] = httpx.Response(200, json=page(many[:5], total=480))
    api.search["ледостав@100"] = httpx.Response(200, json=page(many[5:], total=480, offset=100))
    max_adapter, meter = adapter(tmp_path, api, maxstat_max_pages=2, maxstat_channel_lookups=0)

    events = await collect(max_adapter, query("ледостав"))

    assert api.terms() == [("ледостав", "0"), ("ледостав", "100")]
    assert len(posts_of(events)) == 10
    capped = [e for e in events if isinstance(e, Capped)]
    assert len(capped) == 1
    assert capped[0].limit == 200
    assert "480" in capped[0].note
    assert meter.spent == [COST_SEARCH, COST_SEARCH]
    # Без запросов канала — название по нику.
    assert posts_of(events)[0].source.name == "max.ru/channel_demox"


async def test_my_sources_keep_only_listed_channels(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = httpx.Response(200, json=page([FOREIGN, KRAI], total=150))
    max_adapter, _ = adapter(tmp_path, api)
    mine = [max_catalog()["eniseytv"], SourceInfo("vk", "-1", None, "VK", "https://vk.com/x", 1)]

    events = await collect(max_adapter, query("ледостав", sources=mine))

    assert [p.ref.owner_id for p in posts_of(events)] == ["eniseytv"]
    assert "/v1/channels/-78391094417442" not in api.paths()


async def test_no_max_sources_in_list_means_no_calls(tmp_path: Path) -> None:
    api = Api()
    max_adapter, meter = adapter(tmp_path, api)
    vk_only = [SourceInfo("vk", "-1", None, "VK", "https://vk.com/x", 1)]
    events = await collect(max_adapter, query(sources=vk_only))
    assert posts_of(events) == []
    assert api.requests == []
    assert meter.spent == []


# ---------------------------------------------------------------- ошибки → честные статусы


async def test_without_key_no_access_and_no_calls(tmp_path: Path) -> None:
    api = Api()
    max_adapter, meter = adapter(tmp_path, api, maxstat_token=None)
    with pytest.raises(AdapterError) as caught:
        await collect(max_adapter, query())
    assert caught.value.code == "key-invalid"
    assert caught.value.state == "no-access"
    assert "MAXSTAT_API_TOKEN" in caught.value.message
    assert api.requests == []
    assert meter.spent == []
    assert (await max_adapter.health()).state == "down"


@pytest.mark.parametrize(
    ("status", "code", "problem"),
    [
        (401, "invalid_token", "key-invalid"),
        (403, "inactive_user", "key-invalid"),
        (402, "insufficient_credits", "quota-exhausted"),
    ],
)
async def test_access_errors_are_no_access(
    tmp_path: Path, status: int, code: str, problem: str
) -> None:
    api = Api()
    api.search["ледостав"] = error(status, code)
    max_adapter, _ = adapter(tmp_path, api)
    with pytest.raises(AdapterError) as caught:
        await collect(max_adapter, query("ледостав"))
    assert caught.value.code == problem
    assert caught.value.state == "no-access"
    assert not caught.value.retryable
    assert len(api.requests) == 1  # такие ошибки не повторяем


async def test_overload_is_retried_and_charged_once(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = [
        error(503, "service_unavailable"),
        error(429, "rate_limited"),
        httpx.Response(200, json=page([FOREIGN])),
    ]
    max_adapter, meter = adapter(tmp_path, api, maxstat_channel_lookups=0)
    events = await collect(max_adapter, query("ледостав"))
    assert len(posts_of(events)) == 1
    assert len(api.requests) == 3
    assert meter.spent == [COST_SEARCH]


async def test_down_after_retries_is_unavailable(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = error(503, "service_unavailable")
    max_adapter, _ = adapter(tmp_path, api)
    with pytest.raises(AdapterError) as caught:
        await collect(max_adapter, query("ледостав"))
    assert caught.value.code == "unavailable"
    assert caught.value.retryable
    assert len(api.requests) == 3  # первый вызов и два повтора


async def test_garbage_is_bad_response_not_nothing_found(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = httpx.Response(200, text="<html>капча</html>")
    max_adapter, _ = adapter(tmp_path, api)
    with pytest.raises(AdapterError) as caught:
        await collect(max_adapter, query("ледостав"))
    assert caught.value.code == "bad-response"

    api.search["ледостав"] = httpx.Response(200, json={"items": []})
    with pytest.raises(AdapterError) as caught:
        await collect(max_adapter, query("ледостав"))
    assert caught.value.code == "bad-response"


async def test_rate_limit_mid_search_keeps_found_as_partial(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = httpx.Response(200, json=page([FOREIGN], total=300))
    api.search["ледостав@100"] = error(429, "rate_limited")
    max_adapter, _ = adapter(tmp_path, api, maxstat_channel_lookups=0)
    events = await collect(max_adapter, query("ледостав"))
    assert len(posts_of(events)) == 1
    partial = [e for e in events if isinstance(e, Partial)]
    assert [p.code for p in partial] == ["rate-limited"]


# ---------------------------------------------------------------- бюджет и кэш (НТ-6, Р7)


async def test_budget_exhausted_before_call_makes_no_request(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = httpx.Response(200, json=page([FOREIGN]))
    max_adapter, meter = adapter(tmp_path, api, Meter(left=2))
    with pytest.raises(AdapterError) as caught:
        await collect(max_adapter, query("ледостав"))
    assert caught.value.code == "quota-exhausted"
    assert caught.value.state == "no-access"
    assert "на сегодня исчерпан" in caught.value.message
    assert api.requests == []
    assert meter.spent == []


async def test_budget_runs_out_mid_search_keeps_found(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = httpx.Response(200, json=page([FOREIGN], total=300))
    max_adapter, _ = adapter(tmp_path, api, Meter(left=4), maxstat_channel_lookups=0)
    events = await collect(max_adapter, query("ледостав"))
    assert len(posts_of(events)) == 1
    assert [e.code for e in events if isinstance(e, Partial)] == ["quota-exhausted"]


async def test_cache_saves_credits_on_repeat_and_post_check(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = httpx.Response(200, json=page([FOREIGN]))
    api.other["/v1/channels/-78391094417442"] = httpx.Response(200, json=CHANNEL)
    max_adapter, meter = adapter(tmp_path, api)

    first = posts_of(await collect(max_adapter, query("ледостав")))
    calls, spent = len(api.requests), list(meter.spent)
    again = posts_of(await collect(max_adapter, query("ледостав")))
    checked = await max_adapter.fetch_post(first[0].ref)

    assert again == first
    assert checked is not None
    assert checked.source.name == "Демо Новости"
    assert len(api.requests) == calls
    assert meter.spent == spent


async def test_cache_can_be_switched_off(tmp_path: Path) -> None:
    api = Api()
    api.search["ледостав"] = httpx.Response(200, json=page([FOREIGN]))
    max_adapter, meter = adapter(tmp_path, api, maxstat_cache_minutes=0, maxstat_channel_lookups=0)
    await collect(max_adapter, query("ледостав"))
    await collect(max_adapter, query("ледостав"))
    assert meter.spent == [COST_SEARCH, COST_SEARCH]


async def test_fetch_post_by_link_id(tmp_path: Path) -> None:
    api = Api()
    api.other["/v1/posts/117471790536344929"] = httpx.Response(200, json=FOREIGN)
    api.other["/v1/posts/117471732273259095"] = httpx.Response(
        200, json={**KRAI, "is_deleted": True}
    )
    max_adapter, meter = adapter(tmp_path, api, maxstat_channel_lookups=0)

    found = await max_adapter.fetch_post(PostRef("max", "channel_demox", "AaFX-JoMRWE"))
    assert found is not None
    assert found.text == "Речные маршруты закрывают на ледостав."
    # Пост — 1 кредит; название канала по кредиту не запрашивается.
    assert meter.spent == [1]
    assert found.source.name == "max.ru/channel_demox"
    # Удалён — None; нет в индексе (404) — None; чужой канал в ссылке — None.
    assert await max_adapter.fetch_post(PostRef("max", "eniseytv", "AaFX6wlMIlc")) is None
    assert await max_adapter.fetch_post(PostRef("max", "eniseytv", "AaFYK3M0MWo")) is None
    assert await max_adapter.fetch_post(PostRef("max", "other", "AaFX-JoMRWE")) is None
    # Записанные примеры (номер-число) у MaxStat не спрашиваем.
    calls = len(api.requests)
    assert await max_adapter.fetch_post(PostRef("max", "demo_tv", "1842")) is None
    assert len(api.requests) == calls


async def test_health_reads_free_limits(tmp_path: Path) -> None:
    api = Api()
    api.other["/v1/account/limits"] = httpx.Response(200, json=LIMITS)
    max_adapter, meter = adapter(tmp_path, api)
    health = await max_adapter.health()
    assert health.state == "ok"
    assert "975" in health.message
    await max_adapter.health()
    assert len(api.requests) == 1  # ответ кэшируется на минуту
    assert meter.spent == []


# ---------------------------------------------------------------- каталог, ссылки, запрос


def test_catalog_skips_invite_links() -> None:
    raw = json.loads(
        (Path(__file__).parents[1] / "src/mediamonitor/data/krai-media.json").read_text("utf-8")
    )
    links = [m["links"]["max"] for m in raw["media"] if (m.get("links") or {}).get("max")]
    invites = [link for link in links if "/join/" in link["url"]]
    assert invites, "в каталоге есть приглашения — на них и проверяем пропуск"
    catalog = max_catalog()
    assert len(catalog) == len(links) - len(invites)
    assert "join" not in catalog
    for slug, info in catalog.items():
        assert info.url == f"https://max.ru/{slug}"
        assert info.in_catalog
        assert info.regional
    assert catalog["eniseytv"].platform == "max"
    assert channel_slug(invites[0]["url"]) is None


def test_post_links_and_ids() -> None:
    ref = post_ref("https://max.ru/Channel_DemoX/AaFX-JoMRWE")
    assert ref == PostRef("max", "channel_demox", "AaFX-JoMRWE")
    assert parse_post_url("https://max.ru/channel_demox/AaFX-JoMRWE") == ref
    assert post_url(ref) == "https://max.ru/channel_demox/AaFX-JoMRWE"
    assert post_ref("https://max.ru/c/-76901987009858/AaFXX2VwfBs") is None
    assert post_ref("https://max.ru/join/VHhreMro-NbLWtF3KmeP5tF39hkcZTRlyR5AZw1ryG8") is None
    assert maxstat_post_id("AaFX-JoMRWE") == "117471790536344929"
    assert maxstat_post_id("1842") is None
    assert time_from_post_id("AaFX-JoMRWE") == datetime(2026, 10, 20, 6, 21, 12, 588000, tzinfo=UTC)


def test_search_terms_go_from_narrow_to_broad() -> None:
    assert search_terms("Ледостав на Енисее", "topic") == ["ледостав енисее", "ледостав"]
    assert search_terms("Праздник урожая в Минусинске", "topic") == [
        "праздник урожая минусинске",
        "праздник урожая",
        "минусинске",
    ]
    release = (
        "Паромная переправа через Енисей закрывается. Паромная переправа в Енисейске "
        "работала до ледостава. Переправа откроется после ледостава."
    )
    assert search_terms(release, "news-text")[0] == "переправа паромная ледостава"
    assert search_terms("и в на", "topic") == []


def test_token_from_server_name_or_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAXSTAT_TOKEN", raising=False)
    monkeypatch.setenv("MAXSTAT_API_TOKEN", "ключ-сервера")
    settings = Settings(_env_file=None)
    assert settings.maxstat_token is not None
    assert settings.maxstat_token.get_secret_value() == "ключ-сервера"
    assert "ключ-сервера" not in repr(settings)
    assert "ключ-сервера" not in settings.model_dump_json()
    monkeypatch.delenv("MAXSTAT_API_TOKEN")
    monkeypatch.setenv("MAXSTAT_TOKEN", "запасной")
    fallback = Settings(_env_file=None).maxstat_token
    assert fallback is not None
    assert fallback.get_secret_value() == "запасной"


async def test_data_source_max_switches_only_max(tmp_path: Path) -> None:
    async with httpx.AsyncClient() as client:
        plain = build_adapters(make_settings(tmp_path), client)
        live = build_adapters(make_settings(tmp_path, data_source_max="live"), client)
    assert isinstance(plain["max"], FixtureAdapter)
    assert isinstance(live["max"], MaxAdapter)
    assert isinstance(live["vk"], FixtureAdapter)
    assert live["max"].description.freshness is not None
    assert live["max"].description.freshness.delay_hours == 24


def test_cache_keeps_at_most_max_items_and_drops_oldest() -> None:
    """Кэш MaxStat в памяти ограничен числом записей: старые вытесняются (память API)."""
    cache: TtlCache[int] = TtlCache(3600, lambda: 0.0, max_items=3)
    for number in range(5):
        cache.put(f"k{number}", number)
    assert len(cache) == 3
    assert cache.get("k0") is None
    assert cache.get("k1") is None
    assert [cache.get(f"k{n}") for n in (2, 3, 4)] == [2, 3, 4]
    # Повторная запись того же ключа не раздувает кэш.
    cache.put("k4", 40)
    assert len(cache) == 3
    assert cache.get("k4") == 40


def test_search_pages_cache_is_small(tmp_path: Path) -> None:
    """Страница поиска — до 100 постов целиком: таких страниц держим не больше PAGES_MAX_ITEMS."""
    adapter = MaxAdapter(make_settings(tmp_path), httpx.AsyncClient())
    assert adapter._pages.max_items == PAGES_MAX_ITEMS <= 100
    assert adapter._posts.max_items >= PAGES_MAX_ITEMS
