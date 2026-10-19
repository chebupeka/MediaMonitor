"""`uv run mediamonitor` — запуск сервера (uvicorn) с настройками из окружения."""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn


def selector_loop() -> asyncio.AbstractEventLoop:
    """Windows: асинхронный psycopg не работает с ProactorEventLoop — берём Selector.

    На стенде (Linux, Docker) это не нужно: там цикл по умолчанию и так селекторный.
    """
    return asyncio.SelectorEventLoop()


def main() -> None:
    uvicorn.run(
        "mediamonitor.main:create_app",
        factory=True,
        loop="mediamonitor.__main__:selector_loop" if sys.platform == "win32" else "auto",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        workers=1,  # поиск идёт задачами в процессе; второй процесс не видел бы их хода
    )


if __name__ == "__main__":
    main()
