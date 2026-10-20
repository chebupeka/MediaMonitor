"""Детектор ИИ-текста без скачивания модели: контракт /ai-detect, токен, 503, детерминизм обёртки,
нормализация как на сервере, расчёт маленькой случайной Mistral тем же способом, что у GigaCheck."""

from __future__ import annotations

import json
import threading
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mm_embeddings.app import MAX_DETECT_TEXTS, create_app
from mm_embeddings.detector import (
    Detector,
    DetectorSlot,
    MemoDetector,
    ai_index,
    encode_input,
    normalize_text,
)
from mm_embeddings.settings import DEFAULT_DETECT_MODEL, Settings
from tests.conftest import AUTH, TOKEN, FakeEncoder, fake_score

VECTORS = Path(__file__).resolve().parents[2] / "server" / "tests" / "contract" / "ai-normalize-vectors.json"


@pytest.fixture
def det_client(fake: FakeEncoder, detector: MemoDetector) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(token=TOKEN), fake, detector)) as c:
        yield c


def slot_client(fake: FakeEncoder, slot: DetectorSlot) -> TestClient:
    return TestClient(create_app(Settings(token=TOKEN), fake, slot))


# --------------------------------------------------------------------------- контракт
def test_scores_in_order_with_model_and_version(det_client: TestClient) -> None:
    texts = ["первый текст поста", "второй текст поста", "третий текст поста"]
    r = det_client.post("/ai-detect", json={"texts": texts}, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {
        "model": DEFAULT_DETECT_MODEL,
        "version": "test-rev-nf4",
        "scores": [fake_score(t) for t in texts],
    }


def test_empty_list_tells_model_and_version(det_client: TestClient, detector: MemoDetector) -> None:
    # Сервер так узнаёт версию модели при старте.
    r = det_client.post("/ai-detect", json={"texts": []}, headers=AUTH)
    assert r.json() == {"model": DEFAULT_DETECT_MODEL, "version": "test-rev-nf4", "scores": []}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token-0123456789"}, {"Authorization": f"Basic {TOKEN}"}],
)
def test_ai_detect_needs_token(det_client: TestClient, calls: list[str], headers: dict[str, str]) -> None:
    r = det_client.post("/ai-detect", json={"texts": ["текст"]}, headers=headers)
    assert r.status_code == 401
    assert calls == []


def test_bad_body_is_422(det_client: TestClient, calls: list[str]) -> None:
    assert det_client.post("/ai-detect", json={"texts": "не список"}, headers=AUTH).status_code == 422
    assert det_client.post("/ai-detect", json={"texts": [1]}, headers=AUTH).status_code == 422
    assert det_client.post("/ai-detect", json={}, headers=AUTH).status_code == 422
    too_many = {"texts": [f"текст {i}" for i in range(MAX_DETECT_TEXTS + 1)]}
    assert det_client.post("/ai-detect", json=too_many, headers=AUTH).status_code == 422
    assert calls == []


def test_batch_of_64_is_accepted(det_client: TestClient) -> None:
    texts = [f"текст номер {i}" for i in range(MAX_DETECT_TEXTS)]
    assert len(det_client.post("/ai-detect", json={"texts": texts}, headers=AUTH).json()["scores"]) == 64


def test_health_shows_detector(det_client: TestClient) -> None:
    h = det_client.get("/health").json()
    assert h["status"] == "ok"
    assert h["model"] == "sergeyzh/BERTA"
    assert h["ai_detect"] == {
        "state": "ready",
        "model": DEFAULT_DETECT_MODEL,
        "version": "test-rev-nf4",
        "device": "cpu",
    }


def test_answer_matches_server_client() -> None:
    """Ответ проходит проверку клиента сервера (`aicheck/providers.py`, `_validate`): те же правила."""
    detector = MemoDetector(DEFAULT_DETECT_MODEL, "1b885318d031-nf4", "cuda", lambda t: 0.123456)
    with TestClient(create_app(Settings(token=TOKEN), FakeEncoder(), detector)) as c:
        data = c.post("/ai-detect", json={"texts": ["а", "б"]}, headers=AUTH).json()
    assert isinstance(data["model"], str)
    assert data["model"] == DEFAULT_DETECT_MODEL
    assert isinstance(data["version"], str)
    assert 0 < len(data["version"]) <= 100
    assert data["scores"] == [0.1235, 0.1235]
    assert all(isinstance(s, float) and 0.0 <= s <= 1.0 for s in data["scores"])


