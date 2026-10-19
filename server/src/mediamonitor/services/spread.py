"""«Распространение новости» (Р10, П1, П4, П5, П6).

Никаких AVE, индексов и суммарного «охвата»: подписчики и просмотры — отдельными
цифрами с подписью «как посчитано» (П5, НТ-24). Числа совпадают с подборкой:
размещений = размер группы без исключённых = строки группы в XLSX.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mediamonitor.contract import (
    ByPlacementType,
    ByPlatform,
    OriginNote,
    ReachAnomaly,
    ReachMetric,
    ReleaseFragment,
    ResultItem,
    Selection,
    SpreadAiSummary,
    SpreadOriginal,
    SpreadPlacement,
    SpreadRelease,
    SpreadReport,
    SpreadSelection,
    SpreadTotals,
    SpreadWave,
    WavePoint,
)
from mediamonitor.errors import ApiProblem
from mediamonitor.labels import format_number
from mediamonitor.timeutil import iso, parse_iso, to_krsk, utcnow

AUDIENCE_HOW = (
    "Сумма подписчиков источников по данным площадок. Одни и те же люди могут быть подписаны на "
    "несколько групп, поэтому это не число людей."
)
VIEWS_HOW = (
    "Сумма просмотров по данным площадок. Одноклассники не отдают просмотры: по ним «нет данных», "
    "а не ноль. Размещения с необычными цифрами помечены в таблице."
)


def reach_anomalies(item: ResultItem) -> list[ReachAnomaly]:
    p = item.publication
    out: list[ReachAnomaly] = []
    subscribers = p.source.subscribers
    if p.views is not None and subscribers is not None and p.views > subscribers * 1.5:
        out.append(
            ReachAnomaly(
                code="views-above-subscribers",
                message=f"Просмотров ({format_number(p.views)}) намного больше, чем подписчиков "
                f"у источника ({format_number(subscribers)}): пост мог разойтись через репосты. "
                "Проверьте пост, "
                "прежде чем приводить цифру.",
            )
        )
    if (
        p.views is not None
        and p.reactions is not None
        and p.views >= 10_000
        and p.reactions < p.views * 0.0005
    ):
        out.append(
            ReachAnomaly(
                code="few-reactions",
                message=f"При {format_number(p.views)} просмотрах почти нет реакций "
                f"({format_number(p.reactions)}). Цифра просмотров может быть завышена.",
            )
        )
    return out


def _wave(items: list[ResultItem], hours: int) -> list[WavePoint]:
    dated = [
        (i, to_krsk(parse_iso(i.publication.published_at)))
        for i in items
        if i.publication.published_at
    ]
    if not dated:
        return []

    def floor(moment: datetime) -> datetime:
        base = moment.replace(minute=0, second=0, microsecond=0)
        return base.replace(hour=0) if hours == 24 else base

    first = min(floor(m) for _, m in dated)
    last = max(floor(m) for _, m in dated)
    step = timedelta(hours=hours)
    points: list[WavePoint] = []
    index: dict[datetime, WavePoint] = {}
    moment = first
    while moment <= last and len(points) < 2_000:
        point = WavePoint(start=iso(moment), count=0, by_platform=ByPlatform())
        points.append(point)
        index[moment] = point
        moment += step
    for item, at in dated:
        bucket = index.get(floor(at))
        if bucket is not None:
            bucket.count += 1
            bucket.by_platform.add(item.publication.platform)
    return points


def build_spread(
    selection: Selection,
    release: dict[str, Any] | None,
    group_id: str | None,
    *,
    ai_enabled: bool = False,
) -> SpreadReport:
    group = next(
        (g for g in selection.groups if (g.id == group_id if group_id else g.kind == "release")),
        None,
    )
    if release is None or group is None or group.kind != "release":
        raise ApiProblem(
            "not-found",
            "Распространение считается для поиска по тексту новости. Вставьте текст релиза "
            "в поле поиска.",
        )
    by_id = {i.id: i for i in selection.items}
    members = sorted(
        (by_id[i] for i in group.item_ids if i in by_id and not by_id[i].excluded),
        key=lambda i: i.publication.published_at or "9",
    )
    original = next((m for m in members if m.is_original), members[0] if members else None)
    if original is None:
        raise ApiProblem("not-found", "В группе не осталось размещений: все исключены.")

    notes = [
        OriginNote(
            code="first-among-found",
            message="Первым среди найденного. Более ранние публикации могли не попасть в поиск.",
        )
    ]
    if original.publication.time_reliability == "approximate":
        notes.append(
            OriginNote(
                code="approximate-time",
                message="Время приблизительное: MAX не отдаёт время, оно вычислено "
                "по номеру поста.",
            )
        )
    if original.publication.edited:
        notes.append(OriginNote(code="edited", message="Пост редактировался после публикации."))

    subscribers: dict[str, int | None] = {}
    for m in members:
        subscribers[m.publication.source.id] = m.publication.source.subscribers
    known_subs = [v for v in subscribers.values() if v is not None]
    known_views = [m.publication.views for m in members if m.publication.views is not None]
    by_platform, by_type = ByPlatform(), ByPlacementType()
    for m in members:
        by_platform.add(m.publication.platform)
        if m.placement_type:
            by_type.add(m.placement_type)

    placements = [
        SpreadPlacement(
            item_id=m.id,
            platform=m.publication.platform,
            source_id=m.publication.source.id,
            source_name=m.publication.source.name,
            source_type=m.publication.source.type,
            source_district=m.publication.source.district,
            in_my_sources=m.publication.source.in_my_sources,
            places=list(m.region_reason.places),
            published_at=m.publication.published_at,
            time_reliability=m.publication.time_reliability,
            edited=m.publication.edited,
            subscribers=m.publication.source.subscribers,
            views=m.publication.views,
            reactions=m.publication.reactions,
            anomalies=reach_anomalies(m),
            placement_type=m.placement_type or "retold",
            is_original=m.is_original,
            citation_share=m.citation.share if m.citation else 0.0,
            fragment_ids=list(m.citation.fragment_ids) if m.citation else [],
            repost_of=m.publication.repost_of,
            url=m.publication.url,
            # Та же оценка, что у записи подборки: общий кэш по тексту поста.
            ai_check=m.ai_check,
        )
        for m in members
    ]
    # «Похожи на ИИ: N из M» — только пересказы без исходного: копия повторяет оценку релиза.
    retold = [p for p in placements if p.placement_type == "retold" and not p.is_original]
    ai_retold = (
        SpreadAiSummary(
            likely_ai=sum(1 for p in retold if p.ai_check and p.ai_check.level == "likely-ai"),
            retold=len(retold),
        )
        if ai_enabled
        else None
    )
    copies = [m for m in members if not m.is_original]
    fragments = [
        ReleaseFragment(
            id=f["id"],
            index=f["index"],
            text=f["text"],
            taken_by=sum(1 for m in copies if m.citation and f["id"] in m.citation.fragment_ids),
            of=len(copies),
        )
        for f in release["fragments"]
    ]
    return SpreadReport(
        search_id=selection.search_id,
        group_id=group.id,
        conditions=selection.conditions,
        statuses=selection.statuses,
        selection=SpreadSelection(
            total=selection.counts.total, outside_group=selection.counts.total - len(members)
        ),
        title=str(release["title"]),
        release=SpreadRelease(text=str(release["text"]), fragments=fragments),
        original=SpreadOriginal(
            item_id=original.id,
            source_name=original.publication.source.name,
            platform=original.publication.platform,
            published_at=original.publication.published_at,
            time_reliability=original.publication.time_reliability,
            notes=notes,
        ),
        totals=SpreadTotals(placements=len(members), by_platform=by_platform, by_type=by_type),
        audience=ReachMetric(
            value=sum(known_subs) if known_subs else None,
            with_data=len(known_subs),
            of=len(subscribers),
            how_counted=AUDIENCE_HOW,
        ),
        views=ReachMetric(
            value=sum(known_views) if known_views else None,
            with_data=len(known_views),
            of=len(members),
            how_counted=VIEWS_HOW,
        ),
        wave=SpreadWave(hourly=_wave(members, 1), daily=_wave(members, 24)),
        placements=placements,
        ai_retold=ai_retold,
        computed_at=iso(utcnow()),
    )
