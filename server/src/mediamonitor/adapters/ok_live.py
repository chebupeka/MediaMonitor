"""Одноклассники: публичные страницы групп ok.ru без входа и без ключа (Р2, серая зона).

Откуда данные (живая проверка 20.10.2026):
- лента группы — первая страница `https://ok.ru/group/<gid>` (или `ok.ru/<имя>`): последние
  10 постов; у каждого id топика, начало текста, время в ленте (по Москве) и число классов;
- пост — страница `https://ok.ru/group/<gid>/topic/<tid>`: JSON-LD `Article` с полным текстом
  и точной датой (`datePublished`); несуществующий пост — 404.

Чего не делаем (robots.txt ok.ru и m.ok.ru, проверено 20.10.2026):
- не листаем ленту дальше первой страницы: «Показать ещё» идёт через `/dk?…` и `?cmd=…`,
  они закрыты robots.txt; у m.ok.ru и сама лента открывается только через `/dk?…`;
- не ищем по всему OK: `/search/content/` закрыт robots.txt. «Везде» — группы каталога края
  (`data/krai-media.json`), «Мои источники» — группы пользователя. Личные профили не берём;
- не входим и не обходим капчу: увидели капчу, 403 или 429 — площадка «недоступна»,
  и OK не трогаем `BLOCK_PAUSE` секунд.

Вежливость: не чаще 1 запроса в секунду на ok.ru на весь процесс, тайм-аут на запрос,
честный User-Agent продукта. Кэш (Р7, только экономия запросов): лента — 10 минут,
пост — 6 часов. Просмотров постов OK без входа не показывает: `views` всегда None (НТ-24).

Правила OK (пп. 5.16, 7.4.2 лицензионного соглашения) запрещают автоматический сбор без
согласия — осознанный риск прототипа, назван в паспорте источников (`server/README.md`).
"""

from __future__ import annotations

import asyncio
import html as htmllib
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from importlib import resources
from typing import Any, Literal, cast

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
    RawPost,
    SourceInfo,
    SourceProbe,
)
from mediamonitor.contract import PlatformId, ProblemCode
from mediamonitor.normalize.urls import PostRef, parse_address, source_url
from mediamonitor.settings import Settings

log = logging.getLogger(__name__)

OK_ORIGIN = "https://ok.ru"
# Время в ленте ok.ru без входа — московское (сверено с `datePublished` поста).
MSK = timezone(timedelta(hours=3))
# Столько постов отдаёт первая страница ленты группы без входа; дальше — закрыто robots.txt.
FEED_PAGE_SIZE = 10
# Пауза между запросами к ok.ru, секунд: не чаще 1 запроса в секунду на весь процесс.
MIN_INTERVAL_SEC = 1.1
REQUEST_TIMEOUT_SEC = 15.0
# После капчи, 403 или 429 не обращаемся к ok.ru столько секунд.
BLOCK_PAUSE_SEC = 15 * 60
FEED_TTL_SEC = 10 * 60
TOPIC_TTL_SEC = 6 * 60 * 60
MISSING_TTL_SEC = 10 * 60
NOT_A_GROUP_TTL_SEC = 24 * 60 * 60
# Страницы постов (полный текст и точная дата) за один поиск: не больше стольких и только
# пока успеваем обойти ленты всех групп до PLATFORM_TIMEOUT_SEC (с запасом TIME_RESERVE_SEC).
# Сверх этого пост берётся из ленты: начало текста и время ленты (≈). Повторный поиск берёт
# уже полученные посты из кэша.
TOPIC_PAGES_PER_SEARCH = 60
TIME_RESERVE_SEC = 15.0
# Пределы кэшей в памяти процесса (память API): лент групп, страниц постов и сведений о
# группах (имя → id, id → источник). Сверх предела вытесняются самые старые записи.
FEEDS_MAX_ITEMS = 500
TOPICS_MAX_ITEMS = 2_000
KNOWN_MAX_ITEMS = 2_000

_MONTHS = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "мая": 5,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}


class OkParseError(ValueError):
    """Страница ok.ru не похожа на ожидаемую: формат сменился (НТ-5: это не «пусто»)."""


