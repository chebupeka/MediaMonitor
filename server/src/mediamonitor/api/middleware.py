"""Защита открытого стенда (НТ-6, НТ-9): частота запросов по IP, размер тела, заголовки.

Чистые ASGI-обёртки — корректно работают и с потоком событий SSE.
IP клиента берётся из `scope["client"]`; за обратным прокси (Caddy) uvicorn
запускается с `--proxy-headers --forwarded-allow-ips=<адрес прокси>`.
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mediamonitor.contract import ApiError
from mediamonitor.settings import Settings


class RateLimiter:
    """Скользящее окно: не больше `limit` запросов за 60 секунд на (корзину, IP)."""

    WINDOW = 60.0

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._clock = clock
        self._checks = 0

    def hit(self, bucket: str, key: str, limit: int) -> int | None:
        """Учесть запрос. None — можно; число — через сколько секунд повторить."""
        now = self._clock()
        hits = self._hits.setdefault((bucket, key), deque())
        while hits and now - hits[0] >= self.WINDOW:
            hits.popleft()
        self._checks += 1
        if self._checks % 1000 == 0:
            self._cleanup(now)
        if len(hits) >= limit:
            return max(1, int(self.WINDOW - (now - hits[0])) + 1)
        hits.append(now)
        return None

    def _cleanup(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.WINDOW]:
            del self._hits[key]


def _bucket(method: str, path: str) -> str | None:
    if method == "POST" and (path == "/api/searches" or path.endswith("/retry")):
        return "search"
    if method == "POST" and path in ("/api/workspaces", "/api/workspace/open"):
        return "workspace"
    if method == "POST" and path == "/api/ai-check":
        return "ai-check"
    return None


async def _send_error(
    send: Send, status: int, error: ApiError, headers: list[tuple[bytes, bytes]]
) -> None:
    body = json.dumps(error.dump(), ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    def __init__(
        self, app: ASGIApp, settings: Settings, limiter: RateLimiter | None = None
    ) -> None:
        self.app = app
        self.settings = settings
        self.limiter = limiter or RateLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        method, path = str(scope["method"]), str(scope["path"])
        checks = [("all", self.settings.rate_limit_per_minute)]
        bucket = _bucket(method, path)
        if bucket == "search":
            checks.append(("search", self.settings.search_rate_limit_per_minute))
        elif bucket == "workspace":
            checks.append(("workspace", self.settings.workspace_rate_limit_per_minute))
        elif bucket == "ai-check":
            checks.append(("ai-check", self.settings.ai_check_rate_limit_per_minute))
        for name, limit in checks:
            retry = self.limiter.hit(name, ip, limit)
            if retry is not None:
                error = ApiError(
                    code="too-many-requests",
                    message="Слишком много запросов с вашего адреса. Подождите немного "
                    "и повторите.",
                    retry_after_sec=retry,
                )
                await _send_error(send, 429, error, [(b"retry-after", str(retry).encode())])
                return
        await self.app(scope, receive, send)


class _BodyTooLargeError(Exception):
    pass


class BodyLimitMiddleware:
    """Тело запроса не больше лимита: JSON — MAX_BODY_BYTES, импорт файла — MAX_IMPORT_BYTES."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        limit = (
            self.settings.max_import_bytes
            if path.endswith("/import/preview")
            else self.settings.max_body_bytes
        )
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        too_large = ApiError(
            code="too-long", message="Запрос слишком большой для открытого стенда."
        )
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _send_error(send, 413, too_large, [])
            return
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if not started:
                await _send_error(send, 413, too_large, [])


SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-resource-policy", b"same-site"),
]
API_HEADERS: list[tuple[bytes, bytes]] = [
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"cache-control", b"no-store"),
]


class SecurityHeadersMiddleware:
    """Ответы API — только данные: браузер не выполнит их как страницу (НТ-9)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = str(scope.get("path", "")).startswith(("/api/", "/health"))

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing: list[Any] = list(message.get("headers", []))
                names = {name.lower() for name, _ in existing}
                extra = SECURITY_HEADERS + (API_HEADERS if is_api else [])
                existing += [(k, v) for k, v in extra if k not in names]
                message = {**message, "headers": existing}
            await send(message)

        await self.app(scope, receive, with_headers)
