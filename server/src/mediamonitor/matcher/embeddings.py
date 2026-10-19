"""Модель смысла (эмбеддинги) для воронки: CPU сервера или сервис на компьютере с видеокартой.

Провайдер — настройка: `EMBEDDINGS_URL` не задан — модель на CPU сервера (sentence-transformers
из пакета mm_matching); задан — сервис gpu-node по контракту:

    POST {EMBEDDINGS_URL}/embed   {"texts": [...], "model": "sergeyzh/BERTA",
                                   "prefix": "<префикс задачи или пусто>", "normalize": true}
                               →  {"model": "...", "dim": N, "vectors": [[...], ...]}
    GET  {EMBEDDINGS_URL}/health → {"status": "ok", "model": "...", "device": "cuda" | "cpu"}
    Authorization: Bearer {EMBEDDINGS_TOKEN}

Длинные тексты режутся на куски так же, как в mm_matching (`chunk_text`): вектор текста —
нормированное среднее кусков; префиксы задач BERTA (`categorize_topic: `, `paraphrase: `)
передаются полем prefix. Если сервис недоступен — откат на CPU сервера с пометкой на
странице стенда; через EMBEDDINGS_RETRY_AFTER_SEC сервис пробуем снова.

Сверху — `CachingEmbedder`: векторы в памяти процесса + выгрузка новых в базу и загрузка
посчитанных раньше (services/vectors.py), чтобы пост не считался дважды.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

import httpx
import numpy as np
from mm_matching.embeddings import (
    Embedder,
    EmbedKind,
    Matrix,
    SentenceTransformerEmbedder,
    chunk_text,
    prefixes_for,
)

from mediamonitor.matcher.base import StandNote
from mediamonitor.settings import Settings

log = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 1500
MAX_CHUNKS = 4
Vector = np.ndarray[Any, np.dtype[np.float32]]


def text_key(text: str) -> str:
    """Ключ текста в кэше векторов: тот же текст — тот же вектор."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def _normalize(vector: Vector) -> Vector:
    norm = float(np.linalg.norm(vector))
    return (vector / norm).astype(np.float32) if norm > 0 else vector.astype(np.float32)


class EmbeddingServiceError(Exception):
    """Сервис эмбеддингов не ответил по контракту: недоступен, ошибка, чужая модель."""


