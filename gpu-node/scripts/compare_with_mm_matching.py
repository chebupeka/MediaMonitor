"""Сверка: вектор сервиса совпадает с вектором пакета mm_matching (server/matching) для того же
текста и префикса. Порог — косинус не ниже 0,999.

Запускается окружением воронки (там стоит mm_matching), сервис должен уже работать:

    ..\\server\\matching\\.venv\\Scripts\\python scripts\\compare_with_mm_matching.py --url http://127.0.0.1:8090

Токен — EMBEDDINGS_TOKEN из окружения или из .env в текущей папке.

Длинный текст mm_matching режет на куски по абзацам (до 1500 знаков, не больше 4) и усредняет
векторы кусков. Сервис считает каждый присланный текст целиком (BERTA читает до 512 токенов),
поэтому клиент сервера должен присылать куски (`chunk_text`) и усреднять сам — так и сверяем.
Для наглядности печатается и косинус «без нарезки».
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
import numpy as np
import numpy.typing as npt
from mm_matching.config import MatcherConfig
from mm_matching.embeddings import SentenceTransformerEmbedder, chunk_text, prefixes_for

Matrix = npt.NDArray[np.float32]
THRESHOLD = 0.999

SHORT = [
    "В Красноярске открыли движение по новому мосту через Енисей.",
    "Сотрудники Госавтоинспекции провели рейд «Пешеход» в Ачинске: выявлено 14 нарушений.",
    "Краевое МЧС напоминает о мерах пожарной безопасности в отопительный сезон.",
    "Губернатор Красноярского края провёл совещание по подготовке к зиме.",
    "",
    "ДТП",
]
PARAGRAPHS = [
    "Сегодня в Красноярске состоялось торжественное открытие нового моста через Енисей. "
    "Строительство заняло четыре года, на него направили более 30 миллиардов рублей.",
    "По словам министра транспорта края, мост разгрузит Коммунальный и Октябрьский мосты: "
    "по прогнозам, поток машин в часы пик снизится на треть.",
    "Движение по мосту откроют в 18:00. Сначала пустят легковые автомобили и автобусы, "
    "грузовой транспорт — после окончания работ на развязках правого берега.",
    "Жители Советского района уже оценили новую дорогу: путь до центра города сократится "
    "на 20–25 минут. На мосту по шесть полос в каждую сторону и пешеходные тротуары.",
    "В мэрии напомнили, что в первые дни возможны пробки на подъездах к мосту, и попросили "
    "водителей соблюдать скоростной режим и следить за временными знаками.",
]
LONG = "\n\n".join(PARAGRAPHS * 3)  # ~2,3 тыс. знаков: у mm_matching это два куска


def load_token() -> str:
    token = os.environ.get("EMBEDDINGS_TOKEN", "").strip()
    env_file = Path.cwd() / ".env"
    if not token and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "EMBEDDINGS_TOKEN":
                token = value.strip().strip('"').strip("'")
    return token


def remote(client: httpx.Client, texts: list[str], model: str, prefix: str) -> Matrix:
    r = client.post("/embed", json={"texts": texts, "model": model, "prefix": prefix, "normalize": True})
    r.raise_for_status()
    return np.asarray(r.json()["vectors"], dtype=np.float32).reshape(len(texts), -1)


def remote_chunked(
    client: httpx.Client, texts: list[str], model: str, prefix: str, cfg: MatcherConfig
) -> Matrix:
    """Как клиент сервера: куски тем же `chunk_text`, один запрос, среднее и нормировка."""
    chunks: list[str] = []
    owner: list[int] = []
    for i, t in enumerate(texts):
        for c in chunk_text(t, cfg.max_chunk_chars, cfg.max_chunks):
            chunks.append(c)
            owner.append(i)
    vecs = remote(client, chunks, model, prefix)
    sums = np.zeros((len(texts), vecs.shape[1]), dtype=np.float32)
    np.add.at(sums, np.asarray(owner), vecs)
    norms = np.linalg.norm(sums, axis=1, keepdims=True)
    return (sums / np.where(norms > 0, norms, 1.0)).astype(np.float32)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:8090")
    args = p.parse_args()
    token = load_token()
    if not token:
        print("Нет EMBEDDINGS_TOKEN (окружение или .env в текущей папке)", file=sys.stderr)
        return 2
    cfg = MatcherConfig.from_env()
    model = str(cfg.embedding_model)
    local = SentenceTransformerEmbedder(model, max_chunk_chars=cfg.max_chunk_chars, max_chunks=cfg.max_chunks)
    texts = [*SHORT, LONG]
    labels = [repr(t[:40]) for t in SHORT] + [f"длинный текст, {len(LONG)} знаков"]
    worst = 1.0
    with httpx.Client(
        base_url=args.url.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=300
    ) as client:
        health = client.get("/health").json()
        print(f"сервис: {health}; mm_matching: модель {model}, куски до {cfg.max_chunk_chars} знаков")
        for kind, prefix in prefixes_for(model).items():
            ref = np.asarray(local.encode(texts, kind), dtype=np.float32)
            got = remote_chunked(client, texts, model, prefix, cfg)
            whole = remote(client, texts, model, prefix)
            cos = np.sum(ref * got, axis=1)
            cos_whole = np.sum(ref * whole, axis=1)
            print(f"\nзадача {kind}, префикс {prefix!r}")
            for label, c, cw in zip(labels, cos, cos_whole, strict=True):
                print(f"  {float(c):.6f}   без нарезки {float(cw):.6f}   {label}")
            worst = min(worst, float(np.min(cos)))
    verdict = "совпадают" if worst >= THRESHOLD else "НЕ совпадают"
    print(f"\nминимальный косинус {worst:.6f} (порог {THRESHOLD}) — векторы {verdict}")
    return 0 if worst >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