class OkNotAGroupError(OkParseError):
    """По ссылке не группа (личный профиль, раздел сайта)."""


# ---------------------------------------------------------------- каталог


@dataclass(frozen=True)
class OkGroup:
    """Группа OK: числовой id или короткое имя (недостающее узнаём со страницы группы)."""

    name: str
    gid: str | None
    slug: str | None
    district: str | None = None
    subscribers: int | None = None
    in_catalog: bool = False
    regional: bool = False

    @property
    def key(self) -> str:
        return self.gid or f"@{self.slug}"

    @property
    def url(self) -> str:
        if self.gid:
            return f"{OK_ORIGIN}/group/{self.gid}"
        return f"{OK_ORIGIN}/{self.slug}"


def load_catalog_groups() -> list[OkGroup]:
    """Группы OK из каталога СМИ края. Ссылки на личные профили — не группы: пропускаем."""
    raw = json.loads(
        resources.files("mediamonitor.data").joinpath("krai-media.json").read_text("utf-8")
    )
    groups: list[OkGroup] = []
    seen: set[str] = set()
    for media in raw.get("media", []):
        link = (media.get("links") or {}).get("ok")
        if not isinstance(link, dict) or link.get("kind") != "group":
            continue
        gid = str(link["ownerId"]) if link.get("ownerId") else None
        slug = str(link["handle"]).lower() if link.get("handle") else None
        if gid is None and slug is None:
            continue
        group = OkGroup(
            name=str(media.get("name") or gid or slug),
            gid=gid,
            slug=slug,
            district=media.get("district"),
            subscribers=(media.get("subscribers") or {}).get("ok"),
            in_catalog=True,
            regional=True,
        )
        if group.key not in seen:
            seen.add(group.key)
            groups.append(group)
    return groups


# ---------------------------------------------------------------- разбор страниц


@dataclass(frozen=True)
class FeedPost:
    """Пост в ленте группы: начало текста и время ленты (по Москве)."""

    owner_id: str
    topic_id: str
    snippet: str
    shown_at: datetime | None
    # minute — «10:31», «вчера 07:30»; day — «18 окт» (время не показано).
    precision: Literal["minute", "day"]
    reactions: int | None
    has_media: bool


@dataclass(frozen=True)
class GroupPage:
    gid: str
    name: str
    members: int | None
    closed: bool
    posts: tuple[FeedPost, ...]


@dataclass(frozen=True)
class TopicPage:
    owner_id: str
    topic_id: str
    text: str
    published_at: datetime | None
    edited: bool
    author_name: str | None
    has_media: bool


_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_CANONICAL = re.compile(r'<link rel="canonical" href="https://ok\.ru/([^"?#]+)"')
_GROUP_PATH = re.compile(r"^group/(\d+)/?$")
_H1_GROUP = re.compile(r'<h1 class="group-name_h"[^>]*>(.*?)</h1>', re.S)
_OG_TITLE = re.compile(r'<meta property="og:title" content="([^"]*)"')
_MEMBERS = re.compile(r'Участники<span class="portlet_h_count">([^<]+)<')
_TOPIC_MARK = re.compile(r'data-l="topicId,(\d+),groupId,(\d+)"')
_TIME = re.compile(r"<time[^>]*>(.*?)</time>", re.S)
_TEXT_BLOCK = re.compile(r'class="media-text_cnt_tx[^"]*"[^>]*>(.*?)</div>', re.S)
_REACTIONS = re.compile(r'<button[^>]*\bdata-cnt="(\d+)"[^>]*__reactions')
_REACTIONS_TEXT = re.compile(r'js-reactions">\s*([\d\s\xa0]+)\s*класс')
_MEDIA = re.compile(r'class="media-block media-(?:video|photos?|photo-[a-z]+|link)\b')
_LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_CLOSED = re.compile(r"(?i)\bэто\s+закрытая\s+группа|закрытая\s+группа")
# Признаки страницы капчи или защиты от ботов — только в разметке, без скриптов (в скриптах
# обычных страниц есть строки переводов «captcha_empty» и т. п.). Слова вроде «не робот»
# не берём: они бывают в текстах постов.
_CAPTCHA = re.compile(r"""(?i)name=["']st\.ccode["']|(?:id|class|name)=["'][^"']*captcha""")
_FEED_TIME = re.compile(r"^(?:(сегодня|вчера)\s+)?(\d{1,2}):(\d{2})$")
_FEED_DATE = re.compile(
    r"^(\d{1,2})\s+([а-я]{3})[а-я]*\.?(?:\s+(\d{4}))?(?:\s+(?:в\s+)?(\d{1,2}):(\d{2}))?$"
)