class HttpEmbedder:
    """Клиент сервиса gpu-node. Синхронный: воронка зовёт его из пула потоков."""

    RETRIES = 2

    def __init__(
        self,
        url: str,
        model: str,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        batch_size: int = 256,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = model
        self.url = url.rstrip("/")
        self.batch_size = max(1, min(batch_size, 256))
        self._prefixes = prefixes_for(model)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=5.0), headers=headers, transport=transport
        )
        self.device: str | None = None

    def health(self) -> dict[str, Any]:
        try:
            response = self._client.get(f"{self.url}/health", timeout=5.0)
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EmbeddingServiceError(f"нет ответа ({type(error).__name__})") from error
        if response.status_code != 200 or not isinstance(data, dict) or data.get("status") != "ok":
            raise EmbeddingServiceError(f"сервис ответил кодом {response.status_code}")
        if data.get("model") != self.name:
            raise EmbeddingServiceError(f"на сервисе другая модель: {data.get('model')}")
        self.device = str(data.get("device") or "")
        return data

    def encode(self, texts: Sequence[str], kind: EmbedKind) -> Matrix:
        chunks: list[str] = []
        owner: list[int] = []
        for index, text in enumerate(texts):
            for chunk in chunk_text(text, MAX_CHUNK_CHARS, MAX_CHUNKS):
                chunks.append(chunk)
                owner.append(index)
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), self.batch_size):
            vectors += self._embed(chunks[start : start + self.batch_size], self._prefixes[kind])
        if not vectors:
            return np.zeros((0, 0), dtype=np.float32)
        matrix = np.asarray(vectors, dtype=np.float32)
        sums = np.zeros((len(texts), matrix.shape[1]), dtype=np.float32)
        np.add.at(sums, np.asarray(owner), matrix)
        return np.vstack([_normalize(row) for row in sums])

    def _embed(self, texts: list[str], prefix: str) -> list[list[float]]:
        body = {"texts": texts, "model": self.name, "prefix": prefix, "normalize": True}
        last: Exception | None = None
        for attempt in range(self.RETRIES):
            try:
                response = self._client.post(f"{self.url}/embed", json=body)
            except httpx.HTTPError as error:
                last = error
                time.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code >= 500:
                last = EmbeddingServiceError(f"сервис ответил кодом {response.status_code}")
                time.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code != 200:
                raise EmbeddingServiceError(f"сервис ответил кодом {response.status_code}")
            return self._validate(response, len(texts))
        raise EmbeddingServiceError(f"нет ответа ({type(last).__name__})") from last

    def _validate(self, response: httpx.Response, expected: int) -> list[list[float]]:
        try:
            data = response.json()
        except ValueError as error:
            raise EmbeddingServiceError("ответ не JSON") from error
        if not isinstance(data, dict) or data.get("model") != self.name:
            raise EmbeddingServiceError("в ответе другая модель — векторы несовместимы")
        vectors = data.get("vectors")
        dim = data.get("dim")
        if not isinstance(vectors, list) or len(vectors) != expected or not isinstance(dim, int):
            raise EmbeddingServiceError("число векторов не совпадает с числом текстов")
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != dim:
                raise EmbeddingServiceError("вектор не той длины")
            if not all(isinstance(x, int | float) and math.isfinite(x) for x in vector):
                raise EmbeddingServiceError("в векторе не числа")
        return cast(list[list[float]], vectors)


