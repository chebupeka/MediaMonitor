"""Контракт сервиса: токен, порядок векторов, размерность, пакеты до 256 текстов, /health."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mm_embeddings.app import MAX_TEXTS
from tests.conftest import AUTH, TOKEN, FakeEncoder


def body(texts: list[str], prefix: str = "paraphrase: ", **extra: object) -> dict[str, object]:
    return {"texts": texts, "model": "sergeyzh/BERTA", "prefix": prefix, "normalize": True, **extra}


def test_health_is_public_and_exact(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "model": "sergeyzh/BERTA",
        "device": "cpu",
        "ai_detect": {"state": "disabled", "model": "iitolstykh/GigaCheck-Classifier-Multi"},
    }


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token-0123456789"},
        {"Authorization": f"Bearer {TOKEN}x"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": TOKEN},
        {"Authorization": "Bearer "},
    ],
)
def test_embed_without_valid_token_is_401(
    client: TestClient, fake: FakeEncoder, headers: dict[str, str]
) -> None:
    r = client.post("/embed", json=body(["текст"]), headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert fake.calls == []


def test_token_checked_before_body(client: TestClient) -> None:
    # Без токена не раскрываем даже ошибки разбора тела и неизвестные адреса.
    assert (
        client.post("/embed", content=b"{broken", headers={"Content-Type": "application/json"}).status_code
        == 401
    )
    assert client.get("/docs").status_code == 401
    assert client.get("/openapi.json").status_code == 401


def test_bearer_scheme_is_case_insensitive(client: TestClient) -> None:
    r = client.post("/embed", json=body(["текст"]), headers={"Authorization": f"bearer {TOKEN}"})
    assert r.status_code == 200


def test_one_vector_per_text_in_order(client: TestClient, fake: FakeEncoder) -> None:
    texts = ["первый пост", "второй пост", "третий пост", "первый пост"]
    r = client.post("/embed", json=body(texts), headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["model"] == "sergeyzh/BERTA"
    assert data["dim"] == fake.dim
    vectors = np.asarray(data["vectors"], dtype=np.float32)
    assert vectors.shape == (len(texts), fake.dim)
    for i, t in enumerate(texts):
        np.testing.assert_allclose(vectors[i], fake.vector(t, "paraphrase: "), rtol=1e-6)
    np.testing.assert_allclose(vectors[0], vectors[3])
    reversed_ = np.asarray(client.post("/embed", json=body(texts[::-1]), headers=AUTH).json()["vectors"])
    np.testing.assert_allclose(reversed_[::-1], vectors, rtol=1e-6)


def test_prefix_and_normalize_reach_the_model(client: TestClient, fake: FakeEncoder) -> None:
    client.post("/embed", json=body(["тема"], prefix="categorize_topic: "), headers=AUTH)
    client.post("/embed", json=body(["тема"], prefix="", normalize=False), headers=AUTH)
    assert fake.calls == [(["тема"], "categorize_topic: ", True), (["тема"], "", False)]


def test_vectors_are_unit_length_when_normalized(client: TestClient) -> None:
    data = client.post("/embed", json=body(["а", "б", "в"]), headers=AUTH).json()
    np.testing.assert_allclose(np.linalg.norm(np.asarray(data["vectors"]), axis=1), 1.0, rtol=1e-5)


def test_batch_of_256_is_accepted(client: TestClient) -> None:
    texts = [f"пост номер {i}" for i in range(MAX_TEXTS)]
    data = client.post("/embed", json=body(texts), headers=AUTH).json()
    assert len(data["vectors"]) == MAX_TEXTS
    assert all(len(v) == data["dim"] for v in data["vectors"])


def test_batch_over_256_is_rejected(client: TestClient, fake: FakeEncoder) -> None:
    r = client.post("/embed", json=body([f"пост {i}" for i in range(MAX_TEXTS + 1)]), headers=AUTH)
    assert r.status_code == 422
    assert fake.calls == []


def test_empty_batch(client: TestClient, fake: FakeEncoder) -> None:
    data = client.post("/embed", json=body([]), headers=AUTH).json()
    assert data == {"model": "sergeyzh/BERTA", "dim": fake.dim, "vectors": []}


def test_defaults_prefix_empty_and_normalize_true(client: TestClient, fake: FakeEncoder) -> None:
    r = client.post("/embed", json={"texts": ["x"]}, headers=AUTH)
    assert r.status_code == 200
    assert fake.calls == [(["x"], "", True)]


def test_other_model_is_rejected(client: TestClient, fake: FakeEncoder) -> None:
    r = client.post("/embed", json=body(["x"], model="deepvk/USER2-base"), headers=AUTH)
    assert r.status_code == 400
    assert r.json()["code"] == "model-mismatch"
    assert fake.calls == []


def test_bad_body_is_422(client: TestClient) -> None:
    assert client.post("/embed", json={"texts": "не список"}, headers=AUTH).status_code == 422
    assert client.post("/embed", json={"texts": [1, 2]}, headers=AUTH).status_code == 422
    assert client.post("/embed", json=body(["x"], prefix="p" * 201), headers=AUTH).status_code == 422


def test_model_failure_is_503_json(client: TestClient, fake: FakeEncoder) -> None:
    fake.fail = True
    r = client.post("/embed", json=body(["x"]), headers=AUTH)
    assert r.status_code == 503
    assert r.json()["code"] == "encode-failed"


def test_too_large_body_is_413(client: TestClient) -> None:
    r = client.post("/embed", content=b"{}", headers={**AUTH, "Content-Length": str(64 * 1024 * 1024)})
    assert r.status_code == 413
