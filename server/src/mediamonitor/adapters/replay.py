"""Записанные образцы ответов сайтов СМИ и Дзена: `SITES_SOURCE` / `DZEN_SOURCE=fixtures`.

Нужны для разработки и тестов: с ноутбука за рубежом сайты края не открываются (фильтр по
стране), а адаптерам нужен настоящий разбор настоящей разметки. Образцы лежат в
`mediamonitor/fixtures/sources/`: разметка и структура — как в живых ответах 20.10.2026
(`docs/research/zen-and-sites.md`), тексты — свои, короткие. Сопоставление «адрес → файл»
— `manifest.json`; адрес не из списка — 404. Каталог в этом режиме — только те сайты и
каналы, для которых образцы есть.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import httpx

from mediamonitor.media import MediaCatalog

PACKAGE = "mediamonitor.fixtures"
FOLDER = "sources"


@dataclass(frozen=True)
class Recorded:
    url: str | None
    prefix: str | None
    file: str | None
    status: int
    content_type: str
    location: str | None

    def matches(self, url: str) -> bool:
        if self.url is not None:
            return url == self.url
        return self.prefix is not None and url.startswith(self.prefix)


@dataclass(frozen=True)
class Manifest:
    responses: tuple[Recorded, ...]
    sites: frozenset[str]
    channels: frozenset[str]


def _read(name: str) -> bytes:
    return resources.files(PACKAGE).joinpath(FOLDER, name).read_bytes()


@lru_cache(maxsize=1)
def load_manifest() -> Manifest:
    raw: dict[str, Any] = json.loads(_read("manifest.json"))
    responses = tuple(
        Recorded(
            url=item.get("url"),
            prefix=item.get("prefix"),
            file=item.get("file"),
            status=int(item.get("status", 200)),
            content_type=str(item.get("type", "text/html; charset=UTF-8")),
            location=item.get("location"),
        )
        for item in raw["responses"]
    )
    return Manifest(
        responses=responses,
        sites=frozenset(raw.get("sites", [])),
        channels=frozenset(raw.get("channels", [])),
    )


def sample(name: str) -> bytes:
    """Файл образца по имени (для тестов разбора)."""
    return _read(name)


def replay_response(url: str) -> httpx.Response:
    for item in load_manifest().responses:
        if item.matches(url):
            headers = {"content-type": item.content_type}
            if item.location:
                headers["location"] = item.location
            body = _read(item.file) if item.file else b""
            return httpx.Response(item.status, headers=headers, content=body)
    return httpx.Response(404, headers={"content-type": "text/plain"}, content=b"not recorded")


def replay_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return replay_response(str(request.url))

    return httpx.MockTransport(handler)


def replay_catalog(catalog: MediaCatalog) -> MediaCatalog:
    manifest = load_manifest()
    return catalog.only(set(manifest.sites), set(manifest.channels))