# --------------------------------------------------------------------------- 503
@pytest.mark.parametrize(
    ("slot", "code"),
    [
        (DetectorSlot.disabled(), "ai-detect-disabled"),
        (DetectorSlot(DEFAULT_DETECT_MODEL, "loading"), "ai-detect-loading"),
        (DetectorSlot(DEFAULT_DETECT_MODEL, "failed", error="OSError: нет места"), "ai-detect-failed"),
    ],
)
def test_not_ready_is_503_and_embeddings_still_work(fake: FakeEncoder, slot: DetectorSlot, code: str) -> None:
    with slot_client(fake, slot) as c:
        r = c.post("/ai-detect", json={"texts": ["текст"]}, headers=AUTH)
        assert r.status_code == 503
        assert r.json()["code"] == code
        assert "детектор" in r.json()["detail"]
        # Пустой список тоже 503: сервер не должен думать, что детектор есть.
        assert c.post("/ai-detect", json={"texts": []}, headers=AUTH).status_code == 503
        assert c.get("/health").json()["ai_detect"]["state"] == slot.state
        assert c.post("/embed", json={"texts": ["x"]}, headers=AUTH).status_code == 200


def test_loading_answer_has_retry_after(fake: FakeEncoder) -> None:
    with slot_client(fake, DetectorSlot(DEFAULT_DETECT_MODEL, "loading")) as c:
        r = c.post("/ai-detect", json={"texts": ["текст"]}, headers=AUTH)
    assert r.headers["retry-after"] == "60"
    assert "загружается" in r.json()["detail"]


def test_failed_reason_is_in_health_and_answer(fake: FakeEncoder) -> None:
    slot = DetectorSlot(DEFAULT_DETECT_MODEL, "failed", error="OSError: нет места на диске")
    with slot_client(fake, slot) as c:
        assert c.get("/health").json()["ai_detect"]["error"] == "OSError: нет места на диске"
        answer = c.post("/ai-detect", json={"texts": ["т"]}, headers=AUTH).json()
        assert "нет места на диске" in answer["detail"]


def test_model_error_is_503(fake: FakeEncoder) -> None:
    def broken(text: str) -> float:
        raise RuntimeError("CUDA error: out of memory")

    detector = MemoDetector(DEFAULT_DETECT_MODEL, "v", "cuda", broken)
    with TestClient(create_app(Settings(token=TOKEN), fake, detector)) as c:
        r = c.post("/ai-detect", json={"texts": ["текст"]}, headers=AUTH)
    assert r.status_code == 503
    assert r.json()["code"] == "detect-error"


def test_nan_is_an_error_not_a_score(fake: FakeEncoder) -> None:
    detector = MemoDetector(DEFAULT_DETECT_MODEL, "v", "cuda", lambda t: float("nan"))
    with TestClient(create_app(Settings(token=TOKEN), fake, detector)) as c:
        assert c.post("/ai-detect", json={"texts": ["текст"]}, headers=AUTH).status_code == 503


# --------------------------------------------------------------------------- загрузка фоном
def _settings(**kw: Any) -> Settings:
    return Settings(token=TOKEN, **kw)


def test_disabled_detector_is_not_loaded() -> None:
    loaded: list[Settings] = []

    def loader(s: Settings) -> Detector:
        loaded.append(s)
        raise AssertionError("не должен грузиться")

    slot = DetectorSlot.start(_settings(ai_detect_enabled=False), loader)
    assert slot.state == "disabled"
    assert slot.thread is None
    assert loaded == []


def test_background_load_ready(calls: list[str]) -> None:
    gate = threading.Event()
    detector = MemoDetector(DEFAULT_DETECT_MODEL, "v1", "cuda", lambda t: 0.5)

    def loader(s: Settings) -> Detector:
        gate.wait(5)
        return detector

    slot = DetectorSlot.start(_settings(), loader)
    assert slot.state == "loading"  # порт уже открыт, детектор ещё грузится
    gate.set()
    assert slot.thread is not None
    slot.thread.join(5)
    assert str(slot.state) == "ready"  # str: mypy помнит «loading» из проверки выше
    assert slot.get() is detector
    health = {"state": "ready", "model": DEFAULT_DETECT_MODEL, "version": "v1", "device": "cuda"}
    assert slot.health() == health


def test_background_load_failure_keeps_service(fake: FakeEncoder) -> None:
    def loader(s: Settings) -> Detector:
        raise OSError("No space left on device")

    slot = DetectorSlot.start(_settings(), loader)
    assert slot.thread is not None
    slot.thread.join(5)
    assert slot.state == "failed"
    assert slot.error == "OSError: No space left on device"
    with slot_client(fake, slot) as c:
        assert c.post("/ai-detect", json={"texts": ["т"]}, headers=AUTH).status_code == 503
        assert c.post("/embed", json={"texts": ["т"]}, headers=AUTH).status_code == 200


# --------------------------------------------------------------------------- детерминизм обёртки
def test_same_text_same_score_independent_of_batch(detector: MemoDetector, calls: list[str]) -> None:
    a = "Бабочки — насекомые отряда чешуекрылых."
    b = "В Ачинске прошёл рейд «Пешеход»."
    c = "Краевое МЧС напоминает о мерах пожарной безопасности."
    first = detector.score([a])
    batch = detector.score([b, a, c])
    reverse = detector.score([c, a, b])
    assert batch[1] == first[0] == reverse[1]
    assert batch[0] == reverse[2]
    assert calls == [a, b, c]  # каждый текст считается один раз, отдельно от соседей


