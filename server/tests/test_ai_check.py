"""Проверка текста на ИИ (04-decisions.md, «Проверка текста на ИИ»): один и тот же текст
даёт один результат в отдельной проверке, в подборке и в «Распространении».

Невидимые символы заданы кодами (`chr`): литералы в исходнике легко потерять при правке.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from mediamonitor.adapters.fixture import FixtureStore
from mediamonitor.aicheck import (
    DetectorReply,
    FixtureDetector,
    GigaCheckDetector,
    count_words,
    normalize_text,
    prepare,
    text_hash,
)
from mediamonitor.aicheck.providers import AiDetector, fixture_score
from mediamonitor.db.models import AiCheckRow
from mediamonitor.services.context import AppContext
from mediamonitor.settings import Settings
from tests.conftest import (
    Harness,
    make_app,
    make_settings,
    new_workspace,
    open_client,
    run_search,
)

CONTRACT = Path(__file__).parent / "contract"
NBSP, NNBSP, ZWSP, ZWNJ, ZWJ, BOM, SHY = (
    chr(c) for c in (0x00A0, 0x202F, 0x200B, 0x200C, 0x200D, 0xFEFF, 0x00AD)
)
COMBINING_DIAERESIS = chr(0x0308)
MODEL = "iitolstykh/GigaCheck-Classifier-Multi"

LONG = (
    "В Норильске после капитального ремонта открылась школа номер сорок два. В здании "
    "заменили окна, кровлю и инженерные сети, оборудовали два спортивных зала, бассейн и "
    "новую столовую. Первые уроки пройдут двадцатого октября, а к концу года в школе ещё "
    "откроют кабинеты робототехники и химии. Ремонт оплатили из краевого бюджета, работы "
    "заняли полтора года, сообщили в администрации города."
)


def variants(text: str) -> list[str]:
    """Один текст в разных записях: пробелы, неразрывные пробелы, невидимые символы, NFD."""
    words = text.split(" ")
    return [
        text,
        f"  {text}\n",
        text.replace(" ", "  "),
        text.replace(" ", NBSP),
        NNBSP.join(words),
        "\r\n".join(words),
        "\t".join(words),
        BOM + text.replace(" ", ZWSP + " ") + ZWJ,
        text.replace("о", "о" + SHY, 3).replace("а", "а" + ZWNJ, 2),
        text.replace("ё", "е" + COMBINING_DIAERESIS),
    ]


def ai_settings(tmp_path: Path, **overrides: Any) -> Settings:
    return make_settings(tmp_path, **{"ai_detect_retry_after_sec": 0, **overrides})


def ctx_of(harness: Harness) -> AppContext:
    ctx: AppContext = harness.app.state.ctx
    return ctx


async def ai_check(client: httpx.AsyncClient, text: str) -> dict[str, Any]:
    response = await client.post("/api/ai-check", json={"text": text})
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


async def ai_rows(harness: Harness) -> list[AiCheckRow]:
    async with ctx_of(harness).sessions() as session:
        return list(await session.scalars(select(AiCheckRow)))


def release_text() -> str:
    release = next(r for r in FixtureStore.load().recordings if r.id == "release")
    original = next(p for p in release.posts if p.ref.owner_id == "-100104")
    assert original.text is not None
    return original.text


class ConstDetector(FixtureDetector):
    """Детектор с постоянной оценкой: видно, посчитан результат заново или взят из кэша."""

    def __init__(self, version: str, score: float) -> None:
        super().__init__(model="const", version=version)
        self.score_value = score

    async def score(self, texts: Sequence[str]) -> DetectorReply:
        self.calls += 1
        self.texts += len(texts)
        return DetectorReply(self.model, self.version, [self.score_value] * len(texts))


class GatedDetector(FixtureDetector):
    """Детектор, который отвечает только после `gate.set()`: «медленная видеокарта»."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def score(self, texts: Sequence[str]) -> DetectorReply:
        await self.gate.wait()
        return await super().score(texts)


def detector_factory(detector: AiDetector | None) -> Any:
    def factory(_: Settings) -> AiDetector | None:
        return detector

    return factory


