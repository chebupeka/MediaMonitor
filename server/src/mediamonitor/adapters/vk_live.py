"""ВКонтакте вживую: сервисный ключ своего приложения VK ID, `groups.getById` и `wall.get`.

Почему так (`docs/04-decisions.md`, Р2–Р3, Р7; `docs/research/platform-data-access.md` §1, §11):
- нашему ключу открыты только `wall.get`, `wall.getById` и `groups.getById`; `newsfeed.search`
  и `wall.search` отвечают ошибкой 1051, `execute` сервисному ключу не положен — поэтому
  сервер обходит стены сообществ по списку и отбирает посты сам (воронка Р5);
- охват «Везде» — сообщества краевых СМИ из каталога (`data/krai-media.json`, `data/catalog.json`),
  только сообщества: личные страницы не опрашиваются; «Мои источники» — сообщества пользователя;
- стена листается по 100 постов (`offset`) до начала периода, но не дальше
  `VK_MAX_PAGES_PER_SOURCE` страниц на сообщество (потолок честно показывается);
- не больше `VK_REQUESTS_PER_SECOND` (3) запросов в секунду на ключ, тайм-аут, повтор при
  ошибке 6 «слишком много запросов»; перед каждым вызовом — списание из бюджета стенда (НТ-6);
- Р7: база — кэш. Стена сообщества, полученная не раньше `VK_CACHE_MINUTES` минут назад и
  покрывающая период, берётся из кэша публикаций без вызова VK;
- ключ — только `VK_SERVICE_TOKEN` из окружения сервера; уходит в теле POST, в адресах и
  журналах его нет (НТ-15).

Ошибки VK → честные статусы: нет ключа, ключ недействителен, метод недоступен (5, 28, 1051) —
«нет доступа»; 29 и бюджет стенда — «лимит на сегодня исчерпан»; 15, 18, 30, 203 —
«сообщество закрыто» (поиск идёт дальше, итог «частично»); 6 после повторов — «ограничил
частоту»; сеть, 1, 10 — «недоступен»; непонятный ответ — `bad-response`, а не «0» (НТ-5).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any, Protocol, cast

import httpx

from mediamonitor.adapters.base import (
    AdapterDescription,
    AdapterError,
    AdapterEvent,
    AdapterHealth,
    AdapterQuery,
    CallMeter,
    Capped,
    Partial,
    Posts,
    Progress,
    QuotaInfo,
    RawPost,
    SourceInfo,
    SourceProbe,
)
from mediamonitor.contract import PlatformId
from mediamonitor.normalize.urls import PostRef, parse_address, source_url
from mediamonitor.settings import Settings
from mediamonitor.timeutil import utcnow

log = logging.getLogger(__name__)

PAGE_SIZE = 100
# groups.getById принимает до 500 адресов за вызов.
GROUPS_BATCH = 400
POOL_TTL = timedelta(hours=24)
# Ошибки VK API (dev.vk.ru/ru/reference/errors).
KEY_ERRORS = frozenset({5, 28})
METHOD_CLOSED = frozenset({3, 1051})
RATE_ERRORS = frozenset({6, 9})
DAILY_LIMIT = 29
CLOSED_ERRORS = frozenset({15, 18, 30, 203})
GONE_ERRORS = frozenset({100, 113})
RATE_RETRIES = 2
MEDIA_TYPES = frozenset({"photo", "video", "audio", "doc", "album", "clip", "graffiti", "poll"})
_PROFILE = re.compile(r"^id\d+$")
NAME = "ВКонтакте"


class PostCache(Protocol):
    """Кэш публикаций в базе (Р7). Реализация — `services/post_cache.py`."""

    async def load(self, source: SourceInfo, start: datetime, end: datetime) -> list[RawPost]:
        """Посты сообщества за период из кэша (время получения — прежнее)."""
        ...

    async def store(self, posts: Sequence[RawPost]) -> None:
        """Записать полученные со стены посты, в том числе за пределами периода."""
        ...


class VkApiError(Exception):
    """Ошибка, которую вернул сам VK API (`{"error": {...}}`)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"VK API {code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class VkTarget:
    """Сообщество из каталога края: что отправить в `groups.getById` и как его назвать."""

    key: str  # короткое имя или число без «-»
    name: str
    district: str | None
    subscribers: int | None


