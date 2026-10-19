"""Полнота цитирования (П1): доля релиза дословно и карта фрагментов по абзацам."""

from __future__ import annotations

import pytest

from mm_matching.shingles import citation, fragment_map, overlap, release_paragraphs, shingle

P0 = "Губернатор края открыл новую школу на 1100 мест в микрорайоне Солнечный города Красноярска."
P1 = "В школе 45 кабинетов, бассейн, два спортивных зала и библиотека с читальным залом на сорок мест."
P2 = "Строительство заняло два года, его финансировали из краевого и федерального бюджетов по нацпроекту."
RELEASE = f"{P0}\n{P1}\n{P2}"


def _cit(post: str) -> tuple[float, tuple[str, ...], float]:
    rel = shingle(RELEASE)
    ov = overlap(rel, shingle(post))
    c = citation(ov, release_paragraphs(rel))
    return c.share, c.fragment_ids, ov.post_share


def test_full_copy_is_100_percent() -> None:
    share, frags, post_share = _cit(RELEASE)
    assert share == pytest.approx(1.0)
    assert frags == ("p0", "p1", "p2")
    assert post_share == pytest.approx(1.0)


def test_copy_with_other_formatting_still_counts() -> None:
    post = RELEASE.upper().replace("\n", " ").replace(",", " ,")
    share, _, _ = _cit(post)
    assert share == pytest.approx(1.0)


def test_two_of_three_paragraphs() -> None:
    post = f"Важная новость! {P0} Подробности позже. {P2}"
    share, frags, post_share = _cit(post)
    n0, n1, n2 = (len(p.split()) for p in (P0, P1, P2))
    assert share == pytest.approx((n0 + n2) / (n0 + n1 + n2), abs=0.02)
    assert frags == ("p0", "p2")
    assert 0.8 < post_share < 1.0


def test_retelling_has_no_verbatim_share() -> None:
    post = "В Солнечном открылась большая школа: тысяча с лишним учеников, бассейн и два спортзала."
    share, frags, _ = _cit(post)
    assert share < 0.05
    assert frags == ()


def test_matched_ranges_point_to_post_text() -> None:
    post = f"Коротко: {P1}"
    rel = shingle(RELEASE)
    ov = overlap(rel, shingle(post))
    assert len(ov.post_ranges) == 1
    r = ov.post_ranges[0]
    assert post[r.start : r.end] == P1.rstrip(".")


def test_fragment_map_counts_placements() -> None:
    rel = shingle(RELEASE)
    paras = release_paragraphs(rel)
    cits = [
        citation(overlap(rel, shingle(RELEASE)), paras),
        citation(overlap(rel, shingle(P0)), paras),
        None,
    ]
    fm = fragment_map(RELEASE, cits)
    assert [(f.id, f.taken_by, f.of) for f in fm] == [("p0", 2, 2), ("p1", 1, 2), ("p2", 1, 2)]
    assert fm[1].text == P1
    assert RELEASE[fm[2].start : fm[2].end] == P2


def test_tiny_release_does_not_crash() -> None:
    rel = shingle("Пожар")
    ov = overlap(rel, shingle("В Канске пожар"))
    assert ov.release_share == pytest.approx(1.0)