# ---------------------------------------------------------------- нормализация и ключ


def test_normalize_vectors_shared_with_interface() -> None:
    """Тест-векторы интерфейса (web/src/lib/ai-normalize.ts, выгрузка `npm run export`)."""
    vectors = json.loads((CONTRACT / "ai-normalize-vectors.json").read_text("utf-8"))
    assert len(vectors) >= 8
    for vector in vectors:
        normalized = normalize_text(vector["input"])
        assert normalized == vector["normalized"], vector["note"]
        assert count_words(normalized) == vector["words"], vector["note"]
        assert text_hash(normalized) == vector["sha256"], vector["note"]


def test_text_keys_match_interface_on_real_posts() -> None:
    """Ключ и слова у постов имитации (getSelection, «Распространение») — как у интерфейса."""
    checked = 0
    for name in ("getSelection", "event-release"):
        value = json.loads((CONTRACT / "samples" / f"{name}.json").read_text("utf-8"))["value"]
        events = value if isinstance(value, list) else [{"type": "items", "items": value["items"]}]
        for event in events:
            for item in event.get("items", []):
                check, text = item.get("aiCheck"), item["publication"]["text"]
                if check is None or text is None:
                    continue
                prepared = prepare(text)
                assert prepared.hash == check["textHash"], item["id"]
                assert prepared.words == check["words"], item["id"]
                checked += 1
    assert checked >= 20


def test_same_text_in_different_writings_has_one_key() -> None:
    keys = {prepare(v).hash for v in variants(LONG)}
    words = {prepare(v).words for v in variants(LONG)}
    assert len(keys) == 1
    assert words == {count_words(normalize_text(LONG))}
    # Нормализация — как в интерфейсе: пробельные по str.isspace (U+0085, U+001F тоже).
    assert normalize_text(f"a{chr(0x85)}b{chr(0x1F)}c") == "a b c"
    # Одиночный суррогат — как TextEncoder браузера (U+FFFD), а не ошибка.
    assert text_hash("a" + chr(0xD800)) == text_hash("a" + chr(0xFFFD))


def test_fixture_score_is_deterministic_and_from_hash() -> None:
    text = normalize_text(LONG)
    assert fixture_score(text) == fixture_score(text)
    u = int(text_hash(text)[:12], 16) / 2**48
    assert fixture_score(text) == pytest.approx(u**3, abs=0.0005)
    assert 0.0 <= fixture_score(text) <= 1.0


# ---------------------------------------------------------------- отдельная проверка


async def test_same_text_gives_same_result(tmp_path: Path) -> None:
    detector = FixtureDetector()
    harness = make_app(ai_settings(tmp_path), detector_factory=detector_factory(detector))
    async with open_client(harness.app) as client:
        results = [await ai_check(client, v) for v in variants(LONG)]
    first = results[0]
    assert first["level"] in ("likely-ai", "signs", "unlikely")
    assert first["score"] == fixture_score(normalize_text(LONG))
    assert first["textHash"] == prepare(LONG).hash
    assert first["model"] == "fixture-demo@1"
    # Всё одинаково, включая время первой проверки: остальные — из кэша.
    assert all(r == first for r in results)
    assert detector.calls == 1
    rows = await ai_rows(harness)
    assert [(r.text_hash, r.model, r.model_version) for r in rows] == [
        (first["textHash"], "fixture-demo", "1")
    ]


async def test_repeat_check_comes_from_cache(tmp_path: Path) -> None:
    settings = ai_settings(tmp_path)
    detector = ConstDetector("1", 0.9)
    harness = make_app(settings, detector_factory=detector_factory(detector))
    async with open_client(harness.app) as client:
        first = await ai_check(client, LONG)
        detector.score_value = 0.1  # модель «передумала» бы — но повтор берётся из кэша
        second = await ai_check(client, LONG.replace(" ", NBSP))
    assert first["level"] == "likely-ai"
    assert first["score"] == 0.9
    assert second == first
    assert detector.calls == 1
    # Кэш в базе, а не в памяти процесса: после перезапуска — тот же результат без модели.
    again = ConstDetector("1", 0.1)
    async with open_client(make_app(settings, detector_factory=detector_factory(again)).app) as c:
        assert await ai_check(c, LONG) == first
    assert again.calls == 0