def _text(fragment: str) -> str:
    return _SPACE.sub(" ", htmllib.unescape(_TAG.sub(" ", fragment))).strip()


def _digits(value: str) -> int | None:
    digits = re.sub(r"\D", "", htmllib.unescape(value))
    return int(digits) if digits else None


def visible_html(page: str) -> str:
    """Разметка без скриптов и стилей: признаки ищем только в том, что видит человек."""
    return _SCRIPT.sub(" ", page)


def is_captcha(page: str) -> bool:
    """Капча: её поле в разметке или страница без canonical, где упомянута капча."""
    visible = visible_html(page)
    if _CAPTCHA.search(visible):
        return True
    return _CANONICAL.search(page) is None and "captcha" in visible.lower()


def parse_feed_time(value: str, now: datetime) -> tuple[datetime | None, Literal["minute", "day"]]:
    """Время в ленте ok.ru («10:31», «вчера 07:30», «18 окт», «3 мар 2025») → момент в UTC."""
    text = _SPACE.sub(" ", htmllib.unescape(value).replace("\xa0", " ")).strip().lower()
    local = now.astimezone(MSK)
    match = _FEED_TIME.match(text)
    if match:
        day = local.date() - timedelta(days=1 if match.group(1) == "вчера" else 0)
        hour, minute = int(match.group(2)), int(match.group(3))
        if hour > 23 or minute > 59:
            return None, "day"
        moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK)
        return moment.astimezone(UTC), "minute"
    match = _FEED_DATE.match(text)
    if match:
        month = _MONTHS.get(match.group(2)[:3])
        if month is None:
            return None, "day"
        year = int(match.group(3)) if match.group(3) else local.year
        hour = int(match.group(4)) if match.group(4) else 0
        minute = int(match.group(5)) if match.group(5) else 0
        try:
            moment = datetime(year, month, int(match.group(1)), hour, minute, tzinfo=MSK)
        except ValueError:
            return None, "day"
        if not match.group(3) and moment > local + timedelta(days=1):
            moment = moment.replace(year=year - 1)  # «28 дек» в январе — прошлый год
        precision: Literal["minute", "day"] = "minute" if match.group(4) else "day"
        return moment.astimezone(UTC), precision
    return None, "day"