class CachingEmbedder:
    """Обёртка для воронки: кэш в памяти, учёт новых векторов, откат с сервиса на CPU."""

    def __init__(
        self,
        name: str,
        *,
        local: Callable[[], Embedder],
        remote: HttpEmbedder | None = None,
        retry_after: float = 60.0,
        memory: int = 50_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._local_factory = local
        self._local: Embedder | None = None
        self._remote = remote
        self._retry_after = retry_after
        self._clock = clock
        self._lock = threading.Lock()
        self._memory: OrderedDict[str, Vector] = OrderedDict()
        self._limit = memory
        self._unsaved: set[str] = set()
        self._remote_down_until = 0.0
        self.remote_error: str | None = None
        self.computed = 0  # сколько текстов посчитано моделью (не из кэша)
        self.warm = False

    # ------------------------------------------------------------ провайдер

    @property
    def provider(self) -> str:
        if self._remote is None:
            return "local"
        return "fallback" if self._clock() < self._remote_down_until else "remote"

    def _local_model(self) -> Embedder:
        with self._lock:
            if self._local is None:
                self._local = self._local_factory()
            return self._local

    def check_remote(self) -> None:
        """Проверить сервис при старте; недоступен — сразу считаем на CPU."""
        if self._remote is None:
            return
        try:
            self._remote.health()
            self.remote_error = None
        except EmbeddingServiceError as error:
            self._mark_down(str(error))

    def _mark_down(self, reason: str) -> None:
        self.remote_error = reason
        self._remote_down_until = self._clock() + self._retry_after
        log.warning("Сервис эмбеддингов недоступен (%s): считаем на CPU сервера", reason)

    def _compute(self, texts: list[str], kind: EmbedKind) -> Matrix:
        if self._remote is not None and self._clock() >= self._remote_down_until:
            try:
                result = self._remote.encode(texts, kind)
                self.remote_error = None
                return result
            except EmbeddingServiceError as error:
                self._mark_down(str(error))
        return self._local_model().encode(texts, kind)

    # ------------------------------------------------------------ Embedder для воронки

    def encode(self, texts: Sequence[str], kind: EmbedKind) -> Matrix:
        keys = [f"{kind}:{text_key(t)}" for t in texts]
        with self._lock:
            missing: dict[str, str] = {}
            for key, text in zip(keys, texts, strict=True):
                if key in self._memory:
                    self._memory.move_to_end(key)
                elif key not in missing:
                    missing[key] = text
        if missing:
            fresh = self._compute(list(missing.values()), kind)
            with self._lock:
                self.computed += len(missing)
                for key, vector in zip(missing, fresh, strict=True):
                    self._remember(key, np.asarray(vector, dtype=np.float32))
                    self._unsaved.add(key)
        with self._lock:
            rows = [self._memory.get(key) for key in keys]
        if any(row is None for row in rows):  # вытеснено из памяти между шагами — досчитать
            return self._compute(list(texts), kind)
        return np.vstack(cast(list[Vector], rows)) if rows else np.zeros((0, 0), np.float32)

    def _remember(self, key: str, vector: Vector) -> None:
        self._memory[key] = vector
        self._memory.move_to_end(key)
        while len(self._memory) > self._limit:
            old, _ = self._memory.popitem(last=False)
            self._unsaved.discard(old)

    # ------------------------------------------------------------ кэш в базе

    def preload(self, kind: EmbedKind, vectors: Mapping[str, Sequence[float]]) -> None:
        """Векторы из базы: ключ — хеш текста."""
        with self._lock:
            for key, vector in vectors.items():
                memory_key = f"{kind}:{key}"
                if memory_key not in self._memory:
                    self._remember(memory_key, np.asarray(vector, dtype=np.float32))

    def take_new(self, kind: EmbedKind, keys: set[str]) -> dict[str, list[float]]:
        """Новые (ещё не записанные в базу) векторы этих текстов."""
        out: dict[str, list[float]] = {}
        with self._lock:
            for key in keys:
                memory_key = f"{kind}:{key}"
                if memory_key in self._unsaved and memory_key in self._memory:
                    out[key] = [float(x) for x in self._memory[memory_key]]
                    self._unsaved.discard(memory_key)
        return out

    def notes(self) -> list[StandNote]:
        cached = len(self._memory)
        if self._remote is not None:
            if self.provider == "fallback":
                return [
                    StandNote(
                        "warning",
                        f"Модель смысла: сервис на видеокарте недоступен ({self.remote_error}) — "
                        f"считаем на CPU сервера, медленнее. Векторов в памяти: {cached}.",
                    )
                ]
            device = f" ({self._remote.device})" if self._remote.device else ""
            return [
                StandNote(
                    "info",
                    f"Модель смысла {self.name}: сервис эмбеддингов{device}. "
                    f"Векторов в памяти: {cached}.",
                )
            ]
        state = "прогрета" if self.warm else "загружается при первом поиске"
        return [
            StandNote(
                "info",
                f"Модель смысла {self.name}: CPU сервера, {state}. Векторов в памяти: {cached}.",
            )
        ]


def build_embedder(settings: Settings) -> CachingEmbedder:
    """Провайдер по настройкам: EMBEDDINGS_URL — сервис, иначе CPU сервера."""

    def local() -> Embedder:
        return SentenceTransformerEmbedder(
            settings.embedding_model,
            max_chunk_chars=MAX_CHUNK_CHARS,
            max_chunks=MAX_CHUNKS,
            cache_size=1_000,
        )

    remote = None
    if settings.embeddings_url:
        token = settings.embeddings_token.get_secret_value() if settings.embeddings_token else None
        remote = HttpEmbedder(
            settings.embeddings_url,
            settings.embedding_model,
            token=token,
            timeout=settings.embeddings_timeout_sec,
            batch_size=settings.embeddings_batch_size,
        )
    return CachingEmbedder(
        settings.embedding_model,
        local=local,
        remote=remote,
        retry_after=settings.embeddings_retry_after_sec,
    )
