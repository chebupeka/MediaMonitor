"""Ответы сервера совпадают с контрактом web/src/api/types.ts поле в поле.

JSON Schema собрана из types.ts (scripts/contract/gen-schema.mjs): лишнее поле,
недостающее поле, не тот тип или не то значение из списка — ошибка. Образцы ответов
имитации мокапа (scripts/contract/export-fake.mjs) проверяются той же схемой —
так видно, что схема верна, а сервер отвечает так же, как имитация.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import pytest
from jsonschema import Draft7Validator

from mediamonitor.contract import (
    ApiError,
    QueryAnalysis,
    Selection,
    SpreadReport,
    StandStatus,
    TopicUnderstanding,
)
from tests.conftest import new_workspace, read_stream, run_search

HERE = Path(__file__).parent
SAMPLES = sorted((HERE / "samples").glob("*.json"))


@cache
def schema() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((HERE / "contract.schema.json").read_text("utf-8"))
    return data


def validator(type_name: str) -> Draft7Validator:
    """Валидатор типа контракта: `Selection`, `Source[]` (массив), `SearchEvent`…"""
    is_list = type_name.endswith("[]")
    name = type_name.removesuffix("[]")
    ref: dict[str, Any] = {"$ref": f"#/definitions/{name}"}
    root = {
        "definitions": schema()["definitions"],
        **({"type": "array", "items": ref} if is_list else ref),
    }
    return Draft7Validator(root)


def assert_contract(type_name: str, value: Any) -> None:
    errors = sorted(validator(type_name).iter_errors(value), key=lambda e: list(e.absolute_path))
    details = [
        f"{'/'.join(map(str, e.absolute_path)) or '<корень>'}: {e.message[:200]}"
        for e in errors[:5]
    ]
    assert not errors, f"{type_name}: ответ не совпадает с контрактом:\n" + "\n".join(details)


# ---------------------------------------------------------------- схема и образцы имитации


def test_schema_has_all_contract_types() -> None:
    names = set(schema()["definitions"])
    for name in (
        "Selection",
        "SearchEvent",
        "ExportPreview",
        "SpreadReport",
        "StandStatus",
        "ImportPreview",
    ):
        assert name in names


@pytest.mark.parametrize("sample", SAMPLES, ids=[p.stem for p in SAMPLES])
def test_fake_samples_match_schema(sample: Path) -> None:
    data = json.loads(sample.read_text("utf-8"))
    if data["schema"] is None:
        # excludeSource: встроенный тип `{ itemIds: string[]; counts: SelectionCounts }`.
        assert set(data["value"]) == {"itemIds", "counts"}
        assert all(isinstance(i, str) for i in data["value"]["itemIds"])
        assert_contract("SelectionCounts", data["value"]["counts"])
        return
    assert_contract(data["schema"], data["value"])


@pytest.mark.parametrize(
    ("model", "sample"),
    [
        (Selection, "getSelection"),
        (SpreadReport, "getSpread"),
        (StandStatus, "getStandStatus"),
        (QueryAnalysis, "analyzeQuery-hints"),
        (TopicUnderstanding, "understandTopic"),
        (ApiError, "error-not-found"),
    ],
)
def test_pydantic_models_round_trip_fake_samples(model: Any, sample: str) -> None:
    """Модели сервера читают ответ имитации и отдают его обратно без потерь."""
    value = json.loads((HERE / "samples" / f"{sample}.json").read_text("utf-8"))["value"]
    assert model.model_validate(value).dump() == value


# ---------------------------------------------------------------- ответы сервера


def _key_paths(value: Any, prefix: str = "") -> set[str]:
    """Пути ключей объекта (массивы сворачиваются в `[]`): форма без значений."""
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths |= _key_paths(inner, path)
    elif isinstance(value, list):
        for inner in value:
            paths |= _key_paths(inner, f"{prefix}[]")
    return paths


async def test_every_endpoint_matches_contract(client: httpx.AsyncClient) -> None:
    headers = await new_workspace(client)
    checks: list[tuple[str, Any]] = []

    async def call(type_name: str, method: str, url: str, **kwargs: Any) -> Any:
        response = await client.request(method, url, headers=headers, **kwargs)
        assert response.status_code < 300, f"{method} {url}: {response.status_code} {response.text}"
        body = response.json()
        checks.append((type_name, body))
        return body

    await call("StartState", "GET", "/api/start")
    await call(
        "QueryAnalysis",
        "POST",
        "/api/query/analyze",
        json={"text": "подбери, пожалуйста, ДТП в Красноярском крае на прошлой неделе"},
    )
    await call("QueryAnalysis", "POST", "/api/query/analyze", json={"text": "Енисей"})
    await call(
        "TopicUnderstanding",
        "POST",
        "/api/query/topic",
        json={"text": "Енисей", "meaningId": "river"},
    )
    await call(
        "TopicUnderstanding",
        "POST",
        "/api/query/topic",
        json={
            "text": "ДТП",
            "correction": {"include": [], "exclude": ["main"], "notes": "только про детей"},
        },
    )
    await call("CatalogSource[]", "GET", "/api/catalog")
    catalog = checks[-1][1]
    await call(
        "Source[]",
        "POST",
        "/api/sources/from-catalog",
        json={"ids": [c["id"] for c in catalog[:6]]},
    )
    await call("Source[]", "GET", "/api/sources")
    for url in (
        "https://vk.com/demo_minusinsk",
        "https://vk.com/demo_kodinsk",
        "https://max.ru/demo_achinsk24/1520",
        "https://vk.com/demo_news_sibir",
        "https://example.ru/news",
        "https://vk.com/demo_tv_kraya",
        "https://vk.com/no_such_group_here",
    ):
        await call("SourceCheck", "POST", "/api/sources/check", json={"url": url})
    added = await call(
        "Source",
        "POST",
        "/api/sources",
        json={"url": "https://vk.com/demo_minusinsk", "district": None},
    )
    await call("Source", "PATCH", f"/api/sources/{added['id']}", json={"name": "Минусинск"})
    await client.delete(f"/api/sources/{added['id']}", headers=headers)
    await call("Source", "POST", f"/api/sources/{added['id']}/restore")
    await call("SourcesRecheckReport", "POST", "/api/sources/recheck")
    csv = "Название;Ссылка\nЛесосибирск;https://m.vk.com/demo_lesosib\nСайт;https://example.ru\n;\n".encode()
    preview = await call(
        "ImportPreview",
        "POST",
        "/api/sources/import/preview",
        files={"file": ("список.csv", csv, "text/csv")},
    )
    await call("ImportReport", "POST", f"/api/sources/import/{preview['previewId']}")
    await call("Workspace", "GET", "/api/workspace")
    link = await call("WorkspaceLink", "GET", "/api/workspace/link")
    await call("Workspace", "POST", "/api/workspace/open", json={"key": link["url"]})
    await call("StandStatus", "GET", "/api/stand")

    search_id, events = await run_search(client, headers, mode="my-sources")
    for event in events:
        checks.append(("SearchEvent", event["data"]))
    selection = await call("Selection", "GET", f"/api/searches/{search_id}")
    items = selection["items"]
    # Причина региона «в вашем списке» (п. 48): в «Моих источниках» — у каждой записи.
    assert all(i["regionReason"]["inMySources"] is True for i in items)
    await call(
        "SelectionCounts",
        "POST",
        f"/api/searches/{search_id}/exclusions",
        json={"itemIds": [items[0]["id"]], "excluded": True},
    )
    result = await call(
        "ExcludeSourceResult",
        "POST",
        f"/api/searches/{search_id}/exclusions/source",
        json={"sourceId": items[1]["publication"]["source"]["id"]},
    )
    checks.pop()  # ExcludeSourceResult — встроенный тип, проверяем части
    assert set(result) == {"itemIds", "counts"}
    checks.append(("SelectionCounts", result["counts"]))
    await call(
        "ResultItem",
        "POST",
        f"/api/searches/{search_id}/items",
        json={"url": "https://vk.com/wall-100106_57990"},
    )
    await call("LinkRecheckReport", "POST", f"/api/searches/{search_id}/links/recheck")
    await call("ExportPreview", "GET", f"/api/searches/{search_id}/export/preview")
    await call(
        "ExportPreview",
        "GET",
        f"/api/searches/{search_id}/export/preview",
        params={"onlyRelevance": ["direct", "disputed"]},
    )
    for event in await read_stream(client, headers, search_id, snapshot="true"):
        checks.append(("SearchEvent", event["data"]))
    await call("RecentSearch[]", "GET", "/api/recent")

    release = (
        "В Норильске открылась новая школа на 1 100 учеников. В школе 48 классов, два "
        "спортивных зала и бассейн. Первые уроки пройдут 20 октября."
    )
    release_id, release_events = await run_search(client, headers, release)
    for event in release_events:
        checks.append(("SearchEvent", event["data"]))
    await call("SpreadReport", "GET", f"/api/searches/{release_id}/spread")

    error = await client.get("/api/searches/nope", headers=headers)
    checks.append(("ApiError", error.json()))

    for type_name, value in checks:
        assert_contract(type_name, value)

    # Форма записей, счётчиков, условий и статусов — та же, что у имитации (пути ключей).
    fake = json.loads((HERE / "samples" / "getSelection.json").read_text("utf-8"))["value"]
    parts = ("items[]", "counts", "conditions", "statuses[]")
    fake_paths = {p for p in _key_paths(fake) if p.startswith(parts)}
    server_paths = {p for p in _key_paths(selection) if p.startswith(parts)}
    # Необязательные ветки (репост, цитирование, «потолок» площадки) есть не в каждой подборке.
    optional = (
        "items[].publication.repostOf.",
        "items[].citation.",
        "statuses[].cap.",
        "statuses[].progress.",
        "statuses[].problem.",
    )
    assert {p for p in fake_paths if not p.startswith(optional)} <= server_paths
