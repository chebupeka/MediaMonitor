"""Каталог СМИ края (`data/krai-media.json`): редакции, их сайты и каналы на Дзене.

Источник для дополнительных площадок «Сайты СМИ» и «Дзен» (ТЗ-Ф17). Каталог собран из
таблицы команды и живых проверок 20.10.2026 (`docs/research/zen-and-sites.md`). Здесь —
только чтение: что и как можно опрашивать у каждого сайта и канала, и честная причина,
если нельзя (сайт не открывается, заброшен, robots.txt закрывает ленту).

Ключ сайта — домен без `www.` в ASCII (кириллический — в punycode): `vtruda.ru`.
Ссылки для человека строятся по домену, который сайт сам ставит в своих ссылках
(`link_host`), кириллические — в привычном виде (`газетарабочий.рф`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from importlib import resources
from typing import Any, Literal, cast
from urllib.parse import urlsplit

SiteMode = Literal["rss", "news-list", "off"]
DzenState = Literal["ok", "inactive", "not-found"]

# Почему сайт не опрашиваем — коротко, для строки состояния и проверки ссылки.
_OFF_REASON = {
    "unavailable": "сайт не открывается",
    "stale": "сайт заброшен, последние новости — 2021 год",
    "robots": "лента закрыта в robots.txt",
    "engine": "пока не подключён: другой движок сайта",
}


def ascii_host(host: str) -> str | None:
    """Хост в ASCII (punycode) в нижнем регистре; не получилось — None."""
    value = host.strip().lower().rstrip(".")
    if not value:
        return None
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def display_host(host: str) -> str:
    """Хост для человека: punycode → кириллица (`xn--p1ai` → `рф`)."""
    try:
        return host.encode("ascii").decode("idna")
    except UnicodeError:
        return host


def bare_host(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


@dataclass(frozen=True)
class SiteEntry:
    """Сайт редакции и как его читать."""

    media_id: str
    name: str  # название редакции: «Власть труда»
    kind: str  # «газета», «телеканал»
    district: str | None
    owner: str  # ключ: домен без www в ASCII — «vtruda.ru»
    link_host: str  # домен для ссылок в ASCII — «vtruda.ru», у «Енисея» «www.enisey.tv»
    profile: str | None  # bitrix-smi, custom, wordpress, ucoz
    mode: SiteMode
    feed_url: str | None
    list_url: str | None  # раздел новостей для сайтов без ленты
    search_url: str | None  # шаблон с {query}; None — поиска нет или robots.txt закрывает
    article_check: bool  # можно ли открыть страницу статьи (у «Енисея» защита от программ)
    ip: str | None  # один сервер у 42 сайтов: частоту ограничиваем и по адресу
    off_reason: str | None
    aliases: frozenset[str] = field(default_factory=frozenset)

    @property
    def polled(self) -> bool:
        return self.mode != "off"

    @property
    def base_url(self) -> str:
        """Адрес сайта для человека."""
        return f"https://{display_host(self.link_host)}/"

    def page_url(self, path: str) -> str:
        """Адрес страницы для запроса (ASCII): путь без первого «/»."""
        return f"https://{self.link_host}/{path.lstrip('/')}"

    def description(self) -> str:
        where = f", {self.district}" if self.district else ""
        what = f"Сайт: {self.kind} «{self.name}»{where}."
        if self.off_reason:
            return f"{what} Не опрашивается: {self.off_reason}."
        if self.mode == "news-list":
            return f"{what} Ленты RSS нет — читаем раздел новостей и страницы статей."
        if not self.article_check:
            return f"{what} Читаем только ленту RSS: страницы закрыты защитой от программ."
        return f"{what} Лента RSS, поиск по сайту и страницы статей."


@dataclass(frozen=True)
class DzenEntry:
    """Канал редакции на Дзене."""

    media_id: str
    name: str  # название редакции
    district: str | None
    publisher_id: str
    channel_name: str | None  # dzen.ru/<имя>; None — канал только по id
    title: str | None  # как канал называется на Дзене
    state: DzenState
    subscribers: int | None
    last_post_at: datetime | None
    aliases: frozenset[str] = field(default_factory=frozenset)  # имена и id из ссылок

    @property
    def url(self) -> str:
        if self.channel_name:
            return f"https://dzen.ru/{self.channel_name}"
        return f"https://dzen.ru/id/{self.publisher_id}"

    def description(self) -> str:
        where = f", {self.district}" if self.district else ""
        title = f" (на Дзене — «{self.title}»)" if self.title and self.title != self.name else ""
        what = f"Канал редакции «{self.name}»{title}{where}."
        if self.state == "not-found":
            return f"{what} Канала нет: ссылка из таблицы ведёт на пустую страницу."
        if self.state == "inactive":
            return f"{what} Канал давно не обновляется."
        return what


@dataclass(frozen=True)
class MediaCatalog:
    region: str
    checked_at: str
    sites: tuple[SiteEntry, ...]
    channels: tuple[DzenEntry, ...]

    def site_by_host(self, host: str) -> SiteEntry | None:
        value = ascii_host(host)
        if value is None:
            return None
        for site in self.sites:
            if value in site.aliases or bare_host(value) == site.owner:
                return site
        return None

    def site_by_owner(self, owner: str) -> SiteEntry | None:
        return next((s for s in self.sites if s.owner == owner), None)

    def channel(self, publisher_id: str | None, name: str | None = None) -> DzenEntry | None:
        for entry in self.channels:
            if publisher_id and entry.publisher_id == publisher_id:
                return entry
            if name and name.lower() in entry.aliases:
                return entry
        return None

    @property
    def polled_sites(self) -> tuple[SiteEntry, ...]:
        return tuple(s for s in self.sites if s.polled)

    def only(self, owners: set[str], publishers: set[str]) -> MediaCatalog:
        """Часть каталога (записанные примеры: только сайты и каналы, для которых они есть)."""
        return replace(
            self,
            sites=tuple(s for s in self.sites if s.owner in owners),
            channels=tuple(c for c in self.channels if c.publisher_id in publishers),
        )

    def sites_note(self) -> str:
        """«Подключено 43 сайта из 48. Не опрашиваются: …» — оговорка в статусе площадки."""
        polled = self.polled_sites
        off = [s for s in self.sites if not s.polled]
        head = f"Подключено {_count(len(polled), 'сайт', 'сайта', 'сайтов')} из {len(self.sites)}."
        if not off:
            return head
        groups: dict[str, list[str]] = {}
        for site in off:
            groups.setdefault(site.off_reason or "не опрашивается", []).append(f"«{site.name}»")
        parts = [f"{' и '.join(names)} — {reason}" for reason, names in groups.items()]
        return f"{head} Не опрашиваются: {'; '.join(parts)}."

    def dzen_note(self) -> str:
        """Откуда данные Дзена и честная оговорка о правилах площадки."""
        active = [c for c in self.channels if c.state == "ok"]
        head = f"Каналы {_count(len(active), 'редакции', 'редакций', 'редакций')} края"
        return (
            f"{head}, данные — с публичных страниц каналов. Правила Дзена запрещают копировать "
            "контент без разрешения (п. 5.1) — серая зона, как у Одноклассников."
        )


def _count(value: int, one: str, few: str, many: str) -> str:
    tail = value % 100
    if 11 <= tail <= 14:
        word = many
    elif value % 10 == 1:
        word = one
    elif 2 <= value % 10 <= 4:
        word = few
    else:
        word = many
    return f"{value} {word}"


def _host_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url if "://" in url else f"https://{url}").hostname
    return ascii_host(host) if host else None


def _site(raw: dict[str, Any]) -> SiteEntry | None:
    links = raw.get("links") or {}
    link = links.get("site")
    info = raw.get("site") or {}
    if not link:
        return None
    host = _host_of(link.get("asciiUrl")) or _host_of(link.get("url"))
    if host is None:
        return None
    owner = bare_host(host)
    status = str(info.get("status") or "unavailable")
    profile = info.get("profile")
    robots = info.get("robots") or {}
    feed = info.get("feed") or {}
    search = info.get("search") or {}
    aliases = {host, owner, f"www.{owner}"}
    for url in (link.get("url"), link.get("asciiUrl"), feed.get("url"), search.get("url")):
        other = _host_of(url)
        if other:
            aliases |= {other, bare_host(other)}
    # Ссылки в лентах «битрикс-платформы» — без www (vtruda.ru), у остальных — как в каталоге.
    link_host = owner if profile == "bitrix-smi" else host
    mode: SiteMode = "off"
    off_reason: str | None = None
    feed_url = list_url = None
    if status == "rss" and robots.get("feedDisallowed"):
        off_reason = _OFF_REASON["robots"]
    elif status == "rss" and feed.get("url"):
        mode, feed_url = "rss", str(feed["url"])
    elif status == "html" and profile == "bitrix-smi":
        mode, list_url = "news-list", f"https://{link_host}/news/"
    elif status == "html":
        off_reason = _OFF_REASON["engine"]
    elif status == "stale":
        off_reason = _OFF_REASON["stale"]
    else:
        off_reason = _OFF_REASON["unavailable"]
    search_url = (
        str(search["url"])
        if search.get("url") and search.get("robotsAllowed") and "{query}" in str(search["url"])
        else None
    )
    ips = info.get("ips") or []
    return SiteEntry(
        media_id=str(raw["id"]),
        name=str(raw["name"]),
        kind=str(raw.get("kind") or "СМИ"),
        district=raw.get("district"),
        owner=owner,
        link_host=link_host,
        profile=profile,
        mode=mode,
        feed_url=feed_url,
        list_url=list_url,
        search_url=search_url if mode != "off" else None,
        article_check=profile != "custom",
        ip=str(ips[0]) if ips else None,
        off_reason=off_reason,
        aliases=frozenset(aliases),
    )


def _channel(raw: dict[str, Any]) -> DzenEntry | None:
    link = (raw.get("links") or {}).get("dzen")
    info = raw.get("dzen") or {}
    if not link:
        return None
    publisher = info.get("publisherId") or link.get("channelId")
    if not publisher:
        return None  # канала нет — без id его не найти и не показать
    name = link.get("channelName")
    aliases = {str(publisher).lower()}
    if name:
        aliases.add(str(name).lower())
    last = info.get("lastPostAt")
    return DzenEntry(
        media_id=str(raw["id"]),
        name=str(raw["name"]),
        district=raw.get("district"),
        publisher_id=str(publisher),
        channel_name=str(name) if name else None,
        title=info.get("title"),
        state=cast(DzenState, info.get("status") or "not-found"),
        subscribers=info.get("subscribersNow"),
        last_post_at=datetime.fromisoformat(last) if last else None,
        aliases=frozenset(aliases),
    )


def parse_media_catalog(data: dict[str, Any]) -> MediaCatalog:
    sites: list[SiteEntry] = []
    channels: list[DzenEntry] = []
    for raw in data["media"]:
        site = _site(raw)
        if site is not None:
            sites.append(site)
        channel = _channel(raw)
        if channel is not None:
            channels.append(channel)
    checks = data.get("sources") or {}
    return MediaCatalog(
        region=str(data.get("region") or "krasnoyarsk-krai"),
        checked_at=str((checks.get("siteCheck") or {}).get("at") or data.get("builtAt") or ""),
        sites=tuple(sites),
        channels=tuple(channels),
    )


@lru_cache(maxsize=1)
def load_media_catalog() -> MediaCatalog:
    text = resources.files("mediamonitor.data").joinpath("krai-media.json").read_text("utf-8")
    return parse_media_catalog(json.loads(text))
