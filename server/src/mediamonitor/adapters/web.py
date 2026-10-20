"""Вежливое чтение публичных страниц: сайты СМИ края и каналы Дзена.

Правила (бриф «Э-Источники», `docs/research/zen-and-sites.md` §2.5, §3.4):
- не чаще 1 запроса в секунду на сайт (`SOURCES_MIN_INTERVAL_SEC`); 42 сайта стоят на
  одном сервере, поэтому ещё и не больше `SOURCES_PER_IP` запросов к нему одновременно;
- тайм-аут на запрос, предел размера ответа, переадресации — только внутри своего сайта:
  на чужие адреса (вход Яндекса и VK у Дзена, посторонний домен) не ходим;
- честный User-Agent продукта со ссылкой на стенд, без личных данных;
- короткий кэш ответов (`SOURCES_CACHE_SEC`, 10 минут): повтор поиска не ходит на сайты
  заново. Это экономия, а не заранее собранная база (Р7): ленты читаются в момент поиска.
Капчи и защиту от программ не обходим: такой ответ — «недоступен» с честной причиной.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

from mediamonitor.media import ascii_host, bare_host

FetchProblem = Literal["timeout", "unavailable", "too-large", "redirect", "status"]
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
Sleep = Callable[[float], Awaitable[None]]


class FetchError(Exception):
    """Страницу получить не удалось: что случилось — простым языком."""

    def __init__(self, kind: FetchProblem, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind: FetchProblem = kind
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Page:
    url: str  # итоговый адрес (после переадресаций внутри сайта)
    status: int
    text: str
    location: str | None = None  # куда переадресовал, если переадресацию не прошли


class HostLimiter:
    """Не чаще одного запроса в `interval` секунд на сайт и `per_ip` одновременно на сервер."""

    def __init__(
        self,
        interval: float,
        per_ip: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.interval = interval
        self.per_ip = per_ip
        self._clock = clock
        self._sleep = sleep
        self._next: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._ip: dict[str, asyncio.Semaphore] = {}

    async def turn(self, host: str) -> None:
        """Дождаться своей очереди к сайту: старты запросов не чаще раза в `interval`."""
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = self._clock()
            start = max(now, self._next.get(host, 0.0))
            self._next[host] = start + self.interval
        if start > now:
            await self._sleep(start - now)

    def ip_gate(self, ip: str | None) -> asyncio.Semaphore | None:
        if ip is None:
            return None
        return self._ip.setdefault(ip, asyncio.Semaphore(self.per_ip))


class TtlCache:
    """Кэш ответов на короткое время (Р7: экономия, не источник выдачи)."""

    def __init__(self, ttl: float, size: int = 512, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self.size = size
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, Page]] = OrderedDict()

    def get(self, key: str) -> Page | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires, page = item
        if expires < self._clock():
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return page

    def put(self, key: str, page: Page) -> None:
        if self.ttl <= 0:
            return
        self._items[key] = (self._clock() + self.ttl, page)
        self._items.move_to_end(key)
        while len(self._items) > self.size:
            self._items.popitem(last=False)


def user_agent(version: str, public_url: str) -> str:
    """Честный User-Agent продукта: имя, версия, адрес стенда. Без личных данных."""
    parts = urlsplit(public_url)
    site = f"{parts.scheme}://{parts.netloc}/" if parts.scheme and parts.netloc else ""
    contact = f"; +{site}" if site else ""
    return f"Mediaradar/{version} (prototype media monitor for Krasnoyarsk Krai news{contact})"


class PoliteFetcher:
    """GET с соблюдением правил выше. Один на адаптер: свои куки и пул соединений."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        limiter: HostLimiter,
        cache: TtlCache,
        *,
        timeout: float,
        max_bytes: int,
    ) -> None:
        self.client = client
        self.limiter = limiter
        self.cache = cache
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.requests = 0  # сколько запросов ушло на площадку (для тестов и стенда)

    async def get(
        self,
        url: str,
        *,
        site: str,
        ip: str | None = None,
        allowed_hosts: frozenset[str] = frozenset(),
        follow: bool = True,
        use_cache: bool = True,
        accept: str = HTML_ACCEPT,
    ) -> Page:
        """Страница по адресу. `site` — ключ сайта для частоты (домен без www).

        Переадресации проходим только на `allowed_hosts` (и тот же домен с www и без);
        `follow=False` — вернуть ответ 3xx как есть (Дзен: проверка входа).
        """
        if use_cache:
            cached = self.cache.get(url)
            if cached is not None:
                return cached
        current = url
        for _ in range(4):
            page = await self._one(current, site=site, ip=ip, accept=accept)
            if not (300 <= page.status < 400 and page.location) or not follow:
                if use_cache and page.status == 200:
                    self.cache.put(url, page)
                return page
            target = urljoin(current, page.location)
            host = ascii_host(urlsplit(target).hostname or "") or ""
            own = {ascii_host(urlsplit(current).hostname or "") or "", *allowed_hosts}
            if bare_host(host) not in {bare_host(h) for h in own if h}:
                raise FetchError(
                    "redirect",
                    "сайт переадресует на чужой адрес — туда не ходим",
                    page.status,
                )
            current = target
        raise FetchError("redirect", "слишком много переадресаций")

    async def _one(self, url: str, *, site: str, ip: str | None, accept: str) -> Page:
        await self.limiter.turn(site)
        gate = self.limiter.ip_gate(ip)
        if gate is not None:
            await gate.acquire()
        try:
            self.requests += 1
            timeout = httpx.Timeout(self.timeout, connect=min(self.timeout, 6.0))
            async with self.client.stream(
                "GET", url, headers={"Accept": accept}, timeout=timeout
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_bytes:
                        raise FetchError("too-large", "ответ слишком большой", response.status_code)
                encoding = response.encoding or "utf-8"
                text = bytes(body).decode(encoding, errors="replace")
                return Page(
                    url=str(response.url),
                    status=response.status_code,
                    text=text,
                    location=response.headers.get("location"),
                )
        except httpx.TimeoutException as error:
            raise FetchError("timeout", "не ответил вовремя") from error
        except httpx.HTTPError as error:
            raise FetchError("unavailable", "не открывается") from error
        finally:
            if gate is not None:
                gate.release()
