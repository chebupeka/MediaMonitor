"""Проверка ответа нейросети: только id из входа, метка из списка, номер внутри текста."""

from __future__ import annotations

import pytest

from mm_matching.guard import (
    NEWS_LABELS,
    InvalidResponseError,
    news_prompt,
    parse_verdicts,
    prompt_post,
    verdict_schema,
)
from mm_matching.text import split_sentences

EXPECTED = {"p1": 3}


def test_valid_answer_is_accepted() -> None:
    raw = '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": 2}]}'
    v = parse_verdicts(raw, EXPECTED, NEWS_LABELS)
    assert v["p1"].label == "same_event"
    assert v["p1"].sentence == 2


def test_missing_id_means_unchecked_not_error() -> None:
    assert parse_verdicts('{"verdicts": []}', EXPECTED, NEWS_LABELS) == {}


@pytest.mark.parametrize(
    "raw",
    [
        "это не JSON",
        "",
        '{"verdicts": [{"id": "p9", "label": "same_event", "evidence_sentence": 0}]}',  # чужой id
        '{"verdicts": [{"id": "p1", "label": "прямо", "evidence_sentence": 0}]}',  # не та метка
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": 3}]}',  # вне текста
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": -1}]}',
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": true}]}',
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": 1.0}]}',
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": "1"}]}',
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": 0, "why": "x"}]}',
        '{"verdicts": [], "comment": "лишнее поле"}',
        '{"verdicts": {"id": "p1"}}',
        '[{"id": "p1", "label": "same_event", "evidence_sentence": 0}]',
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": 0},'
        ' {"id": "p1", "label": "other_event", "evidence_sentence": 1}]}',  # повтор id
        '{"verdicts": [{"id": "p1", "id": "p1", "label": "same_event", "evidence_sentence": 0}]}',
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": NaN}]}',
    ],
)
def test_invalid_answers_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidResponseError):
        parse_verdicts(raw, EXPECTED, NEWS_LABELS)


@pytest.mark.parametrize(
    "raw",
    [
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": 0}]} https://vk.com/wall-1_1',
        '{"verdicts": [{"id": "https://vk.com/x", "label": "same_event", "evidence_sentence": 0}]}',
        '{"verdicts": [{"id": "p1", "label": "same_event", "evidence_sentence": 0}], "src": "ngs24.ru"}',
    ],
)
def test_answers_with_links_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidResponseError):
        parse_verdicts(raw, EXPECTED, NEWS_LABELS)


def test_schema_limits_ids_labels_and_sentence_numbers() -> None:
    schema = verdict_schema(["p1"], NEWS_LABELS, 5)
    item = schema["properties"]["verdicts"]["items"]
    assert item["properties"]["id"]["enum"] == ["p1"]
    assert item["properties"]["label"]["enum"] == list(NEWS_LABELS)
    assert item["properties"]["evidence_sentence"]["maximum"] == 4
    assert item["additionalProperties"] is False


def test_prompt_numbers_sentences_like_publication() -> None:
    text = "Первое предложение. Второе предложение!\nТретье"
    pp = prompt_post("p1", text, split_sentences(text))
    _, user = news_prompt("Релиз.", [pp], "abc123")
    assert "[0] Первое предложение." in user
    assert "[2] Третье" in user
