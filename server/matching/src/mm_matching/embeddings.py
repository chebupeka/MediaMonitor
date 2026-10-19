"""Шаг 2 воронки: близость по смыслу — открытая модель на CPU (sentence-transformers).

Модель по умолчанию — `sergeyzh/BERTA` (MIT, 128M параметров, ruMTEB 69,4).
Длинный текст режется на куски по абзацам; вектор текста — нормированное среднее кусков.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Sequence
from typing import Literal, Protocol

import numpy as np
import numpy.typing as npt

from mm_matching.text import split_paragraphs

Vector = npt.NDArray[np.float32]
Matrix = npt.NDArray[np.float32]
# Задача, под которую считается вектор:
# - paraphrase — «тот же текст своими словами» (поиск по тексту новости);
# - topic — «о той же теме» (поиск по теме; запрос и пост с одним префиксом).
EmbedKind = Literal["paraphrase", "topic"]

# Префиксы задач у разных семейств моделей: без них качество падает. Для BERTA
# симметричный `categorize_topic:` на мини-эталоне различает темы лучше, чем пара
# `search_query:` / `search_document:` (AUC 0,99 против 0,86 для «БДД»).
_PREFIXES: dict[str, dict[EmbedKind, str]] = {
    "berta": {"paraphrase": "paraphrase: ", "topic": "categorize_topic: "},
    "frida": {"paraphrase": "paraphrase: ", "topic": "categorize_topic: "},
    "user2": {"paraphrase": "clustering: ", "topic": "classification: "},
    "e5": {"paraphrase": "query: ", "topic": "query: "},
}


def prefixes_for(model_name: str) -> dict[EmbedKind, str]:
    low = model_name.lower()
    for key, value in _PREFIXES.items():
        if key in low:
            return value
    return {"paraphrase": "", "topic": ""}


class Embedder(Protocol):
    """Что нужно воронке от модели эмбеддингов. Векторы нормированы (косинус = скалярное)."""

    name: str

    def encode(self, texts: Sequence[str], kind: EmbedKind) -> Matrix: ...


def chunk_text(text: str, max_chars: int, max_chunks: int) -> list[str]:
    """Режет текст по абзацам на куски до `max_chars` знаков, не больше `max_chunks`."""
    paras = [text[r.start : r.end] for r in split_paragraphs(text)] or [text]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        rest = p
        while len(rest) > max_chars:
            cut = rest.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(rest[:cut])
            rest = rest[cut:].lstrip()
        if cur and len(cur) + 1 + len(rest) > max_chars:
            chunks.append(cur)
            cur = rest
        else:
            cur = f"{cur}\n{rest}" if cur else rest
    if cur:
        chunks.append(cur)
    return chunks[:max_chunks] or [text[:max_chars]]


class SentenceTransformerEmbedder:
    """Обёртка над sentence-transformers: ленивое создание, куски, кеш векторов."""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        batch_size: int = 16,
        max_chunk_chars: int = 1500,
        max_chunks: int = 4,
        cache_size: int = 20000,
    ) -> None:
        self.name = model_name
        self._device = device
        self._batch_size = batch_size
        self._max_chunk_chars = max_chunk_chars
        self._max_chunks = max_chunks
        self._prefixes = prefixes_for(model_name)
        self._model: object | None = None
        self._lock = threading.RLock()  # модель и кеш — по одному вызову за раз
        self._cache: OrderedDict[str, Vector] = OrderedDict()
        self._cache_size = cache_size

    def _load(self) -> object:
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                from transformers.utils import logging as hf_logging

                hf_logging.disable_progress_bar()  # type: ignore[no-untyped-call]
                self._model = SentenceTransformer(self.name, device=self._device)
            return self._model

    def encode(self, texts: Sequence[str], kind: EmbedKind) -> Matrix:
        with self._lock:
            return self._encode_locked(texts, kind)

    def _encode_locked(self, texts: Sequence[str], kind: EmbedKind) -> Matrix:
        prefix = self._prefixes[kind]
        out: list[Vector | None] = []
        missing: dict[int, str] = {}
        for i, t in enumerate(texts):
            key = _cache_key(kind, t)
            vec = self._cache.get(key)
            if vec is None:
                missing[i] = t
            else:
                self._cache.move_to_end(key)
            out.append(vec)
        if missing:
            new = self._encode_uncached(list(missing.values()), prefix)
            for (i, t), vec in zip(missing.items(), new, strict=True):
                out[i] = vec
                self._remember(_cache_key(kind, t), vec)
        dim = next((v.shape[0] for v in out if v is not None), 0)
        return np.vstack([v for v in out if v is not None]) if out else np.zeros((0, dim), np.float32)

    def _encode_uncached(self, texts: list[str], prefix: str) -> list[Vector]:
        chunks: list[str] = []
        owner: list[int] = []
        for i, t in enumerate(texts):
            for c in chunk_text(t, self._max_chunk_chars, self._max_chunks):
                chunks.append(c)
                owner.append(i)
        model = self._load()
        raw = model.encode(  # type: ignore[attr-defined]
            chunks,
            batch_size=self._batch_size,
            prompt=prefix,  # явный префикс: иначе модель подставит свой префикс по умолчанию
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        mat = np.asarray(raw, dtype=np.float32)
        sums = np.zeros((len(texts), mat.shape[1]), dtype=np.float32)
        np.add.at(sums, np.asarray(owner), mat)
        return [_normalize(v) for v in sums]

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _remember(self, key: str, vec: Vector) -> None:
        self._cache[key] = vec
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _cache_key(kind: str, text: str) -> str:
    return kind + ":" + hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def _normalize(v: Vector) -> Vector:
    n = float(np.linalg.norm(v))
    return (v / n).astype(np.float32) if n > 0 else v.astype(np.float32)


def cosine_to_many(query: Vector, docs: Matrix) -> npt.NDArray[np.float32]:
    if docs.shape[0] == 0:
        return np.zeros(0, dtype=np.float32)
    return np.asarray(docs @ query, dtype=np.float32)
