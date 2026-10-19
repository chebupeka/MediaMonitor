"""Подписи и форматы — те же, что в `web/src/lib/labels.ts` и `format.ts`.

Нужны серверу там, где текст собирает он сам: XLSX, лист «Сводка», «Недавние».
Простым языком, без жаргона (ТЗ-Н4, Н5).
"""

from __future__ import annotations

from datetime import date, datetime

from mediamonitor.contract import (
    PlacementType,
    PlatformId,
    PlatformStatus,
    QueryKind,
    RegionReason,
    Relevance,
    SearchMode,
    SelectionMethod,
)
from mediamonitor.timeutil import krsk_today, to_krsk

PLATFORM_NAME: dict[PlatformId, str] = {"vk": "ВКонтакте", "ok": "Одноклассники", "max": "MAX"}
PLATFORM_SHORT: dict[PlatformId, str] = {"vk": "VK", "ok": "OK", "max": "MAX"}

RELEVANCE_LABEL: dict[Relevance, str] = {
    "direct": "Прямо",
    "indirect": "Косвенно",
    "disputed": "Спорно — проверьте",
}
METHOD_LABEL: dict[SelectionMethod, str] = {
    "copy": "копия",
    "semantic": "найдено по смыслу",
    "ai-confirmed": "подтверждено ИИ",
    "ai-unchecked": "не проверено ИИ",
    "manual": "добавлено вручную",
}
PLACEMENT_TYPE_LABEL: dict[PlacementType, str] = {
    "verbatim": "дословно",
    "shortened": "сокращено",
    "retold": "пересказ",
    "repost": "репост",
}
QUERY_KIND_LABEL: dict[QueryKind, str] = {
    "topic": "Тема",
    "event": "Событие или человек",
    "news-text": "Текст новости",
}
MODE_LABEL: dict[SearchMode, str] = {"my-sources": "Мои источники", "everywhere": "Везде"}

MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
NBSP = " "

AI_UNAVAILABLE_NOTE = (
    "Смысловая проверка недоступна: нейросеть не отвечает. Решите сами, подходит ли публикация."
)


def format_number(value: int) -> str:
    """«1 100» — разделитель групп неразрывный пробел, как Intl ru-RU."""
    return f"{value:,}".replace(",", NBSP)


def _format_day(year: int, month: int, day: int) -> str:
    base = f"{day} {MONTHS_SHORT[month - 1]}"
    return base if year == krsk_today().year else f"{base} {year}"


def format_date_time(moment: datetime) -> str:
    """«14 окт, 10:02» по красноярскому времени."""
    local = to_krsk(moment)
    return f"{_format_day(local.year, local.month, local.day)}, {local:%H:%M}"


def format_iso_date(day: date) -> str:
    return _format_day(day.year, day.month, day.day)


def format_period(start: date, end: date) -> str:
    """«1–19 окт», «20 сен – 19 окт», «19 окт»."""
    if start == end:
        return format_iso_date(start)
    if start.year == end.year and start.month == end.month:
        tail = MONTHS_SHORT[end.month - 1]
        if end.year != krsk_today().year:
            tail = f"{tail} {end.year}"
        return f"{start.day}–{end.day} {tail}"
    return f"{format_iso_date(start)} – {format_iso_date(end)}"


def truncate_text(value: str, limit: int) -> str:
    """Обрезать по слову и поставить «…» (как truncateText в интерфейсе)."""
    if len(value) <= limit:
        return value
    cut = value[:limit]
    space = cut.rfind(" ")
    head = cut[:space] if space > limit * 0.6 else cut
    return head.rstrip(",.;:—- \t\n") + "…"


def region_reason_text(reason: RegionReason) -> str:
    parts: list[str] = []
    if reason.regional_source:
        parts.append("краевой источник")
    if reason.in_my_sources:
        parts.append("в вашем списке")
    if reason.places:
        parts.append("упоминается: " + ", ".join(reason.places))
    return " · ".join(parts)


def platform_status_text(status: PlatformStatus) -> str:
    """Короткий текст статуса площадки (как platformStatusView(...).text)."""
    progress = status.progress
    progress_text = (
        f"{format_number(progress.done)} из {format_number(progress.total)}" if progress else ""
    )
    problem = status.problem
    match status.state:
        case "waiting":
            return "ожидает"
        case "searching":
            return f"ищем: {progress_text}" if progress and progress.total > 0 else "ищем"
        case "found":
            return f"найдено {format_number(status.found)}"
        case "nothing":
            if progress and progress.total == 0:
                return "нет источников в списке"
            return "ничего не найдено"
        case "partial":
            return f"частично: {progress_text}"
        case "error":
            if problem and problem.code == "bad-response":
                return "ошибка обработки ответа"
            return "ошибка"
        case "no-access":
            if problem and problem.code == "quota-exhausted":
                return "нет доступа: квота"
            return "нет доступа"
        case "stopped":
            return f"остановлено: {progress_text}" if progress else "остановлено"


def status_summary(statuses: list[PlatformStatus], total: int) -> str:
    """Краткий итог площадок для «Недавних»: «VK ✓ 21 · OK ✓ 7 · MAX ошибка»."""
    if total == 0 and statuses and all(s.state == "nothing" for s in statuses):
        return "ничего не найдено на всех площадках"
    parts = []
    for status in statuses:
        mark = f"✓ {status.found}" if status.state == "found" else platform_status_text(status)
        parts.append(f"{PLATFORM_SHORT[status.platform]} {mark}")
    return " · ".join(parts)