async def test_model_or_version_change_recomputes(tmp_path: Path) -> None:
    settings = ai_settings(tmp_path)
    v1 = ConstDetector("1", 0.9)
    async with open_client(make_app(settings, detector_factory=detector_factory(v1)).app) as c:
        old = await ai_check(c, LONG)
    v2 = ConstDetector("2", 0.1)
    harness = make_app(settings, detector_factory=detector_factory(v2))
    async with open_client(harness.app) as c:
        new = await ai_check(c, LONG)
    assert v2.calls == 1
    assert (old["model"], old["level"]) == ("const@1", "likely-ai")
    assert (new["model"], new["level"], new["score"]) == ("const@2", "unlikely", 0.1)
    assert new["textHash"] == old["textHash"]
    rows = await ai_rows(harness)
    assert sorted(r.model_version for r in rows) == ["1", "2"]
    # Другая модель — тоже новый ключ.
    other = FixtureDetector(model="other-model", version="1")
    async with open_client(make_app(settings, detector_factory=detector_factory(other)).app) as c:
        assert (await ai_check(c, LONG))["model"] == "other-model@1"
    assert other.calls == 1


async def test_too_short_does_not_call_model(tmp_path: Path) -> None:
    detector = FixtureDetector()
    harness = make_app(ai_settings(tmp_path), detector_factory=detector_factory(detector))
    words = LONG.split(" ")
    async with open_client(harness.app) as client:
        short = await ai_check(client, " ".join(words[:39]) + NBSP + ZWSP)
        empty = await ai_check(client, "  " + ZWSP)
        enough = await ai_check(client, " ".join(words[:40]))
    assert short["level"] == "too-short"
    assert short["score"] is None
    assert short["words"] == 39
    assert short["textHash"] == prepare(" ".join(words[:39])).hash
    assert (empty["level"], empty["words"]) == ("too-short", 0)
    assert enough["level"] != "too-short"
    assert enough["words"] == 40
    assert detector.calls == 1  # только текст из 40 слов
    assert len(await ai_rows(harness)) == 1  # «мало текста» в кэш не пишется


async def test_too_long_text_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/ai-check", json={"text": "слово " * 4_000})
    assert response.status_code == 422
    assert response.json()["code"] == "too-long"


# ---------------------------------------------------------------- сервис недоступен


def failing_service(state: dict[str, Any]) -> httpx.MockTransport:
    """Сервис детектора по контракту gpu-node; `state["down"]` — не отвечает."""

    def handler(request: httpx.Request) -> httpx.Response:
        state.setdefault("requests", []).append(request)
        if state.get("down"):
            raise httpx.ConnectError("нет связи", request=request)
        if state.get("status"):
            return httpx.Response(state["status"], json={"detail": "ошибка"})
        texts = json.loads(request.content)["texts"]
        scores = state.get("scores") or [fixture_score(t) for t in texts]
        return httpx.Response(
            200, json={"model": state.get("model", MODEL), "version": "rev-7", "scores": scores}
        )

    return httpx.MockTransport(handler)


async def test_unavailable_service(tmp_path: Path) -> None:
    state: dict[str, Any] = {"down": True}
    detector = GigaCheckDetector(
        "http://gpu-node:8090", token="token-for-tests", transport=failing_service(state)
    )
    harness = make_app(ai_settings(tmp_path), detector_factory=detector_factory(detector))
    async with open_client(harness.app) as client:
        down = await ai_check(client, LONG)
        short = await ai_check(client, "Мало слов.")
        stand = (await client.get("/api/stand")).json()
        assert await ai_rows(harness) == []  # «недоступно» не кэшируется
        state["down"] = False
        up = await ai_check(client, LONG)
        stand_up = (await client.get("/api/stand")).json()
    assert down["level"] == "unavailable"
    assert down["score"] is None
    assert down["textHash"] == prepare(LONG).hash
    assert short["level"] == "too-short"  # короткий текст не зависит от модели
    notes = [e for e in stand["events"] if "Проверка текста на ИИ" in e["message"]]
    assert notes
    assert notes[0]["level"] == "warning"
    assert stand["overall"] == "degraded"
    assert "gpu-node" not in str(stand)  # без внутренних адресов (НТ-15)
    assert up["level"] in ("likely-ai", "signs", "unlikely")
    assert up["model"] == f"{MODEL}@rev-7"
    assert any("снова работает" in e["message"] for e in stand_up["events"])


