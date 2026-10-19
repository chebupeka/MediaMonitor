"""Пороги воронки и настройки из переменных окружения.

Пороги подобраны на мини-эталоне (`eval/`, см. README). Эталон маленький, поэтому
значения — стартовые: их нужно перепроверять на живых данных.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_EMBEDDING_MODEL = "sergeyzh/BERTA"


@dataclass(frozen=True, slots=True)
class NewsThresholds:
    """Поиск по тексту новости (сценарий 2)."""

    # Шаг 1. Копия: доля релиза, вошедшая дословно.
    copy_release_share: float = 0.25
    # Или пост почти целиком состоит из фраз релиза (короткая выжимка).
    copy_post_share: float = 0.6
    copy_min_tokens: int = 12
    # Частичная копия (доля ниже этой) проверяется признаками события: шаблонные фразы
    # пресс-службы совпадают и у разных новостей. Столько противоречий без совпадений — не копия.
    copy_sure_share: float = 0.6
    copy_conflict_for_no: int = 2
    # Шаг 2. Смысловая близость (косинус BERTA, префикс paraphrase). На эталоне: пересказы
    # 0,69–0,93, новости других сюжетов не выше 0,57, похожие о другом событии 0,42–0,90.
    cos_no: float = 0.60  # ниже — явно нет
    cos_yes: float = 0.80  # выше и без противоречий события — явно да
    cos_supported: float = 0.70  # выше, совпал признак события и нет противоречий — явно да
    # Шаг 3. Признаки события.
    support_for_yes: int = 1
    conflict_for_no: int = 1  # столько противоречий и ни одного совпадения — другое событие


@dataclass(frozen=True, slots=True)
class TopicThresholds:
    """Поиск по теме или событию своими словами (сценарий 1)."""

    # Косинус BERTA с префиксом categorize_topic: шкала сжата (по теме 0,67–0,90,
    # не по теме 0,60–0,71), поэтому решает и запас над «не то» карточки темы.
    sim_no: float = 0.64  # близость к теме ниже — явно нет
    sim_yes: float = 0.72  # выше и с запасом над «не то» — явно да
    margin_yes: float = 0.02  # запас над «не то» для явного да
    margin_no: float = -0.04  # заметно ближе к «не то», чем к теме, — явно нет
    sim_direct: float = 0.76  # без нейросети: выше — «прямо», ниже — «косвенно»


@dataclass(frozen=True, slots=True)
class PlacementThresholds:
    """Тип размещения (П2)."""

    verbatim: float = 0.8  # доля релиза для «дословно»
    shortened: float = 0.25  # доля релиза для «сокращено»
    shortened_post_share: float = 0.6  # или пост почти целиком из релиза
    shortened_min_tokens: int = 12
    fragment_taken: float = 0.5  # доля слов абзаца, чтобы абзац считался взятым


@dataclass(frozen=True, slots=True)
class LlmSettings:
    """Нейросеть для серой зоны. Без `OLLAMA_URL` воронка работает без неё."""

    url: str | None = None
    model: str = "hf.co/ai-sage/GigaChat3.1-10B-A1.8B-GGUF:Q4_K_M"
    api: str = "ollama"  # 'ollama' — /api/chat; 'openai' — /v1/chat/completions
    timeout_s: float = 90.0
    max_gray: int = 60  # сколько спорных проверяем за один поиск (НТ-6)
    deadline_s: float = 300.0  # общий бюджет времени нейросети на поиск
    num_ctx: int = 8192

    @classmethod
    def from_env(cls) -> LlmSettings:
        d = cls()
        url = os.environ.get("OLLAMA_URL", "").strip() or None
        return cls(
            url=url.rstrip("/") if url else None,
            model=os.environ.get("OLLAMA_MODEL", "").strip() or d.model,
            api=os.environ.get("LLM_API", "").strip() or d.api,
            timeout_s=_env_float("LLM_TIMEOUT", d.timeout_s),
            max_gray=int(_env_float("LLM_MAX_GRAY", d.max_gray)),
            deadline_s=_env_float("LLM_DEADLINE", d.deadline_s),
            num_ctx=int(_env_float("LLM_NUM_CTX", d.num_ctx)),
        )


@dataclass(frozen=True, slots=True)
class MatcherConfig:
    news: NewsThresholds = field(default_factory=NewsThresholds)
    topic: TopicThresholds = field(default_factory=TopicThresholds)
    placement: PlacementThresholds = field(default_factory=PlacementThresholds)
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    # Длинные тексты режем на куски (модель видит до 512 токенов).
    max_chunk_chars: int = 1500
    max_chunks: int = 4

    @classmethod
    def from_env(cls) -> MatcherConfig:
        return cls(embedding_model=os.environ.get("EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
