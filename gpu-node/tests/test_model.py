"""Настоящая модель BERTA на CPU (~0,5 ГБ, скачивается с Hugging Face при первом запуске).

Пропустить: MM_SKIP_MODEL_TESTS=1.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mm_embeddings.app import create_app
from mm_embeddings.encoder import SentenceTransformerEncoder
from mm_embeddings.settings import Settings
from tests.conftest import AUTH, TOKEN

pytestmark = pytest.mark.skipif(os.environ.get("MM_SKIP_MODEL_TESTS") == "1", reason="MM_SKIP_MODEL_TESTS=1")

TEXTS = [
    "В Красноярске открыли движение по новому мосту через Енисей.",
    "Сотрудники Госавтоинспекции провели рейд «Пешеход» в Ачинске.",
    "Краевое МЧС напоминает о мерах пожарной безопасности в отопительный сезон.",
]


@pytest.fixture(scope="module")
def encoder() -> SentenceTransformerEncoder:
    return SentenceTransformerEncoder(Settings(token=TOKEN, device="cpu", batch_size=16))


@pytest.fixture(scope="module")
def client(encoder: SentenceTransformerEncoder) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(token=TOKEN), encoder)) as c:
        yield c


def test_dimension_and_unit_length(encoder: SentenceTransformerEncoder) -> None:
    m = encoder.encode(TEXTS, "paraphrase: ", normalize=True)
    assert encoder.dim == 768
    assert m.shape == (3, 768)
    assert m.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(m, axis=1), 1.0, rtol=1e-5)


def test_order_and_batch_do_not_change_vectors(encoder: SentenceTransformerEncoder) -> None:
    together = encoder.encode(TEXTS, "paraphrase: ", normalize=True)
    reversed_ = encoder.encode(TEXTS[::-1], "paraphrase: ", normalize=True)[::-1]
    alone = np.vstack([encoder.encode([t], "paraphrase: ", normalize=True) for t in TEXTS])
    assert np.min(np.sum(together * reversed_, axis=1)) > 0.99999
    assert np.min(np.sum(together * alone, axis=1)) > 0.99999


def test_prefix_is_applied_and_empty_means_none(encoder: SentenceTransformerEncoder) -> None:
    para = encoder.encode(TEXTS[:1], "paraphrase: ", normalize=True)[0]
    topic = encoder.encode(TEXTS[:1], "categorize_topic: ", normalize=True)[0]
    empty = encoder.encode(TEXTS[:1], "", normalize=True)[0]
    # Пустой префикс — без префикса, а не префикс модели по умолчанию («categorize_entailment: »).
    default = encoder.encode(TEXTS[:1], "categorize_entailment: ", normalize=True)[0]
    assert float(para @ topic) < 0.999
    assert float(empty @ default) < 0.999


def test_meaning_is_captured(encoder: SentenceTransformerEncoder) -> None:
    a, b, c = encoder.encode(
        [
            "В Красноярске открыли движение по новому мосту через Енисей.",
            "Новый мост через Енисей в Красноярске запустили для машин.",
            "В Норильске прошёл турнир по шахматам среди школьников.",
        ],
        "paraphrase: ",
        normalize=True,
    )
    assert float(a @ b) > float(a @ c) + 0.1


def test_http_batch_of_256_with_real_model(client: TestClient) -> None:
    texts = [f"{TEXTS[i % 3]} Номер {i}." for i in range(256)]
    r = client.post(
        "/embed",
        json={"texts": texts, "model": "sergeyzh/BERTA", "prefix": "paraphrase: ", "normalize": True},
        headers=AUTH,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["dim"] == 768
    vectors = np.asarray(data["vectors"], dtype=np.float32)
    assert vectors.shape == (256, 768)
    # Вектор из JSON совпадает с вектором модели: числа float32 не теряют точности.
    direct = client.app.state.encoder.encode(texts[:3], "paraphrase: ", normalize=True)  # type: ignore[attr-defined]
    assert np.min(np.sum(vectors[:3] * direct, axis=1)) > 0.99999
    assert client.get("/health").json() == {"status": "ok", "model": "sergeyzh/BERTA", "device": "cpu"}
