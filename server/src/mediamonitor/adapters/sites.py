"""Площадка «Сайты СМИ»: сайты районных и краевых газет края (ТЗ-Ф17, вариант Б разведки).

Как ищем (`docs/research/zen-and-sites.md` §2, §4.1), в момент поиска (Р7):
1. Лента RSS сайта (`/rss/` у «битрикс-платформы», `/rss.xml` у «Енисея») — 20–40
   последних материалов с полным текстом и точным временем. У 4 сайтов платформы ленты
   нет — читаем раздел `/news/` (карточки с временем) и страницы статей.
2. Если лента не дотянулась до начала периода — добор поиском по сайту
   (`/search/?q=…&how=d`, robots.txt разрешает; только первая страница — листание
   запрещено). Найденное в периоде дочитываем со страницы статьи (не больше
   `SITES_ARTICLES_PER_SITE` на сайт и `SITES_MAX_ARTICLES` на поиск); остальное — по
   заголовку и отрывку из выдачи, время «приблизительное» (известна только дата).
3. Сайты — параллельно, но не чаще 1 запроса в секунду на сайт и не больше
   `SOURCES_PER_IP` одновременно к общему серверу платформы (`adapters/web.py`).
Сайт не ответил или ответил непонятно — площадка «частично» с названиями сайтов, а не
ошибка всей площадки; не ответил ни один — «ошибка». Сайты, которые нельзя опрашивать
(не открываются, заброшены, robots.txt закрывает ленту), — в оговорке статуса.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

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
from mediamonitor.adapters.site_parse import (
    Card,
    FeedItem,
    ParseError,
    parse_article,
    parse_cards,
    parse_feed,
)
from mediamonitor.adapters.web import HTML_ACCEPT, FetchError, Page, PoliteFetcher
from mediamonitor.contract import HealthState, PlatformId
from mediamonitor.media import MediaCatalog, SiteEntry
from mediamonitor.normalize.query import STOP_WORDS, release_of
from mediamonitor.normalize.text import words
from mediamonitor.normalize.urls import PostRef, parse_address, post_url
from mediamonitor.timeutil import to_krsk, utcnow

log = logging.getLogger(__name__)

FEED_ACCEPT = "application/rss+xml,application/atom+xml,application/xml;q=0.9,text/xml;q=0.8"
MAX_NAMES = 5
# Слова края в запросе сайту не помогают: все сайты и так краевые.
_REGION_WORD = re.compile(r"^(краснояр|красноярск|край|края|краю|краем|крае)", re.IGNORECASE)


@dataclass
class SitesConfig:
    deadline_sec: float = 50.0
    articles_per_site: int = 4
    max_articles: int = 40


@dataclass
class _Budget:
    """Сколько страниц статей ещё можно открыть за этот поиск (вежливость и скорость)."""

    articles: int

    def take(self) -> bool:
        if self.articles <= 0:
            return False
        self.articles -= 1
        return True


@dataclass
class _SiteResult:
    posts: list[RawPost] = field(default_factory=list)
    problem: str | None = None  # лента или раздел новостей не получены — сайт не проверен
    shallow: str | None = None  # проверена только лента: поиск по сайту не ответил


@dataclass
class _Run:
    """Итог последнего опроса для страницы стенда."""

    at: float
    checked: int
    failed: list[str]


def search_phrase(text: str, kind: str) -> str | None:
    """Слова для поиска по сайту: тема — как есть (до 5 значимых слов), текст новости —
    заголовок. Регион и служебные слова убираем: все сайты и так краевые."""
    source = release_of(text).title if kind == "news-text" else text
    picked: list[str] = []
    for word in words(source):
        if len(word) < 3 or word in STOP_WORDS or word.isdigit() or _REGION_WORD.match(word):
            continue
        if word not in picked:
            picked.append(word)
        if len(picked) == 5:
            break
    return " ".join(picked) or None


def _names(items: Sequence[str]) -> str:
    shown = ", ".join(f"«{n}»" for n in items[:MAX_NAMES])
    rest = len(items) - MAX_NAMES
    return f"{shown} и ещё {rest}" if rest > 0 else shown


def _sites(value: int) -> str:
    tail = value % 100
    if value % 10 == 1 and tail != 11:
        return f"{value} сайт"
    if 2 <= value % 10 <= 4 and not 12 <= tail <= 14:
        return f"{value} сайта"
    return f"{value} сайтов"


class SitesAdapter:
    """Сайты СМИ из каталога края: ленты, разделы новостей, поиск и страницы статей."""

    platform: PlatformId = "site"

    def __init__(
        self,
        catalog: MediaCatalog,
        fetcher: PoliteFetcher,
        config: SitesConfig | None = None,
        *,
        via: str = "Ленты RSS, разделы новостей и поиск на сайтах СМИ края",
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.catalog = catalog
        self.fetcher = fetcher
        self.config = config or SitesConfig()
        self._now = now
        self._last: _Run | None = None
        self.description = AdapterDescription(platform="site", via=via, note=catalog.sites_note())

    # ------------------------------------------------------------ каталог и источники

    def source_info(self, site: SiteEntry) -> SourceInfo:
        return SourceInfo(
            platform="site",
            owner_id=site.owner,
            slug=None,
            name=site.name,
            url=site.base_url,
            subscribers=None,
            type="media",
            district=site.district,
            regional=True,
            in_catalog=True,
            closed=not site.polled,
            description=site.description(),
        )

    def catalog_sources(self) -> list[SourceInfo]:
        return [self.source_info(site) for site in self.catalog.sites]

    def _targets(self, query: AdapterQuery) -> tuple[list[SiteEntry], list[str]]:
        """Какие сайты опрашиваем и какие из списка пользователя опросить нельзя."""
        if query.sources is None:
            return list(self.catalog.polled_sites), []
        targets: list[SiteEntry] = []
        skipped: list[str] = []
        for source in query.sources:
            if source.platform != "site":
                continue
            site = self.catalog.site_by_owner(source.owner_id)
            if site is None or not site.polled:
                reason = site.off_reason if site and site.off_reason else "сайта нет в каталоге"
                skipped.append(f"«{source.name}» — {reason}")
            elif site not in targets:
                targets.append(site)
        return targets, skipped

    # ------------------------------------------------------------ поиск

    async def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        targets, skipped = self._targets(query)
        total = len(targets)
        yield Progress(0, total, "sources")
        budget = _Budget(self.config.max_articles)
        tasks = {
            asyncio.create_task(self._scan(site, query, budget), name=f"site-{site.owner}"): site
            for site in targets
        }
        pending = set(tasks)
        failed: list[str] = []
        late: list[str] = []
        shallow: list[str] = []
        found = 0
        done_count = 0
        deadline = time.monotonic() + self.config.deadline_sec
        try:
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                done, pending = await asyncio.wait(
                    pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    site = tasks[task]
                    done_count += 1
                    result = task.result()
                    if result.problem:
                        failed.append(f"«{site.name}» — {result.problem}")
                    elif result.shallow:
                        shallow.append(f"«{site.name}»")
                    if result.posts:
                        found += len(result.posts)
                        yield Posts(result.posts)
                    yield Progress(done_count, total, "sources", site.name)
        finally:
            for task in pending:
                task.cancel()
                late.append(f"«{tasks[task].name}» — не успел ответить")
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        problems = failed + late
        self._last = _Run(time.monotonic(), total, [p.split(" — ")[0] for p in problems])
        if total and len(problems) == total:
            raise AdapterError(
                "unavailable",
                f"Сайты СМИ не ответили: {_names([p.split(' — ')[0] for p in problems])}. "
                "Найденное на других площадках сохранено — повторите поиск по сайтам позже.",
                retryable=True,
            )
        if problems or skipped or shallow:
            parts = []
            if problems:
                parts.append(
                    f"Не ответили {_sites(len(problems))} из {total}: "
                    f"{'; '.join(problems[:MAX_NAMES])}"
                    + (f" и ещё {len(problems) - MAX_NAMES}" if len(problems) > MAX_NAMES else "")
                    + ". Остальные проверены."
                )
            if shallow:
                parts.append(
                    f"У {_sites(len(shallow))} проверена только лента последних материалов: "
                    f"поиск по сайту не ответил ({_names([n.strip('«»') for n in shallow])})."
                )
            if skipped:
                parts.append(f"Не опрашиваются: {'; '.join(skipped)}.")
            yield Partial(
                "sources-closed" if skipped and not (problems or shallow) else "unavailable",
                " ".join(parts),
                retryable=bool(problems or shallow),
            )

    async def _scan(self, site: SiteEntry, query: AdapterQuery, budget: _Budget) -> _SiteResult:
        result = _SiteResult()
        info = self.source_info(site)
        known: set[str] = set()
        oldest: datetime | None = None
        try:
            if site.mode == "rss" and site.feed_url:
                page = await self._get(site, site.feed_url, accept=FEED_ACCEPT)
                items = parse_feed(page.text)
                for item in items:
                    post = self._feed_post(site, info, item)
                    if post is None:
                        continue
                    known.add(post.ref.post_id)
                    if item.published_at is not None:
                        oldest = min(oldest or item.published_at, item.published_at)
                    if _in_period(post.published_at, query):
                        result.posts.append(post)
            elif site.mode == "news-list" and site.list_url:
                page = await self._get(site, site.list_url)
                cards = parse_cards(page.text, self._now())
                if not cards:
                    raise ParseError("в разделе новостей нет карточек")
                fresh = [c for c in cards if c.date is not None]
                if fresh:
                    oldest = min(c.date.moment for c in fresh if c.date is not None)
                result.posts += await self._cards(
                    site, info, cards, query, budget=budget, known=known
                )
        except FetchError as error:
            result.problem = error.message
            return result
        except ParseError as error:
            log.warning("Сайт %s: ответ не разобран: %s", site.owner, error)
            result.problem = "ответ не удалось разобрать"
            return result
        # Добор поиском по сайту, если лента или раздел не дотянулись до начала периода.
        phrase = search_phrase(query.text, query.kind)
        if site.search_url and phrase and (oldest is None or oldest > query.start):
            url = site.search_url.replace("{query}", quote(phrase))
            try:
                page = await self._get(site, url)
                cards = parse_cards(page.text, self._now())
                result.posts += await self._cards(
                    site, info, cards, query, budget=budget, known=known
                )
            except FetchError as error:
                result.shallow = error.message
            except ParseError as error:
                log.warning("Сайт %s: поиск не разобран: %s", site.owner, error)
                result.shallow = "ответ поиска не удалось разобрать"
        return result

    async def _get(self, site: SiteEntry, url: str, *, accept: str | None = None) -> Page:
        page = await self.fetcher.get(
            url,
            site=site.owner,
            ip=site.ip,
            allowed_hosts=site.aliases,
            accept=accept or HTML_ACCEPT,
        )
        if page.status == 200:
            return page
        if page.status in (403, 429, 503) or 300 <= page.status < 400:
            raise FetchError("status", "закрыт защитой от программ или ограничил частоту")
        if page.status in (404, 410):
            raise FetchError("status", "страница не найдена", page.status)
        raise FetchError("status", f"ответил с ошибкой {page.status}", page.status)

    def _ref(self, site: SiteEntry, link: str) -> PostRef | None:
        address = parse_address(urljoin(site.page_url(""), link))
        if address is None or address.post is None or address.owner_id != site.owner:
            return None
        return address.post

    def _feed_post(self, site: SiteEntry, info: SourceInfo, item: FeedItem) -> RawPost | None:
        ref = self._ref(site, item.link)
        if ref is None:
            return None
        return RawPost(
            ref=ref,
            source=info,
            text=item.text or None,
            title=item.title,
            published_at=item.published_at,
            time_reliability="exact" if item.published_at else "unknown",
            edited=False,
            repost_of=None,
            has_media=item.has_media,
            views=None,  # просмотры есть только на странице статьи
            reactions=None,
            alt_urls=(item.link,) if item.link != post_url(ref) else (),
        )

    async def _cards(
        self,
        site: SiteEntry,
        info: SourceInfo,
        cards: Sequence[Card],
        query: AdapterQuery,
        *,
        budget: _Budget,
        known: set[str],
    ) -> list[RawPost]:
        """Карточки раздела новостей или поиска в периоде: свежие дочитываем со страницы."""
        posts: list[RawPost] = []
        opened = 0
        start_day = to_krsk(query.start).date()
        end_day = to_krsk(query.end).date()
        for card in cards:
            ref = self._ref(site, card.href)
            if ref is None or ref.post_id in known:
                continue
            if card.date is not None:
                day = to_krsk(card.date.moment).date()
                if not start_day <= day <= end_day:
                    continue
            known.add(ref.post_id)
            post: RawPost | None = None
            if site.article_check and opened < self.config.articles_per_site and budget.take():
                opened += 1
                try:
                    post = await self._article(site, info, ref)
                except (FetchError, ParseError):
                    post = None  # статья не открылась — берём то, что есть в карточке
            if post is None:
                exact = card.date is not None and card.date.exact
                post = RawPost(
                    ref=ref,
                    source=info,
                    text=card.summary or None,
                    title=card.title,
                    published_at=card.date.moment if card.date else None,
                    time_reliability="exact" if exact else "approximate",
                    edited=False,
                    repost_of=None,
                    has_media=False,
                    views=None,
                    reactions=None,
                )
            if post.published_at is None or _in_period(post.published_at, query):
                posts.append(post)
        return posts

    async def _article(self, site: SiteEntry, info: SourceInfo, ref: PostRef) -> RawPost:
        page = await self._get(site, site.page_url(ref.post_id))
        article = parse_article(page.text, self._now())
        return RawPost(
            ref=ref,
            source=info,
            text=article.text or None,
            title=article.title,
            published_at=article.published_at,
            time_reliability=(
                "unknown"
                if article.published_at is None
                else "exact"
                if article.exact_time
                else "approximate"
            ),
            edited=False,
            repost_of=None,
            has_media=article.has_media,
            views=article.views,
            reactions=None,
        )

    # ------------------------------------------------------------ пост, источник, здоровье
    async def aclose(self) -> None:
        await self.fetcher.client.aclose()

    async def fetch_post(self, ref: PostRef) -> RawPost | None:
        site = self.catalog.site_by_owner(ref.owner_id)
        if site is None:
            return None
        if not site.polled:
            raise AdapterError(
                "unavailable",
                f"Сайт «{site.name}» не опрашивается: {site.off_reason}.",
                retryable=False,
            )
        if not site.article_check:
            raise AdapterError(
                "unavailable",
                f"Сайт «{site.name}» закрыт защитой от программ: ссылку проверить нельзя.",
                retryable=False,
            )
        try:
            page = await self.fetcher.get(
                site.page_url(ref.post_id),
                site=site.owner,
                ip=site.ip,
                allowed_hosts=site.aliases,
                use_cache=False,
            )
        except FetchError as error:
            raise AdapterError(
                "unavailable", f"Сайт «{site.name}» {error.message}.", retryable=True
            ) from error
        if page.status in (404, 410):
            return None
        if page.status != 200:
            raise AdapterError(
                "unavailable",
                f"Сайт «{site.name}» ответил с ошибкой {page.status}.",
                retryable=True,
            )
        try:
            article = parse_article(page.text, self._now())
        except ParseError as error:
            raise AdapterError(
                "bad-response",
                f"Страницу статьи сайта «{site.name}» не удалось разобрать.",
                retryable=True,
            ) from error
        return RawPost(
            ref=ref,
            source=self.source_info(site),
            text=article.text or None,
            title=article.title,
            published_at=article.published_at,
            time_reliability="exact" if article.exact_time else "approximate",
            edited=False,
            repost_of=None,
            has_media=article.has_media,
            views=article.views,
            reactions=None,
        )

    async def probe_source(self, url: str) -> SourceProbe:
        address = parse_address(url)
        if address is None or address.platform != "site" or address.owner_id is None:
            return SourceProbe("not-supported", None)
        site = self.catalog.site_by_owner(address.owner_id)
        if site is None:
            return SourceProbe("not-supported", None)
        info = self.source_info(site)
        if address.post is not None:
            return SourceProbe("post-link", info, address.post)
        return SourceProbe("ok" if site.polled else "closed", info)

    async def health(self) -> AdapterHealth:
        polled = len(self.catalog.polled_sites)
        head = f"Подключено {_sites(polled)} из {len(self.catalog.sites)}."
        run = self._last
        if run is None:
            return AdapterHealth("ok", f"{head} Опрос — в момент поиска, поисков ещё не было.")
        ago = int((time.monotonic() - run.at) // 60)
        when = "только что" if ago < 1 else f"{ago} мин назад"
        if not run.failed:
            return AdapterHealth("ok", f"{head} Последний опрос ({when}): ответили все.")
        state: HealthState = "down" if len(run.failed) >= run.checked else "degraded"
        return AdapterHealth(
            state,
            f"{head} Последний опрос ({when}): не ответили {_sites(len(run.failed))} — "
            f"{_names([n.strip('«»') for n in run.failed])}.",
        )


def _in_period(moment: datetime | None, query: AdapterQuery) -> bool:
    if moment is None:
        return True  # без даты — показываем с пометкой «дата неизвестна» (ТЗ-Ф36)
    # Дата из поиска по сайту — начало дня: день периода целиком.
    return query.start - timedelta(seconds=1) <= moment <= query.end
