"""MAX через сторонний индекс MaxStat (ООО «ФБМ Аналитикс», https://maxstat.ru/api).

Решение Р2: поиск по MAX — только через MaxStat, с сервера, ключом `X-API-Token`
(`MAXSTAT_API_TOKEN`, запасное имя `MAXSTAT_TOKEN`). Включается одной переменной
`DATA_SOURCE_MAX=live` (или общим `DATA_SOURCE=live`), см. `adapters/__init__.py`.

Что проверено живой пробой 20.10.2026 (`server/README.md`, «Паспорт MAX»):
- `GET /v1/posts` — 3 кредита за страницу до 100 постов; несколько слов в `search`
  ищутся вместе («ледостав Енисей» — 0, «ледостав» — 103 за 10 дней), «OR» и «|»
  не работают. Поэтому запрос строится от узкого к широкому (`search_terms`): сначала
  3 главных слова, если выдача меньше страницы — 2, потом одно самое длинное;
- ссылка на пост — `https://max.ru/<канал>/<id из 11 символов>`, id поста MaxStat —
  тот же id, что в ссылке (base64url от int64), время — `published_at` в UTC;
- в посте нет названия канала: название и подписчиков даёт каталог краевых СМИ
  (`data/krai-media.json`, бесплатно) или `GET /v1/channels/{id}` (1 кредит,
  не больше `MAXSTAT_CHANNEL_LOOKUPS` за поиск, кэш на сутки);
- фильтра по региону у поиска нет: регион и тему отбирает воронка (Р4, Р5).

Индекс отстаёт до ~24 ч — `MAX_FRESHNESS` в описании площадки (НТ-4).
Перед каждым платным вызовом — `_spend(<кредиты метода>)` (НТ-6); ответы кэшируются
на `MAXSTAT_CACHE_MINUTES` (Р7: кэш — экономия кредитов, а не источник выдачи).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any

import httpx

from mediamonitor.adapters.base import (
    AdapterDescription,
    AdapterError,
    AdapterEvent,
    AdapterHealth,
    AdapterQuery,
    CallMeter,
    Capped,
    Partial,
    Posts,
    Progress,
    QuotaInfo,
    RawPost,
    SourceInfo,
    SourceProbe,
)
from mediamonitor.adapters.fixture import MAX_FRESHNESS
from mediamonitor.contract import (
    PlatformId,
    QueryKind,
    SourceType,
    TimeReliability,
    source_type,
)
from mediamonitor.normalize.query import STOP_WORDS
from mediamonitor.normalize.text import words
from mediamonitor.normalize.urls import PostRef, parse_address, source_url
from mediamonitor.settings import Settings
from mediamonitor.timeutil import parse_iso, to_krsk

# Цена методов в кредитах (OpenAPI MaxStat, подтверждено заголовком X-Credits-Cost).
COST_SEARCH = 3
COST_POST = 1
COST_CHANNEL = 1
PAGE_SIZE = 100
# offset + limit не больше 10 000 — глубже MaxStat не отдаёт.
DEPTH_LIMIT = 10_000
KEY_ENV = "MAXSTAT_API_TOKEN"
CHANNEL_TTL_SEC = 24 * 3600
HEALTH_TTL_SEC = 60.0
CACHE_MAX_ITEMS = 2_000
TERM_MIN_LENGTH = 4
TERMS_PER_QUERY = 3
# Частые слов пресс-релизов, по которым искать бесполезно (в дополнение к STOP_WORDS).
_EXTRA_STOP = frozenset(
    [
        "также",
        "более",
        "будут",
        "может",
        "можно",
        "этом",
        "этого",
        "которых",
        "которой",
        "котором",
        "своих",
        "своей",
        "время",
        "сегодня",
        "очень",
        "всего",
        "только",
        "кроме",
    ]
)
_POST_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Ники каналов госорганов и организаций края: ИНН начинается с кода региона 24
# (разведка §3.1) — дешёвый признак краевого источника.
_KRAI_SLUG = re.compile(r"^id24\d{8}(?:\d{2})?_(?:gos\d*|biz)$")
NAME = "MAX"


# ---------------------------------------------------------------- разбор ссылок и id


def post_ref(url: str) -> PostRef | None:
    """`https://max.ru/<канал>/<id>` → ключ поста. Канал без ника (`/c/-…`) — None."""
    address = parse_address(url)
    if address is None or address.post is None or address.platform != "max":
        return None
    if not _POST_ID.match(address.post.post_id):
        return None
    return address.post


def maxstat_post_id(post_id: str) -> str | None:
    """id поста в ссылке MAX (base64url от int64) → числовой id поста в MaxStat."""
    if not _POST_ID.match(post_id):
        return None
    try:
        raw = base64.urlsafe_b64decode(post_id + "=")
    except (binascii.Error, ValueError):
        return None
    if len(raw) != 8:
        return None
    return str(int.from_bytes(raw, "big"))


def time_from_post_id(post_id: str) -> datetime | None:
    """Старшие биты id — время публикации в мс (разведка §3.2; недокументировано)."""
    number = maxstat_post_id(post_id)
    if number is None:
        return None
    millis = int(number) >> 16
    try:
        return datetime.fromtimestamp(millis // 1000, tz=UTC) + timedelta(
            milliseconds=millis % 1000
        )
    except (OverflowError, OSError, ValueError):
        return None


def channel_slug(url: str | None) -> str | None:
    """Ссылка на канал → ник. Приглашение (`max.ru/join/…`) и канал без ника — None."""
    if not url:
        return None
    address = parse_address(url)
    if address is None or address.platform != "max" or address.kind != "group":
        return None
    slug = address.slug
    if slug is None or slug in {"join", "c"}:
        return None
    return slug


# ---------------------------------------------------------------- каталог краевых СМИ


@lru_cache(maxsize=1)
def max_catalog() -> dict[str, SourceInfo]:
    """Каналы MAX краевых СМИ из `data/krai-media.json`: ник → источник.

    Ссылки-приглашения (`max.ru/join/…`, вид `invite`) пропускаются: это приватные
    каналы без ника, их посты в публичном индексе не ищутся.
    """
    raw = json.loads(
        resources.files("mediamonitor.data").joinpath("krai-media.json").read_text("utf-8")
    )
    result: dict[str, SourceInfo] = {}
    for media in raw.get("media", []):
        link = (media.get("links") or {}).get("max")
        if not isinstance(link, dict) or link.get("kind") == "invite":
            continue
        slug = channel_slug(link.get("url"))
        if slug is None:
            continue
        subscribers = (media.get("subscribers") or {}).get("max")
        result[slug] = SourceInfo(
            platform="max",
            owner_id=slug,
            slug=slug,
            name=str(media.get("name") or slug),
            url=source_url("max", slug, slug),
            subscribers=subscribers if isinstance(subscribers, int) else None,
            type=source_type(media.get("type")),
            district=media.get("district"),
            regional=True,
            in_catalog=True,
        )
    return result


# ---------------------------------------------------------------- запрос к индексу


def search_terms(text: str, kind: QueryKind) -> list[str]:
    """Запросы к MaxStat от узкого к широкому.

    MaxStat ищет все слова запроса вместе, «или» не понимает. Берём главные слова:
    у темы и события — по порядку, у текста релиза — самые частые. Варианты: 3 слова,
    2 слова, одно самое длинное (обычно самое редкое). Регион в запрос не добавляем:
    слово «Красноярск» отсекло бы посты, где край назван иначе (Р4 — у себя).
    """
    tokens = [
        w
        for w in words(text)
        if len(w) >= TERM_MIN_LENGTH
        and not w.isdigit()
        and w not in STOP_WORDS
        and w not in _EXTRA_STOP
    ]
    if not tokens:
        return []
    if kind == "news-text":
        counts = Counter(tokens)
        first: dict[str, int] = {}
        for index, token in enumerate(tokens):
            first.setdefault(token, index)
        ranked = sorted(counts, key=lambda w: (-counts[w], first[w]))
    else:
        ranked = list(dict.fromkeys(tokens))
    top = ranked[:TERMS_PER_QUERY]
    variants = [" ".join(top[:n]) for n in range(len(top), 1, -1)]
    variants.append(max(top, key=len))
    return list(dict.fromkeys(variants))


# ---------------------------------------------------------------- кэш (Р7)


class TtlCache[V]:
    """Кэш в памяти процесса с временем жизни и пределом размера."""

    def __init__(self, ttl_sec: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_sec = ttl_sec
        self._clock = clock
        self._items: dict[Any, tuple[float, V]] = {}

    def get(self, key: Any) -> V | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires, value = item
        if self._clock() >= expires:
            del self._items[key]
            return None
        return value

    def put(self, key: Any, value: V) -> None:
        if self.ttl_sec <= 0:
            return
        if len(self._items) >= CACHE_MAX_ITEMS:
            now = self._clock()
            self._items = {k: v for k, v in self._items.items() if v[0] > now}
            while len(self._items) >= CACHE_MAX_ITEMS:
                del self._items[next(iter(self._items))]
        self._items[key] = (self._clock() + self.ttl_sec, value)


@dataclass(frozen=True)
class SearchPage:
    total: int
    posts: tuple[dict[str, Any], ...]


# ---------------------------------------------------------------- ошибки


def _no_key() -> AdapterError:
    return AdapterError(
        "key-invalid",
        f"Нет доступа к {NAME}: на сервере не задан ключ MaxStat ({KEY_ENV}). "
        "Сообщите дежурному стенда.",
        retryable=False,
        state="no-access",
    )


def _unavailable() -> AdapterError:
    return AdapterError(
        "unavailable",
        f"{NAME} сейчас недоступен: индекс MaxStat не отвечает. Найденное на других "
        f"площадках сохранено — повторите поиск по {NAME} позже.",
        retryable=True,
    )


def _rate_limited() -> AdapterError:
    return AdapterError(
        "rate-limited",
        f"MaxStat ограничил частоту запросов к {NAME}. Повторите поиск по {NAME} через минуту.",
        retryable=True,
    )


def _bad_response() -> AdapterError:
    return AdapterError(
        "bad-response",
        f"Ответ MaxStat о {NAME} не удалось разобрать. Это ошибка, а не «ничего не найдено» — "
        "повторите позже.",
        retryable=True,
    )


def _error_for(status: int, body: dict[str, Any]) -> AdapterError:
    code = str(body.get("code") or "")
    if status == 401:
        return AdapterError(
            "key-invalid",
            f"Нет доступа к {NAME}: MaxStat не принял ключ (недействителен или отозван). "
            "Сообщите дежурному стенда.",
            retryable=False,
            state="no-access",
        )
    if status == 403:
        return AdapterError(
            "key-invalid",
            f"Нет доступа к {NAME}: аккаунт MaxStat отключён. Сообщите дежурному стенда.",
            retryable=False,
            state="no-access",
        )
    if status == 402:
        what = (
            "нет оплаченного периода"
            if code == "billing_required"
            else "кредиты на этот период закончились"
        )
        return AdapterError(
            "quota-exhausted",
            f"Нет доступа к {NAME}: в MaxStat {what}. Поиск по {NAME} заработает, когда "
            "кредиты обновятся; найденное на других площадках сохранено.",
            retryable=False,
            state="no-access",
        )
    if status == 422:
        return AdapterError(
            "bad-response",
            f"MaxStat не принял параметры запроса к {NAME}. Это ошибка сервера, а не "
            "«ничего не найдено» — сообщите дежурному стенда.",
            retryable=False,
        )
    return _unavailable()


# ---------------------------------------------------------------- адаптер


Sleep = Callable[[float], Awaitable[None]]


class MaxAdapter:
    """MAX: поиск по индексу MaxStat, пост по ключу, сведения о канале."""

    platform: PlatformId = "max"
    key_env = KEY_ENV

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        budget: CallMeter | None = None,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.client = client
        self.budget = budget
        self._sleep = sleep
        cache_sec = settings.maxstat_cache_minutes * 60
        self._pages: TtlCache[SearchPage] = TtlCache(cache_sec, clock)
        self._posts: TtlCache[dict[str, Any]] = TtlCache(cache_sec, clock)
        self._channels: TtlCache[SourceInfo] = TtlCache(CHANNEL_TTL_SEC, clock)
        self._health: TtlCache[AdapterHealth] = TtlCache(HEALTH_TTL_SEC, clock)
        # Сколько кредитов списал MaxStat по заголовку X-Credits-Cost (для проверки цен).
        self.credits_reported = 0
        self.description = AdapterDescription(
            platform="max",
            via="Сторонний индекс MaxStat (ООО «ФБМ Аналитикс»)",
            freshness=MAX_FRESHNESS,
            quota=QuotaInfo(limit=settings.maxstat_credits, unit="кредитов", period="month"),
        )

    # ------------------------------------------------------------ вызовы API

    def _token(self) -> str:
        if self.settings.maxstat_token is None:
            raise _no_key()
        return self.settings.maxstat_token.get_secret_value()

    async def _spend(self, amount: int) -> None:
        """Перед каждым платным вызовом (НТ-6): нет бюджета — AdapterError, вызова нет."""
        if self.budget is not None and amount > 0:
            await self.budget.spend(self.platform, amount)

    async def _get(
        self, path: str, params: dict[str, str | int] | None, *, cost: int, missing_ok: bool = False
    ) -> dict[str, Any] | None:
        """GET к MaxStat с повторами при 429, 5xx и сбоях сети. 404 при `missing_ok` — None."""
        headers = {"X-API-Token": self._token(), "Accept": "application/json"}
        await self._spend(cost)
        url = self.settings.maxstat_base_url.rstrip("/") + path
        error: AdapterError = _unavailable()
        retry_after: float | None = None
        for attempt in range(self.settings.maxstat_retries + 1):
            if attempt:
                pause = 0.5 * 2 ** (attempt - 1) if retry_after is None else min(retry_after, 5.0)
                await self._sleep(pause)
            try:
                response = await self.client.get(
                    url, params=params, headers=headers, timeout=self.settings.maxstat_timeout_sec
                )
            except httpx.HTTPError:
                error, retry_after = _unavailable(), None
                continue
            status = response.status_code
            if status == 200:
                return self._json(response)
            if status == 404 and missing_ok:
                return None
            if status == 429 or status >= 500:
                error = _rate_limited() if status == 429 else _unavailable()
                retry_after = _retry_after(response)
                continue
            raise _error_for(status, _safe_json(response))
        raise error

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise _bad_response() from exc
        if not isinstance(data, dict):
            raise _bad_response()
        cost = response.headers.get("x-credits-cost")
        if cost is not None and cost.isdigit():
            self.credits_reported += int(cost)
        return data

    async def _search_page(
        self, term: str, date_from: str, date_to: str, offset: int
    ) -> SearchPage:
        params: dict[str, str | int] = {
            "search": term,
            "date_from": date_from,
            "date_to": date_to,
            "is_deleted": "false",
            "order_by": "score",
            "order": "desc",
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        key = tuple(sorted(params.items()))
        cached = self._pages.get(key)
        if cached is not None:
            return cached
        data = await self._get("/v1/posts", params, cost=COST_SEARCH)
        if data is None:
            raise _bad_response()
        total, posts = data.get("total"), data.get("posts")
        if not isinstance(total, int) or not isinstance(posts, list):
            raise _bad_response()
        page = SearchPage(total, tuple(p for p in posts if isinstance(p, dict)))
        if len(page.posts) != len(posts):
            raise _bad_response()
        self._pages.put(key, page)
        for post in page.posts:
            self._posts.put(str(post.get("id")), post)
        return page

    # ------------------------------------------------------------ источники

    async def _channel(self, channel_id: str, slug: str, lookups: list[int]) -> SourceInfo:
        """Канал поста: каталог края (бесплатно) → кэш → MaxStat (1 кредит) → по нику."""
        known = max_catalog().get(slug) or self._channels.get(channel_id)
        if known is not None:
            return known
        if lookups[0] > 0:
            lookups[0] -= 1
            try:
                data = await self._get(
                    f"/v1/channels/{channel_id}", None, cost=COST_CHANNEL, missing_ok=True
                )
            except AdapterError as error:
                if error.code in ("quota-exhausted", "key-invalid"):
                    lookups[0] = 0
                data = None
            if data is not None:
                info = _channel_info(data, slug)
                self._channels.put(channel_id, info)
                return info
        return _bare_channel(slug)

    async def _raw_posts(
        self, items: Sequence[dict[str, Any]], lookups: list[int]
    ) -> list[RawPost]:
        result = []
        for item in items:
            parsed = _parse_post(item)
            if parsed is None:
                continue
            ref, channel_id = parsed
            source = await self._channel(channel_id, ref.owner_id, lookups)
            result.append(_raw_post(item, ref, source))
        return result

    # ------------------------------------------------------------ интерфейс площадки

    async def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        self._token()
        wanted: set[str] | None = None
        if query.sources is not None:
            wanted = {(s.slug or s.owner_id).lower() for s in query.sources if s.platform == "max"}
        pages_total = self.settings.maxstat_max_pages
        terms = search_terms(query.text, query.kind)
        if not terms or (wanted is not None and not wanted):
            yield Progress(0, 0, "pages")
            return
        date_from = query.start.astimezone(UTC).date().isoformat()
        date_to = to_krsk(query.end).date().isoformat()
        lookups = [self.settings.maxstat_channel_lookups]
        seen: set[str] = set()
        pages_used = 0
        found = 0
        cap: Capped | None = None
        yield Progress(0, pages_total, "pages")
        try:
            for term in terms:
                offset = 0
                page = SearchPage(0, ())
                while pages_used < pages_total:
                    page = await self._search_page(term, date_from, date_to, offset)
                    pages_used += 1
                    fresh = []
                    for item in page.posts:
                        parsed = _parse_post(item)
                        if parsed is None or parsed[0].id in seen:
                            continue
                        if wanted is not None and parsed[0].owner_id not in wanted:
                            continue
                        seen.add(parsed[0].id)
                        fresh.append(item)
                    raws = [
                        p for p in await self._raw_posts(fresh, lookups) if _in_period(p, query)
                    ]
                    yield Progress(pages_used, pages_total, "pages")
                    if raws:
                        found += len(raws)
                        yield Posts(raws)
                    offset += PAGE_SIZE
                    if offset >= page.total or not page.posts or offset + PAGE_SIZE > DEPTH_LIMIT:
                        break
                if offset < page.total and pages_used >= pages_total:
                    cap = Capped(
                        offset,
                        f"MaxStat нашёл {page.total} публикаций по словам «{term}»; просмотрены "
                        f"{offset} самых близких к запросу — предел стенда {pages_total} "
                        "стр. на поиск",
                    )
                # Узкий запрос дал хотя бы страницу — расширять не нужно.
                if page.total >= PAGE_SIZE or pages_used >= pages_total:
                    break
        except AdapterError as error:
            if found and error.code in ("quota-exhausted", "rate-limited"):
                yield Partial(error.code, error.message, error.retryable)
                return
            raise
        yield Progress(pages_total, pages_total, "pages")
        if cap is not None:
            yield cap

    async def fetch_post(self, ref: PostRef) -> RawPost | None:
        """Пост по ключу через MaxStat: 1 кредит, свежий из поиска — из кэша без платы."""
        self._token()
        number = maxstat_post_id(ref.post_id)
        if ref.platform != "max" or number is None:
            return None
        item = self._posts.get(number)
        if item is None:
            item = await self._get(f"/v1/posts/{number}", None, cost=COST_POST, missing_ok=True)
            if item is None:
                return None
            self._posts.put(number, item)
        if item.get("is_deleted") is True:
            return None
        parsed = _parse_post(item)
        if parsed is None or parsed[0].owner_id != ref.owner_id.lower():
            return None
        # Канал — только из каталога и кэша: перепроверка ссылок подборки не тратит кредиты
        # на названия каналов (иначе по кредиту на каждый новый канал).
        source = await self._channel(parsed[1], parsed[0].owner_id, [0])
        return _raw_post(item, parsed[0], source)

    async def probe_source(self, url: str) -> SourceProbe:
        """Ссылка на канал. Каталог края и кэш — без вызовов; приглашения не поддерживаются."""
        address = parse_address(url)
        if address is None or address.platform != "max":
            return SourceProbe("not-supported", None)
        if address.post is not None:
            known = max_catalog().get(address.post.owner_id)
            return SourceProbe("post-link", known, address.post)
        slug = channel_slug(url)
        if slug is None:
            return SourceProbe("not-supported", None)
        known = max_catalog().get(slug)
        if known is not None:
            return SourceProbe("ok", known)
        # Поиск каналов MaxStat по нику не находит канал (проба 20.10: «eniseytv» — 0),
        # поэтому существование канала здесь не проверяется: ссылка принимается по формату.
        return SourceProbe("ok", _bare_channel(slug))

    async def health(self) -> AdapterHealth:
        """Бесплатный `GET /v1/account/limits`: ключ принят и сколько кредитов осталось."""
        if self.settings.maxstat_token is None:
            return AdapterHealth("down", _no_key().message)
        cached = self._health.get("limits")
        if cached is not None:
            return cached
        try:
            data = await self._get("/v1/account/limits", None, cost=0)
        except AdapterError as error:
            result = AdapterHealth("down", error.message)
        else:
            remaining = (data or {}).get("remaining_credits")
            if not isinstance(remaining, int):
                result = AdapterHealth("degraded", _bad_response().message)
            elif remaining < COST_SEARCH:
                result = AdapterHealth(
                    "down",
                    f"Кредиты MaxStat на этот период закончились: поиск по {NAME} недоступен "
                    "до их обновления.",
                )
            else:
                result = AdapterHealth(
                    "ok", f"MaxStat отвечает: осталось {remaining} кредитов в периоде."
                )
        self._health.put("limits", result)
        return result


# ---------------------------------------------------------------- разбор ответа


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_post(item: dict[str, Any]) -> tuple[PostRef, str] | None:
    """Ключ поста и id канала. Ссылка не в формате `max.ru/<ник>/<id>` — пропускаем."""
    url, channel_id = item.get("url"), item.get("channel_id")
    if not isinstance(url, str) or channel_id is None:
        return None
    ref = post_ref(url)
    if ref is None:
        return None
    return ref, str(channel_id)


def _raw_post(item: dict[str, Any], ref: PostRef, source: SourceInfo) -> RawPost:
    published: datetime | None = None
    reliability: TimeReliability = "unknown"
    value = item.get("published_at")
    if isinstance(value, str):
        try:
            published, reliability = parse_iso(value), "exact"
        except ValueError:
            published = None
    if published is None:
        # Нет времени в ответе — берём из id поста: это расчёт, а не данные площадки (П4).
        published = time_from_post_id(ref.post_id)
        reliability = "approximate" if published is not None else "unknown"
    text = item.get("text")
    views, likes = item.get("views"), item.get("likes")
    return RawPost(
        ref=ref,
        source=source,
        text=text if isinstance(text, str) and text.strip() else None,
        title=None,
        published_at=published,
        time_reliability=reliability,
        edited=False,
        repost_of=None,
        has_media=bool(item.get("attachments")),
        views=views if isinstance(views, int) else None,
        reactions=likes if isinstance(likes, int) else None,
    )


def _guess_type(slug: str, categories: object) -> SourceType:
    if "_gos" in slug:
        return "authority"
    if isinstance(categories, list) and any("СМИ" in str(c) for c in categories):
        return "media"
    return "community"


def _bare_channel(slug: str) -> SourceInfo:
    """Канал, о котором известен только ник."""
    return SourceInfo(
        platform="max",
        owner_id=slug,
        slug=slug,
        name=f"max.ru/{slug}",
        url=source_url("max", slug, slug),
        subscribers=None,
        type=_guess_type(slug, None),
        regional=bool(_KRAI_SLUG.match(slug)),
    )


def _channel_info(data: dict[str, Any], slug: str) -> SourceInfo:
    name = data.get("name")
    subscribers = data.get("subscribers")
    description = data.get("description")
    return SourceInfo(
        platform="max",
        owner_id=slug,
        slug=slug,
        name=name if isinstance(name, str) and name.strip() else f"max.ru/{slug}",
        url=source_url("max", slug, slug),
        subscribers=subscribers if isinstance(subscribers, int) else None,
        type=_guess_type(slug, data.get("categories")),
        regional=bool(_KRAI_SLUG.match(slug)),
        closed=data.get("access") == "private",
        description=description[:500] if isinstance(description, str) else "",
    )


def _in_period(post: RawPost, query: AdapterQuery) -> bool:
    if post.published_at is None:
        return True
    return query.start <= post.published_at <= query.end