async def test_unavailable_in_selection(tmp_path: Path) -> None:
    state: dict[str, Any] = {"status": 503}
    detector = GigaCheckDetector("http://gpu-node:8090", transport=failing_service(state))
    settings = ai_settings(tmp_path, ai_check_min_words=5, ai_detect_retry_after_sec=60)
    harness = make_app(settings, detector_factory=detector_factory(detector))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        search_id, events = await run_search(client, headers)
        selection = (await client.get(f"/api/searches/{search_id}", headers=headers)).json()
    assert events[-1]["event"] == "finished"
    levels = {i["aiCheck"]["level"] for i in selection["items"] if i["publication"]["text"]}
    assert levels <= {"unavailable", "too-short"}
    assert "unavailable" in levels
    assert selection["counts"]["aiLikely"] == selection["counts"]["aiSigns"] == 0


async def test_gigacheck_client_contract(tmp_path: Path) -> None:
    """Клиент: POST /ai-detect {texts}, токен gpu-node, пакеты, порядок оценок, чужая модель."""
    state: dict[str, Any] = {}
    detector = GigaCheckDetector(
        "http://gpu-node:8090/", token="token-for-tests", transport=failing_service(state)
    )
    settings = ai_settings(tmp_path, ai_detect_batch_size=2)
    harness = make_app(settings, detector_factory=detector_factory(detector))
    texts = [f"{LONG} Дополнение номер {n}." for n in range(5)]
    async with open_client(harness.app) as client:
        await asyncio.sleep(0.1)  # проверка сервиса при старте — пустым запросом
        first = await ai_check(client, "  " + texts[0].replace(" ", NBSP))
        many = await ctx_of(harness).ai_checks.check_many(texts)  # первый — из кэша
        separate = [await ai_check(client, t) for t in texts]
        state["model"] = "другая/модель"
        foreign = await ai_check(client, LONG)
        stand = (await client.get("/api/stand")).json()
    requests: list[httpx.Request] = state["requests"]
    assert all(r.url.path == "/ai-detect" and r.method == "POST" for r in requests)
    assert all(r.headers["Authorization"] == "Bearer token-for-tests" for r in requests)
    bodies = [json.loads(r.content)["texts"] for r in requests]
    assert bodies[0] == []  # проверка при старте
    assert bodies[1] == [normalize_text(texts[0])]  # в модель уходит нормализованный текст
    assert [len(b) for b in bodies[2:4]] == [2, 2]  # четыре новых текста — пакетами по 2
    assert [len(b) for b in bodies[4:]] == [1]  # дальше всё из кэша, кроме LONG
    assert first == separate[0]
    assert [c.dump() for c in many] == separate
    for text, result in zip(texts, separate, strict=True):
        assert result["score"] == fixture_score(normalize_text(text))  # порядок оценок сохранён
        assert result["textHash"] == prepare(text).hash
        assert result["model"] == f"{MODEL}@rev-7"
    assert foreign["level"] == "unavailable"
    assert any("другая модель" in e["message"] for e in stand["events"])


# ---------------------------------------------------------------- подборка и «Распространение»


