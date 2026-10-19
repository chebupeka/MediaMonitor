"""Отказ нейросети: воронка работает дальше, спорные честно помечены «не проверено ИИ»."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from mm_matching.config import LlmSettings
from mm_matching.funnel import NOTE_AI_DOWN, NOTE_AI_INVALID, NOTE_AI_OFF, NOTE_AI_UNSURE, FunnelMatcher
from mm_matching.llm import LlmError, OllamaClient, client_from_env
from mm_matching.types import Candidate

from .conftest import OTHER_EVENT, RELEASE, RETOLD, FakeLlm, answer_with

GRAY = [Candidate("a", RETOLD), Candidate("b", OTHER_EVENT)]


def _check_unchecked(make: FunnelMatcher, note: str) -> None:
    rep = make.match_news(RELEASE, [Candidate("copy", RELEASE), *GRAY])
    copy, *gray = rep.results
    assert copy.included and copy.method == "copy"  # шаг 1 работает без нейросети
    for r in gray:
        assert r.included
        assert r.relevance == "disputed"
        assert r.method == "ai-unchecked"
        assert r.method_note == note
        assert r.excerpt is not None
        assert RETOLD.find(r.excerpt.text) >= 0 or OTHER_EVENT.find(r.excerpt.text) >= 0


def test_no_ollama_url(make_matcher: Callable[..., FunnelMatcher], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    assert client_from_env() is None
    m = make_matcher(llm=None)
    _check_unchecked(m, NOTE_AI_OFF)
    assert m.match_news(RELEASE, GRAY).llm.state == "not-configured"


def test_ollama_not_reachable(make_matcher: Callable[..., FunnelMatcher]) -> None:
    llm = FakeLlm(answer_with("same_event"), available=False)
    m = make_matcher(llm=llm)
    _check_unchecked(m, NOTE_AI_DOWN)
    assert llm.calls == []
    assert m.match_news(RELEASE, GRAY).llm.state == "unavailable"


def test_errors_stop_after_two_failures(make_matcher: Callable[..., FunnelMatcher]) -> None:
    llm = FakeLlm(error=LlmError("таймаут"))
    m = make_matcher(llm=llm)
    rep = m.match_news(RELEASE, [Candidate(str(i), RETOLD + f" Номер {i}.") for i in range(5)])
    assert len(llm.calls) == 2
    assert all(r.method_note == NOTE_AI_DOWN and r.relevance == "disputed" for r in rep.results)
    assert rep.llm.state == "unavailable"
    assert rep.llm.unchecked == 5


@pytest.mark.parametrize(
    "answer",
    ["", "не знаю", '{"verdicts": [{"id": "zzz", "label": "same_event", "evidence_sentence": 0}]}'],
)
def test_out_of_schema_answer(make_matcher: Callable[..., FunnelMatcher], answer: str) -> None:
    m = make_matcher(llm=FakeLlm(lambda *_: answer))
    _check_unchecked(m, NOTE_AI_INVALID)


def test_cannot_tell_stays_disputed(make_matcher: Callable[..., FunnelMatcher]) -> None:
    m = make_matcher(llm=FakeLlm(answer_with("cannot_tell", 0)))
    _check_unchecked(m, NOTE_AI_UNSURE)


def test_confirmed_and_rejected(make_matcher: Callable[..., FunnelMatcher]) -> None:
    def reply(system: str, user: str, schema: dict[str, object]) -> str:
        del system, schema
        pid = "p1" if "id=p1" in user else "p2"
        label = "same_event" if "Ачинск" in user.split("ПУБЛИКАЦИЯ")[1] else "other_event"
        return json.dumps({"verdicts": [{"id": pid, "label": label, "evidence_sentence": 0}]})

    rep = make_matcher(llm=FakeLlm(reply)).match_news(RELEASE, GRAY)
    a, b = rep.results
    assert a.included and a.method == "ai-confirmed" and a.relevance == "direct"
    assert a.evidence is not None and a.evidence.basis == "ai" and a.evidence.sentence_index == 0
    assert not b.included and b.stage == "llm"
    assert rep.llm.state == "used" and rep.llm.checked == 2


# ---------------------------------------------------------------- HTTP-клиент


def _client(handler: Callable[[httpx.Request], httpx.Response], api: str = "ollama") -> OllamaClient:
    s = LlmSettings(url="http://ollama.test:11434", model="gigachat-test", api=api, timeout_s=1)
    return OllamaClient(s, transport=httpx.MockTransport(handler))


def test_ollama_request_uses_schema_and_zero_temperature() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gigachat-test:latest"}]})
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"ok": 1}'}})

    c = _client(handler)
    assert c.available()
    assert c.chat_json("sys", "user", {"type": "object"}) == '{"ok": 1}'
    assert seen["format"] == {"type": "object"}
    assert seen["stream"] is False
    assert seen["options"]["temperature"] == 0  # type: ignore[index]


def test_openai_compatible_mode() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    assert _client(handler, api="openai").chat_json("s", "u", {"type": "object"}) == "{}"
    assert seen["path"] == "/v1/chat/completions"
    assert seen["response_format"]["type"] == "json_schema"  # type: ignore[index]


def test_model_missing_means_unavailable() -> None:
    c = _client(lambda req: httpx.Response(200, json={"models": [{"name": "llama3:latest"}]}))
    assert not c.available()


@pytest.mark.parametrize(
    "handler",
    [
        lambda req: httpx.Response(500, text="boom"),
        lambda req: httpx.Response(200, text="<html>не json</html>"),
        lambda req: httpx.Response(200, json={"message": {"content": None}}),
    ],
)
def test_http_failures_become_llm_error(handler: Callable[[httpx.Request], httpx.Response]) -> None:
    with pytest.raises(LlmError):
        _client(handler).chat_json("s", "u", {})


def test_network_errors_become_llm_error() -> None:
    def refuse(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет связи", request=req)

    def slow(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("долго", request=req)

    for handler in (refuse, slow):
        c = _client(handler)
        assert not c.available()
        with pytest.raises(LlmError):
            c.chat_json("s", "u", {})


def test_funnel_with_http_client_end_to_end(make_matcher: Callable[..., FunnelMatcher]) -> None:
    """Воронка → настоящий HTTP-клиент → поддельный Ollama: id берётся из схемы запроса."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gigachat-test"}]})
        body = json.loads(req.content)
        pid = body["format"]["properties"]["verdicts"]["items"]["properties"]["id"]["enum"][0]
        assert "<<<ДАННЫЕ" in body["messages"][1]["content"]
        verdict = {"verdicts": [{"id": pid, "label": "same_event", "evidence_sentence": 0}]}
        return httpx.Response(200, json={"message": {"content": json.dumps(verdict)}})

    rep = make_matcher(llm=_client(handler)).match_news(RELEASE, [Candidate("a", RETOLD)])
    r = rep.results[0]
    assert r.method == "ai-confirmed"
    assert r.relevance == "direct"
    assert rep.llm.state == "used"
