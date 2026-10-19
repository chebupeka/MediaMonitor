"""Окружение Alembic: адрес базы — DATABASE_URL, модель — mediamonitor.db.models."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from mediamonitor.db.models import Base
from mediamonitor.settings import Settings

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def sync_url() -> str:
    """Адрес для миграций: из настройки Alembic (тесты) или из DATABASE_URL.

    Приложение ходит в базу асинхронно; миграции — синхронно тем же драйвером
    (psycopg 3 умеет оба режима), а для SQLite берём встроенный драйвер.
    """
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if not url:
        url = Settings().database_url
    return url.replace("sqlite+aiosqlite", "sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = sync_url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
