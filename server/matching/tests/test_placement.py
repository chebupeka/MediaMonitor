"""Тип размещения (П2): дословно / сокращено / пересказ / репост."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from mm_matching.funnel import FunnelMatcher
from mm_matching.placement import placement_type
from mm_matching.shingles import overlap, shingle
from mm_matching.types import Candidate

from .conftest import RELEASE, RETOLD, FakeLlm, answer_with

SENTS = RELEASE.replace("\n", " ").split(". ")


def _type(post: str, *, is_repost: bool = False) -> str:
    return placement_type(overlap(shingle(RELEASE), shingle(post)), is_repost=is_repost)


def test_verbatim() -> None:
    assert _type("Срочно!\n" + RELEASE) == "verbatim"


def test_shortened_part_of_release() -> None:
    assert _type(". ".join(SENTS[:2])) == "shortened"


def test_short_teaser_made_only_of_release_phrases_is_shortened() -> None:
    teaser = "В Ачинском районе 14 октября на трассе Р-255 столкнулись два автомобиля. Погибли 2 человека."
    assert _type(teaser) == "shortened"


def test_retold() -> None:
    assert _type(RETOLD) == "retold"


def test_repost_flag_wins() -> None:
    assert _type(RELEASE, is_repost=True) == "repost"


@pytest.mark.parametrize(
    ("post", "expected"),
    [
        ("Срочно!\n" + RELEASE, "verbatim"),
        (". ".join(SENTS[:2]), "shortened"),
        (RETOLD, "retold"),
    ],
)
def test_funnel_sets_placement_and_citation(
    make_matcher: Callable[..., FunnelMatcher], post: str, expected: str
) -> None:
    m = make_matcher(llm=FakeLlm(answer_with("same_event", 0)))
    r = m.match_news(RELEASE, [Candidate("c", post)]).results[0]
    assert r.included
    assert r.placement_type == expected
    assert r.citation is not None
    if expected == "verbatim":
        assert r.citation.share > 0.95
        assert r.method == "copy"
    if expected == "retold":
        assert r.citation.share < 0.1
        assert r.method == "ai-confirmed"


def test_excluded_post_has_no_placement(make_matcher: Callable[..., FunnelMatcher]) -> None:
    m = make_matcher(llm=FakeLlm(answer_with("other_event", 0)))
    r = m.match_news(RELEASE, [Candidate("c", RETOLD)]).results[0]
    assert not r.included
    assert r.placement_type is None
    assert r.citation is None
