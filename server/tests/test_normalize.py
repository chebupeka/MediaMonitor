"""Нормализация: ключ повторов (НТ-13), предложения и выдержка, места края (Р4),
разбор поля запроса как в мокапе (НТ-21), красноярское время (НТ-12)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from mediamonitor.labels import format_period, truncate_text
from mediamonitor.normalize.query import analyze, detect_kind, query_stems, release_of
from mediamonitor.normalize.region import find_places
from mediamonitor.normalize.text import excerpt_bounds, split_sentences
from mediamonitor.normalize.urls import (
    PostRef,
    is_safe_post_url,
    parse_address,
    parse_post_url,
    post_url,
)
from mediamonitor.timeutil import day_end, day_start, iso, parse_iso

SAMPLES = Path(__file__).parent / "contract" / "samples"

# ---------------------------------------------------------------- ключ повторов (НТ-13)


@pytest.mark.parametrize(
    "url",
    [
        "https://vk.com/wall-100123_4567",
        "http://vk.ru/wall-100123_4567",
        "https://m.vk.com/wall-100123_4567",
        "vk.com/wall-100123_4567",
        "https://vk.com/demo_portal?w=wall-100123_4567",
        "https://www.vk.com/wall-100123_4567?reply=1",
    ],
)
def test_vk_addresses_give_one_key(url: str) -> None:
    ref = parse_post_url(url)
    assert ref == PostRef("vk", "-100123", "4567")
    assert ref.id == "vk:-100123_4567"
    assert post_url(ref) == "https://vk.com/wall-100123_4567"


def test_ok_and_max_keys() -> None:
    ok = parse_post_url("https://m.ok.ru/group/5600101/topic/30418")
    assert ok is not None
    assert ok.id == "ok:5600101_30418"
    assert post_url(ok) == "https://ok.ru/group/5600101/topic/30418"
    mx = parse_post_url("https://max.ru/Demo_Dorogi/1842")
    assert mx is not None
    assert mx.id == "max:demo_dorogi_1842"
    assert post_url(mx) == "https://max.ru/demo_dorogi/1842"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://evil.example/wall-1_2",
        "https://vk.com.evil.example/wall-1_2",
        "ftp://vk.com/wall-1_2",
        "https://vk.com/wall-1_2 x",
        "",
    ],
)
def test_foreign_addresses_rejected(url: str) -> None:
    assert parse_post_url(url) is None
    assert not is_safe_post_url(url)


def test_group_addresses() -> None:
    club = parse_address("https://vk.com/club100101")
    assert club is not None
    assert club.kind == "group"
    assert club.owner_id == "-100101"
    slug = parse_address("https://m.vk.com/Demo_TV_Kraya")
    assert slug is not None
    assert slug.slug == "demo_tv_kraya"
    assert slug.normalized_from_mobile
    channel = parse_address("max.ru/demo_tv_max")
    assert channel is not None
    assert channel.kind == "group"
    assert channel.owner_id == "demo_tv_max"
    assert parse_address("https://vk.com/feed") is None


# ---------------------------------------------------------------- текст


def test_sentences_and_excerpt_are_substrings() -> None:
    text = (
        "В г. Красноярске на ул. Ленина столкнулись два автомобиля. Пострадавших нет!\n\n"
        "Движение затруднено… Водителей просят объезжать участок? Да."
    )
    spans = split_sentences(text)
    sentences = [text[s.start : s.end] for s in spans]
    assert sentences == [
        "В г. Красноярске на ул. Ленина столкнулись два автомобиля.",
        "Пострадавших нет!",
        "Движение затруднено…",
        "Водителей просят объезжать участок?",
        "Да.",
    ]
    start, end = excerpt_bounds(spans, 1, len(text))
    assert text[start:end].startswith("Пострадавших нет!")
    assert end <= len(text)


def test_truncate_like_interface() -> None:
    assert truncate_text("коротко", 10) == "коротко"
    assert truncate_text("Безопасность дорожного движения в крае", 20) == "Безопасность дорожно…"
    assert truncate_text("Безопасность дорожного движения в крае", 30) == "Безопасность дорожного…"


# ---------------------------------------------------------------- места края (Р4)


@pytest.mark.parametrize(
    ("text", "places"),
    [
        ("В Канске водитель сбил пешехода", ["Канск"]),
        ("Происшествие в Канском районе", ["Канский район"]),
        ("Новости Красноярского края и Норильска", ["Красноярский край", "Норильск"]),
        ("В Красноярском крае похолодало", ["Красноярский край"]),
        ("Заполярье: Дудинка и Таймыр", ["Дудинка", "Таймыр"]),
        ("Москва и Новосибирск", []),
        ("Ачинский глинозёмный комбинат", []),
    ],
)
def test_places(text: str, places: list[str]) -> None:
    assert find_places(text) == places


# ---------------------------------------------------------------- запрос — как в мокапе


@pytest.mark.parametrize(
    "sample", ["analyzeQuery-hints", "analyzeQuery-ambiguous", "analyzeQuery-link"]
)
def test_query_analysis_matches_mockup(sample: str) -> None:
    fake = json.loads((SAMPLES / f"{sample}.json").read_text("utf-8"))["value"]
    ours = analyze(fake["text"], max_length=20_000, today=date(2026, 10, 19)).dump()
    assert ours == fake


def test_kind_and_stems() -> None:
    assert detect_kind("Безопасность дорожного движения") == "topic"
    assert detect_kind("Енисей") == "event"
    assert detect_kind("Раз. Два. Три. Четыре.") == "news-text"
    assert query_stems("Безопасность дорожного движения в Красноярском крае") == [
        "безопасн",
        "дорожно",
        "движен",
    ]


def test_release_fragments() -> None:
    release = release_of("Новая школа в Норильске\n\nПервый абзац. Ещё.\n\nВторой абзац.")
    assert release.title == "Новая школа в Норильске"
    assert [f.id for f in release.fragments] == ["p1", "p2"]
    assert release.fragments[1].text == "Второй абзац."


# ---------------------------------------------------------------- время (НТ-12)


def test_krasnoyarsk_time() -> None:
    moment = datetime(2026, 10, 14, 3, 2, tzinfo=UTC)
    assert iso(moment) == "2026-10-14T10:02:00+07:00"
    assert parse_iso("2026-10-14T10:02:00+07:00") == moment
    assert iso(day_start(date(2026, 10, 14))) == "2026-10-14T00:00:00+07:00"
    assert iso(day_end(date(2026, 10, 14))) == "2026-10-14T23:59:59+07:00"
    assert format_period(date(2026, 10, 1), date(2026, 10, 19)) == "1–19 окт"
