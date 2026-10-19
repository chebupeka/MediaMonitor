"""Настройки сервиса — только из переменных окружения (файл .env подхватывает __main__)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

DEFAULT_MODEL = "sergeyzh/BERTA"
DEFAULT_PORT = 8090
MIN_TOKEN_LENGTH = 16

Device = Literal["auto", "cuda", "cpu"]


class ConfigError(Exception):
    """Ошибка настройки: сервис не стартует и пишет, что поправить."""


@dataclass(frozen=True)
class Settings:
    token: str
    model: str = DEFAULT_MODEL
    device: Device = "auto"
    batch_size: int = 64
    fp16: bool = True
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env

        def get(name: str) -> str:
            # Пустое значение в .env — «не задано», берётся значение по умолчанию.
            return e.get(name, "").strip()

        token = get("EMBEDDINGS_TOKEN")
        if len(token) < MIN_TOKEN_LENGTH:
            raise ConfigError(
                f"EMBEDDINGS_TOKEN не задан или короче {MIN_TOKEN_LENGTH} знаков. "
                "Задайте длинную случайную строку в .env (её же — в EMBEDDINGS_TOKEN на сервере)."
            )
        device = get("EMBEDDINGS_DEVICE").lower() or "auto"
        if device not in ("auto", "cuda", "cpu"):
            raise ConfigError(f"EMBEDDINGS_DEVICE={device!r}: допустимо auto, cuda или cpu.")
        return cls(
            token=token,
            model=get("EMBEDDINGS_MODEL") or DEFAULT_MODEL,
            device=device,  # type: ignore[arg-type]  # проверено выше
            batch_size=_int(get("EMBEDDINGS_BATCH_SIZE"), "EMBEDDINGS_BATCH_SIZE", 64, 1, 1024),
            fp16=_bool(get("EMBEDDINGS_FP16"), "EMBEDDINGS_FP16", default=True),
            host=get("EMBEDDINGS_HOST") or "0.0.0.0",
            port=_int(get("EMBEDDINGS_PORT"), "EMBEDDINGS_PORT", DEFAULT_PORT, 1, 65535),
        )


def _int(raw: str, name: str, default: int, lo: int, hi: int) -> int:
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name}={raw!r}: нужно целое число.") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{name}={value}: допустимо от {lo} до {hi}.")
    return value


def _bool(raw: str, name: str, *, default: bool) -> bool:
    if not raw:
        return default
    low = raw.lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name}={raw!r}: нужно true или false.")