async def test_selection_and_separate_check_agree(tmp_path: Path) -> None:
    detector = FixtureDetector()
    settings = ai_settings(tmp_path, ai_check_min_words=5)
    harness = make_app(settings, detector_factory=detector_factory(detector))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        search_id, events = await run_search(client, headers)
        selection = (await client.get(f"/api/searches/{search_id}", headers=headers)).json()
        items = [i for i in selection["items"] if i["publication"]["text"]]
        separate = [
            await ai_check(client, i["publication"]["text"].replace(" ", NBSP)) for i in items
        ]
    finished = events[-1]["data"]["selection"]
    assert {i["id"]: i.get("aiCheck") for i in finished["items"]} == {
        i["id"]: i.get("aiCheck") for i in selection["items"]
    }
    modelled = 0
    for item, check in zip(items, separate, strict=True):
        mine = item["aiCheck"]
        if mine["level"] == "too-short":
            assert check["level"] == "too-short"
            assert (check["textHash"], check["words"]) == (mine["textHash"], mine["words"])
        else:
            assert check == mine, item["id"]
            modelled += 1
    assert modelled >= 10
    computed = detector.texts
    assert computed <= len({i["aiCheck"]["textHash"] for i in items})  # каждый текст — один раз
    # Счётчики подборки — по тем же оценкам.
    active = [i for i in selection["items"] if not i["excluded"] and i.get("aiCheck")]
    counts = selection["counts"]
    assert counts["aiLikely"] == sum(i["aiCheck"]["level"] == "likely-ai" for i in active)
    assert counts["aiSigns"] == sum(i["aiCheck"]["level"] == "signs" for i in active)


async def test_selection_check_runs_in_background(tmp_path: Path) -> None:
    """Первые записи уходят без оценки; итог не ждёт детектор дольше лимита; оценка — потом."""
    detector = GatedDetector()
    settings = ai_settings(tmp_path, ai_check_min_words=5, ai_detect_finish_wait_sec=0.2)
    harness = make_app(settings, detector_factory=detector_factory(detector))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        search_id, events = await run_search(client, headers)
        pending = (await client.get(f"/api/searches/{search_id}", headers=headers)).json()
        detector.gate.set()
        for _ in range(100):  # фоновая проверка досчитывает после итога
            await asyncio.sleep(0.05)
            done = (await client.get(f"/api/searches/{search_id}", headers=headers)).json()
            if all("aiCheck" in i for i in done["items"] if i["publication"]["text"]):
                break
    assert events[-1]["event"] == "finished"
    first_items = next(e for e in events if e["event"] == "items")["data"]["items"]
    long = [
        i
        for i in first_items
        if i["publication"]["text"] and prepare(i["publication"]["text"]).words >= 5
    ]
    assert long
    assert all("aiCheck" not in i for i in long)  # ещё проверяются
    assert any("aiCheck" not in i for i in pending["items"])
    checked = [i for i in done["items"] if i["publication"]["text"]]
    assert all(i["aiCheck"]["level"] != "unavailable" for i in checked)
    assert all("aiCheck" in i for i in checked)


async def test_items_are_resent_with_ai_check(tmp_path: Path) -> None:
    settings = ai_settings(tmp_path, ai_check_min_words=5)
    harness = make_app(settings, detector_factory=detector_factory(FixtureDetector()))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        _, events = await run_search(client, headers)
    seen: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event["event"] == "items":
            for item in event["data"]["items"]:
                seen.setdefault(item["id"], []).append(item)
    resent = [versions for versions in seen.values() if len(versions) > 1]
    assert resent
    for versions in resent:
        assert "aiCheck" not in versions[0]
        assert versions[-1]["aiCheck"]["level"] in ("likely-ai", "signs", "unlikely")
    finished = events[-1]["data"]["selection"]
    assert all("aiCheck" in i for i in finished["items"] if i["publication"]["text"])


