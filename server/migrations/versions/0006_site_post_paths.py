"""Ключ статьи сайта СМИ — путь страницы: `publications.post_id` до 300 знаков.

У VK, OK и MAX номер поста короткий, а у сайтов СМИ края ключ публикации — путь статьи
(`news/<адрес-из-заголовка>/`, ТЗ-Ф17). Полный ключ `publications.id` остаётся в 300 знаках:
длиннее нормализация не пропускает (`services/normalize_post.py`).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publications") as batch:
        batch.alter_column(
            "post_id",
            existing_type=sa.String(length=100),
            type_=sa.String(length=300),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("publications") as batch:
        batch.alter_column(
            "post_id",
            existing_type=sa.String(length=300),
            type_=sa.String(length=100),
            existing_nullable=False,
        )
