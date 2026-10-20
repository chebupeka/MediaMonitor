"""Отбор без модели смысла (сервис эмбеддингов недоступен): дешёвые признаки отсекают явно чужое."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from mm_matching.config import LlmSettings, MatcherConfig
from mm_matching.funnel import FunnelMatcher
from mm_matching.topic import clear_card_cache, fallback_card
from mm_matching.types import Candidate, TopicCard, TopicFacet

from .conftest import FakeLlm, answer_with


@pytest.fixture(autouse=True)
def _fresh_card_cache() -> Iterator[None]:
    clear_card_cache()
    yield
    clear_card_cache()


ICE = "На Енисее начался ледостав: у Красноярска встали забереги, переправы закрыты."
HOCKEY = "Енисей обыграл Сокол на своём льду, болельщики Красноярска праздновали победу."
WEATHER = "Синоптики обещают снег и мороз до минус двадцати на севере края."


def _by_id(card: TopicCard, posts: list[Candidate], llm: FakeLlm | None = None) -> dict[str, str]:
    s = LlmSettings(url="http://fake", max_gray=100, deadline_s=60)
    m = FunnelMatcher(MatcherConfig(), embedder=None, llm=llm, events=None, llm_settings=s)
    return {r.candidate_id: r.zone for r in m.match_topic(card, posts).results}


def test_post_with_only_one_of_two_query_words_is_cut_not_disputed() -> None:
    # Стенд 20.10: без эмбеддингов все 566 кандидатов ушли в «Спорно» — площадки ищут по
    # любому слову запроса, и «Енисей» без «ледостава» (хоккей) считался «есть общие слова».
    card = fallback_card("ледостав на Енисее")
    posts = [Candidate("ice", ICE), Candidate("hockey", HOCKEY), Candidate("weather", WEATHER)]
    zones = _by_id(card, posts)
    assert zones == {"ice": "gray", "hockey": "no", "weather": "no"}


def test_facet_words_keep_post_without_query_words() -> None:
    # Грань «входит» — тоже слова темы: пост о ней остаётся спорным, его проверит нейросеть.
    card = TopicCard(
        query="ледостав на Енисее",
        summary="",
        includes=(TopicFacet("f1", "закрытие ледовых переправ", "user"),),
        excludes=(),
        made_by="rules",
        note=None,
    )
    post = "В Енисейском районе объявили закрытие ледовых переправ до весны."
    assert _by_id(card, [Candidate("ferry", post)]) == {"ferry": "gray"}


def test_disputed_without_embeddings_still_go_to_llm() -> None:
    card = fallback_card("ледостав на Енисее")
    llm = FakeLlm(answer_with("direct", 0))
    zones = _by_id(card, [Candidate("ice", ICE), Candidate("hockey", HOCKEY)], llm)
    assert zones == {"ice": "gray", "hockey": "no"}
    assert len(llm.calls) == 1  # нейросеть спрашивали только о посте со словами запроса
