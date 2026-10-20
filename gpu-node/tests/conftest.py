from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mm_embeddings.app import create_app
from mm_embeddings.detector import DetectorSlot, MemoDetector
from mm_embeddings.encoder import Matrix
from mm_embeddings.settings import DEFAULT_DETECT_MODEL, Settings

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeEncoder:
    """Детерминированные векторы из хеша «префикс + текст»: контракт проверяется без модели."""

    model_name = "sergeyzh/BERTA"
    device = "cpu"
    dim = 8

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, bool]] = []
        self.fail = False

    def vector(self, text: str, prefix: str, normalize: bool = True) -> Matrix:
        digest = hashlib.sha256((prefix + text).encode("utf-8")).digest()
        v = np.frombuffer(digest[: self.dim * 4], dtype=np.uint32).astype(np.float32) / 2**32 + 0.5
        out = v / np.linalg.norm(v) if normalize else v
        return out.astype(np.float32)

    def encode(self, texts: Sequence[str], prefix: str, normalize: bool) -> Matrix:
        if self.fail:
            raise RuntimeError("CUDA error: device-side assert triggered")
        self.calls.append((list(texts), prefix, normalize))
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self.vector(t, prefix, normalize) for t in texts]).astype(np.float32)


@pytest.fixture
def fake() -> FakeEncoder:
    return FakeEncoder()


def fake_score(text: str) -> float:
    """Оценка-заглушка из хеша текста, до 4 знаков — как округляет обёртка."""
    return round(int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) / 2**32, 4)


@pytest.fixture
def calls() -> list[str]:
    """Какие тексты дошли до «модели» детектора."""
    return []


@pytest.fixture
def detector(calls: list[str]) -> MemoDetector:
    """Настоящая обёртка (нормализация, память, порядок) над заглушкой вместо модели."""

    def score_one(text: str) -> float:
        calls.append(text)
        return fake_score(text)

    return MemoDetector(DEFAULT_DETECT_MODEL, "test-rev-nf4", "cpu", score_one)


@pytest.fixture
def client(fake: FakeEncoder) -> Iterator[TestClient]:
    # Детектор выключен: тесты эмбеддингов не должны скачивать GigaCheck.
    app = create_app(Settings(token=TOKEN), fake, DetectorSlot.disabled())
    with TestClient(app) as c:
        yield c
