"""Общие заготовки тестов: поддельные модель эмбеддингов и нейросеть (без сети и загрузок)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pytest

from mm_matching.config import LlmSettings, MatcherConfig, NewsThresholds
from mm_matching.embeddings import EmbedKind, Matrix
from mm_matching.events import EventExtractor
from mm_matching.funnel import FunnelMatcher
from mm_matching.llm import LlmError
from mm_matching.text import content_stems, tokenize


class FakeEmbedder:
    """Мешок основ слов → вектор. Похожие по словам тексты близки, этого хватает тестам."""

    name = "fake"

    def encode(self, texts: Sequence[str], kind: EmbedKind) -> Matrix:
        del kind
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for i, t in enumerate(texts):
            for s in content_stems(tokenize(t)):
                h = int(hashlib.md5(s.encode()).hexdigest(), 16)
                out[i, h % 256] += 1.0
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


class FakeLlm:
    """Нейросеть-заглушка: отвечает функцией `reply(system, user, schema)` и пишет журнал."""

    def __init__(
        self,
        reply: Callable[[str, str, dict[str, Any]], str] | None = None,
        *,
        available: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.reply = reply
        self._available = available
        self.error = error
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def description(self) -> str:
        return "fake"

    def available(self) -> bool:
        return self._available

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        self.calls.append((system, user, schema))
        if self.error is not None:
            raise self.error
        if self.reply is None:
            raise LlmError("нет ответа")
        return self.reply(system, user, schema)


def verdict_json(pid: str, label: str, sentence: int = 0) -> str:
    return f'{{"verdicts": [{{"id": "{pid}", "label": "{label}", "evidence_sentence": {sentence}}}]}}'


def answer_with(label: str, sentence: int = 0) -> Callable[[str, str, dict[str, Any]], str]:
    """Ответ «как попросили по схеме»: id берём из схемы запроса."""

    def reply(system: str, user: str, schema: dict[str, Any]) -> str:
        del system, user
        pid = schema["properties"]["verdicts"]["items"]["properties"]["id"]["enum"][0]
        return verdict_json(pid, label, sentence)

    return reply


# Всё, что не копия, — в серую зону: так тесты нейросети не зависят от порогов.
ALL_GRAY = MatcherConfig(news=NewsThresholds(cos_no=-1.0, cos_yes=2.0, cos_supported=2.0))


@pytest.fixture(scope="session")
def events() -> EventExtractor:
    return EventExtractor()


@pytest.fixture
def make_matcher() -> Callable[..., FunnelMatcher]:
    def make(
        *,
        llm: Any = None,
        config: MatcherConfig | None = None,
        events: EventExtractor | None = None,
    ) -> FunnelMatcher:
        return FunnelMatcher(
            config or ALL_GRAY,
            embedder=FakeEmbedder(),
            llm=llm,
            events=events,
            llm_settings=LlmSettings(url="http://fake", max_gray=100, deadline_s=60),
        )

    return make


RELEASE = (
    "В Ачинском районе 14 октября на трассе Р-255 столкнулись два автомобиля.\n"
    "Погибли 2 человека, ещё 3 пострадали. По предварительным данным, водитель легковушки "
    "выехал на встречную полосу.\n"
    "На месте работали сотрудники Госавтоинспекции. Ведётся проверка, сообщает пресс-служба "
    "ГУ МВД по Красноярскому краю."
)
RETOLD = (
    "Смертельная авария под Ачинском: во вторник на федеральной трассе столкнулись две машины. "
    "Двое погибли, трое получили травмы. Виновник ДТП, по данным полиции, выехал на встречку."
)
OTHER_EVENT = (
    "В Канске 3 октября водитель иномарки сбил пешехода на улице Ленина. "
    "Пострадавшую доставили в больницу. Обстоятельства выясняет Госавтоинспекция."
)
