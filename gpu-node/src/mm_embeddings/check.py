"""Проверка компьютера с видеокартой: torch и CUDA, сервис эмбеддингов, детектор ИИ-текста, Ollama.

    uv run python -m mm_embeddings.check                                   # torch, CUDA, видеокарта
    uv run python -m mm_embeddings.check --embeddings http://127.0.0.1:8090   # + /ai-detect
    uv run python -m mm_embeddings.check --ollama http://127.0.0.1:11434 \
        --model hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q6_K

Токен сервиса берётся из EMBEDDINGS_TOKEN (.env в текущей папке), токен прокси перед Ollama —
из OLLAMA_PROXY_TOKEN, если он задан. Код выхода 0 — всё в порядке, 1 — есть ошибки.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

DEFAULT_OLLAMA_MODEL = "hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q6_K"
# Сервер ждёт эту модель (AI_DETECT_MODEL) и эти пороги (AI_CHECK_*): docs/12-tech-design.md §13.
AI_DETECT_MODEL = "iitolstykh/GigaCheck-Classifier-Multi"
AI_LIKELY, AI_SIGNS, AI_MIN_WORDS = 0.85, 0.60, 40

# Четыре текста для проверки детектора. «Человек» — начало «Дамы с собачкой» А. П. Чехова
# (1899, общественное достояние): точно написан человеком. «ИИ» — текст нейросети в духе жалобы
# пользователя про бабочек. «Смешанный» — Чехов + абзац нейросети. «Короткий» — меньше 40 слов:
# сервер такой текст детектору не шлёт (too-short), здесь — только для сведения.
AI_TEXTS: dict[str, str] = {
    "человек": (
        "Говорили, что на набережной появилось новое лицо: дама с собачкой. Дмитрий Дмитрич Гуров, "
        "проживший в Ялте уже две недели и привыкший тут, тоже стал интересоваться новыми лицами. "
        "Сидя в павильоне у Верне, он видел, как по набережной прошла молодая дама, невысокого "
        "роста блондинка, в берете; за нею бежал белый шпиц. И потом он встречал её в городском "
        "саду и на сквере, по нескольку раз в день. Она гуляла одна, всё в том же берете, с белым "
        "шпицем; никто не знал, кто она, и называли её просто так: дама с собачкой."
    ),
    "ИИ": (
        "Бабочки — насекомые отряда чешуекрылых, известные своими яркими и разнообразными "
        "крыльями. Они играют важную роль в экосистеме, участвуя в опылении растений и служа "
        "пищей для других животных. Жизненный цикл бабочки включает четыре стадии: яйцо, "
        "гусеница, куколка и взрослая особь. Этот процесс называется полным превращением, или "
        "метаморфозом. Сегодня в мире насчитывается более 150 тысяч видов чешуекрылых, и учёные "
        "продолжают открывать новые. Изучение бабочек помогает лучше понять состояние окружающей "
        "среды, ведь они чутко реагируют на изменения климата."
    ),
    "короткий": "В Красноярске открыли новый мост через Енисей.",
    "смешанный": (
        "Говорили, что на набережной появилось новое лицо: дама с собачкой. Дмитрий Дмитрич Гуров, "
        "проживший в Ялте уже две недели и привыкший тут, тоже стал интересоваться новыми лицами. "
        "Ялта — один из самых известных курортов Черноморского побережья, расположенный на южном "
        "берегу Крыма. Мягкий климат, живописные горы и тёплое море ежегодно привлекают сюда тысячи "
        "туристов. Город славится своими набережными, парками и архитектурными памятниками, "
        "отражающими богатую историю региона."
    ),
}

# Задача того же вида, что у воронки: то же событие или нет, и номер предложения-доказательства.
OLLAMA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["same-event", "other-event", "unsure"]},
        "evidence": {"type": "integer", "minimum": 1, "maximum": 3},
    },
    "required": ["label", "evidence"],
    "additionalProperties": False,
}
OLLAMA_PROMPT = (
    "Новость: «В Красноярске 18 октября открыли движение по новому мосту через Енисей».\n"
    "Пост:\n[1] Вчера в краевом центре запустили движение по новому мосту.\n"
    "[2] По нему пройдут шесть автобусных маршрутов.\n[3] Подписывайтесь на канал.\n"
    "Пост о том же событии? Ответь меткой и номером предложения-доказательства."
)


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def ok(self, text: str) -> None:
        print(f"  OK      {text}")

    def warn(self, text: str) -> None:
        print(f"  ВНИМАНИЕ {text}")

    def fail(self, text: str) -> None:
        self.failed += 1
        print(f"  ОШИБКА  {text}")


def check_torch(r: Report) -> None:
    print("torch и видеокарта")
    import torch

    r.ok(f"torch {torch.__version__}, сборка CUDA {torch.version.cuda or 'нет (CPU)'}")
    if not torch.cuda.is_available():
        r.warn("CUDA недоступна — сервис будет считать на CPU (для RTX 5080 нужна сборка cu128 или cu130)")
        return
    name = torch.cuda.get_device_name(0)
    major, minor = torch.cuda.get_device_capability(0)
    arch = f"sm_{major}{minor}"
    archs = torch.cuda.get_arch_list()
    free, total = torch.cuda.mem_get_info(0)
    r.ok(f"{name}, {arch}, память {total / 2**30:.1f} ГиБ, свободно {free / 2**30:.1f} ГиБ")
    if arch in archs or f"compute_{major}{minor}" in archs:
        r.ok(f"сборка torch поддерживает {arch}")
    else:
        r.fail(f"сборка torch не поддерживает {arch} (есть {', '.join(archs)}): нужна cu128 или новее")
        return
    x = torch.ones((1024, 1024), device="cuda", dtype=torch.float16)
    r.ok(f"вычисление на видеокарте: {float((x @ x)[0, 0]):.0f} (ожидается 1024)")


def check_embeddings(r: Report, url: str, token: str, ai_detect: bool = True) -> None:
    print(f"сервис эмбеддингов {url}")
    with httpx.Client(base_url=url, timeout=120) as c:
        try:
            h = c.get("/health").json()
        except httpx.HTTPError as exc:
            r.fail(f"/health не отвечает: {exc}")
            return
        r.ok(f"/health: {h}")
        if h.get("device") != "cuda":
            r.warn("сервис считает на CPU, а не на видеокарте")
        body = {
            "texts": ["первый", "второй"],
            "model": h.get("model"),
            "prefix": "paraphrase: ",
            "normalize": True,
        }
        if c.post("/embed", json=body).status_code == 401:
            r.ok("без токена — 401")
        else:
            r.fail("без токена сервис ответил не 401")
        if not token:
            r.fail("EMBEDDINGS_TOKEN не задан — остальное не проверить")
            return
        auth = {"Authorization": f"Bearer {token}"}
        resp = c.post("/embed", json=body, headers=auth)
        if resp.status_code != 200:
            r.fail(f"/embed с токеном: {resp.status_code} {resp.text[:200]}")
            return
        data = resp.json()
        r.ok(f"/embed: модель {data['model']}, размерность {data['dim']}, векторов {len(data['vectors'])}")
        texts = [f"Новость номер {i}: в Красноярском крае прошёл рейд ГИБДД. " * 20 for i in range(256)]
        started = time.perf_counter()
        resp = c.post("/embed", json={**body, "texts": texts}, headers=auth)
        elapsed = time.perf_counter() - started
        if resp.status_code == 200 and len(resp.json()["vectors"]) == 256:
            r.ok(f"пакет 256 текстов по ~1200 знаков: {elapsed:.1f} с")
        else:
            r.fail(f"пакет 256 текстов: {resp.status_code} {resp.text[:200]}")
        if ai_detect:
            check_ai_detect(r, c, auth)


def _level(score: float, words: int) -> str:
    """Уровень, как его покажет сервер (те же пороги по умолчанию)."""
    if words < AI_MIN_WORDS:
        return "too-short (сервер не проверяет)"
    if score >= AI_LIKELY:
        return "likely-ai"
    return "signs" if score >= AI_SIGNS else "unlikely"


DETECTOR_NOT_READY = {
    "": "в /health нет ai_detect: на компьютере старый код — обновите его и перезапустите сервис",
    "disabled": "детектор выключен: AI_DETECT_ENABLED=false в .env — уберите строку и перезапустите сервис",
    "loading": "детектор ещё загружается (первый раз скачивает ~14,3 ГБ) — подождите и проверьте снова",
    "failed": "детектор не загрузился: {error} — подробности в окне или журнале сервиса",
}


def check_ai_detect(r: Report, c: httpx.Client, auth: dict[str, str]) -> None:
    print("детектор ИИ-текста (/ai-detect)")
    state = c.get("/health").json().get("ai_detect") or {}
    kind = str(state.get("state", ""))
    if kind != "ready":
        message = DETECTOR_NOT_READY.get(kind, f"детектор в состоянии {kind}")
        r.fail(message.format(error=state.get("error")))
        return
    r.ok(f"/health: {state}")
    if state.get("device") != "cuda":
        r.warn("детектор считает на CPU, а не на видеокарте: будет медленно")
    scores = _check_ai_scores(r, c, auth)
    if scores:
        _check_ai_repeat(r, c, auth, scores)


def _check_ai_scores(r: Report, c: httpx.Client, auth: dict[str, str]) -> list[float]:
    """Токен, пустой список (модель и версия), четыре текста с уровнями, как их покажет сервер."""
    if c.post("/ai-detect", json={"texts": []}).status_code == 401:
        r.ok("без токена — 401")
    else:
        r.fail("без токена /ai-detect ответил не 401")
    resp = c.post("/ai-detect", json={"texts": []}, headers=auth)
    if resp.status_code != 200:
        r.fail(f"/ai-detect с пустым списком: {resp.status_code} {resp.text[:300]}")
        return []
    head = resp.json()
    if head.get("model") == AI_DETECT_MODEL and head.get("version") and head.get("scores") == []:
        r.ok(f"модель {head['model']}, версия {head['version']}")
    else:
        r.fail(f"ответ не по контракту или чужая модель (сервер ждёт {AI_DETECT_MODEL}): {head}")
    names, texts = list(AI_TEXTS), list(AI_TEXTS.values())
    started = time.perf_counter()
    resp = c.post("/ai-detect", json={"texts": texts}, headers=auth)
    elapsed = time.perf_counter() - started
    if resp.status_code != 200 or len(resp.json().get("scores", [])) != len(texts):
        r.fail(f"/ai-detect на {len(texts)} текстах: {resp.status_code} {resp.text[:300]}")
        return []
    scores: list[float] = resp.json()["scores"]
    r.ok(f"{len(texts)} текста за {elapsed:.1f} с")
    for name, text, score in zip(names, texts, scores, strict=True):
        words = len(text.split())
        print(f"          {name:10} {words:3} слов  оценка {score:.4f}  -> {_level(score, words)}")
    by = dict(zip(names, scores, strict=True))
    if by["ИИ"] >= AI_LIKELY:
        r.ok("текст нейросети узнан (likely-ai)")
    else:
        r.warn(f"текст нейросети не набрал {AI_LIKELY}: {by['ИИ']:.4f} — сообщите команде")
    if by["человек"] < AI_SIGNS:
        r.ok("текст человека не назван нейросетью")
    else:
        r.warn(f"текст человека получил {by['человек']:.4f} (ложное срабатывание) — сообщите команде")
    return scores


def _check_ai_repeat(r: Report, c: httpx.Client, auth: dict[str, str], scores: list[float]) -> None:
    """Детерминизм (другой порядок и другие пробелы — те же оценки) и пакет как у сервера."""
    texts = list(AI_TEXTS.values())
    shuffled = [" " + t.replace(" ", "\n", 1) + "  " for t in reversed(texts)]
    again = c.post("/ai-detect", json={"texts": shuffled}, headers=auth).json().get("scores", [])
    if list(reversed(again)) == scores:
        r.ok("тот же текст — та же оценка (другой порядок и пробелы)")
    else:
        r.fail(f"оценки не повторились: {scores} и {list(reversed(again))}")
    batch = [f"{AI_TEXTS['ИИ']} Наблюдение номер {i}." for i in range(16)]
    started = time.perf_counter()
    resp = c.post("/ai-detect", json={"texts": batch}, headers=auth)
    elapsed = time.perf_counter() - started
    if resp.status_code == 200:
        r.ok(f"пакет 16 текстов по ~80 слов (как шлёт сервер): {elapsed:.1f} с")
    else:
        r.fail(f"пакет 16 текстов: {resp.status_code} {resp.text[:200]}")


def check_ollama(r: Report, url: str, model: str, token: str) -> None:
    print(f"Ollama {url}, модель {model}")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=url, timeout=300, headers=headers) as c:
        try:
            version = c.get("/api/version").json().get("version", "?")
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            r.fail(f"/api/version не отвечает: {exc}")
            return
        r.ok(f"версия Ollama {version}")
        names = [m.get("name", "") for m in c.get("/api/tags").json().get("models", [])]
        if model not in names:
            r.fail(f"модели нет: выполните `ollama pull {model}` (есть: {', '.join(names) or 'ничего'})")
            return
        r.ok("модель скачана")
        body = {
            "model": model,
            "messages": [{"role": "user", "content": OLLAMA_PROMPT}],
            "format": OLLAMA_SCHEMA,
            "stream": False,
            "options": {"temperature": 0, "seed": 0, "num_ctx": 8192},
        }
        started = time.perf_counter()
        resp = c.post("/api/chat", json=body)
        elapsed = time.perf_counter() - started
        if resp.status_code != 200:
            r.fail(f"/api/chat: {resp.status_code} {resp.text[:300]}")
            return
        content = resp.json().get("message", {}).get("content", "")
        try:
            answer = json.loads(content)
        except json.JSONDecodeError:
            r.fail(f"ответ не JSON: {content[:300]}")
            return
        if (
            set(answer) == {"label", "evidence"}
            and answer["label"] in OLLAMA_SCHEMA["properties"]["label"]["enum"]
        ):
            r.ok(f"ответ по JSON-схеме за {elapsed:.1f} с (с загрузкой модели): {answer}")
        else:
            r.fail(f"ответ не по схеме: {answer}")
        for m in c.get("/api/ps").json().get("models", []):
            if m.get("name") == model:
                size, vram = int(m.get("size", 0)), int(m.get("size_vram", 0))
                share = 100 * vram / size if size else 0
                ctx = m.get("context_length", "?")
                line = f"в памяти {size / 2**30:.1f} ГиБ, на видеокарте {share:.0f}%, контекст {ctx}"
                if share >= 99:
                    r.ok(line)
                else:
                    r.fail(line + " — часть модели на CPU: не хватает памяти видеокарты")


def main(argv: list[str] | None = None) -> int:
    env_file = Path.cwd() / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    p = argparse.ArgumentParser(description="Проверка компьютера с видеокартой для MediaMonitor")
    p.add_argument(
        "--embeddings", metavar="URL", help="адрес сервиса эмбеддингов, например http://127.0.0.1:8090"
    )
    p.add_argument("--ollama", metavar="URL", help="адрес Ollama, например http://127.0.0.1:11434")
    p.add_argument("--model", default=os.environ.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL)
    p.add_argument(
        "--skip-torch", action="store_true", help="не проверять torch (например, проверка с сервера)"
    )
    p.add_argument("--no-ai-detect", action="store_true", help="не проверять детектор ИИ-текста")
    args = p.parse_args(argv)
    r = Report()
    if not args.skip_torch:
        check_torch(r)
    if args.embeddings:
        token = os.environ.get("EMBEDDINGS_TOKEN", "").strip()
        check_embeddings(r, args.embeddings.rstrip("/"), token, ai_detect=not args.no_ai_detect)
    if args.ollama:
        check_ollama(r, args.ollama.rstrip("/"), args.model, os.environ.get("OLLAMA_PROXY_TOKEN", "").strip())
    print("Итог: " + ("всё в порядке" if r.failed == 0 else f"ошибок: {r.failed}"))
    return 0 if r.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
