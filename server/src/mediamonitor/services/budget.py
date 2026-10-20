"""Бюджет вызовов внешних площадок на открытом стенде (НТ-6).

Ссылка на стенд публичная: без предела любой посетитель может за вечер израсходовать
месячный лимит VK (10 000 вызовов у неверифицированного приложения) или тестовые кредиты
MaxStat — и у экспертов поиск по площадке перестанет работать. Поэтому у каждой платной
площадки два предела: на сутки и на календарный месяц (по красноярскому времени),
оба задаются переменными окружения (`VK_DAILY_CALLS`, `VK_MONTHLY_QUOTA`,
`MAXSTAT_DAILY_CREDITS`, `MAXSTAT_CREDITS`; 0 — без предела на этот период).

Как пользоваться в адаптере: перед каждым платным вызовом `await budget.spend("vk")`
(MaxStat — `spend("max", 3)` за страницу поиска). Вызов, который не помещается в предел,
не делается: `spend` бросает `AdapterError` с кодом `quota-exhausted` и понятным текстом
«лимит на сегодня исчерпан», площадка получает статус «нет доступа», остальные площадки
ищут дальше. Ход поиска перед стартом площадки проверяет бюджет (`ensure_available`),
чтобы не начинать обход, который заведомо упрётся в предел.

Расход хранится в таблице `quota_usage` по ключам «площадка × период» («2026-10-20» —
сутки, «2026-10» — месяц). На 80% (`QUOTA_WARN_RATIO`) дежурный получает предупреждение
в журнале стенда, при исчерпании — ошибку; каждое — один раз за период. Сервер работает
одним процессом, поэтому «проверить и списать» защищены замком процесса; на PostgreSQL
строки счётчика к тому же блокируются на время транзакции.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.adapters.base import AdapterError
from mediamonitor.contract import PlatformId, Quota
from mediamonitor.db.models import QuotaUsageRow
from mediamonitor.db.session import SessionMaker
from mediamonitor.labels import PLATFORM_NAME, PLATFORM_SHORT, format_number
from mediamonitor.services.stand import EventLevel, log_event
from mediamonitor.settings import Settings
from mediamonitor.timeutil import day_start, iso, to_krsk, utcnow

BudgetPeriod = Literal["day", "month"]
MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
PERIOD_UNIT: dict[BudgetPeriod, str] = {"day": "за сутки", "month": "за месяц"}


@dataclass(frozen=True)
class BudgetLimit:
    period: BudgetPeriod
    limit: int  # 0 — без предела на этот период


@dataclass(frozen=True)
class PlatformBudget:
    platform: PlatformId
    unit: str  # «вызовов», «кредитов»
    limits: tuple[BudgetLimit, ...]

    @property
    def active(self) -> tuple[BudgetLimit, ...]:
        return tuple(limit for limit in self.limits if limit.limit > 0)


def budgets_from(settings: Settings) -> dict[PlatformId, PlatformBudget]:
    """Пределы площадок из настроек. Одноклассники — анонимный веб без ключа: без бюджета."""
    return {
        "vk": PlatformBudget(
            "vk",
            "вызовов",
            (
                BudgetLimit("day", settings.vk_daily_calls),
                BudgetLimit("month", settings.vk_monthly_quota),
            ),
        ),
        "max": PlatformBudget(
            "max",
            "кредитов",
            (
                BudgetLimit("day", settings.maxstat_daily_credits),
                BudgetLimit("month", settings.maxstat_credits),
            ),
        ),
    }


@dataclass(frozen=True)
class Window:
    """Период учёта: ключ строки в `quota_usage` и момент, когда предел обновится."""

    period: BudgetPeriod
    key: str
    resets_at: datetime  # UTC


def window(period: BudgetPeriod, now: datetime) -> Window:
    local = to_krsk(now).date()
    if period == "day":
        return Window(period, local.isoformat(), day_start(local + timedelta(days=1)))
    first_next = date(local.year + (local.month == 12), local.month % 12 + 1, 1)
    return Window(period, local.strftime("%Y-%m"), day_start(first_next))


def exhausted_message(platform: PlatformId, period: BudgetPeriod, resets_at: datetime) -> str:
    name = PLATFORM_NAME[platform]
    if period == "day":
        return (
            f"Лимит запросов к {name} на сегодня исчерпан: это предел открытого стенда. "
            f"Поиск по {name} снова заработает после 00:00 по красноярскому времени, "
            "найденное на других площадках сохранено."
        )
    local = to_krsk(resets_at)
    return (
        f"Лимит запросов к {name} на этот месяц исчерпан: это предел открытого стенда. "
        f"Поиск по {name} снова заработает {local.day} {MONTHS_GENITIVE[local.month - 1]}, "
        "найденное на других площадках сохранено."
    )


class BudgetExhaustedError(AdapterError):
    """Вызов площадки не помещается в предел: статус «нет доступа», повтор сегодня не поможет."""

    def __init__(self, platform: PlatformId, period: BudgetPeriod, resets_at: datetime) -> None:
        super().__init__(
            "quota-exhausted",
            exhausted_message(platform, period, resets_at),
            retryable=False,
            state="no-access",
        )
        self.platform: PlatformId = platform
        self.period: BudgetPeriod = period
        self.resets_at = resets_at


class CallBudget:
    """Суточный и месячный предел вызовов платных площадок (VK, MaxStat)."""

    def __init__(
        self,
        settings: Settings,
        sessions: SessionMaker,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._budgets = budgets_from(settings)
        self._sessions = sessions
        self._warn_ratio = settings.quota_warn_ratio
        self._clock = clock
        self._lock = asyncio.Lock()

    def covers(self, platform: PlatformId) -> bool:
        budget = self._budgets.get(platform)
        return budget is not None and bool(budget.active)

    async def ensure_available(self, platform: PlatformId, amount: int = 1) -> None:
        """Хватит ли бюджета на `amount` вызовов; нет — `BudgetExhaustedError`."""
        budget = self._budgets.get(platform)
        if budget is None or not budget.active:
            return
        now = self._clock()
        async with self._sessions() as session:
            for limit in budget.active:
                current = window(limit.period, now)
                row = await session.get(QuotaUsageRow, (platform, current.key))
                used = row.used if row else 0
                if used + amount > limit.limit:
                    raise BudgetExhaustedError(platform, limit.period, current.resets_at)

    async def spend(self, platform: PlatformId, amount: int = 1) -> None:
        """Списать `amount` вызовов перед обращением к площадке.

        Не помещается хотя бы в один предел — ничего не списывается, бросается
        `BudgetExhaustedError`. Пересекли 80% или исчерпали предел — запись в журнал стенда.
        """
        if amount <= 0:
            return
        budget = self._budgets.get(platform)
        if budget is None or not budget.active:
            return
        now = self._clock()
        windows = [(limit, window(limit.period, now)) for limit in budget.active]
        async with self._lock, self._sessions.begin() as session:
            rows = [await self._row(session, budget, limit, current) for limit, current in windows]
            for row, (limit, current) in zip(rows, windows, strict=True):
                if row.used + amount > limit.limit:
                    raise BudgetExhaustedError(platform, limit.period, current.resets_at)
            for row, (limit, current) in zip(rows, windows, strict=True):
                before = row.used
                row.used += amount
                row.limit = limit.limit
                await self._notify(
                    session, budget=budget, limit=limit, current=current, row=row, before=before
                )

    async def quota(self, session: AsyncSession, platform: PlatformId) -> Quota | None:
        """Для страницы стенда: самый напряжённый из периодов (при равенстве — сутки)."""
        budget = self._budgets.get(platform)
        if budget is None or not budget.active:
            return None
        now = self._clock()
        best: tuple[float, Quota] | None = None
        for limit in budget.active:
            current = window(limit.period, now)
            row = await session.get(QuotaUsageRow, (platform, current.key))
            used = row.used if row else 0
            share = used / limit.limit
            if best is None or share > best[0]:
                best = (
                    share,
                    Quota(
                        used=used,
                        limit=limit.limit,
                        unit=f"{budget.unit} {PERIOD_UNIT[limit.period]}",
                        resets_at=iso(current.resets_at),
                    ),
                )
        return best[1] if best else None

    async def _row(
        self, session: AsyncSession, budget: PlatformBudget, limit: BudgetLimit, current: Window
    ) -> QuotaUsageRow:
        row = await session.get(QuotaUsageRow, (budget.platform, current.key), with_for_update=True)
        if row is None:
            row = QuotaUsageRow(
                platform=budget.platform,
                period=current.key,
                used=0,
                limit=limit.limit,
                unit=f"{budget.unit} {PERIOD_UNIT[limit.period]}",
                resets_at=current.resets_at,
                warned=False,
            )
            session.add(row)
        return row

    async def _notify(
        self,
        session: AsyncSession,
        *,
        budget: PlatformBudget,
        limit: BudgetLimit,
        current: Window,
        row: QuotaUsageRow,
        before: int,
    ) -> None:
        short = PLATFORM_SHORT[budget.platform]
        what = "суточного" if limit.period == "day" else "месячного"
        amounts = (
            f"{format_number(row.used)} из {format_number(limit.limit)} "
            f"{budget.unit} {PERIOD_UNIT[limit.period]}"
        )
        if before < limit.limit <= row.used:
            row.warned = True
            level: EventLevel = "error"
            local = to_krsk(current.resets_at)
            when = (
                "до 00:00"
                if limit.period == "day"
                else f"до {local.day} {MONTHS_GENITIVE[local.month - 1]}"
            )
            kind = "суточный" if limit.period == "day" else "месячный"
            await log_event(
                session,
                level,
                f"{short}: {kind} лимит открытого стенда исчерпан ({amounts}). "
                f"Поиск по площадке остановлен {when}.",
            )
            return
        if not row.warned and row.used >= limit.limit * self._warn_ratio:
            row.warned = True
            percent = round(row.used / limit.limit * 100)
            await log_event(
                session,
                "warning",
                f"{short}: израсходовано {percent}% {what} лимита ({amounts}).",
            )
