"""Адреса площадок и ключ публикации (НТ-13).

Разные адреса одного поста (vk.com, vk.ru, m.vk.com, `?w=wall…`) приводятся к одному
ключу «площадка + владелец + номер поста» и дают одну запись. Ссылки, которые видит
пользователь, строит сервис из ключа — никогда не берёт из текста поста (НТ-9, НТ-10).

Сайты СМИ — только из каталога края (`media.py`): ключ — домен без `www.` в ASCII и путь
статьи (`site:vtruda.ru_news/batka-ataman/`). Дзен — id издателя и `a-<id>` или `b-<id>`;
в ссылке на публикацию Дзена владельца нет, его узнаёт адаптер со страницы публикации.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from mediamonitor.contract import PlatformId
from mediamonitor.media import ascii_host, display_host, load_media_catalog

HOSTS: dict[str, PlatformId] = {
    "vk.com": "vk",
    "vk.ru": "vk",
    "m.vk.com": "vk",
    "m.vk.ru": "vk",
    "www.vk.com": "vk",
    "www.vk.ru": "vk",
    "ok.ru": "ok",
    "m.ok.ru": "ok",
    "www.ok.ru": "ok",
    "max.ru": "max",
    "www.max.ru": "max",
    "dzen.ru": "dzen",
    "www.dzen.ru": "dzen",
    "m.dzen.ru": "dzen",
    "zen.yandex.ru": "dzen",
}

_NUM = re.compile(r"^-?\d{1,20}$")
_SLUG = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
_VK_WALL = re.compile(r"^wall(-?\d{1,20})_(\d{1,20})$")
_VK_CLUB = re.compile(r"^(?:club|public|event)(\d{1,20})$")
# Номер поста MAX: в ссылках площадки — 11 символов base64url (`AaCtvjqCDhM`), в записанных
# примерах — число.
_MAX_POST = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
# Не каналы MAX: приглашения в приватный канал и каналы без ника (`/c/-<id>`).
_MAX_NOT_CHANNEL = {"join", "c"}
# Служебные разделы, которые не являются группой или каналом.
_RESERVED = {
    "feed",
    "search",
    "im",
    "groups",
    "friends",
    "video",
    "music",
    "settings",
    "login",
    "dk",
    "app",
    "apps",
}
_DZEN_ID = re.compile(r"^[A-Za-z0-9_\-]{6,64}$")
_DZEN_RESERVED = _RESERVED | {
    "a",
    "b",
    "id",
    "t",
    "news",
    "media",
    "api",
    "legal",
    "user",
    "profile",
    "articles",
    "shorts",
    "suite",
    "help",
}
# Путь статьи на сайте: латиница, цифры и безопасные знаки, без «..».
_SITE_PATH = re.compile(r"^[A-Za-z0-9._~%\-]+(?:/[A-Za-z0-9._~%\-]+)*/?$")


@dataclass(frozen=True)
class PostRef:
    """Ключ публикации. Для MAX владелец — имя канала из адреса (`max.ru/<имя>/<номер>`)."""

    platform: PlatformId
    owner_id: str
    post_id: str

    @property
    def id(self) -> str:
        return f"{self.platform}:{self.owner_id}_{self.post_id}"

    @property
    def url(self) -> str:
        return post_url(self)


@dataclass(frozen=True)
class Address:
    """Разобранная ссылка на группу, канал или пост."""

    platform: PlatformId
    kind: Literal["group", "post"]
    # Числовой id владельца (VK — со знаком «-» для сообществ, OK — id группы); None — только имя.
    owner_id: str | None
    slug: str | None
    post: PostRef | None
    # Ссылка была мобильной или с лишним: «привели к обычной» (импорт, SC-11).
    normalized_from_mobile: bool


def _split(raw: str) -> tuple[str, str, str] | None:
    value = raw.strip()
    if not value or any(ch.isspace() for ch in value):
        return None
    if "://" not in value:
        value = "https://" + value
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"}:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    return host, parts.path, parts.query


def parse_address(raw: str) -> Address | None:
    """Ссылка → площадка и что это (группа или пост). Не ссылка на VK, OK или MAX — None."""
    split = _split(raw)
    if split is None:
        return None
    host, path, query = split
    platform = HOSTS.get(host)
    if platform is None:
        return _parse_site(host, path)
    if platform == "dzen":
        return _parse_dzen([s for s in path.split("/") if s], host != "dzen.ru")
    # Мобильный, «www.» или vk.ru — приводим к обычному адресу (vk.com, ok.ru, max.ru).
    mobile = host.startswith(("m.", "www.")) or (platform == "vk" and host.endswith(".ru"))
    segments = [s for s in path.split("/") if s]
    if platform == "vk":
        return _parse_vk(segments, query, mobile)
    if platform == "ok":
        return _parse_ok(segments, mobile)
    return _parse_max(segments, mobile)


def _parse_vk(segments: list[str], query: str, mobile: bool) -> Address | None:
    wall = parse_qs(query).get("w", [""])[0]
    match = _VK_WALL.match(wall) or (_VK_WALL.match(segments[0]) if segments else None)
    if match:
        owner, number = match.group(1), match.group(2)
        ref = PostRef("vk", owner, number)
        return Address("vk", "post", owner, None, ref, mobile or bool(wall))
    if len(segments) != 1:
        return None
    name = segments[0]
    club = _VK_CLUB.match(name)
    if club:
        return Address("vk", "group", f"-{club.group(1)}", None, None, mobile)
    if name.lower() in _RESERVED or not _SLUG.match(name):
        return None
    return Address("vk", "group", None, name.lower(), None, mobile)


def _parse_ok(segments: list[str], mobile: bool) -> Address | None:
    if len(segments) >= 2 and segments[0] == "group" and _NUM.match(segments[1]):
        owner = segments[1]
        if len(segments) == 4 and segments[2] == "topic" and segments[3].isdigit():
            return Address("ok", "post", owner, None, PostRef("ok", owner, segments[3]), mobile)
        if len(segments) == 2:
            return Address("ok", "group", owner, None, None, mobile)
        return None
    if len(segments) == 1 and _SLUG.match(segments[0]) and segments[0] not in _RESERVED:
        return Address("ok", "group", None, segments[0].lower(), None, mobile)
    return None


def _parse_max(segments: list[str], mobile: bool) -> Address | None:
    if not segments or not _SLUG.match(segments[0]) or segments[0].lower() in _RESERVED:
        return None
    slug = segments[0].lower()
    if slug in _MAX_NOT_CHANNEL:
        return None
    if len(segments) == 2 and _MAX_POST.match(segments[1]):
        return Address("max", "post", slug, slug, PostRef("max", slug, segments[1]), mobile)
    if len(segments) == 1:
        return Address("max", "group", slug, slug, None, mobile)
    return None


def _parse_site(host: str, path: str) -> Address | None:
    """Сайт СМИ из каталога края: главная — источник, путь из 2+ частей — статья."""
    site = load_media_catalog().site_by_host(host)
    if site is None:
        return None
    other = ascii_host(host) != site.link_host
    segments = [s for s in path.split("/") if s]
    if len(segments) < 2:
        return Address("site", "group", site.owner, None, None, other)
    post_path = "/".join(segments)
    # Битрикс отдаёт страницы со «/» на конце: один пост — один ключ (НТ-13).
    if "." not in segments[-1]:
        post_path += "/"
    if len(post_path) > 250 or ".." in post_path or not _SITE_PATH.match(post_path):
        return None
    return Address("site", "post", site.owner, None, PostRef("site", site.owner, post_path), other)


def _parse_dzen(segments: list[str], other_host: bool) -> Address | None:
    if len(segments) >= 2 and segments[0] in ("a", "b") and _DZEN_ID.match(segments[1]):
        # Владельца в ссылке нет: его узнаёт адаптер со страницы публикации.
        ref = PostRef("dzen", "", f"{segments[0]}-{segments[1]}")
        return Address("dzen", "post", None, None, ref, other_host)
    if len(segments) >= 2 and segments[0] == "id" and _DZEN_ID.match(segments[1]):
        return Address("dzen", "group", segments[1].lower(), None, None, other_host)
    if len(segments) >= 4 and segments[:3] == ["profile", "editor", "id"]:
        # Ссылка на редактор канала: сам канал — dzen.ru/id/<id>.
        if _DZEN_ID.match(segments[3]):
            return Address("dzen", "group", segments[3].lower(), None, None, True)
        return None
    if len(segments) == 1 and _SLUG.match(segments[0]):
        name = segments[0].lower()
        if name not in _DZEN_RESERVED:
            return Address("dzen", "group", None, name, None, other_host)
    return None


def parse_post_url(raw: str) -> PostRef | None:
    address = parse_address(raw)
    return address.post if address and address.kind == "post" else None


def post_url(ref: PostRef) -> str:
    """Прямая ссылка на пост, построенная из ключа."""
    if ref.platform == "vk":
        return f"https://vk.com/wall{ref.owner_id}_{ref.post_id}"
    if ref.platform == "ok":
        return f"https://ok.ru/group/{ref.owner_id}/topic/{ref.post_id}"
    if ref.platform == "site":
        return f"https://{_site_link_host(ref.owner_id)}/{ref.post_id}"
    if ref.platform == "dzen":
        kind, _, number = ref.post_id.partition("-")
        return f"https://dzen.ru/{kind}/{number}"
    return f"https://max.ru/{ref.owner_id}/{ref.post_id}"


def _site_link_host(owner: str) -> str:
    """Домен для ссылок на сайт: как сайт ставит его сам, кириллица — в привычном виде."""
    site = load_media_catalog().site_by_owner(owner)
    return display_host(site.link_host if site else owner)


def source_url(platform: PlatformId, owner_id: str | None, slug: str | None) -> str:
    """Ссылка на группу или канал."""
    if platform == "vk":
        if slug:
            return f"https://vk.com/{slug}"
        return f"https://vk.com/club{(owner_id or '').lstrip('-')}"
    if platform == "ok":
        # Группа с коротким адресом без числового id (каталог края): ok.ru/<адрес>.
        if slug and (not owner_id or not owner_id.isdigit()):
            return f"https://ok.ru/{slug}"
        return f"https://ok.ru/group/{owner_id}"
    if platform == "site":
        return f"https://{_site_link_host(owner_id or '')}/"
    if platform == "dzen":
        return f"https://dzen.ru/{slug}" if slug else f"https://dzen.ru/id/{owner_id}"
    return f"https://max.ru/{slug or owner_id}"


def source_id(platform: PlatformId, owner_id: str) -> str:
    """Идентификатор источника в справочнике: `vk:-100101`, `max:demo_tv`."""
    return f"{platform}:{owner_id}"


def is_safe_post_url(url: str) -> bool:
    """Ссылка ведёт на пост площадки и построена по её формату (для XLSX и проверок)."""
    ref = parse_post_url(url)
    return ref is not None and post_url(ref) == url