def test_whitespace_variants_are_one_text(detector: MemoDetector, calls: list[str]) -> None:
    base = "В Норильске открылась школа на 1100 мест, пишет краевой портал."
    variants = [
        base,
        "  В Норильске\n\nоткрылась\tшкола на 1100 мест,\r\nпишет краевой портал.\n",
        "В Норильске открылась шко"
        + chr(0x00AD)
        + "ла на 1100"
        + chr(0x200B)
        + " мест, пишет краевой портал.",
        "В Норильске" + chr(0x00A0) + "открылась школа на 1100 мест, пишет краевой портал.",
        unicodedata.normalize("NFD", base),  # «й» разложена на «и» + U+0306
    ]
    scores = detector.score(variants)
    assert len(set(scores)) == 1
    assert calls == [base]


def test_scores_rounded_and_clamped() -> None:
    values = iter([0.987654321, 1.0000001, -1e-9])
    d = MemoDetector("m", "v", "cpu", lambda t: next(values))
    assert d.score(["а", "б", "в"]) == [0.9877, 1.0, 0.0]


def test_memo_is_bounded(calls: list[str]) -> None:
    def score_one(text: str) -> float:
        calls.append(text)
        return 0.5

    d = MemoDetector("m", "v", "cpu", score_one, memo_size=2)
    d.score(["а", "б", "в", "а"])  # «а» вытеснен «в» и считается снова
    assert calls == ["а", "б", "в", "а"]


@pytest.mark.skipif(not VECTORS.is_file(), reason="нет server/tests/contract/ai-normalize-vectors.json")
def test_normalization_matches_server_vectors() -> None:
    vectors = json.loads(VECTORS.read_text("utf-8"))
    assert vectors
    for v in vectors:
        assert normalize_text(v["input"]) == v["normalized"], v["note"]
        assert normalize_text(v["normalized"]) == v["normalized"], v["note"]  # повтор ничего не меняет


# --------------------------------------------------------------------------- вход и модель
class FakeTokenizer:
    bos_token_id = 1
    eos_token_id = 2

    def __call__(self, text: str, add_special_tokens: bool) -> dict[str, list[int]]:
        assert add_special_tokens is False
        return {"input_ids": [10 + (ord(ch) % 100) for ch in text]}


def test_input_like_gigacheck() -> None:
    tok = FakeTokenizer()
    assert encode_input(tok, "абв", 1024) == [1, *tok("абв", add_special_tokens=False)["input_ids"], 2]
    long = encode_input(tok, "x" * 50, 10)
    assert len(long) == 10
    assert long[0] == 1
    assert long[-1] == 2


def test_ai_label_index() -> None:
    assert ai_index({0: "ai", 1: "human"}) == 0
    assert ai_index({"0": "human", "1": "AI"}) == 1
    with pytest.raises(RuntimeError, match="ai"):
        ai_index({0: "human", 1: "mixed"})


def test_model_reads_eos_token_like_gigacheck() -> None:
    """Маленькая случайная Mistral: наш расчёт по одному тексту = расчёт GigaCheck пакетом с
    выравниванием (pad = 0, токен `</s>` ищется как «первый pad − 1»), и не зависит от соседей."""
    import torch
    from transformers import MistralConfig

    from mm_embeddings.detector import build_model_class

    torch.manual_seed(0)
    cfg = MistralConfig(
        vocab_size=64,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=128,
        pad_token_id=0,
        id2label={0: "ai", 1: "human"},
    )
    model = build_model_class()(cfg).eval()
    seqs = [[1, 5, 6, 7, 2], [1, 9, 2], [1, 11, 12, 13, 14, 15, 16, 2]]
    with torch.inference_mode():
        ours = [model(torch.tensor([s])).float().softmax(-1)[0, 0].item() for s in seqs]
        again = [model(torch.tensor([s])).float().softmax(-1)[0, 0].item() for s in reversed(seqs)]
        # Как в gigacheck: пакет с выравниванием справа нулями, токен </s> — перед первым pad.
        width = max(map(len, seqs))
        ids = torch.tensor([s + [0] * (width - len(s)) for s in seqs])
        mask = (ids != 0).long()
        hidden = model.model(input_ids=ids, attention_mask=mask, use_cache=False).last_hidden_state
        pos = torch.eq(ids, 0).long().argmax(-1) - 1
        logits = model.classification_head(hidden[torch.arange(len(seqs)), pos])
        theirs = logits.float().softmax(-1)[:, 0].tolist()
    assert ours == list(reversed(again))
    for a, b in zip(ours, theirs, strict=True):
        assert a == pytest.approx(b, abs=1e-5)
