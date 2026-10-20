"""Адреса площадок и ключ публикации (НТ-13).

Разные адреса одного поста (vk.com, vk.ru, m.vk.com, `?w=wall…`) приводятся к одному
ключу «площадка + владелец + номер поста» и дают одну запись. Ссылки, которые видит
пользователь, строит сервис из ключа — никогда не берёт из текста поста (НТ-9, НТ-10).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from mediamonitor.contract import PlatformId

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
        return None
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


def parse_post_url(raw: str) -> PostRef | None:
    address = parse_address(raw)
    return address.post if address and address.kind == "post" else None


def post_url(ref: PostRef) -> str:
    """Прямая ссылка на пост, построенная из ключа."""
    if ref.platform == "vk":
        return f"https://vk.com/wall{ref.owner_id}_{ref.post_id}"
    if ref.platform == "ok":
        return f"https://ok.ru/group/{ref.owner_id}/topic/{ref.post_id}"
    return f"https://max.ru/{ref.owner_id}/{ref.post_id}"


def source_url(platform: PlatformId, owner_id: str | None, slug: str | None) -> str:
    """Ссылка на группу или канал."""
    if platform == "vk":
        if slug:
            return f"https://vk.com/{slug}"
        return f"https://vk.com/club{(owner_id or '').lstrip('-')}"
    if platform == "ok":
        return (
            f"https://ok.ru/{slug}" if slug and not owner_id else f"https://ok.ru/group/{owner_id}"
        )
    return f"https://max.ru/{slug or owner_id}"


def source_id(platform: PlatformId, owner_id: str) -> str:
    """Идентификатор источника в справочнике: `vk:-100101`, `max:demo_tv`."""
    return f"{platform}:{owner_id}"


def is_safe_post_url(url: str) -> bool:
    """Ссылка ведёт на пост площадки и построена по её формату (для XLSX и проверок)."""
    ref = parse_post_url(url)
    return ref is not None and post_url(ref) == url
