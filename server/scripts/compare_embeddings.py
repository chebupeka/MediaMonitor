"""Сверка провайдеров эмбеддингов: сервис gpu-node (EMBEDDINGS_URL) и CPU сервера дают
одинаковые векторы для тех же текстов и задач (косинус не ниже 0,999).

    set EMBEDDINGS_URL=http://<адрес>:8090 и EMBEDDINGS_TOKEN=..., затем
    uv run python scripts/compare_embeddings.py

Сервер без модели на CPU (образ без torch, EMBEDDINGS_CPU_FALLBACK=false) сверяет сервис с
эталоном, посчитанным заранее на CPU другого компьютера:

    uv run python scripts/compare_embeddings.py --save scripts/berta-reference.json   # с моделью
    python scripts/compare_embeddings.py --reference scripts/berta-reference.json     # на сервере

Сравниваются клиенты сервера целиком: длинный текст режется на куски тем же `chunk_text`
(до 1500 знаков, не больше 4 кусков), векторы кусков усредняются и нормируются.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from mm_matching.embeddings import EmbedKind

from mediamonitor.matcher.embeddings import EmbeddingServiceError, HttpEmbedder, build_embedder
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


KINDS: tuple[EmbedKind, ...] = ("topic", "paraphrase")


def save_reference(path: Path) -> int:
    """Эталон: векторы модели на CPU этого компьютера для TEXTS по обеим задачам."""
    settings = Settings()
    local = build_embedder(settings.model_copy(update={"embeddings_url": None}))
    data: dict[str, object] = {"model": settings.embedding_model, "texts": TEXTS}
    for kind in KINDS:
        data[kind] = [[round(float(x), 7) for x in row] for row in local.encode(TEXTS, kind)]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Эталон {settings.embedding_model}: {len(TEXTS)} текстов → {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return compare(argv)
    except EmbeddingServiceError as error:
        print(f"Сервис эмбеддингов: {error}", file=sys.stderr)
        return 2


def compare(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--save", type=Path, help="посчитать эталон на CPU и сохранить")
    parser.add_argument("--reference", type=Path, help="сверить сервис с эталоном из файла")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.save:
        return save_reference(args.save)
    settings = Settings()
    if not settings.embeddings_url:
        print("Задайте EMBEDDINGS_URL (и EMBEDDINGS_TOKEN)", file=sys.stderr)
        return 2
    token = settings.embeddings_token.get_secret_value() if settings.embeddings_token else None
    remote = HttpEmbedder(settings.embeddings_url, settings.embedding_model, token=token)
    health = remote.health()
    reference: dict[str, object] | None = None
    if args.reference:
        reference = json.loads(args.reference.read_text(encoding="utf-8"))
        assert reference["model"] == settings.embedding_model, "эталон другой модели"
        assert reference["texts"] == TEXTS, "эталон для других текстов"
        local = None
    else:
        local = build_embedder(settings.model_copy(update={"embeddings_url": None}))
    report: dict[str, object] = {
        "service": health,
        "against": str(args.reference) if args.reference else "cpu",
        "lengths": [len(t) for t in TEXTS],
    }
    worst = 1.0
    for kind in KINDS:
        a = remote.encode(TEXTS, kind)
        if reference is not None:
            b = np.asarray(reference[kind], dtype=np.float32)
        else:
            assert local is not None
            b = local.encode(TEXTS, kind)
        cosines = [round(float(x), 6) for x in np.sum(a * b, axis=1)]
        report[kind] = cosines
        worst = min(worst, *cosines)
    report["min_cosine"] = round(worst, 6)
    report["ok"] = worst >= THRESHOLD
    print(json.dumps(report, ensure_ascii=False))
    return 0 if worst >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