def parse_group_page(page: str, now: datetime) -> GroupPage:
    """Страница группы → id, название, участники, закрыта ли, посты первой страницы ленты."""
    canonical = _CANONICAL.search(page)
    if canonical is None:
        raise OkParseError("нет canonical-ссылки")
    path = canonical.group(1)
    group = _GROUP_PATH.match(path)
    if group is None:
        if path.startswith("profile/"):
            raise OkNotAGroupError("личный профиль, а не группа")
        raise OkNotAGroupError(f"не группа: /{path}")
    gid = group.group(1)
    title = _H1_GROUP.search(page)
    name = _text(title.group(1)) if title else ""
    if not name:
        og = _OG_TITLE.search(page)
        name = htmllib.unescape(og.group(1)).split(" | ")[0].strip() if og else ""
    if not name:
        raise OkParseError("нет названия группы")
    members_match = _MEMBERS.search(page)
    members = _digits(members_match.group(1)) if members_match else None

    posts: list[FeedPost] = []
    seen: set[str] = set()
    for block in page.split('class="feed-w"')[1:]:
        mark = _TOPIC_MARK.search(block)
        if mark is None:
            continue  # видео или фото без топика — не пост
        topic_id, owner_id = mark.group(1), mark.group(2)
        if owner_id != gid or topic_id in seen:
            continue  # чужой топик в ленте (рекомендация) или повтор
        seen.add(topic_id)
        text_match = _TEXT_BLOCK.search(block)
        snippet = _text(text_match.group(1)) if text_match else ""
        snippet = re.sub(r"\s*(?:\.\.\.|…)\s*$", "", snippet)
        time_match = _TIME.search(block)
        shown_at, precision = (
            parse_feed_time(_text(time_match.group(1)), now) if time_match else (None, "day")
        )
        reactions_match = _REACTIONS.search(block) or _REACTIONS_TEXT.search(block)
        posts.append(
            FeedPost(
                owner_id=gid,
                topic_id=topic_id,
                snippet=snippet,
                shown_at=shown_at,
                precision=precision,
                reactions=_digits(reactions_match.group(1)) if reactions_match else None,
                has_media=bool(_MEDIA.search(block)),
            )
        )
    visible = visible_html(page)
    marks = {m.group(1) for m in _TOPIC_MARK.finditer(page) if m.group(2) == gid}
    if marks and not posts:
        # Топики в разметке есть, а разобрать не вышло — формат ленты сменился (НТ-5).
        raise OkParseError("лента группы не разобрана")
    closed = not posts and bool(_CLOSED.search(_text(visible)))
    return GroupPage(gid=gid, name=name, members=members, closed=closed, posts=tuple(posts))


def _ld_items(page: str) -> Iterable[dict[str, Any]]:
    for match in _LD_JSON.finditer(page):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        stack: list[Any] = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                yield item
                if "@graph" in item:
                    stack.append(item["@graph"])


def parse_topic_page(page: str) -> TopicPage:
    """Страница поста → полный текст и точная дата из JSON-LD `Article`."""
    article = next((i for i in _ld_items(page) if i.get("@type") == "Article"), None)
    if article is None:
        raise OkParseError("нет JSON-LD Article")
    url = article.get("url")
    if not isinstance(url, str):
        canonical = _CANONICAL.search(page)
        url = f"{OK_ORIGIN}/{canonical.group(1)}" if canonical else ""
    address = parse_address(url)
    if address is None or address.post is None:
        raise OkParseError("нет ссылки на пост")
    body = article.get("articleBody")
    if not isinstance(body, str):
        body = article.get("headline") if isinstance(article.get("headline"), str) else ""
    published = _iso(article.get("datePublished"))
    modified = _iso(article.get("dateModified"))
    authors = article.get("author")
    author = authors[0] if isinstance(authors, list) and authors else authors
    author_name = author.get("name") if isinstance(author, dict) else None
    return TopicPage(
        owner_id=address.post.owner_id,
        topic_id=address.post.post_id,
        text=str(body).strip(),
        published_at=published,
        edited=published is not None and modified is not None and modified > published,
        author_name=author_name if isinstance(author_name, str) else None,
        has_media=bool(article.get("image") or article.get("video")),
    )


def _iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MSK)
    return parsed.astimezone(UTC)


# ---------------------------------------------------------------- вежливость и кэш


class _Throttle:
    """Не чаще одного запроса в `interval` секунд на всех, кто делит адаптер."""

    def __init__(self, interval: float, clock: Callable[[], float]) -> None:
        self.interval = interval
        self._clock = clock
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = self._clock()
            delay = self._next - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next = max(now, self._next) + self.interval


