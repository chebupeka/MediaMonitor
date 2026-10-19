"""Миграции совпадают с моделью; ключей в репозитории нет (НТ-15)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from mediamonitor.db.models import Base

SERVER = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    config = Config(str(SERVER / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


def test_migrations_match_models(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        diff = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata
        )
        tables = set(inspect(connection).get_table_names())
    assert diff == [], f"модель и миграции расходятся: {diff}"
    assert set(Base.metadata.tables) <= tables
    command.downgrade(config, "base")
    with engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) <= {"alembic_version"}
    engine.dispose()


# ---------------------------------------------------------------- ключи (НТ-15)

SECRET_PATTERNS = [
    re.compile(r"vk1\.a\.[A-Za-z0-9_\-]{20,}"),  # ключ доступа VK
    re.compile(
        r"(?i)(token|secret|api[_-]?key|password)\s*[:=]\s*['\"][A-Za-z0-9_\-./+]{16,}['\"]"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
# matching/ — отдельный проект «Э-Отбор» со своими проверками; здесь — только наш код.
SKIP_DIRS = {
    ".venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "matching",
}


TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".ini",
    ".yaml",
    ".yml",
    ".json",
    ".md",
    ".example",
    ".mjs",
    ".txt",
    "",
}


def _files() -> list[Path]:
    result = []
    for root, dirs, files in os.walk(SERVER):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        result += [Path(root) / f for f in files if Path(f).suffix in TEXT_SUFFIXES]
    return result


def test_no_secrets_in_repository() -> None:
    found = []
    for path in _files():
        text = path.read_text("utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                found.append(f"{path.relative_to(SERVER)}: {pattern.pattern[:30]}")
    assert found == [], "похоже на ключ в репозитории: " + "; ".join(found)


def test_env_example_has_no_values_for_secrets() -> None:
    example = (SERVER / ".env.example").read_text("utf-8")
    secrets = (
        "VK_SERVICE_TOKEN",
        "MAXSTAT_TOKEN",
        "LLM_API_KEY",
        "EMBEDDINGS_TOKEN",
        "POSTGRES_PASSWORD",
    )
    for line in example.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() in secrets:
            assert value.strip() == "", f"{name}: в .env.example значения ключей не пишем"
    for name in (*secrets, "OLLAMA_URL", "DATABASE_URL"):
        assert re.search(rf"^{name}=", example, re.MULTILINE), f"{name} нет в .env.example"


def test_blank_values_in_env_mean_not_set(tmp_path: Path) -> None:
    from pydantic import SecretStr

    from mediamonitor.settings import DEFAULT_DATABASE_URL, Settings

    env = tmp_path / ".env"
    env.write_text(
        "VK_SERVICE_TOKEN=\nMAXSTAT_TOKEN=  \nLLM_API_KEY=\nOLLAMA_URL=\nDATABASE_URL=\n", "utf-8"
    )
    settings = Settings(_env_file=str(env))
    assert settings.vk_service_token is None
    assert settings.maxstat_token is None
    assert settings.llm_api_key is None
    assert settings.ollama_url is None
    assert settings.database_url == DEFAULT_DATABASE_URL
    filled = Settings(_env_file=None, vk_service_token=SecretStr("секрет-для-проверки"))
    assert "секрет-для-проверки" not in repr(filled)  # ключ не попадает в логи
