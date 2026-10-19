"""Модель эмбеддингов: загрузка один раз, выбор устройства, fp16 на видеокарте, пакетный подсчёт.

Подсчёт повторяет `SentenceTransformerEmbedder` из пакета `mm_matching` (server/matching):
`model.encode(texts, prompt=prefix)`. Префикс передаётся явно и пустым тоже — иначе BERTA
подставит свой префикс по умолчанию («categorize_entailment: »).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from mm_embeddings.settings import Settings

log = logging.getLogger("mm_embeddings")

Matrix = npt.NDArray[np.float32]

# Длиннее модель всё равно не прочитает: BERTA обрезает вход до 512 токенов (~2,5–3,5 тыс.
# знаков русского текста). Обрезка знаков заранее не меняет вектор, но защищает от огромных строк.
MAX_TEXT_CHARS = 20_000
# Если видеокарте не хватило памяти (соседка — Ollama), пакет считается ещё раз мелкими порциями.
OOM_RETRY_BATCH = 8


class Encoder(Protocol):
    """Что нужно сервису от модели."""

    model_name: str
    device: str
    dim: int

    def encode(self, texts: Sequence[str], prefix: str, normalize: bool) -> Matrix: ...


class DeviceError(RuntimeError):
    """Запрошенное устройство недоступно или torch собран без поддержки этой видеокарты."""


def resolve_device(requested: str) -> str:
    """auto → cuda, если видеокарта доступна и поддержана этой сборкой torch, иначе cpu."""
    import torch

    if requested == "cpu":
        return "cpu"
    if not torch.cuda.is_available():
        if requested == "cuda":
            raise DeviceError(
                f"EMBEDDINGS_DEVICE=cuda, но CUDA недоступна: torch {torch.__version__}, "
                f"сборка CUDA {torch.version.cuda or 'нет (CPU-сборка)'}. "
                "Поставьте сборку с CUDA: uv sync --extra cu128 и проверьте драйвер (nvidia-smi)."
            )
        log.warning("CUDA недоступна (torch %s) — считаем на CPU", torch.__version__)
        return "cpu"
    major, minor = torch.cuda.get_device_capability(0)
    arch = f"sm_{major}{minor}"
    supported = torch.cuda.get_arch_list()
    if arch not in supported and f"compute_{major}{minor}" not in supported:
        raise DeviceError(
            f"Видеокарта {torch.cuda.get_device_name(0)} ({arch}) не поддержана этой сборкой torch "
            f"{torch.__version__} (CUDA {torch.version.cuda}; есть {', '.join(supported)}). "
            "Для RTX 50xx (Blackwell, sm_120) нужна сборка cu128 или новее: uv sync --extra cu128."
        )
    return "cuda"


class SentenceTransformerEncoder:
    """Обёртка над sentence-transformers. Один экземпляр на процесс, вызовы по одному (блокировка)."""

    def __init__(self, settings: Settings) -> None:
        import torch
        from sentence_transformers import SentenceTransformer
        from transformers.utils import logging as hf_logging

        hf_logging.disable_progress_bar()  # type: ignore[no-untyped-call]
        self.model_name = settings.model
        self.device = resolve_device(settings.device)
        self._batch_size = settings.batch_size
        self._lock = threading.Lock()
        started = time.perf_counter()
        model: Any = SentenceTransformer(settings.model, device=self.device)
        if self.device == "cuda" and settings.fp16:
            model.half()
        model.eval()
        self._model = model
        get_dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        self.dim = int(get_dim())
        # Прогрев: первый вызов на видеокарте заметно дольше остальных.
        self.encode(["Красноярск"], "paraphrase: ", normalize=True)
        dtype = str(next(model.parameters()).dtype).replace("torch.", "")
        gpu = f", {torch.cuda.get_device_name(0)}" if self.device == "cuda" else ""
        log.info(
            "модель %s загружена за %.1f с: %s%s, %s, размерность %d; torch %s, CUDA %s",
            self.model_name,
            time.perf_counter() - started,
            self.device,
            gpu,
            dtype,
            self.dim,
            torch.__version__,
            torch.version.cuda or "нет",
        )

    def encode(self, texts: Sequence[str], prefix: str, normalize: bool) -> Matrix:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        batch = [t[:MAX_TEXT_CHARS] for t in texts]
        with self._lock:
            try:
                raw = self._encode(batch, prefix, self._batch_size)
            except Exception as exc:
                if self.device != "cuda" or not _is_cuda_oom(exc):
                    raise
                import torch

                log.warning(
                    "не хватило памяти видеокарты на пакет из %d текстов — считаю порциями", len(batch)
                )
                torch.cuda.empty_cache()
                raw = self._encode(batch, prefix, OOM_RETRY_BATCH)
        mat = np.asarray(raw, dtype=np.float32)
        if normalize:
            # Нормируем в float32 уже после модели: на fp16 так точнее.
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            mat = mat / np.where(norms > 0, norms, 1.0)
        return mat.astype(np.float32, copy=False)

    def _encode(self, texts: list[str], prefix: str, batch_size: int) -> Any:
        return self._model.encode(
            texts,
            batch_size=batch_size,
            prompt=prefix,  # явный префикс, даже пустой: иначе модель подставит свой
            normalize_embeddings=False,
            convert_to_numpy=True,
            show_progress_bar=False,
        )


def _is_cuda_oom(exc: Exception) -> bool:
    import torch

    return isinstance(exc, torch.cuda.OutOfMemoryError) or "out of memory" in str(exc).lower()
