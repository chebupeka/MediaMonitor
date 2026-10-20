"""Счётчики открытого стенда на клиента за сутки: новые рабочие места с одного IP (НТ-6).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_daily_usage",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("client_hash", sa.String(length=64), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("kind", "client_hash", "day", name=op.f("pk_client_daily_usage")),
    )


def downgrade() -> None:
    op.drop_table("client_daily_usage")
