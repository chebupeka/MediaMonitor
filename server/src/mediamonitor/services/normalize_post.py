"""Пост площадки → запись публикации (нормализация, НТ-13).

Ключ и ссылки строит сервис; текст очищается от управляющих символов; предложения,
места края и хеш считаются один раз при получении.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.adapters.base import RawPost, SourceInfo
from mediamonitor.contract import TimeReliability
from mediamonitor.db.models import PublicationRow
from mediamonitor.normalize.region import find_places
from mediamonitor.normalize.text import Span, clean_text, content_hash, split_sentences
from mediamonitor.normalize.urls import PostRef, parse_post_url, post_url
from mediamonitor.timeutil import utcnow

log = logging.getLogger(__name__)

_OWNER = {
    "vk": re.compile(r"^-?\d{1,20}$"),
    "ok": re.compile(r"^\d{1,20}$"),
    "max": re.compile(r"^[a-z0-9_.\-]{1,100}$"),
    # Домен сайта в ASCII без www; id издателя Дзена.
    "site": re.compile(r"^[a-z0-9.\-]{1,200}$"),
    "dzen": re.compile(r"^[a-z0-9]{6,64}$"),
}
_NUMBER = re.compile(r"^\d{1,20}$")
_POST = {
    "vk": _NUMBER,
    "ok": _NUMBER,
    # MAX: 11 символов base64url из ссылки площадки (`AaCtvjqCDhM`), в примерах — число
    # (как `_MAX_POST` в normalize/urls.py).
    "max": re.compile(r"^[A-Za-z0-9_\-]{1,20}$"),
    # Путь статьи без первого «/»: news/batka-ataman/.
    "site": re.compile(r"^(?!.*\.\.)[A-Za-z0-9._~%\-]+(?:/[A-Za-z0-9._~%\-]+)*/?$"),
    "dzen": re.compile(r"^[ab]-[A-Za-z0-9_\-]{6,64}$"),
}


@dataclass(frozen=True)
class NormPost:
    ref: PostRef
    source: SourceInfo
    url: str
    merged_urls: tuple[str, ...]
    title: str | None
    text: str | None
    spans: tuple[Span, ...]
    published_at: datetime | None
    time_reliability: TimeReliability
    edited: bool
    repost_of: dict[str, str] | None
    has_media: bool
    views: int | None
    reactions: int | None
    places: tuple[str, ...]
    content_hash: str | None
    # Время получения с площадки (кэш Р7); None — сейчас.
    fetched_at: datetime | None = None

    @property
    def id(self) -> str:
        return self.ref.id


def _count(value: int | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def normalize(
    raw: RawPost, split: Callable[[str], list[Span]] = split_sentences
) -> NormPost | None:
    """None — пост с некорректным ключом (такой ссылке верить нельзя, в выдачу не идёт)."""
    ref = raw.ref
    if (
        not _OWNER[ref.platform].match(ref.owner_id)
        or not _POST[ref.platform].match(ref.post_id)
        or len(ref.id) > 300  # столбец publications.id
    ):
        log.warning("Пропущен пост с некорректным ключом: %s", ref.platform)
        return None
    url = post_url(ref)
    merged = []
    for alt in raw.alt_urls:
        parsed = parse_post_url(alt)
        if parsed == ref and alt != url and alt not in merged:
            merged.append(alt)
    text = clean_text(raw.text)
    title = clean_text(raw.title)
    spans = tuple(split(text)) if text else ()
    repost = None
    if raw.repost_of is not None:
        name, link = raw.repost_of
        original = parse_post_url(link)
        if original is not None:
            repost = {"sourceName": name, "url": post_url(original)}
    return NormPost(
        ref=ref,
        source=raw.source,
        url=url,
        merged_urls=tuple(merged),
        title=title,
        text=text,
        spans=spans,
        published_at=raw.published_at,
        time_reliability="unknown" if raw.published_at is None else raw.time_reliability,
        edited=raw.edited,
        repost_of=repost,
        has_media=raw.has_media,
        views=_count(raw.views),
        reactions=_count(raw.reactions),
        places=tuple(find_places(title, text)),
        content_hash=content_hash(text),
        fetched_at=raw.fetched_at,
    )


async def upsert_publication(
    session: AsyncSession, post: NormPost, source_id: str
) -> PublicationRow:
    """Записать пост в кэш публикаций (Р7) — одна запись на ключ (НТ-13).

    `fetched_at` — время получения с площадки: у поста из кэша оно прежнее."""
    now = utcnow()
    fetched = post.fetched_at or now
    row = await session.get(PublicationRow, post.id)
    sentences: list[Any] = [[s.start, s.end] for s in post.spans]
    if row is None:
        row = PublicationRow(
            id=post.id,
            platform=post.ref.platform,
            owner_id=post.ref.owner_id,
            post_id=post.ref.post_id,
            source_id=source_id,
            url=post.url,
            merged_urls=list(post.merged_urls),
            title=post.title,
            text=post.text,
            sentences=sentences,
            published_at=post.published_at,
            time_reliability=post.time_reliability,
            edited=post.edited,
            repost_of=post.repost_of,
            has_media=post.has_media,
            views=post.views,
            reactions=post.reactions,
            fetched_at=fetched,
            link_state="not-checked",
            link_checked_at=None,
            content_hash=post.content_hash,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row
    row.source_id = source_id
    row.merged_urls = list(dict.fromkeys([*row.merged_urls, *post.merged_urls]))
    row.title = post.title
    row.text = post.text
    row.sentences = sentences
    row.published_at = post.published_at
    row.time_reliability = post.time_reliability
    row.edited = post.edited
    row.repost_of = post.repost_of
    row.has_media = post.has_media
    row.views = post.views
    row.reactions = post.reactions
    row.fetched_at = fetched
    row.content_hash = post.content_hash
    row.updated_at = now
    return row