@dataclass(frozen=True)
class WallMark:
    """Что известно о стене сообщества в кэше: когда получена и до какой даты прочитана."""

    fetched_at: datetime
    # Самый старый пост, до которого дочитали (без закреплённого); None — стена прочитана вся.
    reached: datetime | None

    def covers(self, start: datetime, now: datetime, ttl: timedelta) -> bool:
        if ttl <= timedelta(0) or now - self.fetched_at > ttl:
            return False
        return self.reached is None or self.reached <= start


def _read_json(name: str) -> dict[str, Any]:
    text = resources.files("mediamonitor.data").joinpath(name).read_text("utf-8")
    return cast(dict[str, Any], json.loads(text))


def _community_key(owner: str | None, slug: str | None) -> str | None:
    """Адрес сообщества для groups.getById; личная страница — None (не опрашиваем)."""
    owner = (owner or "").strip()
    slug = (slug or "").strip().lower()
    if owner.startswith("-") and owner[1:].isdigit():
        return owner[1:]
    if slug and not _PROFILE.match(slug):
        club = re.match(r"^(?:club|public|event)(\d+)$", slug)
        return club.group(1) if club else slug
    return None


def load_vk_catalog() -> list[VkTarget]:
    """Охват «Везде» для VK: сообщества краевых СМИ из `krai-media.json` и VK-записи
    `catalog.json`, без личных страниц и без повторов."""
    targets: dict[str, VkTarget] = {}
    for media in _read_json("krai-media.json").get("media", []):
        vk = (media.get("links") or {}).get("vk")
        if not isinstance(vk, dict) or vk.get("kind") != "community":
            continue
        key = _community_key(vk.get("ownerId"), vk.get("handle"))
        if key is None:
            continue
        subscribers = (media.get("subscribers") or {}).get("vk")
        targets.setdefault(
            key,
            VkTarget(
                key=key,
                name=str(media.get("name") or key),
                district=media.get("district"),
                subscribers=subscribers if isinstance(subscribers, int) else None,
            ),
        )
    for entry in _read_json("catalog.json").get("sources", []):
        if entry.get("platform") != "vk" or entry.get("kind") == "profile":
            continue
        key = _community_key(str(entry.get("ownerId") or ""), entry.get("slug"))
        if key is None:
            continue
        subscribers = entry.get("subscribers")
        targets.setdefault(
            key,
            VkTarget(
                key=key,
                name=str(entry.get("name") or key),
                district=entry.get("district"),
                subscribers=subscribers if isinstance(subscribers, int) else None,
            ),
        )
    return list(targets.values())


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _count(block: object) -> int | None:
    return _int(block.get("count")) if isinstance(block, dict) else None


def _names(response: dict[str, Any]) -> dict[int, str]:
    """Имена владельцев из `extended=1`: сообщества — с минусом, люди — как есть."""
    names: dict[int, str] = {}
    for group in response.get("groups") or []:
        gid = _int(group.get("id")) if isinstance(group, dict) else None
        if gid is not None:
            names[-gid] = str(group.get("name") or "")
    for person in response.get("profiles") or []:
        pid = _int(person.get("id")) if isinstance(person, dict) else None
        if pid is not None:
            first = str(person.get("first_name") or "")
            last = str(person.get("last_name") or "")
            names[pid] = f"{first} {last}".strip()
    return names


def parse_post(
    item: dict[str, Any], source: SourceInfo, names: dict[int, str], fetched_at: datetime
) -> RawPost | None:
    """Пост `wall.get` → RawPost. Всё — только из ответа VK (К14). Непонятная запись — None."""
    owner, number, date = _int(item.get("owner_id")), _int(item.get("id")), _int(item.get("date"))
    if owner is None or number is None:
        return None
    donut = item.get("donut")
    if isinstance(donut, dict) and donut.get("is_donut"):
        return None  # платная запись: текст закрыт
    parts = [str(item.get("text") or "").strip()]
    attachments = list(item.get("attachments") or [])
    repost: tuple[str, str] | None = None
    history = item.get("copy_history") or []
    if history and isinstance(history[0], dict):
        original = history[0]
        o_owner, o_number = _int(original.get("owner_id")), _int(original.get("id"))
        if o_owner is not None and o_number is not None:
            name = names.get(o_owner) or ("Сообщество ВКонтакте" if o_owner < 0 else "Автор VK")
            repost = (name, f"https://vk.com/wall{o_owner}_{o_number}")
        parts.append(str(original.get("text") or "").strip())
        attachments.extend(original.get("attachments") or [])
    has_media = False
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        kind = attachment.get("type")
        if kind in MEDIA_TYPES:
            has_media = True
        elif kind == "link":
            link = attachment.get("link")
            title = str(link.get("title") or "").strip() if isinstance(link, dict) else ""
            # Заголовок статьи по ссылке — часть сообщения, если его нет в тексте.
            if title and not any(title in part for part in parts):
                parts.append(title)
    text = "\n\n".join(part for part in parts if part) or None
    likes, reposts = _count(item.get("likes")), _count(item.get("reposts"))
    reactions = None if likes is None and reposts is None else (likes or 0) + (reposts or 0)
    return RawPost(
        ref=PostRef("vk", str(owner), str(number)),
        source=source,
        text=text,
        title=None,
        published_at=datetime.fromtimestamp(date, UTC) if date else None,
        time_reliability="exact" if date else "unknown",
        edited=bool(item.get("edited")),
        repost_of=repost,
        has_media=has_media,
        views=_count(item.get("views")),
        reactions=reactions,
        fetched_at=fetched_at,
    )


