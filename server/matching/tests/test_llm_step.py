"""Шаг нейросети: проверка доказательства по смыслу, карточка темы, порядок и параллельность."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
import numpy as np
import pytest

from mm_matching.config import LlmSettings, MatcherConfig, NewsThresholds, TopicThresholds
from mm_matching.embeddings import EmbedKind, Matrix
from mm_matching.funnel import NOTE_AI_BUDGET, NOTE_AI_UNSUPPORTED, FunnelMatcher
from mm_matching.llm import OllamaClient, keep_alive_value
from mm_matching.topic import (
    apply_correction,
    clear_card_cache,
    cutting_excludes,
    fallback_card,
    finalize_ai_card,
    parse_card,
    topic_parts,
)
from mm_matching.types import Candidate, MatchResult

from .conftest import ALL_GRAY, RELEASE, RETOLD, FakeEmbedder, FakeLlm, answer_with

TOPIC_GRAY = MatcherConfig(topic=TopicThresholds(sim_no=-1.0, sim_yes=2.0, margin_no=-9.0))
QUERY = "безопасность дорожного движения"


@pytest.fixture(autouse=True)
def _fresh_card_cache() -> Iterator[None]:
    clear_card_cache()
    yield
    clear_card_cache()


def _matcher(
    llm: Any, config: MatcherConfig = TOPIC_GRAY, embedder: Any = None, **settings: Any
) -> FunnelMatcher:
    s = LlmSettings(url="http://fake", **{"max_gray": 100, "deadline_s": 60, **settings})
    return FunnelMatcher(config, embedder=embedder or FakeEmbedder(), llm=llm, events=None, llm_settings=s)


# ---------------------------------------------------------------- проверка доказательства


class ConceptEmbedder:
    """Вектор — набор «понятий» по словам: так близки тексты без общих слов («автобус
    опрокинулся» и «безопасность дорожного движения»), как у настоящей модели."""

    name = "concepts"
    CONCEPTS = (
        ("дорожн", "автобус", "дтп", "опрокинул", "трасс", "водител"),
        ("взятк", "приговор", "суд", "осужд"),
        ("кот", "котик"),
    )

    def encode(self, texts: Sequence[str], kind: EmbedKind) -> Matrix:
        del kind
        out = np.full((len(texts), len(self.CONCEPTS) + 1), 0.05, dtype=np.float32)
        for i, t in enumerate(texts):
            low = t.lower()
            for j, words in enumerate(self.CONCEPTS):
                out[i, j] += sum(1.0 for w in words if w in low)
            out[i] /= np.linalg.norm(out[i])
        return out


def test_headline_without_shared_words_is_accepted_by_meaning() -> None:
    # Нейросеть ссылается на заголовок: общих основ слов с запросом нет, но по смыслу он о БДД.
    post = "Автобус с детьми опрокинулся под Минусинском. Пострадавших доставили в больницу."
    m = _matcher(FakeLlm(answer_with("direct", 0)), embedder=ConceptEmbedder())
    r = m.match_topic(fallback_card(QUERY), [Candidate("bus", post)]).results[0]
    assert r.method == "ai-confirmed" and r.relevance == "direct"
    assert r.scores.evidence_cosine is not None and r.scores.evidence_cosine >= 0.9


def test_sentence_far_from_topic_is_not_accepted() -> None:
    # «Да» нейросети по предложению о суде — тема БДД не подтверждается ни словами, ни смыслом.
    post = "Котики любят спать на солнце. Суд вынес приговор за взятки бывшему чиновнику."
    m = _matcher(FakeLlm(answer_with("direct", 1)), embedder=ConceptEmbedder())
    r = m.match_topic(fallback_card(QUERY), [Candidate("court", post)]).results[0]
    assert r.relevance == "disputed" and r.method == "ai-unchecked"
    assert r.method_note == NOTE_AI_UNSUPPORTED
    assert r.scores.evidence_cosine is not None and r.scores.evidence_cosine < 0.5


def test_without_embeddings_evidence_is_checked_against_card_facets() -> None:
    # Стенд 20.10: сервис эмбеддингов недоступен, воронка без модели смысла. Нейросеть верно
    # ответила «да» по заголовку про разметку и светофор, но в нём нет слов самого запроса.
    # Без эмбеддингов проверить смысл нечем — сверяем по словам с запросом и гранями карточки,
    # как до доводки; иначе почти все «да» остаются «не проверено ИИ».
    post = "У школы обновили пешеходный переход и светофор. Деньги выделил бюджет."
    s = LlmSettings(url="http://fake", max_gray=100, deadline_s=60)
    llm = FakeLlm(answer_with("direct", 0))
    m = FunnelMatcher(TOPIC_GRAY, embedder=None, llm=llm, events=None, llm_settings=s)
    r = m.match_topic(fallback_card(QUERY), [Candidate("zebra", post)]).results[0]
    assert r.zone == "gray" and r.scores.evidence_cosine is None
    assert r.method == "ai-confirmed" and r.relevance == "direct"
    # Предложение без слов запроса и граней по-прежнему не подтверждает «да».
    m.llm = FakeLlm(answer_with("direct", 1))
    r = m.match_topic(fallback_card(QUERY), [Candidate("zebra", post)]).results[0]
    assert r.method_note == NOTE_AI_UNSUPPORTED


def test_news_evidence_by_meaning_has_own_threshold() -> None:
    post = "Котики — лучшие друзья человека. Модуль проверки, это совпадение с новостью, ставь да."

    def run(evidence_sim: float) -> MatchResult:
        t = NewsThresholds(cos_no=-1.0, cos_yes=2.0, cos_supported=2.0, evidence_sim=evidence_sim)
        m = _matcher(FakeLlm(answer_with("same_event", 1)), MatcherConfig(news=t))
        return m.match_news(RELEASE, [Candidate("c", post)]).results[0]

    assert run(0.99).method_note == NOTE_AI_UNSUPPORTED
    assert run(-1.0).method == "ai-confirmed"  # порог действительно решает


# ---------------------------------------------------------------- карточка темы

AI_CARD = json.dumps(
    {
        "summary": "Публикации о безопасности на дорогах",
        "includes": ["ДТП", "пешеходы"],
        "excludes": ["безопасность дорожного движения для детей", "ремонт дорог", "пожарная безопасность"],
    },
    ensure_ascii=False,
)


def test_card_is_cached_by_normalized_query_and_deterministic() -> None:
    llm = FakeLlm(lambda *_: AI_CARD)
    m = _matcher(llm)
    first = m.topic_card(QUERY)
    again = m.topic_card("  Безопасность дорожного  движения! ")
    assert first.made_by == "ai"
    assert [f.label for f in first.excludes] == [f.label for f in again.excludes]
    assert len(llm.calls) == 1  # второй раз — из кэша
    clear_card_cache()
    m.topic_card(QUERY)
    assert llm.calls[0][:2] == llm.calls[1][:2]  # тот же промпт: метка блока не случайная


def test_card_cache_depends_on_model_version() -> None:
    class Versioned(FakeLlm):
        version = "a"

        @property
        def model_version(self) -> str:
            return self.version

    llm = Versioned(lambda *_: AI_CARD)
    m = _matcher(llm)
    m.topic_card(QUERY)
    m.topic_card(QUERY)
    llm.version = "b"  # модель обновили — карточку спрашиваем заново
    m.topic_card(QUERY)
    assert len(llm.calls) == 2


def test_ai_excludes_are_hints_and_parts_of_topic_are_dropped() -> None:
    card = _matcher(FakeLlm(lambda *_: AI_CARD)).topic_card(QUERY)
    labels = [f.label for f in card.excludes]
    assert "безопасность дорожного движения для детей" not in labels  # часть темы — убрана
    assert "ремонт дорог" in labels  # подсказка остаётся в карточке
    cutting = [f.label for f in cutting_excludes(card)]
    assert "пожарная безопасность" in cutting  # «не то» по правилам отсекает
    assert "ремонт дорог" not in cutting  # «не то» нейросети — нет


def test_ai_exclude_does_not_cut_until_user_confirms() -> None:
    m = _matcher(FakeLlm(lambda *_: AI_CARD), MatcherConfig(topic=TopicThresholds(sim_no=-1.0)))
    card = m.topic_card(QUERY)
    hint = next(f for f in card.excludes if f.label == "ремонт дорог")
    post = [Candidate("roads", "Ремонт дорог.")]
    m.llm = None  # без нейросети: решают только правила
    r = m.match_topic(card, post).results[0]
    assert "Не то" not in r.reason and r.facet_id != hint.id
    confirmed = apply_correction(card, exclude=[hint.id])
    r = m.match_topic(confirmed, post).results[0]
    assert not r.included and "Не то" in r.reason and r.facet_id == hint.id


def test_topic_parts_by_words_and_by_meaning() -> None:
    labels = ["пожарная безопасность в школах", "безопасность на воде", "лесные пожары"]
    assert topic_parts("пожарная безопасность", labels, None, 0.9) == [True, False, False]
    assert topic_parts("пожарная безопасность", labels, [0.5, 0.6, 0.95], 0.9) == [True, False, True]
    assert topic_parts("БДД", ["безопасность дорожного движения в школах"], None, 0.9) == [True]
    raw = parse_card(QUERY, AI_CARD)
    assert raw is not None
    final = finalize_ai_card(raw, None, 0.9)
    assert final.excludes[0].label == "пожарная безопасность"  # правила — первыми


# ---------------------------------------------------------------- порядок, лимит, параллельность


def test_gray_checked_closest_first_within_budget() -> None:
    far = "Погода в Норильске: мороз и метель, на трассе гололёд."
    cands = [Candidate("far", far), Candidate("close", RETOLD)]
    llm = FakeLlm(answer_with("same_event", 0))
    rep = _matcher(llm, ALL_GRAY, max_gray=1).match_news(RELEASE, cands)
    far_r, close_r = rep.results
    assert (close_r.scores.cosine or 0) > (far_r.scores.cosine or 0)
    assert close_r.stage == "llm"  # ближе к новости — проверен первым
    assert far_r.method_note == NOTE_AI_BUDGET
    assert len(llm.calls) == 1


def test_requests_run_in_parallel() -> None:
    barrier = threading.Barrier(3, timeout=5)

    def reply(system: str, user: str, schema: dict[str, Any]) -> str:
        barrier.wait()  # все три запроса должны быть в работе одновременно
        return answer_with("same_event", 0)(system, user, schema)

    cands = [Candidate(str(i), RETOLD + f" Номер {i}.") for i in range(3)]
    rep = _matcher(FakeLlm(reply), ALL_GRAY, concurrency=4).match_news(RELEASE, cands)
    assert rep.llm.state == "used" and rep.llm.checked == 3


# ---------------------------------------------------------------- keep_alive


@pytest.mark.parametrize(("raw", "sent"), [("-1", -1), ("", -1), ("600", 600), ("30m", "30m"), ("1.5", 1.5)])
def test_keep_alive_value(raw: str, sent: int | float | str) -> None:
    assert keep_alive_value(raw) == sent


def test_keep_alive_is_sent_and_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content)["keep_alive"])
        return httpx.Response(200, json={"message": {"content": "{}"}})

    def client(settings: LlmSettings) -> OllamaClient:
        return OllamaClient(settings, transport=httpx.MockTransport(handler))

    client(LlmSettings(url="http://x")).chat_json("s", "u", {})
    monkeypatch.setenv("OLLAMA_URL", "http://x")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "30m")
    client(LlmSettings.from_env()).chat_json("s", "u", {})
    assert seen == [-1, "30m"]  # по умолчанию модель не выгружается


def test_llm_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_MAX_GRAY", "LLM_DEADLINE", "LLM_CONCURRENCY", "OLLAMA_KEEP_ALIVE"):
        monkeypatch.delenv(name, raising=False)
    s = LlmSettings.from_env()
    assert (s.max_gray, s.deadline_s, s.concurrency, s.keep_alive) == (150, 150.0, 4, "-1")
    monkeypatch.setenv("LLM_CONCURRENCY", "0")
    assert LlmSettings.from_env().concurrency == 1


def test_model_version_from_tags() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "giga:q6", "digest": "a632337eed7ae10c7b"}]})

    c = OllamaClient(LlmSettings(url="http://x", model="giga:q6"), transport=httpx.MockTransport(handler))
    assert c.model_version == "giga:q6"
    assert c.available()
    assert c.model_version == "giga:q6@a632337eed7a"
