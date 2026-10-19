"""Импорт списка источников из Excel или CSV (ТЗ-Ф16, SC-11).

Сначала разбор: что будет с каждой строкой (добавим / уже в списке / пропустим и
почему) — ничего не добавляя. Потом добавление ровно строк «добавим» этого разбора.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
import secrets
import zipfile
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Literal, cast

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediamonitor.adapters import AdapterRegistry
from mediamonitor.adapters.base import SourceInfo
from mediamonitor.contract import (
    ImportColumn,
    ImportCounts,
    ImportDuplicate,
    ImportOutcomeAdd,
    ImportOutcomeDuplicate,
    ImportOutcomeEmpty,
    ImportOutcomeSkip,
    ImportPreview,
    ImportReport,
    ImportRow,
    ImportSkipped,
    PlatformId,
    SourceRef,
    source_type,
)
from mediamonitor.db.models import ImportPreviewRow, PlatformSourceRow, WorkspaceRow
from mediamonitor.errors import ApiProblem
from mediamonitor.normalize.urls import parse_address, source_id
from mediamonitor.services import sources as source_service
from mediamonitor.timeutil import utcnow

PREVIEW_TTL = timedelta(hours=1)
_URLISH = re.compile(r"^\s*(https?://|www\.)\S+\s*$", re.IGNORECASE)
_NAME_HEADER = re.compile(r"назв|имя|источник|name|title", re.IGNORECASE)


@dataclass(frozen=True)
class Table:
    sheet: str
    rows: list[list[str]]


def read_table(file_name: str, content: bytes, max_rows: int) -> Table:
    lowered = file_name.lower()
    if lowered.endswith(".xls"):
        raise ApiProblem(
            "invalid",
            f"«{file_name}» — старый формат Excel (.xls). Сохраните файл как .xlsx или CSV "
            "и выберите снова.",
        )
    if lowered.endswith(".xlsx"):
        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except (zipfile.BadZipFile, KeyError, ValueError, OSError) as error:
            raise ApiProblem("invalid", f"«{file_name}» не открывается как файл Excel.") from error
        sheet = workbook.worksheets[0]
        rows = []
        for values in sheet.iter_rows(values_only=True, max_row=max_rows + 1):
            rows.append(["" if v is None else str(v) for v in values])
        name = sheet.title
        workbook.close()
        return Table(name, rows)
    if lowered.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1251", errors="replace")
        sample = text[:4096]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [row for _, row in zip(range(max_rows + 1), reader, strict=False)]
        return Table("CSV", rows)
    raise ApiProblem(
        "invalid", f"«{file_name}» — не таблица. Нужен файл Excel (.xlsx, .xls) или CSV."
    )


def _detect_columns(rows: list[list[str]]) -> tuple[int | None, int | None, int | None, int]:
    """(колонка ссылок, колонка названий, строка-заголовок, число колонок)."""
    width = max((len(r) for r in rows), default=0)
    if width == 0:
        return None, None, None, 0
    header: int | None = None
    first = rows[0] if rows else []
    looks_like_data = any(_URLISH.match(v) or parse_address(v) for v in first if v.strip())
    if first and not looks_like_data and any(v.strip() for v in first):
        header = 0
    data = rows[1:] if header == 0 else rows
    scores = [0] * width
    for row in data:
        for index, value in enumerate(row):
            if value.strip() and (parse_address(value) or _URLISH.match(value)):
                scores[index] += 1
    url_col = max(range(width), key=lambda i: scores[i]) if any(scores) else None
    name_col = None
    if header == 0:
        for index, title in enumerate(rows[0]):
            if index != url_col and _NAME_HEADER.search(title):
                name_col = index
                break
    if name_col is None:
        name_col = next(
            (
                i
                for i in range(width)
                if i != url_col and any(len(r) > i and r[i].strip() for r in data)
            ),
            None,
        )
    return url_col, name_col, header, width


def _ref(row: PlatformSourceRow, mine: bool) -> SourceRef:
    return SourceRef(
        id=row.id,
        platform=cast(PlatformId, row.platform),
        name=row.name,
        url=row.url,
        type=source_type(row.type),
        district=row.district,
        subscribers=row.subscribers,
        in_my_sources=mine,
        regional=row.regional,
    )


async def preview_import(
    session: AsyncSession,
    *,
    adapters: AdapterRegistry,
    workspace: WorkspaceRow,
    file_name: str,
    content: bytes,
    max_rows: int,
) -> ImportPreview:
    table = read_table(file_name, content, max_rows)
    url_col, name_col, header, width = _detect_columns(table.rows)
    columns = []
    for index in range(width):
        title = table.rows[0][index] if header == 0 and index < len(table.rows[0]) else ""
        role: Literal["url", "name", "ignored"]
        if index == url_col:
            role, explain = "url", "ссылки — по ним добавляем"
        elif index == name_col:
            role, explain = "name", "название — подставим, если площадка не отдаст своё"
        else:
            role, explain = "ignored", "не используем"
        columns.append(
            ImportColumn(letter=get_column_letter(index + 1), title=title, role=role, note=explain)
        )

    active = {s.id for s in await source_service.list_sources(session, workspace)}
    data_rows = table.rows[1:] if header == 0 else table.rows
    first_number = 2 if header == 0 else 1
    gate = asyncio.Semaphore(4)
    probes: dict[str, Any] = {}

    async def probe(url: str) -> Any:
        if url not in probes:
            async with gate:
                try:
                    probes[url] = await source_service.probe(adapters, url)
                except ApiProblem as problem:
                    probes[url] = problem
        return probes[url]

    rows: list[ImportRow] = []
    seen: set[str] = set()
    for offset, values in enumerate(data_rows):
        number = first_number + offset
        value = values[url_col] if url_col is not None and url_col < len(values) else ""
        title = values[name_col] if name_col is not None and name_col < len(values) else ""
        if not value.strip():
            rows.append(
                ImportRow(
                    row=number, value=value, title=title, outcome=ImportOutcomeEmpty(kind="empty")
                )
            )
            continue
        address = parse_address(value)
        if address is None:
            reason = (
                "Ссылка на сайт, а не на группу"
                if _URLISH.match(value)
                else "Это не ссылка на группу или канал ВКонтакте, Одноклассников или MAX"
            )
            rows.append(
                ImportRow(
                    row=number,
                    value=value,
                    title=title,
                    outcome=ImportOutcomeSkip(kind="skip", reason=reason),
                )
            )
            continue
        if address.kind == "post":
            reason = "Ссылка на пост, а не на группу: добавьте группу, где он вышел"
            rows.append(
                ImportRow(
                    row=number,
                    value=value,
                    title=title,
                    outcome=ImportOutcomeSkip(kind="skip", reason=reason),
                )
            )
            continue
        result = await probe(value.strip())
        if isinstance(result, ApiProblem):
            outcome: Any = ImportOutcomeSkip(
                kind="skip", reason=f"Не удалось проверить: {result.message}"
            )
        elif result.state == "closed":
            outcome = ImportOutcomeSkip(kind="skip", reason="Группа закрыта: посты не видны")
        elif result.state != "ok" or result.source is None:
            outcome = ImportOutcomeSkip(
                kind="skip", reason="По ссылке ничего нет: группа удалена или ссылка с ошибкой"
            )
        else:
            info: SourceInfo = result.source
            if not info.name and title.strip():
                info = replace(info, name=title.strip())
            directory = await source_service.upsert_source(session, info)
            sid = source_id(info.platform, info.owner_id)
            if sid in active or sid in seen:
                outcome = ImportOutcomeDuplicate(kind="duplicate", source=_ref(directory, True))
            else:
                seen.add(sid)
                note: str | None = None
                if value != value.strip():
                    note = "убрали лишние пробелы"
                elif address.normalized_from_mobile:
                    note = "мобильная ссылка — привели к обычной"
                outcome = ImportOutcomeAdd(kind="add", source=_ref(directory, False), note=note)
        rows.append(ImportRow(row=number, value=value, title=title, outcome=outcome))

    counts = ImportCounts(add=0, duplicate=0, skip=0, empty=0)
    for row in rows:
        kind = row.outcome.kind
        setattr(counts, kind, getattr(counts, kind) + 1)
    preview = ImportPreview(
        preview_id=f"imp_{secrets.token_hex(8)}",
        file_name=file_name,
        sheet_name=table.sheet,
        total_rows=len(table.rows),
        header_row=1 if header == 0 else None,
        columns=columns,
        rows=rows,
        counts=counts,
    )
    await session.execute(
        delete(ImportPreviewRow).where(ImportPreviewRow.created_at < utcnow() - PREVIEW_TTL)
    )
    session.add(
        ImportPreviewRow(
            id=preview.preview_id,
            workspace_id=workspace.id,
            payload=preview.dump(),
            created_at=utcnow(),
        )
    )
    return preview


async def run_import(
    session: AsyncSession, workspace: WorkspaceRow, preview_id: str
) -> ImportReport:
    row = await session.scalar(
        select(ImportPreviewRow).where(
            ImportPreviewRow.id == preview_id, ImportPreviewRow.workspace_id == workspace.id
        )
    )
    if row is None or utcnow() - row.created_at > PREVIEW_TTL:
        raise ApiProblem("not-found", "Разбор файла устарел. Выберите файл ещё раз.")
    preview = ImportPreview.model_validate(row.payload)
    report = ImportReport(added=[], duplicates=[], skipped=[])
    active = {s.id for s in await source_service.list_sources(session, workspace)}
    for item in preview.rows:
        outcome = item.outcome
        if isinstance(outcome, ImportOutcomeAdd):
            if outcome.source.id in active:
                report.duplicates.append(
                    ImportDuplicate(row=item.row, value=item.value, name=outcome.source.name)
                )
                continue
            directory = await session.get(PlatformSourceRow, outcome.source.id)
            if directory is None:
                report.skipped.append(
                    ImportSkipped(row=item.row, value=item.value, reason="Источник не найден")
                )
                continue
            entry = await source_service.attach(
                session, workspace.id, directory, "import", source_service.ok_check()
            )
            active.add(directory.id)
            report.added.append(source_service.to_source(entry, directory))
        elif isinstance(outcome, ImportOutcomeDuplicate):
            report.duplicates.append(
                ImportDuplicate(row=item.row, value=item.value, name=outcome.source.name)
            )
        elif isinstance(outcome, ImportOutcomeSkip):
            report.skipped.append(
                ImportSkipped(row=item.row, value=item.value, reason=outcome.reason)
            )
    await session.delete(row)
    return report