class _Gate:
    """Не чаще `rps` запросов в секунду на ключ (общий для всех поисков процесса)."""

    def __init__(
        self,
        rps: float,
        sleep: Callable[[float], Awaitable[None]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.interval = 1.0 / rps
        self.sleep = sleep
        self.clock = clock
        self.next_at = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            now = self.clock()
            if self.next_at > now:
                await self.sleep(self.next_at - now)
                now = max(now, self.next_at)
            self.next_at = now + self.interval


@dataclass
class _Walk:
    posts: list[RawPost]
    capped: bool


class VkAdapter:
    """ВКонтакте через VK API с сервисным ключом своего приложения VK ID."""

    platform: PlatformId = "vk"
    key_env = "VK_SERVICE_TOKEN"

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        budget: CallMeter | None = None,
        *,
        cache: PostCache | None = None,
        catalog: Sequence[VkTarget] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.settings = settings
        self.client = client
        self.budget = budget
        self.cache = cache
        self.catalog = list(catalog) if catalog is not None else load_vk_catalog()
        self.sleep = sleep
        self.clock = clock
        self.gate = _Gate(settings.vk_requests_per_second, sleep)
        self.ttl = timedelta(minutes=settings.vk_cache_minutes)
        self.marks: dict[str, WallMark] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._pool: tuple[datetime, list[SourceInfo]] | None = None
        self._pool_lock = asyncio.Lock()
        # Последний сбой доступа (ключ, метод) — для страницы стенда.
        self._access_problem: str | None = None
        self.calls = 0
        self.description = AdapterDescription(
            platform="vk",
            via="VK API: стены сообществ (wall.get), сервисный ключ",
            quota=QuotaInfo(
                limit=settings.vk_monthly_quota, unit="вызовов в месяц", period="month"
            ),
        )

    # ------------------------------------------------------------ вызов API

    def _no_key(self) -> AdapterError:
        return AdapterError(
            "key-invalid",
            "Нет доступа к ВКонтакте: на сервере не задан сервисный ключ VK. "
            "Сообщите дежурному стенда.",
            retryable=False,
            state="no-access",
        )

    async def _spend(self, amount: int = 1) -> None:
        if self.budget is not None:
            await self.budget.spend(self.platform, amount)

    async def call(self, method: str, **params: object) -> Any:
        """Один метод VK API: бюджет, частота, тайм-аут, повтор при ошибке 6 и сбое сети."""
        token = self.settings.vk_service_token
        if token is None:
            raise self._no_key()
        data = {key: str(value) for key, value in params.items()}
        data["v"] = self.settings.vk_api_version
        data["access_token"] = token.get_secret_value()
        url = f"{self.settings.vk_api_url.rstrip('/')}/{method}"
        rate_tries = 0
        network_tries = 0
        while True:
            await self._spend()
            await self.gate.wait()
            self.calls += 1
            try:
                response = await self.client.post(
                    url, data=data, timeout=self.settings.vk_timeout_sec
                )
            except httpx.HTTPError as error:
                network_tries += 1
                if network_tries <= 1:
                    continue
                raise AdapterError(
                    "unavailable",
                    "ВКонтакте не отвечает. Найденное сохранено — можно повторить поиск "
                    "по ВКонтакте.",
                    retryable=True,
                ) from error
            if response.status_code >= 500:
                network_tries += 1
                if network_tries <= 1:
                    continue
                raise AdapterError(
                    "unavailable",
                    "ВКонтакте не отвечает. Найденное сохранено — можно повторить поиск "
                    "по ВКонтакте.",
                    retryable=True,
                )
            try:
                body = response.json()
            except ValueError as error:
                raise self._bad_response() from error
            if not isinstance(body, dict):
                raise self._bad_response()
            error_block = body.get("error")
            if isinstance(error_block, dict):
                code = _int(error_block.get("error_code")) or 0
                message = str(error_block.get("error_msg") or "")
                if code in RATE_ERRORS and rate_tries < RATE_RETRIES:
                    rate_tries += 1
                    await self.sleep(float(rate_tries))
                    continue
                raise VkApiError(code, message)
            if "response" not in body:
                raise self._bad_response()
            return body["response"]

    @staticmethod
    def _bad_response() -> AdapterError:
        return AdapterError(
            "bad-response",
            "ВКонтакте ответил в непонятном формате. Это ошибка, а не «ничего не найдено» — "
            "повторите позже.",
            retryable=True,
        )

    def _fatal(self, error: VkApiError) -> AdapterError:
        """Ошибка, после которой обходить сообщества дальше бессмысленно."""
        if error.code in KEY_ERRORS:
            self._access_problem = (
                "Нет доступа к ВКонтакте: сервисный ключ недействителен. Сообщите дежурному стенда."
            )
            return AdapterError(
                "key-invalid", self._access_problem, retryable=False, state="no-access"
            )
        if error.code in METHOD_CLOSED:
            self._access_problem = (
                "Нет доступа к ВКонтакте: метод VK API закрыт для нашего приложения. "
                "Сообщите дежурному стенда."
            )
            return AdapterError(
                "key-invalid", self._access_problem, retryable=False, state="no-access"
            )
        if error.code == DAILY_LIMIT:
            return AdapterError(
                "quota-exhausted",
                "ВКонтакте: лимит запросов на сегодня исчерпан (ограничение самого VK). "
                "Поиск по ВКонтакте снова заработает завтра, найденное сохранено.",
                retryable=False,
                state="no-access",
            )
        if error.code in RATE_ERRORS:
            return AdapterError(
                "rate-limited",
                "ВКонтакте ограничил частоту запросов. Повторите через минуту.",
                retryable=True,
                state="partial",
            )
        return AdapterError(
            "unavailable",
            f"ВКонтакте недоступен (ошибка {error.code}). Найденное сохранено — можно "
            "повторить поиск по ВКонтакте.",
            retryable=True,
        )

    # ------------------------------------------------------------ сообщества

    async def _groups(self, keys: Sequence[str]) -> list[dict[str, Any]]:
        """groups.getById пачками; адрес, который VK не принял (ошибка 100), отпадает."""
        result: list[dict[str, Any]] = []
        for start in range(0, len(keys), GROUPS_BATCH):
            result.extend(await self._groups_batch(list(keys[start : start + GROUPS_BATCH])))
        return result

    async def _groups_batch(self, keys: list[str]) -> list[dict[str, Any]]:
        try:
            response = await self.call(
                "groups.getById", group_ids=",".join(keys), fields="members_count"
            )
        except VkApiError as error:
            if error.code in GONE_ERRORS:
                if len(keys) == 1:
                    return []
                middle = len(keys) // 2
                return [
                    *await self._groups_batch(keys[:middle]),
                    *await self._groups_batch(keys[middle:]),
                ]
            raise self._fatal(error) from error
        # С версии 5.194 ответ — {"groups": [...], "profiles": [...]}, раньше — список.
        groups = response.get("groups") if isinstance(response, dict) else response
        if not isinstance(groups, list):
            raise self._bad_response()
        return [g for g in groups if isinstance(g, dict) and _int(g.get("id")) is not None]

    @staticmethod
    def _info(group: dict[str, Any], target: VkTarget | None) -> SourceInfo:
        gid = cast(int, group["id"])
        owner = f"-{gid}"
        slug = str(group.get("screen_name") or "").lower() or None
        subscribers = _int(group.get("members_count"))
        return SourceInfo(
            platform="vk",
            owner_id=owner,
            slug=slug,
            name=str(group.get("name") or (target.name if target else owner)),
            url=source_url("vk", owner, slug),
            subscribers=subscribers
            if subscribers is not None
            else (target.subscribers if target else None),
            type="media",
            district=target.district if target else None,
            regional=True,
            in_catalog=True,
            closed=bool(group.get("is_closed")) or bool(group.get("deactivated")),
        )

    async def pool(self) -> list[SourceInfo]:
        """Сообщества охвата «Везде»: каталог края, разрешённый в id (раз в сутки)."""
        async with self._pool_lock:
            now = self.clock()
            if self._pool is not None and now - self._pool[0] < POOL_TTL:
                return self._pool[1]
            groups = await self._groups([t.key for t in self.catalog])
            by_key = {t.key.lower(): t for t in self.catalog}
            seen: set[str] = set()
            infos: list[SourceInfo] = []
            skipped: list[str] = []
            for group in groups:
                gid = str(group["id"])
                target = by_key.get(gid) or by_key.get(str(group.get("screen_name") or "").lower())
                info = self._info(group, target)
                if info.owner_id in seen:
                    continue
                seen.add(info.owner_id)
                if info.closed:
                    skipped.append(info.name)
                    continue
                infos.append(info)
            if skipped:
                log.warning(
                    "VK: закрытые или удалённые сообщества каталога: %s", ", ".join(skipped)
                )
            self._pool = (now, infos)
            return infos

    # ------------------------------------------------------------ стена

    def _lock(self, owner: str) -> asyncio.Lock:
        lock = self._locks.get(owner)
        if lock is None:
            lock = self._locks[owner] = asyncio.Lock()
        return lock

    async def _wall(self, source: SourceInfo, start: datetime, end: datetime) -> _Walk:
        """Посты сообщества за период: из кэша (Р7) или листая wall.get до начала периода."""
        owner = source.owner_id
        async with self._lock(owner):
            mark = self.marks.get(owner)
            if self.cache is not None and mark and mark.covers(start, self.clock(), self.ttl):
                return _Walk(await self.cache.load(source, start, end), capped=False)
            fetched_at = self.clock()
            collected: list[RawPost] = []
            offset = 0
            pages = 0
            oldest: datetime | None = None
            exhausted = False
            capped = False
            while True:
                if pages >= self.settings.vk_max_pages_per_source:
                    capped = True
                    break
                response = await self.call(
                    "wall.get",
                    owner_id=owner,
                    count=PAGE_SIZE,
                    offset=offset,
                    filter="owner",
                    extended=1,
                )
                pages += 1
                if not isinstance(response, dict) or not isinstance(response.get("items"), list):
                    raise self._bad_response()
                items = [i for i in response["items"] if isinstance(i, dict)]
                names = _names(response)
                for item in items:
                    post = parse_post(item, source, names, fetched_at)
                    if post is None:
                        continue
                    collected.append(post)
                    # Закреплённый пост бывает старым — по нему не судим, дочитали ли до периода.
                    published = None if item.get("is_pinned") else post.published_at
                    if published is not None and (oldest is None or published < oldest):
                        oldest = published
                offset += len(items)
                total = _int(response.get("count"))
                if not items or (total is not None and offset >= total):
                    exhausted = True
                    break
                if oldest is not None and oldest < start:
                    break
            if self.cache is not None and collected:
                try:
                    await self.cache.store(collected)
                    self.marks[owner] = WallMark(fetched_at, None if exhausted else oldest)
                except Exception:  # кэш — ускорение, а не условие поиска
                    log.exception("VK: не удалось записать стену %s в кэш", owner)
            elif self.cache is not None and exhausted:
                self.marks[owner] = WallMark(fetched_at, None)
            in_period = [
                p
                for p in collected
                if p.published_at is not None and start <= p.published_at <= end
            ]
            return _Walk(in_period, capped)

    # ------------------------------------------------------------ интерфейс адаптера

    async def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        if self.settings.vk_service_token is None:
            raise self._no_key()
        mine = query.sources is not None
        try:
            if query.sources is not None:
                sources = [s for s in query.sources if s.platform == "vk"]
            else:
                sources = await self.pool()
        except VkApiError as error:
            raise self._fatal(error) from error
        total = len(sources)
        closed: list[str] = []
        capped: list[str] = []
        for index, source in enumerate(sources):
            yield Progress(index, total, "sources", source.name)
            if source.closed:
                closed.append(source.name)
                continue
            try:
                walk = await self._wall(source, query.start, query.end)
            except VkApiError as error:
                if error.code in CLOSED_ERRORS or error.code in GONE_ERRORS:
                    closed.append(source.name)
                    continue
                if error.code in RATE_ERRORS:
                    yield Partial(
                        "rate-limited",
                        "ВКонтакте ограничил частоту запросов: проверена только часть "
                        f"сообществ ({index} из {total}). Повторите через минуту.",
                        True,
                    )
                    return
                raise self._fatal(error) from error
            self._access_problem = None
            if walk.capped:
                capped.append(source.name)
            if walk.posts:
                yield Posts(walk.posts)
        yield Progress(total, total, "sources", None)
        if capped:
            limit = self.settings.vk_max_pages_per_source * PAGE_SIZE
            yield Capped(
                limit,
                f"ВКонтакте: в {_count_word(len(capped))} просмотрены только "
                f"последние {limit} постов",
            )
        if closed:
            yield Partial("sources-closed", _closed_message(closed, mine), False)

    async def fetch_post(self, ref: PostRef) -> RawPost | None:
        """Пост по ключу (проверка ссылки, «добавить по ссылке»): wall.getById."""
        try:
            response = await self.call(
                "wall.getById", posts=f"{ref.owner_id}_{ref.post_id}", extended=1
            )
        except VkApiError as error:
            if error.code in CLOSED_ERRORS or error.code in GONE_ERRORS:
                return None
            raise self._fatal(error) from error
        items = response.get("items") if isinstance(response, dict) else response
        if not isinstance(items, list):
            raise self._bad_response()
        if not items or not isinstance(items[0], dict):
            return None
        names = _names(response) if isinstance(response, dict) else {}
        owner = ref.owner_id
        source = SourceInfo(
            platform="vk",
            owner_id=owner,
            slug=None,
            name=names.get(int(owner)) or "Сообщество ВКонтакте",
            url=source_url("vk", owner, None),
            subscribers=None,
        )
        for group in (response.get("groups") or []) if isinstance(response, dict) else []:
            if isinstance(group, dict) and f"-{group.get('id')}" == owner:
                source = replace(self._info(group, None), regional=False, in_catalog=False)
        return parse_post(items[0], source, names, self.clock())

    async def probe_source(self, url: str) -> SourceProbe:
        """Проверить ссылку на сообщество (П9): groups.getById, 1 вызов."""
        address = parse_address(url)
        if address is None or address.platform != "vk":
            return SourceProbe("not-supported", None)
        if address.post is not None:
            owner = address.post.owner_id
            if not owner.startswith("-"):
                return SourceProbe("post-link", None, address.post)
            key = owner[1:]
        else:
            key = _community_key(address.owner_id, address.slug) or ""
            if not key:
                # Личная страница (vk.com/id…): опрашиваем только сообщества.
                return SourceProbe("not-supported", None)
        try:
            groups = await self._groups([key])
        except VkApiError as error:  # pragma: no cover — _groups переводит ошибки сам
            raise self._fatal(error) from error
        if not groups:
            if address.post is not None:
                return SourceProbe("post-link", None, address.post)
            return SourceProbe("not-found", None)
        info = replace(self._info(groups[0], None), regional=False, in_catalog=False)
        if address.post is not None:
            return SourceProbe("post-link", info, address.post)
        if groups[0].get("deactivated"):
            return SourceProbe("not-found", None)
        if info.closed:
            return SourceProbe("closed", info)
        return SourceProbe("ok", info)

    async def health(self) -> AdapterHealth:
        if self.settings.vk_service_token is None:
            return AdapterHealth("down", self._no_key().message)
        if self._access_problem:
            return AdapterHealth("down", self._access_problem)
        return AdapterHealth(
            "ok",
            f"Живые данные: VK API, стены сообществ. «Везде» — {len(self.catalog)} сообществ "
            f"края из каталога; повтор за {self.settings.vk_cache_minutes} мин — из кэша.",
        )


def _count_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} сообществе"
    return f"{n} сообществах"


def _closed_message(names: Iterable[str], mine: bool) -> str:
    listed = list(names)
    shown = ", ".join(f"«{n}»" for n in listed[:5])
    more = f" и ещё {len(listed) - 5}" if len(listed) > 5 else ""
    where = "из вашего списка" if mine else "края"
    if len(listed) == 1:
        return (
            f"Одно сообщество {where} закрыто или недоступно: {shown}. Его посты не видны, "
            "остальные проверены."
        )
    return (
        f"Часть сообществ {where} закрыта или недоступна: {shown}{more}. Их посты не видны, "
        "остальные проверены."
    )
