"""Детектор ИИ-текста GigaCheck-Classifier-Multi в процессе сервиса эмбеддингов.

Модель (Hugging Face `iitolstykh/GigaCheck-Classifier-Multi`, Apache-2.0) — Mistral-7B-v0.3
с головой классификации: два класса `ai` и `human` (`config.id2label`). Оценка текста —
вероятность класса `ai` после softmax, 0…1. Ничего сводить не нужно: классов два.

Свой класс модели вместо `trust_remote_code`: код с Hugging Face (`modeling_gigacheck.py`)
тянет пакет `gigacheck` (Python 3.11) ради одного слоя. Здесь тот же расчёт без чужого кода:
`MistralModel` → скрытое состояние последнего токена `</s>` → `dense` → `tanh` → `out_proj`
(как `MistralAIDetectorForSequenceClassification` и `get_eos_token` в github.com/ai-forever/gigacheck).
Вход — как `GigaCheckForSequenceClassification._get_inputs`: токены без служебных, не больше
`max_length - 2` (1022), потом `<s>` в начало и `</s>` в конец. Веса и токенизатор — с
зафиксированной ревизии (`DEFAULT_DETECT_REVISION`).

Детерминизм (docs/12-tech-design.md §13): модель в `eval`, без случайности; каждый текст
считается отдельно (пакет из одного текста, без выравнивания), поэтому оценка не зависит от
соседей по запросу. Повтор того же текста берётся из памяти процесса. Текст нормализуется так
же, как на сервере (`server/src/mediamonitor/aicheck/text.py`); сервер шлёт уже нормализованный
текст, повторная нормализация его не меняет.

На видеокарте модель грузится в 4 битах (nf4, расчёт в bf16): bf16 целиком — 14,5 ГБ, рядом
с GigaChat в 16 ГБ не помещается. Голова классификации остаётся в bf16.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from mm_embeddings.settings import DEFAULT_DETECT_MODEL, Settings

log = logging.getLogger("mm_embeddings")

AI_LABEL = "ai"
# Сервер режет текст до 20 000 знаков после нормализации; модель всё равно читает 1022 токена
# (~400–500 русских слов). Обрезка знаков заранее защищает от огромных строк.
MAX_TEXT_CHARS = 20_000
DEFAULT_MAX_TOKENS = 1024
# Сколько оценок помнить: повтор того же текста — тот же ответ без модели.
MEMO_SIZE = 4096
SCORE_DIGITS = 4

DetectorState = Literal["disabled", "loading", "ready", "failed"]


# --------------------------------------------------------------------------- нормализация
# Шаг в шаг как server/src/mediamonitor/aicheck/text.py (и web/src/lib/ai-normalize.ts).
def _chars(*codes: int | tuple[int, int]) -> str:
    parts = []
    for code in codes:
        if isinstance(code, tuple):
            parts.append(f"{re.escape(chr(code[0]))}-{re.escape(chr(code[1]))}")
        else:
            parts.append(re.escape(chr(code)))
    return "[" + "".join(parts) + "]"


_NBSP = chr(0x00A0)
_INVISIBLE = re.compile(_chars((0x200B, 0x200D), 0xFEFF, 0x00AD))
_WHITESPACE = re.compile(
    _chars(
        (0x0009, 0x000D),
        (0x001C, 0x001F),
        0x0020,
        0x0085,
        0x00A0,
        0x1680,
        (0x2000, 0x200A),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
    )
    + "+"
)


def normalize_text(text: str) -> str:
    """NFC, без невидимых символов, пробелы схлопнуты, края обрезаны (как на сервере)."""
    value = unicodedata.normalize("NFC", text)
    value = _INVISIBLE.sub("", value)
    value = value.replace(_NBSP, " ")
    value = _WHITESPACE.sub(" ", value)
    return value.strip(" ")


# --------------------------------------------------------------------------- интерфейс
class Detector(Protocol):
    """Что нужно сервису от детектора: имя модели, версия (ревизия и сжатие) и оценки."""

    model_name: str
    version: str
    device: str

    def score(self, texts: Sequence[str]) -> list[float]: ...


class DetectorNotReadyError(Exception):
    """Детектор выключен, ещё грузится или не загрузился — ответ 503."""

    def __init__(self, state: DetectorState, message: str) -> None:
        super().__init__(message)
        self.state = state


class DetectorSlot:
    """Состояние детектора в сервисе: выключен, грузится (фоном), готов или не загрузился.

    Модель грузится фоном после старта: эмбеддинги работают сразу, а /ai-detect до конца
    загрузки отвечает 503. Если загрузка упала, сервис эмбеддингов работает дальше.
    """

    def __init__(
        self,
        model_name: str,
        state: DetectorState,
        detector: Detector | None = None,
        error: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.state: DetectorState = state
        self.detector = detector
        self.error = error
        self.started = time.monotonic()
        self.thread: threading.Thread | None = None

    @classmethod
    def ready(cls, detector: Detector) -> DetectorSlot:
        return cls(detector.model_name, "ready", detector)

    @classmethod
    def disabled(cls, model_name: str = DEFAULT_DETECT_MODEL) -> DetectorSlot:
        return cls(model_name, "disabled")

    @classmethod
    def start(cls, settings: Settings, loader: Callable[[Settings], Detector] | None = None) -> DetectorSlot:
        """Начать загрузку фоном (или вернуть «выключен», если AI_DETECT_ENABLED=false)."""
        if not settings.ai_detect_enabled:
            log.info("детектор ИИ-текста выключен (AI_DETECT_ENABLED=false)")
            return cls.disabled(settings.ai_detect_model)
        slot = cls(settings.ai_detect_model, "loading")
        load = loader or GigaCheckDetector

        def run() -> None:
            try:
                detector = load(settings)
            except BaseException as exc:  # любая ошибка загрузки: сервис эмбеддингов живёт дальше
                slot.error = _short_error(exc)
                slot.state = "failed"
                log.exception("детектор ИИ-текста %s не загрузился", settings.ai_detect_model)
                return
            slot.detector = detector
            slot.state = "ready"

        slot.thread = threading.Thread(target=run, name="ai-detect-load", daemon=True)
        slot.thread.start()
        return slot

    def get(self) -> Detector:
        if self.state == "ready" and self.detector is not None:
            return self.detector
        if self.state == "disabled":
            raise DetectorNotReadyError(
                "disabled",
                "детектор ИИ-текста выключен на компьютере с видеокартой (AI_DETECT_ENABLED=false)",
            )
        if self.state == "loading":
            minutes = (time.monotonic() - self.started) / 60
            raise DetectorNotReadyError(
                "loading",
                f"детектор ИИ-текста ещё загружается ({minutes:.0f} мин): первая загрузка скачивает "
                "~14,3 ГБ, дальше — 1–3 минуты. Повторите позже",
            )
        raise DetectorNotReadyError(
            "failed", f"детектор ИИ-текста не загрузился: {self.error}. Подробности в журнале сервиса"
        )

    def health(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state, "model": self.model_name}
        if self.detector is not None:
            out["version"] = self.detector.version
            out["device"] = self.detector.device
        if self.error:
            out["error"] = self.error
        return out


def _short_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split()) or type(exc).__name__
    return f"{type(exc).__name__}: {text}"[:300]


class MemoDetector:
    """Обёртка над расчётом одного текста: нормализация, порядок, память повторов.

    `score_one` — оценка одного уже нормализованного текста. Каждый текст считается отдельно,
    поэтому результат не зависит от состава пакета; одинаковые тексты считаются один раз.
    """

    def __init__(
        self,
        model_name: str,
        version: str,
        device: str,
        score_one: Callable[[str], float],
        memo_size: int = MEMO_SIZE,
    ) -> None:
        self.model_name = model_name
        self.version = version
        self.device = device
        self._score_one = score_one
        self._memo: OrderedDict[str, float] = OrderedDict()
        self._memo_size = memo_size
        self._lock = threading.Lock()

    def score(self, texts: Sequence[str]) -> list[float]:
        out: list[float] = []
        with self._lock:  # модель считает по одному запросу за раз
            for raw in texts:
                text = normalize_text(raw)[:MAX_TEXT_CHARS]
                key = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
                cached = self._memo.get(key)
                if cached is None:
                    cached = _clamp(self._score_one(text))
                    self._memo[key] = cached
                    if len(self._memo) > self._memo_size:
                        self._memo.popitem(last=False)
                else:
                    self._memo.move_to_end(key)
                out.append(cached)
        return out


def _clamp(value: float) -> float:
    if math.isnan(value):  # модель сломалась: лучше ошибка, чем «не похоже»
        raise ValueError("модель вернула NaN")
    return round(min(1.0, max(0.0, float(value))), SCORE_DIGITS)


# --------------------------------------------------------------------------- модель
@dataclass(frozen=True)
class Plan:
    """Как грузить модель: устройство и сжатие."""

    device: str
    quant: Literal["nf4", "int8", "bf16"]


def plan(settings: Settings) -> Plan:
    """auto: на видеокарте — nf4, на CPU — bf16 (bitsandbytes на CPU здесь не используем)."""
    from mm_embeddings.encoder import resolve_device

    device = resolve_device(settings.device)
    quant = settings.ai_detect_quant
    if quant == "auto":
        quant = "nf4" if device == "cuda" else "bf16"
    if device == "cpu" and quant != "bf16":
        raise RuntimeError(
            f"AI_DETECT_QUANT={quant} работает только на видеокарте; на CPU — bf16 (~15 ГБ памяти)"
        )
    return Plan(device, quant)


def build_model_class() -> type[Any]:
    """Класс модели GigaCheck на основе Mistral (ленивый импорт torch и transformers)."""
    import torch
    from torch import nn
    from transformers import MistralConfig, MistralModel, MistralPreTrainedModel

    class ClassificationHead(nn.Module):
        def __init__(self, hidden_size: int, num_labels: int) -> None:
            super().__init__()
            self.dense = nn.Linear(hidden_size, hidden_size)
            self.dropout = nn.Dropout(0.1)  # в eval не действует
            self.out_proj = nn.Linear(hidden_size, num_labels)

        def forward(self, features: torch.Tensor) -> torch.Tensor:
            x = self.dropout(features)
            x = torch.tanh(self.dense(x))
            x = self.dropout(x)
            return self.out_proj(x)  # type: ignore[no-any-return]

    class GigaCheckClassifier(MistralPreTrainedModel):  # type: ignore[no-untyped-call]
        config_class = MistralConfig
        base_model_prefix = "model"
        _no_split_modules = ["MistralDecoderLayer"]  # noqa: RUF012 — так в transformers

        def __init__(self, config: MistralConfig) -> None:
            super().__init__(config)
            self.model = MistralModel(config)
            self.classification_head = ClassificationHead(config.hidden_size, int(config.num_labels or 2))
            self.post_init()  # type: ignore[no-untyped-call]

        def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
            """Логиты классов по токену `</s>` — последнему во входе без выравнивания."""
            hidden = self.model(input_ids=input_ids, use_cache=False).last_hidden_state
            eos = hidden[:, -1, :]
            head_dtype = self.classification_head.dense.weight.dtype
            return self.classification_head(eos.to(head_dtype))  # type: ignore[no-any-return]

    return GigaCheckClassifier


def encode_input(tokenizer: Any, text: str, max_tokens: int) -> list[int]:
    """Токены как у `GigaCheckForSequenceClassification._get_inputs`: `<s>` + до max-2 + `</s>`."""
    tokens = list(tokenizer(text, add_special_tokens=False)["input_ids"])[: max_tokens - 2]
    return [int(tokenizer.bos_token_id), *tokens, int(tokenizer.eos_token_id)]


def ai_index(id2label: dict[Any, str]) -> int:
    for key, label in id2label.items():
        if str(label).strip().lower() == AI_LABEL:
            return int(key)
    raise RuntimeError(f"в config.id2label нет класса «{AI_LABEL}»: {id2label}")


def GigaCheckDetector(settings: Settings) -> MemoDetector:  # noqa: N802 — фабрика вместо класса
    """Загрузить GigaCheck (скачивание при первом запуске ~14,3 ГБ) и вернуть детектор."""
    import torch
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer, BitsAndBytesConfig, MistralConfig
    from transformers.utils import logging as hf_logging

    hf_logging.disable_progress_bar()  # type: ignore[no-untyped-call]
    started = time.perf_counter()
    how = plan(settings)
    name, revision = settings.ai_detect_model, settings.ai_detect_revision
    log.info("детектор ИИ-текста: загружаю %s@%s (%s, %s)…", name, revision[:12], how.device, how.quant)

    # config.json читаем и сами: transformers 5 убирает из конфига max_length (параметр генерации),
    # а путь в кэше (…/snapshots/<коммит>/config.json) даёт точный коммит, даже если ревизия — «main».
    # Папка на диске вместо имени на Hugging Face — без скачивания (версия «local-…»).
    if Path(name).is_dir():
        config_path, commit = Path(name) / "config.json", "local"
    else:
        config_path = Path(hf_hub_download(name, "config.json", revision=revision))
        commit = config_path.parent.name if config_path.parent.parent.name == "snapshots" else revision
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    max_tokens = int(raw.get("max_length") or DEFAULT_MAX_TOKENS)
    config = MistralConfig.from_pretrained(name, revision=revision)
    index = ai_index(dict(config.id2label or {}))
    tokenizer = AutoTokenizer.from_pretrained(name, revision=revision)

    kwargs: dict[str, Any] = {"revision": revision, "config": config, "dtype": torch.bfloat16}
    if how.quant == "nf4":
        kwargs["quantization_config"] = BitsAndBytesConfig(  # type: ignore[no-untyped-call]
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            llm_int8_skip_modules=["classification_head"],
        )
    elif how.quant == "int8":
        kwargs["quantization_config"] = BitsAndBytesConfig(  # type: ignore[no-untyped-call]
            load_in_8bit=True, llm_int8_skip_modules=["classification_head"]
        )
    if how.device == "cuda":
        kwargs["device_map"] = {"": 0}
    model = build_model_class().from_pretrained(name, **kwargs)
    model.eval()
    device = next(model.parameters()).device

    def score_one(text: str) -> float:
        ids = torch.tensor([encode_input(tokenizer, text, max_tokens)], dtype=torch.long, device=device)
        with torch.inference_mode():
            try:
                logits = model(ids)
            except Exception as exc:
                if how.device == "cuda" and "out of memory" in str(exc).lower():
                    torch.cuda.empty_cache()
                raise
        probs = logits.float().softmax(dim=-1)
        return float(probs[0, index])

    version = f"{commit[:12]}-{how.quant}"
    detector = MemoDetector(name, version, how.device, score_one)
    warm = time.perf_counter()
    score_one("Прогрев детектора: короткий текст для первой оценки.")
    vram = ""
    if how.device == "cuda":
        vram = f", видеопамять процесса {torch.cuda.memory_allocated(0) / 2**30:.1f} ГиБ"
    log.info(
        "детектор ИИ-текста %s (%s) загружен за %.0f с, прогрев %.1f с%s",
        name,
        version,
        time.perf_counter() - started,
        time.perf_counter() - warm,
        vram,
    )
    return detector
