"""HTTP-сервис эмбеддингов. Контракт (под него написан клиент сервера MediaMonitor):

    POST /embed   Authorization: Bearer <EMBEDDINGS_TOKEN>
        {"texts": [...], "model": "sergeyzh/BERTA", "prefix": "paraphrase: ", "normalize": true}
        → {"model": "...", "dim": 768, "vectors": [[...], ...]}   один вектор на текст, порядок сохранён
    POST /ai-detect   Authorization: Bearer <EMBEDDINGS_TOKEN>      (docs/12-tech-design.md §13)
        {"texts": ["нормализованный текст", ...]}
        → {"model": "iitolstykh/GigaCheck-Classifier-Multi", "version": "1b885318d031-nf4",
           "scores": [0.97, ...]}
        scores[i] — вероятность класса «ai» для texts[i] (0…1), порядок сохранён; пустой список —
        пустой scores с model и version. Детектор выключен, грузится или не загрузился — 503.
    GET /health   (без токена)
        → {"status": "ok", "model": "...", "device": "cuda" | "cpu",
           "ai_detect": {"state": "ready" | "loading" | "failed" | "disabled", "model": "...", ...}}

Без токена или с чужим токеном — 401 на любой адрес, кроме /health.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

import orjson
from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from mm_embeddings.detector import Detector, DetectorNotReadyError, DetectorSlot
from mm_embeddings.encoder import Encoder, SentenceTransformerEncoder
from mm_embeddings.settings import Settings

log = logging.getLogger("mm_embeddings")

MAX_TEXTS = 256
# Сервер шлёт детектору пакеты до AI_DETECT_BATCH_SIZE (по умолчанию 16, не больше 64).
MAX_DETECT_TEXTS = 64
MAX_PREFIX_CHARS = 200
# 256 текстов по 20 000 знаков кириллицы — около 10 МБ; больше — явная ошибка клиента.
MAX_BODY_BYTES = 32 * 1024 * 1024
PUBLIC_PATHS = frozenset({"/health"})


class EmbedRequest(BaseModel):
    texts: Annotated[list[str], Field(max_length=MAX_TEXTS)]
    model: str | None = None
    prefix: Annotated[str, Field(max_length=MAX_PREFIX_CHARS)] = ""
    normalize: bool = True


class DetectRequest(BaseModel):
    texts: Annotated[list[str], Field(max_length=MAX_DETECT_TEXTS)]


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"detail": message, "code": code}, status_code=status, headers=headers)


def create_app(
    settings: Settings | None = None,
    encoder: Encoder | None = None,
    detector: Detector | DetectorSlot | None = None,
) -> FastAPI:
    """Собрать приложение. `encoder` и `detector` подставляют тесты; иначе модели грузятся при старте:
    эмбеддинги — до открытия порта, детектор — фоном после (пока грузится, /ai-detect отвечает 503)."""
    cfg = settings or Settings.from_env()
    token = cfg.token.encode("utf-8")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Модель эмбеддингов грузится один раз до приёма запросов; пока грузится, порт закрыт.
        app.state.encoder = encoder or await run_in_threadpool(SentenceTransformerEncoder, cfg)
        if isinstance(detector, DetectorSlot):
            app.state.detector = detector
        elif detector is not None:
            app.state.detector = DetectorSlot.ready(detector)
        else:
            app.state.detector = DetectorSlot.start(cfg)
        yield

    app = FastAPI(
        title="MediaMonitor embeddings",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path not in PUBLIC_PATHS:
            scheme, _, value = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not secrets.compare_digest(value.strip().encode("utf-8"), token):
                return _error(
                    401,
                    "unauthorized",
                    "нужен заголовок Authorization: Bearer <EMBEDDINGS_TOKEN>",
                    {"WWW-Authenticate": "Bearer"},
                )
            length = request.headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_BODY_BYTES:
                return _error(413, "too-large", f"тело запроса больше {MAX_BODY_BYTES // 1024 // 1024} МБ")
        return await call_next(request)

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        enc: Encoder = request.app.state.encoder
        slot: DetectorSlot = request.app.state.detector
        return {"status": "ok", "model": enc.model_name, "device": enc.device, "ai_detect": slot.health()}

    @app.post("/embed")
    async def embed(body: EmbedRequest, request: Request) -> Response:
        enc: Encoder = request.app.state.encoder
        if body.model and body.model.strip().lower() != enc.model_name.lower():
            return _error(400, "model-mismatch", f"сервис считает модель {enc.model_name}, а не {body.model}")
        try:
            vectors = await run_in_threadpool(enc.encode, body.texts, body.prefix, body.normalize)
        except Exception:
            log.exception("не удалось посчитать векторы для %d текстов", len(body.texts))
            return _error(
                503, "encode-failed", "модель не смогла посчитать векторы, подробности в журнале сервиса"
            )
        if vectors.shape[0] != len(body.texts):  # не должно случаться; лучше ошибка, чем сдвиг векторов
            log.error("модель вернула %d векторов на %d текстов", vectors.shape[0], len(body.texts))
            return _error(500, "internal", "число векторов не совпало с числом текстов")
        payload = {"model": enc.model_name, "dim": enc.dim, "vectors": vectors}
        # orjson пишет float32 кратко и быстро: 256 векторов по 768 чисел — около 2 МБ.
        return Response(
            orjson.dumps(payload, option=orjson.OPT_SERIALIZE_NUMPY), media_type="application/json"
        )

    @app.post("/ai-detect")
    async def ai_detect(body: DetectRequest, request: Request) -> Response:
        slot: DetectorSlot = request.app.state.detector
        try:
            det = slot.get()
        except DetectorNotReadyError as exc:
            headers = {"Retry-After": "60"} if exc.state == "loading" else None
            return _error(503, f"ai-detect-{exc.state}", str(exc), headers)
        try:
            scores = await run_in_threadpool(det.score, body.texts) if body.texts else []
        except Exception:
            log.exception("детектор не смог оценить %d текстов", len(body.texts))
            return _error(
                503, "detect-error", "детектор не смог оценить тексты, подробности в журнале сервиса"
            )
        if len(scores) != len(body.texts):  # не должно случаться; лучше ошибка, чем сдвиг оценок
            log.error("детектор вернул %d оценок на %d текстов", len(scores), len(body.texts))
            return _error(500, "internal", "число оценок не совпало с числом текстов")
        return JSONResponse({"model": det.model_name, "version": det.version, "scores": scores})

    return app
