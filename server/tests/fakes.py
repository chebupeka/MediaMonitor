"""Подмены для тестов воронки: лёгкая модель смысла вместо BERTA и нейросеть-заглушка.

Модель — «мешок основ слов» (как в тестах mm_matching): похожие по словам тексты близки.
Пороги воронки под неё снижены — проверяется устройство сервера, а не качество отбора.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from mm_matching.config import MatcherConfig, NewsThresholds, TopicThresholds
from mm_matching.embeddings import EmbedKind, Matrix
from mm_matching.events import EventExtractor
from mm_matching.llm import LlmError
from mm_matching.text import content_stems, tokenize

from mediamonitor.ai.judge import AiStats, AiStatus, JudgeRequest, TopicDraft, Verdict
from mediamonitor.matcher.embeddings import CachingEmbedder, HttpEmbedder
from mediamonitor.matcher.funnel import FunnelMatcher
from mediamonitor.settings import Settings

_EVENTS: EventExtractor | None = None


def shared_events() -> EventExtractor:
    """Natasha грузится ~1 с — одна на все тесты."""
    global _EVENTS  # noqa: PLW0603
    if _EVENTS is None:
        _EVENTS = EventExtractor()
    return _EVENTS


class FakeEmbedder:
    name = "fake-berta"

    def __init__(self) -> None:
        self.calls: list[tuple[EmbedKind, int]] = []

    def encode(self, texts: Sequence[str], kind: EmbedKind) -> Matrix:
        self.calls.append((kind, len(texts)))
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for i, text in enumerate(texts):
            for stem in content_stems(tokenize(text)):
                out[i, int(hashlib.md5(stem.encode()).hexdigest(), 16) % 256] += 1.0  # noqa: S324
            norm = np.linalg.norm(out[i])
            if norm:
                out[i] /= norm
        return out


FAKE_CONFIG = MatcherConfig(
    news=NewsThresholds(cos_no=0.15, cos_yes=0.55, cos_supported=0.35),
    topic=TopicThresholds(sim_no=0.04, sim_yes=0.2, margin_yes=0.0, margin_no=-0.3, sim_direct=0.3),
    embedding_model="fake-berta",
)


class FakeLlm:
    """Нейросеть-заглушка с журналом: отвечает «direct» по последнему предложению."""

    def __init__(self, *, available: bool = True, fail: bool = False) -> None:
        self._available = available
        self.fail = fail
        self.calls = 0

    @property
    def description(self) -> str:
        return "fake"

    def available(self) -> bool:
        return self._available

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        del system, user
        self.calls += 1
        if self.fail:
            raise LlmError("нейросеть недоступна")
        if "verdicts" not in schema.get("properties", {}):
            return json.dumps(
                {
                    "summary": "Тема поиска",
                    "includes": ["ДТП"],
                    "excludes": ["Пожарная безопасность"],
                },
                ensure_ascii=False,
            )
        item = schema["properties"]["verdicts"]["items"]["properties"]
        pid = item["id"]["enum"][0]
        label = "direct" if "direct" in item["label"]["enum"] else item["label"]["enum"][0]
        return json.dumps({"verdicts": [{"id": pid, "label": label, "evidence_sentence": 0}]})


class AvailableJudge:
    """Сервер считает нейросеть доступной; отвечает за отбор нейросеть воронки (FakeLlm)."""

    model_label = "fake"

    def __init__(self) -> None:
        self.stats = AiStats()

    async def status(self) -> AiStatus:
        return AiStatus(True, None)

    async def judge(self, request: JudgeRequest) -> dict[str, Verdict]:
        del request
        return {}

    async def topic_card(self, text: str, notes: str | None) -> TopicDraft | None:
        del text, notes
        return None

    async def warmup(self) -> None:
        return None


def make_funnel(
    settings: Settings,
    *,
    embedder: FakeEmbedder | None = None,
    remote: HttpEmbedder | None = None,
    llm: Any = None,
    clock: Callable[[], float] | None = None,
) -> FunnelMatcher:
    model = embedder or FakeEmbedder()
    extra: dict[str, Any] = {"clock": clock} if clock else {}
    caching = CachingEmbedder(
        "fake-berta",
        local=lambda: model,
        remote=remote,
        retry_after=settings.embeddings_retry_after_sec,
        **extra,
    )
    return FunnelMatcher(
        settings, embedder=caching, llm=llm, events=shared_events(), config=FAKE_CONFIG
    )


def create_test_funnel(settings: Settings) -> FunnelMatcher:
    """Фабрика для MATCHER в тестах: воронка с лёгкой моделью, без нейросети."""
    return make_funnel(settings)
