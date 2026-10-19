"""Запуск: `uv run mm-embeddings` (или `python -m mm_embeddings`) из папки gpu-node.

Читает .env из текущей папки (переменные окружения важнее файла), грузит модель и только
потом открывает порт EMBEDDINGS_HOST:EMBEDDINGS_PORT (по умолчанию 0.0.0.0:8090).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from mm_embeddings.app import create_app
from mm_embeddings.encoder import DeviceError, SentenceTransformerEncoder
from mm_embeddings.settings import ConfigError, Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Запросы к Hugging Face и предупреждение о префиксе модели по умолчанию — шум: префикс
    # всегда передаётся явно (см. encoder.py).
    for name in ("httpx", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(name).setLevel(logging.ERROR)
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")  # huggingface_hub ставит свой уровень при импорте
    env_file = Path.cwd() / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    # Пустое значение в .env (или в EnvironmentFile systemd) значит «не задано». Иначе huggingface_hub
    # возьмёт пустой путь и положит модель в текущую папку.
    for name in ("HF_HOME", "HF_HUB_CACHE"):
        if name in os.environ and not os.environ[name].strip():
            del os.environ[name]
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Ошибка настройки: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        encoder = SentenceTransformerEncoder(settings)
    except DeviceError as exc:
        print(f"Ошибка видеокарты: {exc}", file=sys.stderr)
        sys.exit(3)
    app = create_app(settings, encoder)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
