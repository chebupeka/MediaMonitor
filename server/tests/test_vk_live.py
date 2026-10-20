"""Живой адаптер VK на записанных ответах VK API (без сети и без настоящего ключа).

Ответы собраны по документации VK API 5.199 (dev.vk.ru): `groups.getById` — объект
`{"groups": [...], "profiles": [...]}`, `wall.get` с `extended=1` — `{"count", "items",
"groups", "profiles"}`, ошибки — `{"error": {"error_code", "error_msg"}}`. Проверяем листание
по `offset` до начала периода, период и закреплённый пост, перепосты, ошибки 5, 6, 15, 18, 29,
30, 1051, бюджет, закрытые сообщества, кэш (Р7) и пометку демо у площадок на примерах.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

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
    RawPost,
    SourceInfo,
)
from mediamonitor.adapters.vk_live import VkAdapter, VkTarget, load_vk_catalog
from mediamonitor.ai.judge import AiJudge, NullJudge
from mediamonitor.contract import PLATFORM_ORDER, PlatformId
from mediamonitor.db.session import create_all, create_engine, create_sessions
from mediamonitor.main import create_app
from mediamonitor.services.post_cache import DbPostCache
from mediamonitor.settings import Settings
from tests.conftest import fixture_store, make_settings, new_workspace, open_client
from tests.conftest import run_search as run

NOW = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)  # 14:00 19.10.2026 по Красноярску
FAKE_KEY = "test-only-not-a-real-key"


# ---------------------------------------------------------------- записанный VK API


def post(owner: int, number: int, at: datetime, text: str = "", **extra: Any) -> dict[str, Any]:
    """Пост стены, как его отдаёт wall.get (поля — по документации объекта «Запись на стене»)."""
    return {
        "id": number,
        "owner_id": owner,
        "from_id": owner,
        "date": int(at.timestamp()),
        "post_type": "post",
        "text": text,
        "attachments": [],
        "comments": {"count": 0},
        "likes": {"count": 10, "user_likes": 0, "can_like": 1},
        "reposts": {"count": 2, "user_reposted": 0},
        "views": {"count": 500},
        **extra,
    }


def group(gid: int, name: str, screen: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": gid,
        "name": name,
        "screen_name": screen,
        "is_closed": 0,
        "type": "page",
        "members_count": 1000 + gid,
        **extra,
    }


@dataclass
class FakeVk:
    """VK API на записанных ответах: стены, сообщества, ошибки по очереди."""

    walls: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    # (метод, owner_id или "") → коды ошибок, которые вернуть по очереди перед ответом
    errors: dict[tuple[str, str], list[int]] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        assert form["access_token"] == FAKE_KEY
        assert "access_token" not in str(request.url)  # ключ — только в теле запроса
        assert form["v"] == "5.199"
        self.calls.append((method, form))
        queue = self.errors.get((method, form.get("owner_id", "")))
        if queue:
            code = queue.pop(0)
            return httpx.Response(
                200, json={"error": {"error_code": code, "error_msg": f"error {code}"}}
            )
        if method == "groups.getById":
            found = []
            for key in form["group_ids"].split(","):
                g = self.groups.get(key) or next(
                    (x for x in self.groups.values() if str(x["id"]) == key), None
                )
                if g is not None:
                    found.append(g)
            if not found:
                return httpx.Response(
                    200, json={"error": {"error_code": 100, "error_msg": "group_ids invalid"}}
                )
            return httpx.Response(200, json={"response": {"groups": found, "profiles": []}})
        if method == "wall.get":
            owner = int(form["owner_id"])
            items = self.walls.get(owner, [])
            offset, count = int(form["offset"]), int(form["count"])
            names = [
                {"id": -o, "name": f"Источник {-o}", "screen_name": f"src{-o}"}
                for o in (
                    {owner} | {c["owner_id"] for i in items for c in i.get("copy_history", [])}
                )
                if o < 0
            ]
            return httpx.Response(
                200,
                json={
                    "response": {
                        "count": len(items),
                        "items": items[offset : offset + count],
                        "groups": names,
                        "profiles": [],
                    }
                },
            )
        if method == "wall.getById":
            owner_s, _, number = form["posts"].partition("_")
            items = [i for i in self.walls.get(int(owner_s), []) if str(i["id"]) == number]
            return httpx.Response(
                200, json={"response": {"items": items, "groups": [], "profiles": []}}
            )
        return httpx.Response(200, json={"error": {"error_code": 3, "error_msg": "Unknown method"}})

    def wall_calls(self, owner: int | None = None) -> list[dict[str, str]]:
        return [
            form
            for method, form in self.calls
            if method == "wall.get" and (owner is None or form["owner_id"] == str(owner))
        ]


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Meter:
    """Бюджет вызовов: считает списания, после `limit` — «лимит на сегодня исчерпан»."""

    def __init__(self, limit: int = 1_000_000) -> None:
        self.limit = limit
        self.spent = 0

    async def spend(self, platform: PlatformId, amount: int = 1) -> None:
        assert platform == "vk"
        if self.spent + amount > self.limit:
            raise AdapterError(
                "quota-exhausted",
                "Лимит запросов к ВКонтакте на сегодня исчерпан: это предел открытого стенда.",
                retryable=False,
                state="no-access",
            )
        self.spent += amount


async def no_sleep(_: float) -> None:
    return None


CATALOG = [
    VkTarget(key="gazeta_one", name="Газета один", district="Ачинск", subscribers=None),
    VkTarget(key="102", name="Газета два", district="Канск", subscribers=None),
]


def vk_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "vk_service_token": FAKE_KEY,
        "data_source_vk": "live",
        "vk_requests_per_second": 20.0,
        **overrides,
    }
    return make_settings(tmp_path, **values)


def adapter(
    tmp_path: Path,
    fake: FakeVk,
    *,
    budget: Meter | None = None,
    cache: DbPostCache | None = None,
    clock: Clock | None = None,
    sleeps: list[float] | None = None,
    **overrides: Any,
) -> VkAdapter:
    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return VkAdapter(
        vk_settings(tmp_path, **overrides),
        client,
        budget,
        cache=cache,
        catalog=CATALOG,
        sleep=sleep,
        clock=clock or Clock(NOW),
    )


def query(days: int = 7, sources: list[SourceInfo] | None = None) -> AdapterQuery:
    return AdapterQuery(
        text="тема",
        kind="topic",
        start=NOW - timedelta(days=days),
        end=NOW,
        sources=sources,
    )


async def collect(events: AsyncIterator[AdapterEvent]) -> tuple[list[RawPost], list[AdapterEvent]]:
    posts: list[RawPost] = []
    other: list[AdapterEvent] = []
    async for event in events:
        if isinstance(event, Posts):
            posts.extend(event.posts)
        else:
            other.append(event)
    return posts, other


def two_groups(fake: FakeVk) -> None:
    fake.groups["gazeta_one"] = group(101, "Газета один | новости", "gazeta_one")
    fake.groups["club102"] = group(102, "Газета два", "club102")


def hourly(owner: int, hours: int, start_id: int = 1000) -> list[dict[str, Any]]:
    """Стена: по посту в час, новые сверху."""
    return [
        post(owner, start_id - i, NOW - timedelta(hours=i), f"Пост {i} часов назад")
        for i in range(hours)
    ]


# ---------------------------------------------------------------- листание и период


async def test_pages_until_period_start_and_skips_old_pinned(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    pinned = post(-101, 5, NOW - timedelta(days=400), "Закреплённый старый пост", is_pinned=1)
    fake.walls[-101] = [pinned, *hourly(-101, 300)]
    fake.walls[-102] = hourly(-102, 3, 50)
    vk = adapter(tmp_path, fake)

    posts, events = await collect(vk.search(query(days=7)))  # 168 часов

    # Стена 101: закреплённый старый пост не останавливает листание; страница 2 (offset 100)
    # дочитывает до начала периода, третьей страницы нет.
    assert [c["offset"] for c in fake.wall_calls(-101)] == ["0", "100"]
    assert all(c["count"] == "100" and c["filter"] == "owner" for c in fake.wall_calls())
    in_101 = [p for p in posts if p.ref.owner_id == "-101"]
    assert len(in_101) == 169  # от 0 до 168 часов включительно
    assert all(
        p.published_at is not None and p.published_at >= NOW - timedelta(days=7) for p in posts
    )
    assert not any(p.ref.post_id == "5" for p in posts)  # закреплённый вне периода
    # Короткая стена: одна страница, count меньше страницы.
    assert len(fake.wall_calls(-102)) == 1
    assert not any(isinstance(e, (Partial, Capped)) for e in events)
    # groups.getById — одним вызовом на весь каталог.
    assert [m for m, _ in fake.calls].count("groups.getById") == 1


async def test_page_cap_is_reported_honestly(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    fake.walls[-101] = hourly(-101, 2000)
    vk = adapter(tmp_path, fake, vk_max_pages_per_source=3)
    _, events = await collect(vk.search(query(days=30)))
    assert len(fake.wall_calls(-101)) == 3
    caps = [e for e in events if isinstance(e, Capped)]
    assert caps
    assert caps[0].limit == 300
    assert "последние 300 постов" in caps[0].note


# ---------------------------------------------------------------- разбор поста


async def test_repost_fields_link_title_and_media(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    original = post(-777, 4242, NOW - timedelta(hours=5), "Исходная новость о мосте в Ачинске")
    fake.walls[-101] = [
        post(
            -101,
            10,
            NOW - timedelta(hours=1),
            "Делимся новостью",
            copy_history=[original],
            edited=int((NOW - timedelta(minutes=30)).timestamp()),
            views={"count": 1234},
            likes={"count": 7},
            reposts={"count": 3},
        ),
        post(
            -101,
            9,
            NOW - timedelta(hours=2),
            "Читайте на сайте",
            attachments=[
                {"type": "link", "link": {"url": "https://example.ru/a", "title": "Новый мост"}},
                {"type": "photo", "photo": {"id": 1}},
            ],
        ),
        post(-101, 8, NOW - timedelta(hours=3), "Платный пост", donut={"is_donut": True}),
    ]
    vk = adapter(tmp_path, fake)
    posts, _ = await collect(vk.search(query(days=1, sources=[source(-101)])))
    by_id = {p.ref.post_id: p for p in posts}
    assert set(by_id) == {"10", "9"}  # платный пост без текста не берём
    repost = by_id["10"]
    assert repost.ref.id == "vk:-101_10"
    assert repost.repost_of == ("Источник 777", "https://vk.com/wall-777_4242")
    assert repost.text == "Делимся новостью\n\nИсходная новость о мосте в Ачинске"
    assert repost.views == 1234
    assert repost.reactions == 10  # лайки + репосты
    assert repost.edited is True
    assert repost.time_reliability == "exact"
    assert repost.published_at == NOW - timedelta(hours=1)
    linked = by_id["9"]
    assert linked.text == "Читайте на сайте\n\nНовый мост"
    assert linked.has_media is True
    assert linked.repost_of is None


def source(owner: int, *, closed: bool = False, name: str | None = None) -> SourceInfo:
    return SourceInfo(
        platform="vk",
        owner_id=str(owner),
        slug=None,
        name=name or f"Сообщество {-owner}",
        url=f"https://vk.com/club{-owner}",
        subscribers=None,
        closed=closed,
    )


# ---------------------------------------------------------------- ошибки VK


async def test_error_5_is_no_access(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    fake.errors[("wall.get", "-101")] = [5]
    vk = adapter(tmp_path, fake)
    with pytest.raises(AdapterError) as failure:
        await collect(vk.search(query(sources=[source(-101)])))
    assert failure.value.code == "key-invalid"
    assert failure.value.state == "no-access"
    assert "ключ недействителен" in failure.value.message
    assert FAKE_KEY not in failure.value.message
    assert (await vk.health()).state == "down"


async def test_error_6_is_retried_then_partial(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    fake.walls[-101] = hourly(-101, 5)
    fake.walls[-102] = hourly(-102, 5, 70)
    fake.errors[("wall.get", "-101")] = [6]  # один раз — повтор помогает
    sleeps: list[float] = []
    vk = adapter(tmp_path, fake, sleeps=sleeps)
    posts, events = await collect(vk.search(query(sources=[source(-101), source(-102)])))
    assert len(posts) == 10
    assert 1.0 in sleeps
    assert not any(isinstance(e, Partial) for e in events)

    fake.calls.clear()
    fake.errors[("wall.get", "-101")] = [6, 6, 6]  # не проходит — «частично», дальше не идём
    vk = adapter(tmp_path, fake)
    posts, events = await collect(vk.search(query(sources=[source(-101), source(-102)])))
    partial = [e for e in events if isinstance(e, Partial)]
    assert partial
    assert partial[0].code == "rate-limited"
    assert partial[0].retryable
    assert len(fake.wall_calls(-101)) == 3  # первый вызов и два повтора
    assert fake.wall_calls(-102) == []


@pytest.mark.parametrize("code", [15, 18, 30])
async def test_closed_or_deleted_community_does_not_stop_search(tmp_path: Path, code: int) -> None:
    fake = FakeVk()
    two_groups(fake)
    fake.walls[-102] = hourly(-102, 4, 70)
    fake.errors[("wall.get", "-101")] = [code]
    vk = adapter(tmp_path, fake)
    posts, events = await collect(
        vk.search(query(sources=[source(-101, name="Закрытая"), source(-102)]))
    )
    assert len(posts) == 4
    partial = [e for e in events if isinstance(e, Partial)]
    assert len(partial) == 1
    assert partial[0].code == "sources-closed"
    assert "«Закрытая»" in partial[0].message
    assert not partial[0].retryable


async def test_daily_limit_29_and_method_closed_1051(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    fake.errors[("wall.get", "-101")] = [29]
    vk = adapter(tmp_path, fake)
    with pytest.raises(AdapterError) as limit:
        await collect(vk.search(query(sources=[source(-101)])))
    assert limit.value.code == "quota-exhausted"
    assert limit.value.state == "no-access"
    assert "лимит запросов на сегодня исчерпан" in limit.value.message

    fake.errors[("wall.get", "-101")] = [1051]
    with pytest.raises(AdapterError) as closed:
        await collect(vk.search(query(sources=[source(-101)])))
    assert closed.value.state == "no-access"
    assert "Нет доступа к ВКонтакте" in closed.value.message


async def test_no_key_is_no_access_without_calls(tmp_path: Path) -> None:
    fake = FakeVk()
    vk = adapter(tmp_path, fake, vk_service_token=None)
    with pytest.raises(AdapterError) as failure:
        await collect(vk.search(query()))
    assert failure.value.state == "no-access"
    assert "не задан сервисный ключ" in failure.value.message
    assert fake.calls == []


async def test_bad_response_is_an_error_not_zero(tmp_path: Path) -> None:
    def broken(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>не JSON</html>")

    vk = VkAdapter(
        vk_settings(tmp_path),
        httpx.AsyncClient(transport=httpx.MockTransport(broken)),
        catalog=CATALOG,
        sleep=no_sleep,
    )
    with pytest.raises(AdapterError) as failure:
        await collect(vk.search(query(sources=[source(-101)])))
    assert failure.value.code == "bad-response"


# ---------------------------------------------------------------- бюджет и частота


async def test_every_call_is_spent_from_budget(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    fake.walls[-101] = hourly(-101, 150)
    fake.walls[-102] = hourly(-102, 2, 70)
    meter = Meter()
    vk = adapter(tmp_path, fake, budget=meter)
    await collect(vk.search(query(days=7)))
    # groups.getById 1 + стена 101 две страницы + стена 102 одна.
    assert len(fake.calls) == 4
    assert meter.spent == 4

    # Бюджет кончился посреди обхода: вызов не делается, статус «лимит на сегодня исчерпан».
    fake.calls.clear()
    meter = Meter(limit=1)
    vk = adapter(tmp_path, fake, budget=meter)
    with pytest.raises(AdapterError) as exhausted:
        await collect(vk.search(query(days=7)))
    assert exhausted.value.code == "quota-exhausted"
    assert "на сегодня исчерпан" in exhausted.value.message
    assert len(fake.calls) == 1  # только groups.getById


async def test_requests_per_second_are_limited(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    sleeps: list[float] = []
    vk = adapter(tmp_path, fake, sleeps=sleeps, vk_requests_per_second=3.0)
    await collect(vk.search(query(sources=[source(-101), source(-102)])))
    # Два вызова подряд: второй ждёт около 1/3 секунды.
    assert sleeps
    assert all(0 < s <= 1 / 3 + 1e-6 for s in sleeps)


# ---------------------------------------------------------------- закрытые сообщества


async def test_closed_community_from_catalog_is_not_polled(tmp_path: Path) -> None:
    fake = FakeVk()
    fake.groups["gazeta_one"] = group(101, "Газета один", "gazeta_one", is_closed=1)
    fake.groups["club102"] = group(102, "Газета два", "club102")
    fake.walls[-102] = hourly(-102, 2, 70)
    vk = adapter(tmp_path, fake)
    posts, events = await collect(vk.search(query()))
    assert fake.wall_calls(-101) == []
    assert len(posts) == 2
    assert not any(isinstance(e, Partial) for e in events)

    # В «Моих источниках» закрытое сообщество названо, вызова тоже нет.
    fake.calls.clear()
    _, events = await collect(
        vk.search(query(sources=[source(-101, closed=True, name="Газета один"), source(-102)]))
    )
    assert fake.wall_calls(-101) == []
    partial = [e for e in events if isinstance(e, Partial)]
    assert partial
    assert "«Газета один»" in partial[0].message


async def test_probe_source_states(tmp_path: Path) -> None:
    fake = FakeVk()
    fake.groups["gazeta_one"] = group(101, "Газета один", "gazeta_one")
    fake.groups["closed_one"] = group(103, "Закрытая", "closed_one", is_closed=1)
    vk = adapter(tmp_path, fake)
    ok = await vk.probe_source("https://vk.com/gazeta_one")
    assert ok.state == "ok"
    assert ok.source is not None
    assert ok.source.owner_id == "-101"
    assert (await vk.probe_source("https://vk.com/closed_one")).state == "closed"
    assert (await vk.probe_source("https://vk.com/nobody_here")).state == "not-found"
    calls = len(fake.calls)
    # Личная страница — не сообщество: не опрашиваем.
    assert (await vk.probe_source("https://vk.com/id586913986")).state == "not-supported"
    assert len(fake.calls) == calls


# ---------------------------------------------------------------- кэш (Р7)


async def test_repeat_search_within_ttl_uses_cache(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'cache.db'}")
    await create_all(engine)
    cache = DbPostCache(create_sessions(engine))
    fake = FakeVk()
    two_groups(fake)
    fake.walls[-101] = hourly(-101, 120)
    fake.walls[-102] = hourly(-102, 3, 70)
    clock = Clock(NOW)
    vk = adapter(tmp_path, fake, cache=cache, clock=clock, vk_cache_minutes=30)
    try:
        first, _ = await collect(vk.search(query(days=3)))
        calls = len(fake.calls)
        assert calls == 3  # groups.getById + 101 (страница дочитала до начала периода) + 102

        # Через 10 минут тот же период и период короче — без вызовов VK, те же посты.
        clock.now = NOW + timedelta(minutes=10)
        again, _ = await collect(vk.search(query(days=3)))
        shorter, _ = await collect(vk.search(query(days=1)))
        assert len(fake.calls) == calls
        assert {p.ref.id for p in again} == {p.ref.id for p in first}
        assert {p.ref.id for p in shorter} <= {p.ref.id for p in first}
        # Время получения — настоящее, а не время повторного поиска.
        assert all(p.fetched_at == NOW for p in again)

        # Период длиннее, чем дочитали, — стена 101 листается заново; 102 прочитана вся.
        await collect(vk.search(query(days=10)))
        assert len(fake.wall_calls(-101)) == 1 + 2
        assert len(fake.wall_calls(-102)) == 1

        # Кэш устарел — снова в VK.
        clock.now = NOW + timedelta(minutes=45)
        await collect(vk.search(query(days=1)))
        assert len(fake.wall_calls(-102)) == 2
    finally:
        await engine.dispose()


# ---------------------------------------------------------------- каталог и режимы данных


def test_catalog_takes_only_communities() -> None:
    targets = load_vk_catalog()
    keys = {t.key for t in targets}
    krai = [t for t in targets if t.regional]
    federal = [t for t in targets if not t.regional]
    assert len(krai) == 45  # 48 редакций, у трёх ссылка на личную страницу
    assert len(federal) == 21  # docs/research/vk-krai-communities.md
    assert "avangard_online" in keys
    assert "68905670" in keys  # vk.com/club68905670 → число
    assert {"ria", "tassagency", "ru__novosti"} <= {t.key for t in federal}
    assert not any(k.startswith("id") and k[2:].isdigit() for k in keys)
    assert len(keys) == len(targets)


async def test_federal_communities_read_one_page_and_are_not_regional(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    fake.groups["ria"] = group(15755094, "РИА Новости", "ria")
    fake.walls[-15755094] = [
        post(-15755094, 900_000 - i, NOW - timedelta(minutes=10 * i), f"Новость {i}")
        for i in range(500)
    ]
    catalog = [*CATALOG, VkTarget("ria", "РИА Новости", None, None, regional=False)]
    vk = VkAdapter(
        vk_settings(tmp_path),
        httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
        catalog=catalog,
        sleep=no_sleep,
        clock=Clock(NOW),
    )
    pool = {s.owner_id: s for s in await vk.pool()}
    assert pool["-101"].regional
    assert pool["-15755094"].regional is False  # краевой — только по месту в тексте
    posts, events = await collect(vk.search(query(days=7)))
    assert len(fake.wall_calls(-15755094)) == 1  # VK_FEDERAL_MAX_PAGES=1
    assert len([p for p in posts if p.ref.owner_id == "-15755094"]) == 100
    caps = [e for e in events if isinstance(e, Capped)]
    assert caps
    assert "федеральных сообществ (1)" in caps[0].note
    assert "последние 100 постов" in caps[0].note


def test_per_platform_data_source(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, data_source="fixtures", data_source_vk="live")
    assert settings.source_of("vk") == "live"
    assert settings.source_of("ok") == "fixtures"
    assert settings.demo_platforms == ("ok", "max")
    assert not settings.all_fixtures
    # Демо-оценка ИИ — только когда все площадки на примерах.
    assert settings.ai_detect_kind == "off"
    blank = make_settings(tmp_path, data_source="live", data_source_ok="", data_source_max=" ")
    assert blank.source_of("ok") == "live"
    assert blank.demo_platforms == ()

    registry = build_adapters(
        settings, httpx.AsyncClient(transport=httpx.MockTransport(FakeVk().handler))
    )
    assert isinstance(registry["vk"], VkAdapter)
    assert isinstance(registry["ok"], FixtureAdapter)
    assert isinstance(registry["max"], FixtureAdapter)


# ---------------------------------------------------------------- сквозной поиск: живой VK + демо


async def test_live_vk_and_demo_platforms_in_selection(tmp_path: Path) -> None:
    fake = FakeVk()
    two_groups(fake)
    period_day = datetime(2026, 10, 10, 5, 0, tzinfo=UTC)
    fake.walls[-101] = [
        post(
            -101,
            77,
            period_day,
            "Безопасность дорожного движения: в Ачинске проверили пешеходные переходы у школ",
        )
    ]
    settings = vk_settings(tmp_path, data_source="fixtures")
    store = fixture_store()

    def factory(s: Settings, _: httpx.AsyncClient) -> AdapterRegistry:
        client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        registry: AdapterRegistry = {
            p: FixtureAdapter(p, store) for p in PLATFORM_ORDER if p != "vk"
        }
        registry["vk"] = VkAdapter(s, client, catalog=CATALOG, sleep=no_sleep)
        return registry

    def judge(s: Settings, _: httpx.AsyncClient) -> AiJudge:
        return NullJudge(s.llm_model_label)

    app = create_app(settings, adapter_factory=factory, judge_factory=judge)
    async with open_client(app) as client:
        headers = await new_workspace(client)
        search_id, events = await run(client, headers)
        assert events[-1]["event"] == "finished"
        selection = events[-1]["data"]["selection"]
        statuses = {s["platform"]: s for s in selection["statuses"]}
        assert "demo" not in statuses["vk"]
        assert statuses["ok"]["demo"] is True
        assert statuses["max"]["demo"] is True
        items = selection["items"]
        vk_items = [i for i in items if i["publication"]["platform"] == "vk"]
        demo_items = [i for i in items if i["publication"]["platform"] != "vk"]
        assert vk_items, "живой пост VK должен попасть в подборку"
        assert vk_items[0]["publication"]["url"] == "https://vk.com/wall-101_77"
        assert all("demo" not in i["publication"] for i in vk_items)
        assert demo_items
        assert all(i["publication"]["demo"] is True for i in demo_items)

        preview = (
            await client.get(f"/api/searches/{search_id}/export/preview", headers=headers)
        ).json()
        columns = [c["id"] for c in preview["publications"]["columns"]]
        url_at = columns.index("url")
        platform_at = columns.index("platform")
        for row in preview["publications"]["rows"]:
            if row[platform_at] == "ВКонтакте":
                assert str(row[url_at]).startswith("https://vk.com/wall-")
            else:
                assert row[url_at] == "демо-публикация, ссылки нет"
        data_note = next(
            e["value"] for e in preview["summary"]["entries"] if e["label"] == "Данные"
        )
        assert "ВКонтакте — живые данные" in data_note
        assert "Одноклассники и MAX — пока демонстрационные примеры" in data_note
        assert json.dumps(selection).find(FAKE_KEY) == -1
