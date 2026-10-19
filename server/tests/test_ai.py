"""Нейросеть (Р5–Р6, НТ-8, SC-08): ответы только по схеме, номер предложения проверяется,
ловушки в тексте не работают, отказ нейросети → «не проверено ИИ», а не «не относится».

Ollama подменяется httpx.MockTransport: настоящая модель для тестов не нужна.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from mediamonitor.ai.judge import (
    JudgeItem,
    JudgeRequest,
    OllamaJudge,
    validate_topic,
    validate_verdicts,
)
from mediamonitor.settings import Settings
from tests.conftest import make_app, make_settings, new_workspace, open_client, run_search

ITEMS = [JudgeItem("c1", ["Первое.", "Второе."]), JudgeItem("c2", ["Одно."])]


def verdicts(*entries: dict[str, Any]) -> str:
    return json.dumps({"verdicts": list(entries)})


# ---------------------------------------------------------------- проверка ответа (НТ-8)


def test_valid_verdicts() -> None:
    result = validate_verdicts(
        verdicts(
            {"id": "c1", "label": "direct", "evidence_sentence": 1},
            {"id": "c2", "label": "unrelated", "evidence_sentence": 0},
        ),
        ITEMS,
    )
    assert {k: (v.label, v.sentence) for k, v in result.items()} == {
        "c1": ("direct", 1),
        "c2": ("unrelated", 0),
    }


def test_invalid_verdicts_are_dropped() -> None:
    bad = [
        "не JSON",
        json.dumps([]),
        json.dumps({"verdicts": [], "extra": 1}),
        verdicts({"id": "c9", "label": "direct", "evidence_sentence": 0}),  # чужой id
        verdicts({"id": "c1", "label": "direct", "evidence_sentence": 2}),  # нет такого предложения
        verdicts({"id": "c1", "label": "direct", "evidence_sentence": -1}),
        verdicts({"id": "c1", "label": "direct", "evidence_sentence": True}),
        verdicts({"id": "c1", "label": "yes", "evidence_sentence": 0}),  # метка не из списка
        verdicts(
            {"id": "c1", "label": "direct", "evidence_sentence": 0, "url": "x"}
        ),  # лишнее поле
        verdicts({"id": "https://vk.com/wall-1_1", "label": "direct", "evidence_sentence": 0}),
    ]
    for content in bad:
        assert validate_verdicts(content, ITEMS) == {}, content


def test_duplicate_answers_are_not_trusted() -> None:
    content = verdicts(
        {"id": "c1", "label": "direct", "evidence_sentence": 0},
        {"id": "c1", "label": "unrelated", "evidence_sentence": 1},
        {"id": "c2", "label": "indirect", "evidence_sentence": 0},
    )
    assert set(validate_verdicts(content, ITEMS)) == {"c2"}


def test_topic_signs_only_from_query() -> None:
    query = "В Норильске 20 октября открылась школа на 1 100 учеников"
    content = json.dumps(
        {
            "summary": "Открытие школы в Норильске",
            "includes": ["Открытие школы"],
            "excludes": ["Другие школы"],
            "signs": {
                "who": ["Министр"],
                "where": ["Норильске"],
                "when": ["20 октября"],
                "numbers": ["1 100", "500"],
            },
        },
        ensure_ascii=False,
    )
    draft = validate_topic(content, query)
    assert draft is not None
    assert draft.who == []
    assert draft.where == ["Норильске"]
    assert draft.when == ["20 октября"]
    assert draft.numbers == ["1 100"]
    with_link = content.replace("Открытие школы в Норильске", "см. https://evil.example")
    assert validate_topic(with_link, query) is None


# ---------------------------------------------------------------- поиск с нейросетью


def ollama(
    handler: Callable[[dict[str, Any]], httpx.Response],
) -> Callable[[Settings, httpx.AsyncClient], OllamaJudge]:
    seen: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "gigachat"}]})
        body = json.loads(request.content)
        seen.append(body)
        return handler(body)

    def factory(settings: Settings, _: httpx.AsyncClient) -> OllamaJudge:
        client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        judge = OllamaJudge("http://ollama.test", settings, client)
        judge.requests = seen  # type: ignore[attr-defined]
        return judge

    return factory


def payload(body: dict[str, Any]) -> dict[str, Any]:
    content = str(body["messages"][1]["content"])
    data: dict[str, Any] = json.loads(content.split("\n", 1)[1])
    return data


def answer(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def judge_everything(body: dict[str, Any]) -> httpx.Response:
    if body["response_format"]["json_schema"]["name"] == "topic":
        return answer(
            json.dumps(
                {
                    "summary": "Безопасность на дорогах края",
                    "includes": ["ДТП"],
                    "excludes": ["Пожарная безопасность"],
                    "signs": {"who": [], "where": [], "when": [], "numbers": []},
                }
            )
        )
    items = payload(body)["items"]
    entries = []
    for index, item in enumerate(items):
        if index % 4 == 3:
            entries.append({"id": item["id"], "label": "unrelated", "evidence_sentence": 0})
        elif index % 4 == 2:
            # Ловушка: id не из входа и номер предложения, которого нет.
            entries.append({"id": "c999", "label": "direct", "evidence_sentence": 0})
            entries.append(
                {
                    "id": item["id"],
                    "label": "direct",
                    "evidence_sentence": len(item["sentences"]) + 5,
                }
            )
        else:
            entries.append(
                {
                    "id": item["id"],
                    "label": "direct",
                    "evidence_sentence": len(item["sentences"]) - 1,
                }
            )
    return answer(json.dumps({"verdicts": entries}))


async def test_search_with_ai(tmp_path: Path) -> None:
    factory = ollama(judge_everything)
    settings = make_settings(tmp_path, ollama_url="http://ollama.test", llm_api="openai")
    app = make_app(settings, judge_factory=factory).app
    async with open_client(app) as client:
        headers = await new_workspace(client)
        _, events = await run_search(client, headers)
        types = [e["event"] for e in events]
        assert "ai-unavailable" not in types
        topic = next(e["data"]["topic"] for e in events if e["event"] == "topic")
        assert topic["madeBy"] == "ai"
        assert [f["label"] for f in topic["excludes"]] == ["Пожарная безопасность"]
        selection = events[-1]["data"]["selection"]
        assert selection["aiAvailable"] is True
        methods = {i["method"] for i in selection["items"]}
        assert "ai-confirmed" in methods
        assert "ai-unchecked" in methods  # ответ-ловушка не принят, пост не потерян
        for item in selection["items"]:
            if item["method"] == "ai-confirmed":
                assert item["evidence"]["basis"] == "ai"
                assert (
                    item["evidence"]["sentenceIndex"] == len(item["publication"]["sentences"]) - 1
                )
            if item["method"] == "ai-unchecked":
                assert item["relevance"] == "disputed"
        requests = app.state.ctx.judge.requests
        judged = [r for r in requests if r["response_format"]["json_schema"]["name"] == "verdicts"]
        assert judged
        for request in judged:
            assert request["temperature"] == 0
            data = payload(request)
            assert set(data) == {"query", "includes", "excludes", "items"}
            for item in data["items"]:
                assert set(item) == {"id", "sentences"}
                assert item["id"].startswith("c")
            # Нейросеть не получает ни ссылок, ни дат, ни источников — только тексты.
            text = json.dumps(data, ensure_ascii=False)
            assert "vk.com" not in text
            assert "+07:00" not in text


async def test_ai_goes_down_during_search(tmp_path: Path) -> None:
    def broken(body: dict[str, Any]) -> httpx.Response:
        return httpx.Response(500, json={"error": "out of memory"})

    settings = make_settings(tmp_path, ollama_url="http://ollama.test", llm_api="openai")
    app = make_app(settings, judge_factory=ollama(broken)).app
    async with open_client(app) as client:
        headers = await new_workspace(client)
        _, events = await run_search(client, headers)
        types = [e["event"] for e in events]
        assert "ai-unavailable" in types
        selection = events[-1]["data"]["selection"]
        assert selection["aiAvailable"] is False
        assert any(n["code"] == "ai-unavailable" for n in selection["notices"])
        unchecked = [i for i in selection["items"] if i["method"] == "ai-unchecked"]
        assert unchecked, "спорные остаются в подборке"
        assert all(i["relevance"] == "disputed" for i in unchecked)
        assert all("Смысловая проверка недоступна" in (i["methodNote"] or "") for i in unchecked)
        topic = next(e["data"]["topic"] for e in events if e["event"] == "topic")
        assert topic["madeBy"] == "rules"


async def test_ai_not_configured(client: httpx.AsyncClient) -> None:
    topic = (await client.post("/api/query/topic", json={"text": "ДТП в Канске"})).json()
    assert topic["madeBy"] == "rules"
    assert "Смысловая проверка недоступна" in topic["note"]
    stand = (await client.get("/api/stand")).json()
    assert stand["ai"]["state"] == "down"
    assert stand["ai"]["warm"] is False
    assert stand["overall"] == "degraded"


async def test_native_ollama_api_shares_context_with_funnel(tmp_path: Path) -> None:
    """LLM_API=ollama: /api/chat с тем же num_ctx и keep_alive, что у воронки (модель не
    перезагружается между запросами), формат ответа — JSON-схема."""
    seen: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gigachat"}]})
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        seen.append(body)
        item = payload({"messages": body["messages"]})["items"][0]
        verdict = {"id": item["id"], "label": "direct", "evidence_sentence": 0}
        return httpx.Response(
            200, json={"message": {"content": json.dumps({"verdicts": [verdict]})}}
        )

    settings = make_settings(tmp_path, ollama_url="http://ollama.test")
    assert settings.llm_api == "ollama"
    assert settings.llm_model.endswith(":Q6_K")
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    judge = OllamaJudge("http://ollama.test", settings, client)
    assert (await judge.status()).available
    verdicts = await judge.judge(
        JudgeRequest(query="ДТП", includes=[], excludes=[], items=[JudgeItem("c1", ["Авария."])])
    )
    assert verdicts["c1"].label == "direct"
    assert seen[0]["options"]["num_ctx"] == 8192
    assert seen[0]["keep_alive"] == "30m"
    assert seen[0]["format"]["required"] == ["verdicts"]
    await client.aclose()


def test_ollama_model_alias(tmp_path: Path) -> None:
    from mediamonitor.settings import Settings

    settings = Settings(_env_file=None, ollama_model="hf.co/x:Q8_0")
    assert settings.llm_model == "hf.co/x:Q8_0"
