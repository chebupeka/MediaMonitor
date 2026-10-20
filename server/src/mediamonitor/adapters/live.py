"""Заготовки настоящих адаптеров VK и OK; MAX — `adapters/max_live.py` (MaxStat).

Каждый реализует интерфейс `PlatformAdapter`, честно отвечает «нет доступа», если ключ
не задан, и «ещё не подключено» — пока логика получения данных не написана.
Что именно делать, записано в TODO со ссылками на разведку
(`docs/research/platform-data-access.md`, §1, §2, §3, §6–§7).

Общее правило для всех трёх (§7.1): поиск или список даёт кандидатов, каждая ссылка
перед показом проверяется живым запросом (`fetch_post`), ключи — только из переменных
окружения на сервере (НТ-15). Сбор — только с сервера, без логинов пользователей (Р2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from mediamonitor.adapters.base import (
    AdapterDescription,
    AdapterError,
    AdapterEvent,
    AdapterHealth,
    AdapterQuery,
    CallMeter,
    QuotaInfo,
    RawPost,
    SourceProbe,
)
from mediamonitor.adapters.max_live import MaxAdapter  # MAX — индекс MaxStat, свой файл
from mediamonitor.contract import PlatformId
from mediamonitor.labels import PLATFORM_NAME
from mediamonitor.normalize.urls import PostRef
from mediamonitor.settings import Settings


class _LiveAdapter:
    platform: PlatformId
    description: AdapterDescription
    # Имя переменной окружения с ключом; None — площадке ключ не нужен.
    key_env: str | None = None

    def __init__(
        self, settings: Settings, client: httpx.AsyncClient, budget: CallMeter | None = None
    ) -> None:
        self.settings = settings
        self.client = client
        self.budget = budget

    async def _spend(self, amount: int = 1) -> None:
        """Перед каждым платным вызовом площадки (НТ-6): нет бюджета — AdapterError,
        вызов не делается. VK — 1 за вызов API, MaxStat — кредиты метода (поиск — 3)."""
        if self.budget is not None:
            await self.budget.spend(self.platform, amount)

    def _has_key(self) -> bool:
        return True

    def _not_ready(self) -> AdapterError:
        name = PLATFORM_NAME[self.platform]
        if not self._has_key():
            return AdapterError(
                "key-invalid",
                f"Нет доступа к {name}: на сервере не задан ключ {self.key_env}. "
                "Сообщите дежурному стенда.",
                retryable=False,
                state="no-access",
            )
        return AdapterError(
            "unavailable",
            f"Поиск по {name} на этом сервере ещё не подключён.",
            retryable=False,
            state="no-access",
        )

    async def search(self, query: AdapterQuery) -> AsyncIterator[AdapterEvent]:
        del query
        events: list[AdapterEvent] = []  # TODO(И1): события поиска площадки
        for event in events:
            yield event
        raise self._not_ready()

    async def fetch_post(self, ref: PostRef) -> RawPost | None:
        del ref
        raise self._not_ready()

    async def probe_source(self, url: str) -> SourceProbe:
        del url
        raise self._not_ready()

    async def health(self) -> AdapterHealth:
        error = self._not_ready()
        return AdapterHealth("down", error.message)


class VkAdapter(_LiveAdapter):
    """ВКонтакте через официальный API с сервисным ключом своего приложения VK ID.

    TODO(И1, разведка §1.2–§1.3, §6, §7.1):
    - «мои источники»: `wall.search` (owner_id=-<id>, query=…) по каждой группе списка,
      либо `wall.get` + отбор по периоду; `count` ≤ 100, листаем `offset`;
    - «везде»: `newsfeed.search` (q, start_time, end_time), если метод открыт новому
      приложению (проба §7.4 п. 1); иначе — широкий пул сообществ края + `wall.search`;
    - `groups.getById` (fields=members_count,city) — подписчики и город источника;
    - проверка ссылки: `wall.getById` (posts=<owner>_<id>); пост удалён → None;
    - ошибки API → AdapterError: 5 → key-invalid; 6, 9, 29 → rate-limited / quota-exhausted;
      15, 18, 30 → закрытая группа (Partial «sources-closed»);
      непонятный JSON → bad-response (НТ-5);
    - перед каждым вызовом API — `await self._spend()`: бюджет на сутки и месяц (НТ-6,
      10 000 вызовов в месяц у неверифицированного приложения).
    """

    platform: PlatformId = "vk"
    key_env = "VK_SERVICE_TOKEN"

    def __init__(
        self, settings: Settings, client: httpx.AsyncClient, budget: CallMeter | None = None
    ) -> None:
        super().__init__(settings, client, budget)
        self.description = AdapterDescription(
            platform="vk",
            via="VK API (сервисный ключ)",
            quota=QuotaInfo(
                limit=settings.vk_monthly_quota, unit="вызовов в месяц", period="month"
            ),
        )

    def _has_key(self) -> bool:
        return self.settings.vk_service_token is not None


class OkAdapter(_LiveAdapter):
    """Одноклассники: анонимный веб-поиск ok.ru и страницы постов (ключ не нужен).

    TODO(И1, разведка §2.3–§2.4, §6, §7.1):
    - «везде»: `ok.ru/search/content` с сервера; разбор выдачи; при смене формата —
      bad-response, а не «0 найдено» (НТ-5);
    - «мои источники»: лента группы `m.ok.ru/group/<id>/topics` или поиск с фильтром автора;
    - пост: страница `ok.ru/group/<gid>/topic/<tid>`, JSON-LD (`datePublished`, полный
      текст); 404 → поста нет;
    - просмотров OK не отдаёт → views=None («нет данных», НТ-24);
    - правила OK запрещают автоматический сбор без разрешения — нужно «да» экспертов (Б1).
    """

    platform: PlatformId = "ok"

    def __init__(
        self, settings: Settings, client: httpx.AsyncClient, budget: CallMeter | None = None
    ) -> None:
        super().__init__(settings, client, budget)
        self.description = AdapterDescription(platform="ok", via="Веб-поиск Одноклассников")


__all__ = ["MaxAdapter", "OkAdapter", "VkAdapter"]
