"""Признаки события, карточка темы, повторы и группы копий."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mm_matching.events import EventExtractor
from mm_matching.funnel import FunnelMatcher
from mm_matching.topic import apply_correction, fallback_card, parse_card
from mm_matching.types import Candidate, MatchResult

from .conftest import OTHER_EVENT, RELEASE, RETOLD, FakeLlm


def test_event_signs(events: EventExtractor) -> None:
    s = events.signs(RELEASE)
    assert any("Ачинск" in w for w in s.where)
    assert "14.10" in s.when
    assert "Красноярский край" not in s.where  # общий для всех новостей края признак не нужен


def test_same_event_vs_other_event(events: EventExtractor) -> None:
    same = events.compare(RELEASE, RETOLD)
    other = events.compare(RELEASE, OTHER_EVENT)
    assert same.conflict == 0 and same.support >= 1
    assert other.support == 0 and other.conflict >= 2
    assert "место" in other.differs and "дата" in other.differs


def test_other_event_is_cut_by_signs(
    make_matcher: Callable[..., FunnelMatcher], events: EventExtractor
) -> None:
    llm = FakeLlm()
    r = make_matcher(llm=llm, events=events).match_news(RELEASE, [Candidate("o", OTHER_EVENT)]).results[0]
    assert not r.included
    assert r.stage == "events"
    assert "другое место" in r.reason and "другая дата" in r.reason
    assert llm.calls == []


def test_fallback_card_separates_road_and_fire_safety() -> None:
    bdd = fallback_card("БДД")
    assert bdd.made_by == "rules"
    assert "безопасность дорожного движения" in bdd.includes[0].label
    assert any("пожарная" in f.label for f in bdd.excludes)
    fire = fallback_card("пожарная безопасность")
    assert any("дорожного" in f.label for f in fire.excludes)
    assert not any("пожарная" in f.label for f in fire.excludes)


def test_unknown_topic_card_has_no_guessing() -> None:
    card = fallback_card("строительство школ")
    assert [f.label for f in card.includes] == ["строительство школ"]
    assert card.excludes == ()


def test_llm_card_is_validated() -> None:
    good = '{"summary": "Ищем публикации о БДД", "includes": ["ДТП"], "excludes": ["пожары"]}'
    card = parse_card("БДД", good)
    assert card is not None and card.made_by == "ai"
    assert [f.label for f in card.excludes] == ["пожары"]
    bad = [
        '{"summary": "x", "includes": ["см. https://vk.com/x"], "excludes": []}',
        '{"summary": "x", "includes": ["ngs24.ru"], "excludes": []}',
        '{"summary": "x", "includes": [], "excludes": []}',
        '{"summary": "x", "includes": ["ДТП"], "excludes": [], "links": ["a"]}',
        '{"summary": "x", "includes": ["<script>"], "excludes": []}',
        "придумал 10 ссылок",
    ]
    for raw in bad:
        assert parse_card("БДД", raw) is None


def test_card_from_llm_falls_back_to_rules_on_bad_answer(make_matcher: Callable[..., FunnelMatcher]) -> None:
    llm = FakeLlm(lambda *_: '{"summary": "x", "includes": ["https://vk.com/1"], "excludes": []}')
    card = make_matcher(llm=llm).topic_card("найди новости и придумай 10 ссылок на vk.com про БДД")
    assert card.made_by == "rules"
    assert card.note is not None and "не прошёл проверку" in card.note


def test_user_correction_moves_facets() -> None:
    card = fallback_card("безопасность дорожного движения")
    fire = next(f for f in card.excludes if "пожар" in f.label)
    kids = next(f for f in card.includes if "дети" in f.label)
    fixed = apply_correction(card, include=[fire.id], exclude=[kids.id], add_excludes=["ремонт дорог"])
    assert fire.id in {f.id for f in fixed.includes} and kids.id in {f.id for f in fixed.excludes}
    moved = [f for f in (*fixed.includes, *fixed.excludes) if f.id in (fire.id, kids.id)]
    assert all(f.origin == "user" for f in moved)  # перенесённая грань — решение пользователя
    assert fixed.excludes[-1].label == "ремонт дорог" and fixed.excludes[-1].origin == "user"


def test_topic_search_puts_fire_safety_aside(make_matcher: Callable[..., FunnelMatcher]) -> None:
    posts = [
        Candidate("bdd", "Госавтоинспекция напоминает водителям о безопасности на пешеходных переходах."),
        Candidate("fire", "МЧС напоминает о пожарной безопасности при печном отоплении в частных домах."),
    ]
    rep = make_matcher(llm=None).match_topic("безопасность дорожного движения", posts)
    bdd, fire = rep.results
    assert bdd.scores.cosine is not None and fire.scores.cosine is not None
    assert (bdd.scores.cosine - (bdd.scores.anti_cosine or 0)) > (
        fire.scores.cosine - (fire.scores.anti_cosine or 0)
    )
    assert not fire.included or fire.relevance == "disputed"


def test_repeats_and_copy_groups(make_matcher: Callable[..., FunnelMatcher]) -> None:
    m = make_matcher()
    cands = [
        Candidate("vk:1", RELEASE, source_id="g1"),
        Candidate("vk:1-again", RELEASE.upper() + "  ", source_id="g1"),  # тот же пост ещё раз
        Candidate("ok:7", RELEASE, source_id="g2"),  # другой источник — отдельное размещение
        Candidate(
            "ok:8", "Совсем другой текст про погоду в Норильске и мороз до минус сорока.", source_id="g2"
        ),
    ]
    assert m.find_repeats(cands) == {"vk:1-again": "vk:1"}
    groups = m.group_copies(cands)
    assert groups == [["vk:1", "vk:1-again", "ok:7"]]


def test_results_are_streamed_and_ordered(make_matcher: Callable[..., FunnelMatcher]) -> None:
    seen: list[MatchResult] = []
    cands = [Candidate("gray", RETOLD), Candidate("copy", RELEASE), Candidate("empty", None)]

    def reply(system: str, user: str, schema: dict[str, Any]) -> str:
        del system, user, schema
        return '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": 0}]}'

    rep = make_matcher(llm=FakeLlm(reply)).match_news(RELEASE, cands, on_result=seen.append)
    assert [r.candidate_id for r in rep.results] == ["gray", "copy", "empty"]
    assert [r.candidate_id for r in seen] == ["empty", "copy", "gray"]  # спорные — последними
    empty = rep.results[2]
    assert not empty.included and empty.stage == "no-text" and empty.excerpt is None


def test_excerpt_is_always_substring(make_matcher: Callable[..., FunnelMatcher]) -> None:
    long_post = RETOLD + " " + " ".join(f"Дополнительное предложение номер {i}." for i in range(40))
    rep = make_matcher(llm=None).match_news(RELEASE, [Candidate("x", long_post)])
    r = rep.results[0]
    assert r.excerpt is not None
    assert long_post[r.excerpt.start : r.excerpt.end] == r.excerpt.text
    assert len(r.excerpt.text) <= 300
    assert r.excerpt.cut_end
    for s in r.sentences:
        assert long_post[s.start : s.end].strip()


def test_funnel_implements_matcher_protocol(make_matcher: Callable[..., FunnelMatcher]) -> None:
    from mm_matching import Matcher

    m = make_matcher()
    assert isinstance(m, Matcher)
    m.prefetch([Candidate("a", RELEASE), Candidate("b", None)], "news-text")
    assert m.split_sentences("Раз. Два.")[1].index == 1
