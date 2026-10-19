"""Сверка провайдеров эмбеддингов: сервис gpu-node (EMBEDDINGS_URL) и CPU сервера дают
одинаковые векторы для тех же текстов и задач (косинус не ниже 0,999).

    set EMBEDDINGS_URL=http://<адрес>:8090 и EMBEDDINGS_TOKEN=..., затем
    uv run python scripts/compare_embeddings.py

Сравниваются клиенты сервера целиком: длинный текст режется на куски тем же `chunk_text`
(до 1500 знаков, не больше 4 кусков), векторы кусков усредняются и нормируются.
"""

from __future__ import annotations

import json
import sys

import numpy as np

from mediamonitor.matcher.embeddings import HttpEmbedder, build_embedder
from mediamonitor.settings import Settings

THRESHOLD = 0.999
SHORT = [
    "В Красноярске открыли движение по новому мосту через Енисей.",
    "Сотрудники Госавтоинспекции провели рейд «Пешеход» в Ачинске: выявлено 14 нарушений.",
    "Краевое МЧС напоминает о мерах пожарной безопасности в отопительный сезон.",
    "ДТП",
]
PARAGRAPH = (
    "Сегодня в Красноярске состоялось торжественное открытие нового моста через Енисей. "
    "Строительство заняло четыре года, на него направили более 30 миллиардов рублей. "
    "По словам министра транспорта края, мост разгрузит Коммунальный и Октябрьский мосты."
)
LONG = "\n\n".join([PARAGRAPH] * 12)  # ~3 тыс. знаков: несколько кусков
TEXTS = [*SHORT, LONG, "\n".join([PARAGRAPH] * 30)]  # последний — больше 4 кусков


def main() -> int:
    settings = Settings()
    if not settings.embeddings_url:
        print("Задайте EMBEDDINGS_URL (и EMBEDDINGS_TOKEN)", file=sys.stderr)
        return 2
    token = settings.embeddings_token.get_secret_value() if settings.embeddings_token else None
    remote = HttpEmbedder(settings.embeddings_url, settings.embedding_model, token=token)
    health = remote.health()
    local = build_embedder(settings.model_copy(update={"embeddings_url": None}))
    report: dict[str, object] = {"service": health, "lengths": [len(t) for t in TEXTS]}
    worst = 1.0
    for kind in ("topic", "paraphrase"):
        a = remote.encode(TEXTS, kind)
        b = local.encode(TEXTS, kind)
        cosines = [round(float(x), 6) for x in np.sum(a * b, axis=1)]
        report[kind] = cosines
        worst = min(worst, *cosines)
    report["min_cosine"] = round(worst, 6)
    report["ok"] = worst >= THRESHOLD
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if worst >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