async def test_spread_uses_same_checks(tmp_path: Path) -> None:
    settings = ai_settings(tmp_path)
    detector = ConstDetector("1", 0.9)
    harness = make_app(settings, detector_factory=detector_factory(detector))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        search_id, _ = await run_search(client, headers, release_text())
        selection = (await client.get(f"/api/searches/{search_id}", headers=headers)).json()
        spread = (await client.get(f"/api/searches/{search_id}/spread", headers=headers)).json()
        by_id = {i["id"]: i for i in selection["items"]}
        long = [p for p in spread["placements"] if p.get("aiCheck", {}).get("level") == "likely-ai"]
        separate = [await ai_check(client, by_id[p["itemId"]]["publication"]["text"]) for p in long]
    assert spread["placements"]
    for placement in spread["placements"]:
        assert placement.get("aiCheck") == by_id[placement["itemId"]].get("aiCheck")
    assert long  # в релизе есть тексты от 40 слов
    assert separate == [p["aiCheck"] for p in long]
    retold = [
        p for p in spread["placements"] if p["placementType"] == "retold" and not p["isOriginal"]
    ]
    assert spread["aiRetold"] == {
        "likelyAi": sum(p.get("aiCheck", {}).get("level") == "likely-ai" for p in retold),
        "retold": len(retold),
    }


async def test_spread_without_detector_has_no_ai_summary(tmp_path: Path) -> None:
    harness = make_app(ai_settings(tmp_path), detector_factory=detector_factory(None))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        search_id, _ = await run_search(client, headers, release_text())
        spread = (await client.get(f"/api/searches/{search_id}/spread", headers=headers)).json()
        check = await ai_check(client, LONG)
        stand = (await client.get("/api/stand")).json()
    assert "aiRetold" not in spread
    assert check["level"] == "unavailable"
    assert any(e["level"] == "warning" and "не подключена" in e["message"] for e in stand["events"])


async def test_concurrent_checks_of_one_text_compute_once(tmp_path: Path) -> None:
    detector = GatedDetector()
    harness = make_app(ai_settings(tmp_path), detector_factory=detector_factory(detector))
    async with open_client(harness.app):
        service = ctx_of(harness).ai_checks
        tasks = [asyncio.create_task(service.check_text(v)) for v in variants(LONG)[:4]]
        await asyncio.sleep(0.05)
        detector.gate.set()
        results = await asyncio.gather(*tasks)
    assert detector.texts == 1
    assert all(r == results[0] for r in results)


def test_default_provider_by_settings(tmp_path: Path) -> None:
    assert make_settings(tmp_path).ai_detect_kind == "fixture"
    live = make_settings(tmp_path, data_source="live")
    assert live.ai_detect_kind == "off"  # без сервиса на живых данных — не выдумываем оценки
    stand = make_settings(tmp_path, environment="production")
    assert stand.ai_detect_kind == "off"  # на стенде демо-оценка — только явно
    demo = make_settings(tmp_path, environment="production", ai_detect_provider="fixture")
    assert demo.ai_detect_kind == "fixture"
    assert make_settings(tmp_path, ai_detect_provider="gigacheck").ai_detect_kind == "off"
    remote = make_settings(tmp_path, data_source="live", ai_detect_url="http://127.0.0.1:8090/")
    assert remote.ai_detect_kind == "gigacheck"
    assert remote.ai_detect_url == "http://127.0.0.1:8090"
    with pytest.raises(ValueError, match="AI_CHECK_SIGNS_THRESHOLD"):
        make_settings(tmp_path, ai_check_signs_threshold=0.9, ai_check_likely_threshold=0.8)


async def test_repeat_search_takes_checks_from_cache(tmp_path: Path) -> None:
    settings = ai_settings(tmp_path, ai_check_min_words=5)
    detector = FixtureDetector()
    harness = make_app(settings, detector_factory=detector_factory(detector))
    async with open_client(harness.app) as client:
        headers = await new_workspace(client)
        first_id, _ = await run_search(client, headers)
        computed = detector.texts
        second_id, _ = await run_search(client, headers, repeatOf=first_id)
        first = (await client.get(f"/api/searches/{first_id}", headers=headers)).json()
        second = (await client.get(f"/api/searches/{second_id}", headers=headers)).json()
        async with ctx_of(harness).sessions() as session:
            rows = await session.scalar(select(func.count()).select_from(AiCheckRow))
    assert computed > 0
    assert detector.texts == computed  # повторный поиск модель не трогает
    assert rows == computed
    assert {i["id"]: i.get("aiCheck") for i in first["items"]} == {
        i["id"]: i.get("aiCheck") for i in second["items"]
    }
