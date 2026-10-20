"""Площадка «Дзен»: каналы редакций края на Дзене (второй шаг варианта Б разведки).

Что берём (`docs/research/zen-and-sites.md` §3, проверено с ноутбука 20.10.2026):
- данные страницы канала через её же JSON-адрес
  `dzen.ru/api/web/v1/channel?channel_name=<имя>|channel_id=<id>&referrer_place=layout` —
  20 последних публикаций: заголовок, начало текста (у коротких постов — весь текст),
  точное время, просмотры, ссылка. Дальше — адрес `feedData.more.link` из ответа (листание),
  не больше `DZEN_MAX_PAGES` страниц на канал;
- страница публикации `dzen.ru/a/<id>` или `/b/<id>` — полный текст и просмотры; только для
  проверки ссылки и «добавить по ссылке».
RSS и открытого API у Дзена нет, поиск Дзена — это поиск Яндекса, robots.txt закрывает его
для программ: не пользуемся. Входы — внутренние и недокументированные, правила Дзена
(п. 5.1) прямо не разрешают копирование: это серая зона, как у Одноклассников, — поэтому
площадка за переключателем `DZEN_SOURCE` и так подписана в интерфейсе и «паспорте».

Первый заход на страницу публикации Дзен переадресует на проверку входа Яндекса и VK и
сам ставит куки «проверка сделана». На чужие адреса мы не ходим: повторяем запрос к dzen.ru
с этими куками. Поменялся формат ответа — `bad-response`, а не «ничего не найдено» (НТ-5).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from typing import Any
from urllib.parse import urlencode, urlsplit

from mediamonitor.adapters.base import (
    AdapterDescription,
    AdapterError,
    AdapterEvent,
    AdapterHealth,
    AdapterQuery,
    Partial,
    Posts,
    Progress,
    RawPost,
    SourceInfo,
    SourceProbe,
)
from mediamonitor.adapters.web import FetchError, Page, PoliteFetcher
from mediamonitor.contract import HealthState, PlatformId, ProblemCode
from mediamonitor.media import DzenEntry, MediaCatalog
from mediamonitor.normalize.urls import PostRef, parse_address
from mediamonitor.timeutil import utcnow

log = logging.getLogger(__name__)

DZEN_HOST = "dzen.ru"
JSON_ACCEPT = "application/json,text/plain;q=0.9,*/*;q=0.8"
_SSO_HOSTS = ("passport.yandex", "login.vk.", "id.vk.", "sso.dzen.ru")
_ITEM_ID = re.compile(r"^https://dzen\.ru/(a|b)/([A-Za-z0-9_\-]{6,64})")
MAX_NAMES = 5


class DzenFormatError(Exception):
    """Ответ Дзена не похож на ожидаемый: поменялся формат."""


@dataclass
class DzenConfig:
    deadline_sec: float = 60.0
    max_pages: int = 3


@dataclass
class _Channel:
    entry: DzenEntry
    info: SourceInfo
    more: str | None = None
    oldest: datetime | None = None
    pages: int = 0
    problem: str | None = None


@dataclass
class _Run:
    at: float
    checked: int
    failed: list[str] = field(default_factory=list)


def _moment(value: Any) -> datetime | None:
    """Секунды или миллисекунды с 1970 года (строка или число) → момент в UTC."""
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    if number > 10**11:
        number //= 1000
    try:
        return datetime.fromtimestamp(number, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _rich_text(value: Any) -> str:
    """Текст короткого поста: `rich_text.json[*]` с типом `text`."""
    if not isinstance(value, dict):
        return ""
    parts = [
        str(part.get("data") or "")
        for part in value.get("json") or []
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    return "\n".join(p.strip() for p in parts if p.strip())


def parse_channel(data: Any) -> tuple[list[dict[str, Any]], str | None, int | None]:
    """Ответ JSON-адреса канала → публикации, адрес следующей страницы, подписчики."""
    if not isinstance(data, dict):
        raise DzenFormatError("ответ канала — не объект")
    # Первая страница — `feedData.items`, следующие (`channel-more`) — `items` сверху.
    feed = data.get("feedData", data)
    if not isinstance(feed, dict) or not isinstance(feed.get("items"), list):
        raise DzenFormatError("в ответе канала нет feedData.items")
    more = feed.get("more")
    link = more.get("link") if isinstance(more, dict) else None
    subscribers = None
    channel = data.get("channel")
    if isinstance(channel, dict) and isinstance(channel.get("source"), dict):
        subscribers = _count(channel["source"].get("subscribers"))
    items = [i for i in feed["items"] if isinstance(i, dict)]
    return items, str(link) if isinstance(link, str) else None, subscribers


@dataclass(frozen=True)
class DzenItem:
    kind: str  # a — статья, b — короткий пост
    item_id: str
    title: str | None
    text: str
    published_at: datetime | None
    views: int | None
    likes: int | None
    has_media: bool


def parse_item(raw: dict[str, Any]) -> DzenItem | None:
    """Публикация из ленты канала; видео, подборки и прочие блоки — None."""
    kind = raw.get("type")
    if kind == "article":
        link = raw.get("shareLink")
        when = raw.get("publicationDate")
        title = str(raw.get("title") or "").strip() or None
        text = str(raw.get("text") or "").strip()
        media = isinstance(raw.get("image"), dict)
    elif kind == "brief":
        link = raw.get("share_link")
        when = raw.get("publication_date")
        title = None
        text = _rich_text(raw.get("rich_text"))
        media = bool(raw.get("items"))
    else:
        return None
    match = _ITEM_ID.match(str(link or ""))
    if match is None:
        return None
    social = raw.get("socialInfo") if isinstance(raw.get("socialInfo"), dict) else {}
    return DzenItem(
        kind=match.group(1),
        item_id=match.group(2),
        title=title,
        text=text,
        published_at=_moment(when),
        views=_count(raw.get("views")),
        likes=_count((social or {}).get("likesCount")),
        has_media=media,
    )


# ---------------------------------------------------------------- страница публикации

_META = re.compile(r'<meta\s+property="og:(title|description)"\s+content="([^"]*)"', re.IGNORECASE)
_PUBLICATION = re.compile(
    r'"publication":\{"id":"([0-9a-f]{12,40})",'
    r'"publisherId":"([0-9a-f]{12,40})"'
)
_PUBLISH_TIME = re.compile(r'"publishTime":(\d{10,13})')
_VIEWS = re.compile(r'"publicationStatistics":\{"views":(\d+)')
_PUBLISHER = re.compile(r'"publisher":\{"id":"([0-9a-f]{12,40})","name":"((?:[^"\\]|\\.)*)"')
_AUTHOR_PREFIX = re.compile(r"^(?:Статья|Пост|Видео) автора «[^»]*» в Дзене\s*✍?:\s*")


@dataclass(frozen=True)
class DzenPage:
    publisher_id: str
    publisher_name: str | None
    title: str | None
    text: str
    published_at: datetime | None
    views: int | None


def _content_text(markup: str) -> str:
    marker = '"contentState":'
    index = markup.find(marker)
    if index < 0:
        return ""
    try:
        value, _ = json.JSONDecoder().raw_decode(markup, index + len(marker))
        state = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return ""
    if not isinstance(state, dict):
        return ""
    draft = state.get("draftJsState")
    if isinstance(draft, dict):
        blocks = draft.get("blocks") or []
        texts = [str(b.get("text") or "").strip() for b in blocks if isinstance(b, dict)]
        return "\n".join(t for t in texts if t)
    return _rich_text(state.get("rich_text"))


def parse_publication_page(markup: str) -> DzenPage:
    publication = _PUBLICATION.search(markup)
    if publication is None:
        raise DzenFormatError("на странице нет данных публикации")
    meta = {name.lower(): unescape(value) for name, value in _META.findall(markup)}
    publisher = _PUBLISHER.search(markup)
    name = json.loads(f'"{publisher.group(2)}"') if publisher else None
    when = _PUBLISH_TIME.search(markup[publication.start() : publication.start() + 2000])
    views = _VIEWS.search(markup)
    text = _content_text(markup) or _AUTHOR_PREFIX.sub("", meta.get("description", ""))
    title = meta.get("title") or None
    if title and name and title == name:
        title = None  # у короткого поста og:title — название канала
    return DzenPage(
        publisher_id=publication.group(2),
        publisher_name=name,
        title=title,
        text=text,
        published_at=_moment(when.group(1)) if when else None,
        views=int(views.group(1)) if views else None,
    )


class DzenAdapter:
    """Каналы редакций края на Дзене (только из каталога края)."""

    platform: PlatformId = "dzen"

    def __init__(
        self,
        catalog: MediaCatalog,
        fetcher: PoliteFetcher,
        config: DzenConfig | None = None,
        *,
        via: str = "Страницы каналов редакций края на Дзене",
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.catalog = catalog
        self.fetcher = fetcher
        self.config = config or DzenConfig()
        self._now = now
        self._last: _Run | None = None
        self.description = AdapterDescription(platform="dzen", via=via, note=catalog.dzen_note())

    # ------------------------------------------------------------ источники

    def source_info(self, entry: DzenEntry, subscribers: int | None = None) -> SourceInfo:
        return SourceInfo(
            platform="dzen",
            owner_id=entry.publisher_id,
            slug=entry.channel_name.lower() if entry.channel_name else None,
            name=entry.name,
            url=entry.url,
            subscribers=subscribers if subscribers is not None else entry.subscribers,
            type="media",
            district=entry.district,
            regional=True,
            in_catalog=True,
            closed=entry.state == "not-found",
            description=entry.description(),
            last_post_at=entry.last_post_at,
        )

    def catalog_sources(self) -> list[SourceInfo]:
        return [self.source_info(entry) for entry in self.catalog.channels]

    def _targets(self, query: AdapterQuery) -> tuple[list[DzenEntry], list[str]]:
        if query.sources is None:
            chosen = [
                c
                for c in self.catalog.channels
                if c.state == "ok"
                or (
                    c.state == "inactive"
                    and c.last_post_at is not None
                    and c.last_post_at >= query.start
                )
            ]
            return chosen, []
        targets: list[DzenEntry] = []
        skipped: list[str] = []
        for source in query.sources:
            if source.platform != "dzen":
                continue
            entry = self.catalog.channel(source.owner_id, source.slug)
            if entry is None or entry.state == "not-found":
                skipped.append(f"«{source.name}» — канала нет на Дзене")
            elif entry not in targets:
                targets.append(entry)
        return targets, skipped

    # ------------------------------------------------------------ запросы к dzen.ru

    async def _get(self, url: str, *, accept: str, use_cache: bool) -> Page:
        """GET dzen.ru без переходов на чужие адреса: проверка входа ставит куки сама."""
        for _ in range(3):
            page = await self.fetcher.get(
                url, site=DZEN_HOST, follow=False, use_cache=use_cache, accept=accept
            )
            if not (300 <= page.status < 400):
                return page
            target = page.location or ""
            host = urlsplit(target).hostname or ""
            if any(mark in host for mark in _SSO_HOSTS):
                continue  # куки «проверка сделана» уже стоят — повторяем свой запрос
            if host in ("", DZEN_HOST, f"www.{DZEN_HOST}") and target:
                url = target if host else f"https://{DZEN_HOST}{target}"
                continue
            raise FetchError("redirect", "Дзен переадресует на чужой адрес — туда не ходим")
        raise FetchError("redirect", "Дзен просит войти — без входа страница недоступна")

    def _channel_url(self, entry: DzenEntry) -> str:
        key = (
            {"channel_name": entry.channel_name}
            if entry.channel_name
            else {"channel_id": entry.publisher_id}
        )
        params = {**key, "country_code": "ru", "lang": "ru", "referrer_place": "layout"}
        return f"https://{DZEN_HOST}/api/web/v1/channel?{urlencode(params)}"

    async def _page(self, channel: _Channel, url: str, query: AdapterQuery) -> list[RawPost]:
        page = await self._get(url, accept=JSON_ACCEPT, use_cache=True)
        if page.status == 404:
            raise FetchError("status", "канал не найден", 404)
        if page.status != 200:
            raise FetchError("status", f"ответил с ошибкой {page.status}", page.status)
        try:
            data = json.loads(page.text)
        except ValueError as error:
            raise DzenFormatError("ответ канала — не JSON") from error
        items, more, subscribers = parse_channel(data)
        if subscribers is not None:
            channel.info = self.source_info(channel.entry, subscribers)
        channel.pages += 1
        more_host = urlsplit(more).hostname if more else None
        channel.more = more if more_host == DZEN_HOST else None
        posts: list[RawPost] = []
        for raw in items:
            item = parse_item(raw)
            if item is None:
                continue
            if item.published_at is not None:
                channel.oldest = min(channel.oldest or item.published_at, item.published_at)
            if item.published_at is not None and not (
                query.start <= item.published_at <= query.end
            ):
                continue
            posts.append(self._post(channel, item))
        return posts

    def _post(self, channel: _Channel, item: DzenItem) -> RawPost:
        return RawPost(
            ref=PostRef("dzen", channel.entry.publisher_id, f"{item.kind}-{item.item_id}"),
            source=channel.info,
            text=item.text or None,
            title=item.title,
            published_at=item.published_at,
            time_reliability="exact" if item.published_at else "unknown",
            edited=False,
            repost_of=None,
            has_media=item.has_media,
            views=item.views,
            reactions=item.likes,
        )

    # ------------------------------------------------------------ поиск

    async def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        entries, skipped = self._targets(query)
        channels = [_Channel(e, self.source_info(e)) for e in entries]
        total = len(channels)
        yield Progress(0, total, "sources")
        deadline = time.monotonic() + self.config.deadline_sec
        done = 0
        # Сначала первая страница каждого канала, потом — листание тех, кому не хватило.
        for channel in channels:
            if time.monotonic() >= deadline:
                channel.problem = "не успели посмотреть"
                continue
            try:
                async with asyncio.timeout(max(0.1, deadline - time.monotonic())):
                    posts = await self._page(channel, self._channel_url(channel.entry), query)
            except TimeoutError:
                channel.problem = "не успели посмотреть"
                continue
            except FetchError as error:
                channel.problem = error.message
                posts = []
            except DzenFormatError as error:
                log.warning("Дзен, канал %s: %s", channel.entry.publisher_id, error)
                channel.problem = "ответ в непонятном формате"
                posts = []
            done += 1
            if posts:
                yield Posts(posts)
            yield Progress(done, total, "sources", channel.entry.name)
        short: list[_Channel] = []
        for channel in channels:
            while (
                channel.problem is None
                and channel.more
                and channel.oldest is not None
                and channel.oldest > query.start
                and channel.pages < self.config.max_pages
            ):
                if time.monotonic() >= deadline:
                    short.append(channel)
                    break
                try:
                    async with asyncio.timeout(max(0.1, deadline - time.monotonic())):
                        posts = await self._page(channel, channel.more, query)
                except (TimeoutError, FetchError, DzenFormatError):
                    short.append(channel)
                    break
                if posts:
                    yield Posts(posts)
        failed = [c for c in channels if c.problem]
        self._last = _Run(time.monotonic(), total, [c.entry.name for c in failed])
        formats = [c for c in failed if c.problem == "ответ в непонятном формате"]
        if total and len(failed) == total:
            if len(formats) == total:
                raise AdapterError(
                    "bad-response",
                    "Дзен ответил в непонятном формате: похоже, страница канала поменялась. "
                    "Это ошибка, а не «ничего не найдено».",
                    retryable=True,
                )
            raise AdapterError(
                "unavailable",
                "Дзен не ответил. Найденное на других площадках сохранено — повторите поиск "
                "по Дзену позже.",
                retryable=True,
            )
        parts: list[str] = []
        if failed:
            names = "; ".join(f"«{c.entry.name}» — {c.problem}" for c in failed[:MAX_NAMES])
            more_names = f" и ещё {len(failed) - MAX_NAMES}" if len(failed) > MAX_NAMES else ""
            parts.append(f"Не открылись каналы {len(failed)} из {total}: {names}{more_names}.")
        if short:
            parts.append(
                f"У {len(short)} каналов не успели долистать до начала периода — "
                "повторите поиск, чтобы досмотреть."
            )
        if skipped:
            parts.append(f"Не опрашиваются: {'; '.join(skipped)}.")
        if parts:
            code: ProblemCode = (
                "unavailable" if failed else "timeout" if short else "sources-closed"
            )
            yield Partial(code, " ".join(parts), retryable=bool(failed or short))

    # ------------------------------------------------------------ пост, источник, здоровье
    async def aclose(self) -> None:
        await self.fetcher.client.aclose()

    async def fetch_post(self, ref: PostRef) -> RawPost | None:
        kind, _, number = ref.post_id.partition("-")
        if kind not in ("a", "b") or not number:
            return None
        url = f"https://{DZEN_HOST}/{kind}/{number}"
        try:
            page = await self._get(url, accept="text/html", use_cache=False)
        except FetchError as error:
            raise AdapterError("unavailable", f"Дзен: {error.message}.", retryable=True) from error
        if page.status in (404, 410):
            return None
        if page.status != 200:
            raise AdapterError(
                "unavailable", f"Дзен ответил с ошибкой {page.status}.", retryable=True
            )
        try:
            data = parse_publication_page(page.text)
        except DzenFormatError as error:
            raise AdapterError(
                "bad-response",
                "Страницу публикации Дзена не удалось разобрать: похоже, поменялся формат.",
                retryable=True,
            ) from error
        entry = self.catalog.channel(data.publisher_id)
        if entry is not None:
            info = self.source_info(entry)
        else:
            info = SourceInfo(
                platform="dzen",
                owner_id=data.publisher_id,
                slug=None,
                name=data.publisher_name or "Канал Дзена",
                url=f"https://{DZEN_HOST}/id/{data.publisher_id}",
                subscribers=None,
                type="media",
            )
        return RawPost(
            ref=PostRef("dzen", data.publisher_id, ref.post_id),
            source=info,
            text=data.text or None,
            title=data.title,
            published_at=data.published_at,
            time_reliability="exact" if data.published_at else "unknown",
            edited=False,
            repost_of=None,
            has_media=False,
            views=data.views,
            reactions=None,
        )

    async def probe_source(self, url: str) -> SourceProbe:
        address = parse_address(url)
        if address is None or address.platform != "dzen":
            return SourceProbe("not-supported", None)
        if address.post is not None:
            return SourceProbe("post-link", None, address.post)
        entry = self.catalog.channel(address.owner_id, address.slug)
        if entry is None:
            # Каналы не из каталога края в первой версии честно не поддерживаем.
            return SourceProbe("not-supported", None)
        info = self.source_info(entry)
        if entry.state == "not-found":
            return SourceProbe("not-found", None)
        return SourceProbe("ok", info)

    async def health(self) -> AdapterHealth:
        active = sum(1 for c in self.catalog.channels if c.state == "ok")
        head = f"Каналов в каталоге: {active}."
        run = self._last
        if run is None:
            return AdapterHealth("ok", f"{head} Опрос — в момент поиска, поисков ещё не было.")
        if not run.failed:
            return AdapterHealth("ok", f"{head} Последний опрос: ответили все каналы.")
        state: HealthState = "down" if len(run.failed) >= run.checked else "degraded"
        names = ", ".join(f"«{n}»" for n in run.failed[:MAX_NAMES])
        return AdapterHealth(state, f"{head} Последний опрос: не открылись {names}.")
