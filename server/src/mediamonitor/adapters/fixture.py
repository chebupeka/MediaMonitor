"""FixtureAdapter — площадка на записанных примерах. ТОЛЬКО для разработки и тестов.

Записи взяты из демо-наборов мокапа (web/src/api/fake/datasets) и лежат в
`mediamonitor/fixtures/*.json` (генерирует server/scripts/contract/export-fake.mjs).
Источники в них вымышлены, ссылки ведут на несуществующие посты — поэтому в продукте
(DATA_SOURCE=live) этот адаптер не используется (Р11 п. 3: никакой имитации в продукте).

Какую запись отдаём на запрос — как в имитации (web/src/api/fake/query.ts):
текст релиза или его кусок → набор релиза; БДД, ДТП… → набор БДД; «Енисей» → событие;
запрос про другой регион → пусто; иначе — поиск по словам во всех записях.

Режимы сбоев (FIXTURE_FAILURES=«max:unavailable,ok:slow»), чтобы проверить сценарий 5:
- `unavailable` — площадка не отвечает на середине хода (повтор помогает);
- `bad-response` — непонятный ответ (НТ-5), повтор помогает;
- `rate-limited` — ограничение частоты: «частично», повтор помогает;
- `slow` — шаги хода в 10 раз медленнее (задержка);
- `timeout` — площадка молчит: срабатывает PLATFORM_TIMEOUT_SEC;
- `quota` — кончилась квота: «нет доступа», повтор не помогает;
- `key-invalid` — ключ недействителен: «нет доступа».
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from importlib import resources
from typing import Any, Literal, cast

from mediamonitor.adapters.base import (
    AdapterDescription,
    AdapterError,
    AdapterEvent,
    AdapterHealth,
    AdapterQuery,
    Capped,
    Partial,
    Posts,
    Progress,
    RawPost,
    SourceInfo,
    SourceProbe,
)
from mediamonitor.contract import (
    DataFreshness,
    HealthState,
    PlatformId,
    PlatformState,
    ProblemCode,
    TimeReliability,
    source_type,
)
from mediamonitor.labels import PLATFORM_NAME
from mediamonitor.normalize.query import is_other_region, query_stems
from mediamonitor.normalize.text import shingles, words
from mediamonitor.normalize.urls import PostRef, parse_address, source_url
from mediamonitor.timeutil import parse_iso, utcnow

FailureMode = Literal[
    "unavailable", "bad-response", "rate-limited", "slow", "timeout", "quota", "key-invalid"
]
FAILURE_MODES: tuple[FailureMode, ...] = (
    "unavailable",
    "bad-response",
    "rate-limited",
    "slow",
    "timeout",
    "quota",
    "key-invalid",
)
# Сбои, которые не проходят при повторе.
PERSISTENT: frozenset[FailureMode] = frozenset({"quota", "key-invalid"})
# Момент «сейчас» в демо-данных мокапа (web/src/api/fake/clock.ts).
FIXTURE_NOW = parse_iso("2026-10-19T14:32:00+07:00")
OK_CAP = 100
PAGE_STEPS = 5
MAX_FRESHNESS = DataFreshness(
    delay_hours=24,
    note="MAX ищется через сторонний индекс: публикации последних ~24 часов могут ещё не найтись.",
)


def parse_failures(spec: str) -> dict[PlatformId, FailureMode]:
    """«max:unavailable,ok:slow» → {max: unavailable, ok: slow}. Ошибка в записи — ValueError."""
    result: dict[PlatformId, FailureMode] = {}
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        platform, _, mode = part.partition(":")
        if platform not in ("vk", "ok", "max") or mode not in FAILURE_MODES:
            raise ValueError(f"FIXTURE_FAILURES: непонятная запись «{part}»")
        result[cast(PlatformId, platform)] = mode
    return result


@dataclass
class Recording:
    id: str
    regex: list[re.Pattern[str]]
    shingle_index: set[str]
    min_shingle_hits: int
    meaning_id: str | None
    posts: list[RawPost]
    # Посты некраевых источников (п. 48): площадка отдаёт их только при поиске по списку.
    list_only: list[RawPost] = field(default_factory=list)

    def matches(self, text: str, meaning_id: str | None) -> bool:
        if self.meaning_id is not None and self.meaning_id != (meaning_id or "all"):
            return False
        lowered = text.lower()
        if any(p.search(lowered) for p in self.regex):
            return True
        if self.min_shingle_hits > 0:
            hits = len(shingles(text) & self.shingle_index)
            return hits >= self.min_shingle_hits
        return False


@dataclass
class FixtureStore:
    """Все записанные примеры: источники, ответы на запросы, посты «по ссылке»."""

    sources: dict[str, SourceInfo]
    recordings: list[Recording]
    posts: dict[str, RawPost]
    everywhere_pool: dict[PlatformId, int]

    @classmethod
    def load(cls, *, shift_to_now: bool = False) -> FixtureStore:
        package = resources.files("mediamonitor.fixtures")

        def read(name: str) -> dict[str, Any]:
            return cast(dict[str, Any], json.loads(package.joinpath(name).read_text("utf-8")))

        shift = (utcnow() - FIXTURE_NOW) if shift_to_now else timedelta(0)
        sources_raw = read("sources.json")
        sources: dict[str, SourceInfo] = {}
        for raw in sources_raw["sources"]:
            info = _source_info(raw)
            sources[raw["id"]] = info
        posts: dict[str, RawPost] = {}
        recordings: list[Recording] = []
        for rec in read("recordings.json")["recordings"]:
            rec_posts = [_raw_post(p, sources, shift) for p in rec["posts"]]
            list_only = [_raw_post(p, sources, shift) for p in rec.get("listOnly", [])]
            for post in [*rec_posts, *list_only]:
                posts.setdefault(post.ref.id, post)
            match = rec["match"]
            index: set[str] = set()
            for text in match["shingleTexts"]:
                index |= shingles(text)
            recordings.append(
                Recording(
                    id=rec["id"],
                    regex=[re.compile(p, re.IGNORECASE) for p in match["regex"]],
                    shingle_index=index,
                    min_shingle_hits=int(match["minShingleHits"]),
                    meaning_id=match["meaningId"],
                    posts=rec_posts,
                    list_only=list_only,
                )
            )
        for raw in read("extra-posts.json")["posts"]:
            post = _raw_post(raw, sources, shift)
            posts.setdefault(post.ref.id, post)
        pool = cast(dict[PlatformId, int], sources_raw["everywherePool"])
        return cls(sources=sources, recordings=recordings, posts=posts, everywhere_pool=pool)

    def pick(self, text: str, meaning_id: str | None, *, my_sources: bool = False) -> list[RawPost]:
        """Что «вернула площадка» на запрос — по правилам имитации."""
        if is_other_region(text):
            return []
        for recording in self.recordings:
            if recording.matches(text, meaning_id):
                return [*recording.posts, *recording.list_only] if my_sources else recording.posts
        return self._keyword_search(text)

    def _keyword_search(self, text: str) -> list[RawPost]:
        stems = query_stems(text)[:6]
        if not stems:
            return []
        result = []
        for post in self.posts.values():
            hay = " ".join(words(f"{post.title or ''} {post.text or ''}"))
            if all(stem in hay for stem in stems):
                result.append(post)
        return result

    def find_source(
        self, platform: PlatformId, owner_id: str | None, slug: str | None
    ) -> SourceInfo | None:
        for info in self.sources.values():
            if info.platform != platform:
                continue
            if owner_id is not None and info.owner_id == owner_id:
                return info
            if slug is not None and info.slug == slug:
                return info
        return None

    def catalog(self) -> Iterable[SourceInfo]:
        return (s for s in self.sources.values() if s.in_catalog)


def _source_info(raw: dict[str, Any]) -> SourceInfo:
    platform = cast(PlatformId, raw["platform"])
    if platform == "vk":
        owner = f"-{raw['ownerId']}"
        slug: str | None = str(raw["slug"]).lower()
    elif platform == "ok":
        owner, slug = str(raw["ownerId"]), None
    else:
        owner = slug = str(raw["slug"]).lower()
    regional = bool(raw["regional"])
    closed = bool(raw["closed"])
    return SourceInfo(
        platform=platform,
        owner_id=owner,
        slug=slug,
        name=str(raw["name"]),
        url=source_url(platform, owner, slug),
        subscribers=raw["subscribers"],
        type=source_type(raw["type"]),
        district=raw["district"],
        regional=regional,
        in_catalog=regional and not closed,
        closed=closed,
        description=str(raw["description"]),
    )


def _raw_post(raw: dict[str, Any], sources: dict[str, SourceInfo], shift: timedelta) -> RawPost:
    source = sources[raw["sourceId"]]
    platform = cast(PlatformId, raw["platform"])
    owner = source.owner_id if platform == "max" else str(raw["ownerId"])
    published = parse_iso(raw["publishedAt"]) + shift if raw["publishedAt"] else None
    repost = raw.get("repostOf")
    return RawPost(
        ref=PostRef(platform, owner, str(raw["postId"])),
        source=source,
        text=raw["text"],
        title=raw["title"],
        published_at=published,
        time_reliability=cast(TimeReliability, raw["timeReliability"]),
        edited=bool(raw["edited"]),
        repost_of=(str(repost["sourceName"]), str(repost["url"])) if repost else None,
        has_media=bool(raw["hasMedia"]),
        views=raw["views"],
        reactions=raw["reactions"],
        alt_urls=tuple(raw["altUrls"]),
    )


@dataclass(frozen=True)
class _Failure:
    code: ProblemCode
    template: str
    retryable: bool
    state: PlatformState

    def error(self, platform: PlatformId) -> AdapterError:
        message = self.template.format(name=PLATFORM_NAME[platform])
        return AdapterError(self.code, message, retryable=self.retryable, state=self.state)


# Тексты — как в мокапе (web/src/api/fake/engine.ts, failureFor).
FAILURES: dict[FailureMode, _Failure] = {
    "unavailable": _Failure(
        "unavailable",
        "{name} не отвечает. Найденное на других площадках сохранено — можно повторить поиск "
        "по {name}.",
        True,
        "error",
    ),
    "bad-response": _Failure(
        "bad-response",
        "{name} ответил в непонятном формате. Это ошибка, а не «ничего не найдено» — повторите "
        "позже.",
        True,
        "error",
    ),
    "rate-limited": _Failure(
        "rate-limited",
        "{name} ограничил частоту запросов: проверена только часть источников. Повторите через "
        "минуту.",
        True,
        "partial",
    ),
    "quota": _Failure(
        "quota-exhausted",
        "Кончилась квота запросов к {name} на сегодня. Поиск по {name} снова заработает "
        "после 00:00.",
        False,
        "no-access",
    ),
    "key-invalid": _Failure(
        "key-invalid",
        "Нет доступа к {name}: ключ доступа недействителен. Сообщите дежурному стенда.",
        False,
        "no-access",
    ),
    "timeout": _Failure("timeout", "{name} не уложился во время.", True, "error"),
    "slow": _Failure("timeout", "{name} отвечает медленно.", True, "searching"),
}
MIDWAY: frozenset[FailureMode] = frozenset({"unavailable", "bad-response", "rate-limited"})


class FixtureAdapter:
    """Площадка на записанных примерах с управляемыми сбоями."""

    def __init__(
        self,
        platform: PlatformId,
        store: FixtureStore,
        *,
        failure: FailureMode | None = None,
        step_delay_sec: float = 0.0,
    ) -> None:
        self.platform: PlatformId = platform
        self.store = store
        self.failure = failure
        self.step_delay_sec = step_delay_sec
        # Посты, «удалённые после поиска» (НТ-19) — для тестов перепроверки ссылок.
        self.deleted: set[str] = set()
        self.description = AdapterDescription(
            platform=platform,
            via=f"Фикстуры: записанные примеры {PLATFORM_NAME[platform]} (не живые данные)",
            freshness=MAX_FRESHNESS if platform == "max" else None,
            quota=None,
        )

    def _active_failure(self, attempt: int) -> FailureMode | None:
        if self.failure is None:
            return None
        if self.failure in PERSISTENT or attempt == 1:
            return self.failure
        return None

    async def _step(self, failure: FailureMode | None) -> None:
        delay = self.step_delay_sec * (10 if failure == "slow" else 1)
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            await asyncio.sleep(0)

    async def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        failure = self._active_failure(query.attempt)
        if failure is not None and failure in PERSISTENT:
            raise FAILURES[failure].error(self.platform)
        if failure == "timeout":
            await asyncio.sleep(3600)
        candidates = [
            p
            for p in self.store.pick(
                query.text, query.meaning_id, my_sources=query.sources is not None
            )
            if p.ref.platform == self.platform and _in_period(p, query)
        ]
        candidates.sort(key=_newest_first)
        capped = False
        # Одноклассники отдают не больше OK_CAP результатов: упёрлись — честно говорим (SC-16).
        if self.platform == "ok" and len(candidates) >= OK_CAP:
            candidates, capped = candidates[:OK_CAP], True
        fail_at: int | None = None

        if query.sources is not None:
            units = [s for s in query.sources if s.platform == self.platform]
            total = len(units)
            if failure in MIDWAY:
                fail_at = max(1, round(total * 0.45))
            closed: list[str] = []
            for index, source in enumerate(units):
                yield Progress(index, total, "sources", source.name)
                await self._step(failure)
                if fail_at is not None and failure is not None and index >= fail_at:
                    if failure == "rate-limited":
                        error = FAILURES[failure].error(self.platform)
                        yield Partial("rate-limited", error.message, error.retryable)
                        return
                    raise FAILURES[failure].error(self.platform)
                known = self.store.find_source(self.platform, source.owner_id, source.slug)
                if source.closed or (known is not None and known.closed):
                    closed.append(source.name)
                    continue
                batch = [p for p in candidates if p.source.owner_id == source.owner_id]
                if batch:
                    yield Posts(batch)
            yield Progress(total, total, "sources", None)
            if closed:
                names = ", ".join(f"«{n}»" for n in closed)
                what = (
                    "Одна группа из списка закрыта"
                    if len(closed) == 1
                    else "Часть групп из списка закрыта"
                )
                yield Partial(
                    "sources-closed",
                    f"{what}: {names}. Её посты не видны, остальные проверены."
                    if len(closed) == 1
                    else f"{what}: {names}. Их посты не видны, остальные проверены.",
                    False,
                )
        else:
            total = self.store.everywhere_pool.get(self.platform, 10)
            if failure in MIDWAY:
                fail_at = max(1, round(total * 0.45))
            released = 0
            for step in range(total):
                yield Progress(step, total, "sources", None)
                await self._step(failure)
                if fail_at is not None and failure is not None and step >= fail_at:
                    if failure == "rate-limited":
                        error = FAILURES[failure].error(self.platform)
                        yield Partial("rate-limited", error.message, error.retryable)
                        return
                    raise FAILURES[failure].error(self.platform)
                # Как страницы общего поиска: порция — раз в несколько шагов хода.
                upto = round(len(candidates) * (step + 1) / total)
                if upto > released and (step % PAGE_STEPS == 0 or step == total - 1):
                    yield Posts(candidates[released:upto])
                    released = upto
            yield Progress(total, total, "sources", None)
        if capped:
            yield Capped(OK_CAP, f"Одноклассники отдают не больше {OK_CAP} результатов на запрос")

    async def fetch_post(self, ref: PostRef) -> RawPost | None:
        failure = self._active_failure(1)
        if failure is not None and failure in {"quota", "key-invalid", "unavailable"}:
            raise FAILURES[failure].error(self.platform)
        if ref.id in self.deleted:
            return None
        return self.store.posts.get(ref.id)

    async def probe_source(self, url: str) -> SourceProbe:
        address = parse_address(url)
        if address is None or address.platform != self.platform:
            return SourceProbe("not-supported", None)
        if address.post is not None:
            owner = self.store.find_source(self.platform, address.post.owner_id, address.slug)
            return SourceProbe("post-link", owner, address.post)
        info = self.store.find_source(self.platform, address.owner_id, address.slug)
        if info is None:
            return SourceProbe("not-found", None)
        if info.closed:
            return SourceProbe("closed", info)
        return SourceProbe("ok", info)

    async def health(self) -> AdapterHealth:
        if self.failure is not None:
            failure = FAILURES[self.failure]
            state: HealthState = "down" if failure.state in ("error", "no-access") else "degraded"
            return AdapterHealth(state, failure.error(self.platform).message)
        return AdapterHealth("ok", "Работает на записанных примерах (режим разработки).")


def _newest_first(post: RawPost) -> tuple[int, float]:
    """Новые сверху, посты без даты — в конце."""
    if post.published_at is None:
        return (1, 0.0)
    return (0, -post.published_at.timestamp())


def _in_period(post: RawPost, query: AdapterQuery) -> bool:
    if post.published_at is None:
        return True  # без даты — показываем с пометкой «дата неизвестна» (ТЗ-Ф36)
    return query.start <= post.published_at <= query.end
