"""Живая проба VK API на стенде: форма ответов groups.getById / wall.get / execute.

Запуск (только в работающем контейнере api, ключ — из его окружения, не печатается):

    cd /opt/mediamonitor/app/server && \\
    docker compose -f compose.yaml -f compose.server.yaml exec -T api python - < scripts/vk_probe.py

Не больше ~12 вызовов VK. Печатает только устройство ответов (ключи, коды ошибок, даты),
чтобы сверить разбор adapters/vk_live.py с настоящими ответами.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

API = os.environ.get("VK_API_URL", "https://api.vk.com/method").rstrip("/")
KEY = os.environ.get("VK_SERVICE_TOKEN", "").strip()
calls = [0]


def call(method: str, **params: object) -> dict[str, Any]:
    calls[0] += 1
    data = {k: str(v) for k, v in params.items()} | {"v": "5.199", "access_token": KEY}
    response = httpx.post(f"{API}/{method}", data=data, timeout=20)
    try:
        body: dict[str, Any] = response.json()
    except ValueError:
        return {"_status": response.status_code}
    return body


def error(body: dict[str, Any]) -> dict[str, Any] | None:
    block = body.get("error")
    if isinstance(block, dict):
        return {"code": block.get("error_code"), "msg": block.get("error_msg")}
    return None


def groups_of(body: dict[str, Any]) -> list[dict[str, Any]]:
    response = body.get("response")
    found = response.get("groups") if isinstance(response, dict) else response
    return [g for g in found or [] if isinstance(g, dict)]


def main() -> None:
    print("ключ задан:", bool(KEY))
    body = call(
        "groups.getById",
        group_ids="avangard_online,club68905670,gazeta_nkk,id586913986,no_such_group_zzz_999",
        fields="members_count",
    )
    print("\n1. groups.getById:", error(body) or type(body.get("response")).__name__)
    for g in groups_of(body):
        print("  ", {k: g.get(k) for k in ("id", "screen_name", "is_closed", "deactivated")})

    body = call("wall.get", owner_id="-68905670", count=5, filter="owner", extended=1)
    print("\n2. wall.get:", error(body) or "ok")
    response = body.get("response") or {}
    print("   ключи ответа:", sorted(response), "count:", response.get("count"))
    for item in (response.get("items") or [])[:5]:
        print(
            "   ",
            {k: item.get(k) for k in ("id", "owner_id", "date", "is_pinned", "edited")},
            "views:",
            item.get("views"),
            "likes:",
            (item.get("likes") or {}).get("count"),
            "вложения:",
            [a.get("type") for a in item.get("attachments") or []],
            "copy_history:",
            len(item.get("copy_history") or []),
        )

    body = call("execute", code='return API.wall.get({"owner_id": -68905670, "count": 1});')
    print("\n3. execute:", error(body) or "работает")

    for owner in ("-29585514", "-48293807"):
        body = call("wall.get", owner_id=owner, count=100, filter="owner", extended=1)
        response = body.get("response") or {}
        items = response.get("items") or []
        reposts = [i for i in items if i.get("copy_history")]
        links = [a for i in items for a in i.get("attachments") or [] if a.get("type") == "link"]
        print(f"\n4. wall.get {owner}:", error(body) or f"count={response.get('count')}")
        if reposts:
            original = reposts[0]["copy_history"][0]
            print("   copy_history:", sorted(original))
            print(
                "   владелец оригинала в groups:",
                any(
                    -g.get("id", 0) == original.get("owner_id")
                    for g in response.get("groups") or []
                ),
            )
        if links:
            print("   link:", sorted(links[0].get("link") or {}))

    body = call("wall.get", owner_id="-68905670", count=2, offset=100000, filter="owner")
    print("\n5. offset за концом стены:", error(body) or len(body["response"].get("items") or []))
    body = call("wall.get", owner_id="-999999999999", count=1)
    print("6. несуществующее сообщество:", error(body))
    body = call("wall.getById", posts="-68905670_1", extended=1)
    print("7. wall.getById:", error(body) or sorted(body.get("response") or {}))
    print("\nвызовов VK:", calls[0])


main()
