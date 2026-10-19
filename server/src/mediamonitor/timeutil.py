"""Время Красноярска (НТ-12).

Храним моменты в UTC, наружу отдаём ISO 8601 со смещением +07:00
(`2026-10-14T10:02:00+07:00`). Период поиска — календарные дни по Красноярску,
границы включительно.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KRSK = ZoneInfo("Asia/Krasnoyarsk")
TIME_ZONE_LABEL = "время красноярское"
TIME_ZONE_LABEL_FULL = "время красноярское, UTC+7"


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_krsk(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(KRSK)


def iso(moment: datetime) -> str:
    """Момент → `YYYY-MM-DDTHH:MM:SS+07:00` (без долей секунды)."""
    return to_krsk(moment).replace(microsecond=0).isoformat()


def iso_or_none(moment: datetime | None) -> str | None:
    return iso(moment) if moment is not None else None


def parse_iso(value: str) -> datetime:
    """ISO 8601 со смещением → момент в UTC. Без смещения считаем время красноярским."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KRSK)
    return parsed.astimezone(UTC)


def krsk_today(now: datetime | None = None) -> date:
    return to_krsk(now or utcnow()).date()


def day_start(day: date) -> datetime:
    """Начало календарного дня по Красноярску, в UTC."""
    return datetime.combine(day, time.min, tzinfo=KRSK).astimezone(UTC)


def day_end(day: date) -> datetime:
    """Конец календарного дня по Красноярску (23:59:59.999999), в UTC."""
    return datetime.combine(day, time.max, tzinfo=KRSK).astimezone(UTC)


def add_days(day: date, days: int) -> date:
    return day + timedelta(days=days)


def excel_local(moment: datetime) -> datetime:
    """Момент для ячейки XLSX: красноярское время без пояса (Excel поясов не знает)."""
    return to_krsk(moment).replace(tzinfo=None, microsecond=0)