class _TtlCache[T]:
    def __init__(self, ttl: float, clock: Callable[[], float], max_items: int = 5_000) -> None:
        self.ttl = ttl
        self._clock = clock
        self._max = max_items
        self._items: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        item = self._items.get(key)
        if item is None:
            return None
        if item[0] < self._clock():
            del self._items[key]
            return None
        return item[1]

    def __len__(self) -> int:
        return len(self._items)

    def put(self, key: str, value: T, ttl: float | None = None) -> None:
        self._items.pop(key, None)
        if len(self._items) >= self._max:
            for old in list(self._items)[: self._max // 10 or 1]:
                del self._items[old]
        self._items[key] = (self._clock() + (self.ttl if ttl is None else ttl), value)


def _bounded_set[V](items: dict[str, V], key: str, value: V) -> None:
    """Запись в словарь сведений не больше KNOWN_MAX_ITEMS: самые старые вытесняются."""
    items.pop(key, None)
    items[key] = value
    while len(items) > KNOWN_MAX_ITEMS:
        del items[next(iter(items))]


@dataclass(frozen=True)
class _Missing:
    """Отметка в кэше: группы или поста нет (404)."""


_MISSING = _Missing()


# ---------------------------------------------------------------- адаптер


class OkAdapter:
    """Одноклассники: публичные страницы групп ok.ru (без входа, без ключа)."""

    platform: PlatformId = "ok"

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        budget: CallMeter | None = None,
        *,
        groups: Sequence[OkGroup] | None = None,
        min_interval_sec: float = MIN_INTERVAL_SEC,
        topic_pages_per_search: int = TOPIC_PAGES_PER_SEARCH,
        search_budget_sec: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        del budget  # OK бесплатен: вызовы не списываются, вежливость — паузой между запросами
        self.settings = settings
        self.client = client
        self.groups = list(load_catalog_groups() if groups is None else groups)
        self.topic_pages_per_search = topic_pages_per_search
        self.search_budget_sec = (
            max(10.0, settings.platform_timeout_sec - TIME_RESERVE_SEC)
            if search_budget_sec is None
            else search_budget_sec
        )
        self.min_interval_sec = min_interval_sec
        # Средняя длительность запроса к ok.ru (с паузой): по ней считаем, успеем ли.
        self._request_sec = min_interval_sec
        self._clock = clock
        self._now = now
        self._throttle = _Throttle(min_interval_sec, clock)
        self._feeds: _TtlCache[GroupPage | _Missing] = _TtlCache(
            FEED_TTL_SEC, clock, FEEDS_MAX_ITEMS
        )
        self._topics: _TtlCache[TopicPage | _Missing] = _TtlCache(
            TOPIC_TTL_SEC, clock, TOPICS_MAX_ITEMS
        )
        # Короткое имя → id группы и сведения о группе для fetch_post (без лишних запросов).
        self._gids: dict[str, str] = {}
        self._known: dict[str, SourceInfo] = {}
        self._reactions: _TtlCache[int] = _TtlCache(TOPIC_TTL_SEC, clock)
        self._blocked_until = 0.0
        self._last_problem: str | None = None
        self._headers = {
            "User-Agent": (
                f"MediaMonitor/{settings.app_version} (regional media monitoring prototype; "
                f"+{settings.public_app_url})"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }
        self.description = AdapterDescription(
            platform="ok",
            via=f"Публичные страницы групп ok.ru без входа ({len(self.groups)} групп каталога)",
            tags=["без ключа", "серая зона"],
        )

    # ------------------------------------------------------------ HTTP

    def _blocked_error(self) -> AdapterError:
        minutes = max(1, round((self._blocked_until - self._clock()) / 60))
        return AdapterError(
            "unavailable",
            "Одноклассники попросили подтвердить, что запросы не от робота. Обходить проверку "
            f"не будем: OK недоступны, повторите через {minutes} мин. Найденное сохранено.",
            retryable=True,
        )

    def _block(self, reason: str) -> None:
        self._blocked_until = self._clock() + BLOCK_PAUSE_SEC
        self._last_problem = reason
        log.warning("OK: %s — пауза %d с", reason, BLOCK_PAUSE_SEC)

    async def _get(self, url: str) -> httpx.Response:
        if self._clock() < self._blocked_until:
            raise self._blocked_error()
        await self._throttle.wait()
        sent = self._clock()
        try:
            response = await self.client.get(
                url,
                headers=self._headers,
                timeout=REQUEST_TIMEOUT_SEC,
                follow_redirects=True,
            )
        except httpx.TimeoutException as exc:
            self._last_problem = "тайм-аут"
            raise AdapterError(
                "timeout",
                f"Одноклассники не ответили за {REQUEST_TIMEOUT_SEC:.0f} с. Найденное "
                "сохранено — повторите поиск по площадке.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            self._last_problem = "нет связи"
            raise AdapterError(
                "unavailable",
                "Одноклассники недоступны: нет связи с ok.ru. Найденное сохранено — "
                "повторите позже.",
                retryable=True,
            ) from exc
        spent = max(self.min_interval_sec, self._clock() - sent)
        self._request_sec = 0.7 * self._request_sec + 0.3 * spent
        status = response.status_code
        if status in (403, 429) or (status == 200 and is_captcha(response.text)):
            self._block("капча или защита от ботов" if status != 429 else "429")
            if status == 429:
                raise AdapterError(
                    "rate-limited",
                    "Одноклассники просят реже обращаться к сайту. Найденное сохранено — "
                    "повторите через 15 минут.",
                    retryable=True,
                )
            raise self._blocked_error()
        if status >= 500 or (status != 404 and status >= 400):
            self._last_problem = f"HTTP {status}"
            raise AdapterError(
                "unavailable",
                f"Одноклассники ответили ошибкой {status}. Найденное сохранено — повторите позже.",
                retryable=True,
            )
        self._last_problem = None
        return response

    # ------------------------------------------------------------ страницы

    async def _group_page(self, group: OkGroup) -> GroupPage | None:
        """Страница группы из кэша или с ok.ru. None — группы нет (404 или удалена)."""
        key = group.gid or self._gids.get(group.slug or "") or f"@{group.slug}"
        cached = self._feeds.get(key)
        if cached is not None:
            return None if isinstance(cached, _Missing) else cached
        url = f"{OK_ORIGIN}/group/{key}" if key.isdigit() else group.url
        response = await self._get(url)
        if response.status_code == 404:
            self._feeds.put(key, _MISSING, MISSING_TTL_SEC)
            return None
        try:
            page = parse_group_page(response.text, self._now())
        except OkNotAGroupError:
            # Короткое имя ведёт на личный профиль: до завтра не спрашиваем.
            self._feeds.put(key, _MISSING, NOT_A_GROUP_TTL_SEC)
            raise
        if group.slug:
            _bounded_set(self._gids, group.slug, page.gid)
        self._feeds.put(page.gid, page)
        for post in page.posts:
            if post.reactions is not None:
                self._reactions.put(f"{post.owner_id}_{post.topic_id}", post.reactions)
        return page

    async def _topic_page(self, owner_id: str, topic_id: str) -> TopicPage | None:
        key = f"{owner_id}_{topic_id}"
        cached = self._topics.get(key)
        if cached is not None:
            return None if isinstance(cached, _Missing) else cached
        response = await self._get(f"{OK_ORIGIN}/group/{owner_id}/topic/{topic_id}")
        if response.status_code == 404:
            self._topics.put(key, _MISSING, MISSING_TTL_SEC)
            return None
        try:
            topic = parse_topic_page(response.text)
        except OkParseError as exc:
            raise AdapterError(
                "bad-response",
                "Страницу поста Одноклассников не удалось разобрать: формат сменился. Это "
                "ошибка, а не «ничего не найдено».",
                retryable=True,
            ) from exc
        self._topics.put(key, topic)
        return topic

    def _source(self, page: GroupPage, group: OkGroup) -> SourceInfo:
        info = SourceInfo(
            platform="ok",
            owner_id=page.gid,
            slug=None,
            name=page.name or group.name,
            url=source_url("ok", page.gid, None),
            subscribers=page.members if page.members is not None else group.subscribers,
            type="media" if group.in_catalog else "community",
            district=group.district,
            regional=group.regional,
            in_catalog=group.in_catalog,
            closed=page.closed,
        )
        _bounded_set(self._known, page.gid, info)
        return info

    # ------------------------------------------------------------ поиск

    def _targets(self, query: AdapterQuery) -> list[OkGroup]:
        if query.sources is None:
            return list(self.groups)
        catalog = {g.gid: g for g in self.groups if g.gid}
        catalog_slugs = {g.slug: g for g in self.groups if g.slug}
        targets: list[OkGroup] = []
        for source in query.sources:
            if source.platform != "ok":
                continue
            owner = source.owner_id if source.owner_id.isdigit() else None
            slug = source.slug or (None if owner else source.owner_id.lower())
            known = catalog.get(owner or "") or catalog_slugs.get(slug or "")
            targets.append(
                OkGroup(
                    name=source.name,
                    gid=owner or (known.gid if known else None),
                    slug=slug,
                    district=source.district or (known.district if known else None),
                    subscribers=source.subscribers,
                    in_catalog=known is not None,
                    regional=source.regional or known is not None,
                )
            )
        return targets

    async def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        targets = self._targets(query)
        total = len(targets)
        started = self._clock()
        pages_left = self.topic_pages_per_search
        closed: list[str] = []
        missing: list[str] = []
        broken: list[str] = []
        deeper = 0
        for index, group in enumerate(targets):
            yield Progress(index, total, "sources", group.name)
            try:
                page = await self._group_page(group)
            except OkParseError as exc:
                log.warning("OK: страница группы %s не разобрана: %s", group.url, exc)
                (missing if isinstance(exc, OkNotAGroupError) else broken).append(group.name)
                continue
            if page is None:
                missing.append(group.name)
                continue
            source = self._source(page, group)
            if page.closed:
                closed.append(group.name)
                continue
            if (
                len(page.posts) >= FEED_PAGE_SIZE
                and page.posts[-1].shown_at is not None
                and page.posts[-1].shown_at > query.start
            ):
                deeper += 1  # период глубже первой страницы ленты: ранние посты не видны
            # Страницы постов делим поровну между группами: время, которое останется после
            # лент оставшихся групп, — на эту и следующие (недобранное переходит дальше).
            left = total - index - 1
            per_request = max(self._request_sec, 0.05)
            spare = self.search_budget_sec - (self._clock() - started) - left * per_request
            share = min(pages_left, max(0, int(spare / per_request / (left + 1))))
            batch: list[RawPost] = []
            for post in page.posts:
                if not _maybe_in_period(post, query):
                    continue
                key = f"{post.owner_id}_{post.topic_id}"
                topic: TopicPage | _Missing | None = self._topics.get(key)
                if topic is None and share > 0:
                    share -= 1
                    pages_left -= 1
                    topic = await self._topic_page(post.owner_id, post.topic_id) or _MISSING
                if isinstance(topic, _Missing):
                    continue  # пост удалён между лентой и страницей поста
                raw = (
                    _from_topic(topic, source, post.reactions)
                    if topic is not None
                    else _from_feed(post, source)
                )
                exact = raw.time_reliability == "exact" and raw.published_at is not None
                if exact and not query.start <= cast(datetime, raw.published_at) <= query.end:
                    continue
                batch.append(raw)
            if batch:
                yield Posts(batch)
        yield Progress(total, total, "sources", None)
        if deeper:
            yield Capped(
                FEED_PAGE_SIZE,
                f"Одноклассники без входа показывают только {FEED_PAGE_SIZE} последних постов "
                f"группы: у {_groups(deeper)} период глубже, более ранние посты не видны",
            )
        if broken and len(broken) == total:
            raise AdapterError(
                "bad-response",
                "Страницы групп Одноклассников не удалось разобрать: формат сменился. Это "
                "ошибка, а не «ничего не найдено».",
                retryable=True,
            )
        problem = _summary(closed, missing, broken)
        if problem is not None:
            yield problem

    # ------------------------------------------------------------ пост и источник

    async def fetch_post(self, ref: PostRef) -> RawPost | None:
        topic = await self._topic_page(ref.owner_id, ref.post_id)
        if topic is None:
            return None
        source = self._known.get(topic.owner_id) or SourceInfo(
            platform="ok",
            owner_id=topic.owner_id,
            slug=None,
            name=topic.author_name or f"Группа {topic.owner_id}",
            url=source_url("ok", topic.owner_id, None),
            subscribers=None,
        )
        reactions = self._reactions.get(f"{topic.owner_id}_{topic.topic_id}")
        return _from_topic(topic, source, reactions)

    async def probe_source(self, url: str) -> SourceProbe:
        address = parse_address(url)
        if address is None or address.platform != "ok":
            return SourceProbe("not-supported", None)
        if address.post is not None:
            return SourceProbe("post-link", self._known.get(address.post.owner_id), address.post)
        catalog = next(
            (
                g
                for g in self.groups
                if (address.owner_id and g.gid == address.owner_id)
                or (address.slug and g.slug == address.slug)
            ),
            None,
        )
        group = catalog or OkGroup(
            name=address.slug or address.owner_id or url,
            gid=address.owner_id,
            slug=address.slug,
        )
        try:
            page = await self._group_page(group)
        except OkNotAGroupError:
            return SourceProbe("not-supported", None)
        except OkParseError as exc:
            raise AdapterError(
                "bad-response",
                "Страницу группы Одноклассников не удалось разобрать: формат сменился.",
                retryable=True,
            ) from exc
        if page is None:
            return SourceProbe("not-found", None)
        info = self._source(page, group)
        if page.closed:
            return SourceProbe("closed", replace(info, closed=True))
        return SourceProbe("ok", info)

    async def health(self) -> AdapterHealth:
        """Без запросов к ok.ru: по последнему ответу (страница стенда опрашивается часто)."""
        if self._clock() < self._blocked_until:
            return AdapterHealth("down", self._blocked_error().message)
        if self._last_problem is not None:
            return AdapterHealth(
                "degraded", f"Последний запрос к ok.ru не удался: {self._last_problem}."
            )
        return AdapterHealth(
            "ok",
            f"Публичные страницы {len(self.groups)} групп каталога края, без входа; "
            "не чаще 1 запроса в секунду.",
        )


def _maybe_in_period(post: FeedPost, query: AdapterQuery) -> bool:
    """По времени ленты: может ли пост попасть в период (точную дату даст страница поста)."""
    if post.shown_at is None:
        return True
    span = timedelta(minutes=1) if post.precision == "minute" else timedelta(days=1)
    return post.shown_at + span > query.start and post.shown_at <= query.end


def _from_topic(topic: TopicPage, source: SourceInfo, reactions: int | None) -> RawPost:
    return RawPost(
        ref=PostRef("ok", topic.owner_id, topic.topic_id),
        source=source,
        text=topic.text or None,
        title=None,
        published_at=topic.published_at,
        time_reliability="exact" if topic.published_at is not None else "unknown",
        edited=topic.edited,
        repost_of=None,
        has_media=topic.has_media,
        views=None,
        reactions=reactions,
    )


def _from_feed(post: FeedPost, source: SourceInfo) -> RawPost:
    """Пост только из ленты: начало текста и время ленты — дата приблизительная (≈)."""
    return RawPost(
        ref=PostRef("ok", post.owner_id, post.topic_id),
        source=source,
        text=post.snippet or None,
        title=None,
        published_at=post.shown_at,
        time_reliability="approximate" if post.shown_at is not None else "unknown",
        edited=False,
        repost_of=None,
        has_media=post.has_media,
        views=None,
        reactions=post.reactions,
    )


def _groups(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} группы"
    return f"{count} групп"


def _names(names: Sequence[str]) -> str:
    shown = ", ".join(f"«{n}»" for n in names[:5])
    return shown + (f" и ещё {len(names) - 5}" if len(names) > 5 else "")


def _summary(closed: list[str], missing: list[str], broken: list[str]) -> Partial | None:
    """Одно предупреждение на поиск: что из списка групп не удалось посмотреть."""
    parts: list[str] = []
    code: ProblemCode = "sources-closed"
    if broken:
        code = "bad-response"
        parts.append(f"страницы не разобраны (формат сменился): {_names(broken)}")
    if closed:
        parts.append(f"закрыты: {_names(closed)}")
    if missing:
        parts.append(f"не найдены или это не группы: {_names(missing)}")
    if not parts:
        return None
    message = "Часть групп OK не просмотрена — " + "; ".join(parts) + ". Остальные проверены."
    return Partial(code, message, retryable=bool(broken))
