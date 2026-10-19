from __future__ import annotations

from mm_matching.text import split_paragraphs, split_sentences, text_hash, tokenize


def test_sentences_have_valid_offsets() -> None:
    text = "Заголовок без точки\nПервое предложение. Второе — с т.д. и т.п. внутри!  \n\nТретье?"
    sents = split_sentences(text)
    assert [s.index for s in sents] == list(range(len(sents)))
    assert text[sents[0].start : sents[0].end] == "Заголовок без точки"
    assert text[sents[-1].start : sents[-1].end] == "Третье?"
    for s in sents:
        chunk = text[s.start : s.end]
        assert chunk == chunk.strip()
        assert chunk


def test_paragraphs_split_on_newlines() -> None:
    text = "  Абзац один.\n\n Абзац два. \nАбзац три"
    paras = [text[p.start : p.end] for p in split_paragraphs(text)]
    assert paras == ["Абзац один.", "Абзац два.", "Абзац три"]


def test_hash_ignores_case_punctuation_yo_and_links() -> None:
    a = "Ёлка в Красноярске!   Подробнее: https://example.org/x"
    b = "елка в красноярске подробнее"
    assert text_hash(a) == text_hash(b)
    assert text_hash(a) != text_hash("ёлка в Норильске")


def test_tokens_skip_urls() -> None:
    words = [t.norm for t in tokenize("Смотрите www.site.ru/news и vk.com/wall-1_2 сегодня")]
    assert words[0] == "смотрите"
    assert "сегодня" in words
    assert "www" not in words
