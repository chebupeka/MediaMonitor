"""Замер времени поиска с воронкой «Э-Отбор» на записанных примерах (без кэша и с кэшем).

    uv run python scripts/bench_search.py --db bench.db --fresh --query bdd     # без кэша
    uv run python scripts/bench_search.py --db bench.db --query bdd             # с кэшем в базе

Каждый запуск — новый процесс: память пустая, модель грузится заново (время прогрева
печатается отдельно и в время поиска не входит). «С кэшем» — векторы постов берутся
из таблицы post_embeddings той же базы. Площадки отвечают мгновенно (задержка 0),
так что замер — это время отбора. Наборы: bdd — 51 пост, large — 500 постов.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from asgi_lifespan import LifespanManager
from sqlalchemy import select

from mediamonitor.db.models import SearchEventRow
from mediamonitor.main import create_app
from mediamonitor.matcher.funnel import FunnelMatcher
from mediamonitor.settings import Settings

QUERIES = {"bdd": "Безопасность дорожного движения", "large": "нагрузочный набор 500"}
PERIOD = {"preset": "custom", "from": "2026-09-20", "to": "2026-10-19"}


async def run(db: Path, query: str, batch: int) -> dict[str, Any]:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{db.as_posix()}",
        environment="test",
        data_source="fixtures",
        fixture_step_delay_ms=0,
        llm_warmup=False,
        matcher_warmup=False,
        ollama_url=None,
        match_batch_size=batch,
        rate_limit_per_minute=100_000,
    )
    app = create_app(settings)
    async with LifespanManager(app, startup_timeout=600, shutdown_timeout=60) as manager:
        matcher = app.state.ctx.matcher
        assert isinstance(matcher, FunnelMatcher)
        began = time.perf_counter()
        await matcher.warmup()
        warmup = time.perf_counter() - began
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://bench", timeout=3600
        ) as client:
            key = (await client.post("/api/workspaces")).json()["key"]
            headers = {"X-Workspace-Key": key}
            computed_before = matcher.embedder.computed
            started = time.perf_counter()
            body = {"text": QUERIES[query], "period": PERIOD, "mode": "everywhere"}
            search_id = (await client.post("/api/searches", json=body, headers=headers)).json()[
                "searchId"
            ]
            # Поток читаем через ASGITransport целиком; время первых записей — по журналу событий.
            events = (await client.get(f"/api/searches/{search_id}/events", headers=headers)).text
            total = time.perf_counter() - started
            selection = (await client.get(f"/api/searches/{search_id}", headers=headers)).json()
        async with app.state.ctx.sessions() as session:
            rows = list(
                await session.scalars(
                    select(SearchEventRow)
                    .where(SearchEventRow.search_id == search_id)
                    .order_by(SearchEventRow.seq)
                )
            )
        first_items = next((r.created_at for r in rows if r.type == "items"), None)
        start_at = rows[0].created_at
        return {
            "query": query,
            "warmup_s": round(warmup, 1),
            "search_s": round(total, 1),
            "first_items_s": round((first_items - start_at).total_seconds(), 1)
            if first_items
            else None,
            "items_events": sum(1 for r in rows if r.type == "items"),
            "found": selection["counts"]["total"],
            "texts_embedded": matcher.embedder.computed - computed_before,
            "events_bytes": len(events),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--query", choices=sorted(QUERIES), default="bdd")
    parser.add_argument("--fresh", action="store_true", help="удалить базу — замер без кэша")
    parser.add_argument("--batch", type=int, default=16)
    args = parser.parse_args()
    if args.fresh:
        for path in args.db.parent.glob(args.db.name + "*"):
            path.unlink()
    result = asyncio.run(run(args.db, args.query, args.batch))
    result["cache"] = "нет" if args.fresh else "есть"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
