"""Кэш публикаций площадок в базе (Р7: база — кэш, а не источник выдачи).

Адаптер VK пишет сюда всю прочитанную стену сообщества, а повторный поиск в пределах
`VK_CACHE_MINUTES` берёт посты отсюда, не вызывая VK. Таблица — существующая `publications`
(одна запись на пост, ключ НТ-13) и справочник `platform_sources`; новой схемы нет.
Время получения у поста из кэша — настоящее, «получено в 14:32» не молодеет.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import select

from mediamonitor.adapters.base import RawPost, SourceInfo
from mediamonitor.contract import TimeReliability
from mediamonitor.db.models import PublicationRow
from mediamonitor.db.session import SessionMaker
from mediamonitor.normalize.urls import PostRef
from mediamonitor.services.normalize_post import normalize, upsert_publication
from mediamonitor.services.sources import upsert_source


class DbPostCache:
    """`PostCache` адаптеров на таблицах `publications` и `platform_sources`."""

    def __init__(self, sessions: SessionMaker) -> None:
        self.sessions = sessions

    async def store(self, posts: Sequence[RawPost]) -> None:
        async with self.sessions.begin() as session:
            directory: dict[str, str] = {}
            for raw in posts:
                post = normalize(raw)
                if post is None:
                    continue
                key = f"{raw.source.platform}:{raw.source.owner_id}"
                if key not in directory:
                    row = await upsert_source(session, raw.source)
                    directory[key] = row.id
                await upsert_publication(session, post, directory[key])

    async def load(self, source: SourceInfo, start: datetime, end: datetime) -> list[RawPost]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(PublicationRow)
                .where(
                    PublicationRow.platform == source.platform,
                    PublicationRow.owner_id == source.owner_id,
                    PublicationRow.published_at >= start,
                    PublicationRow.published_at <= end,
                )
                .order_by(PublicationRow.published_at.desc())
            )
            return [_raw(row, source) for row in rows]


def _raw(row: PublicationRow, source: SourceInfo) -> RawPost:
    repost = row.repost_of
    return RawPost(
        ref=PostRef(source.platform, row.owner_id, row.post_id),
        source=source,
        text=row.text,
        title=row.title,
        published_at=row.published_at,
        time_reliability=cast(TimeReliability, row.time_reliability),
        edited=row.edited,
        repost_of=(str(repost["sourceName"]), str(repost["url"])) if repost else None,
        has_media=row.has_media,
        views=row.views,
        reactions=row.reactions,
        alt_urls=tuple(str(u) for u in row.merged_urls),
        fetched_at=row.fetched_at,
    )
