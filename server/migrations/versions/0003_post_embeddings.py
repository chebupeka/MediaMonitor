"""Кэш векторов смысла по посту и версии модели (п. 45): вместо колонки publications.embedding.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VECTOR = sa.JSON(none_as_null=True).with_variant(Vector(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "post_embeddings",
        sa.Column("publication_id", sa.String(length=300), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text_key", sa.String(length=64), nullable=False),
        sa.Column("vector", VECTOR, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_post_embeddings_publication_id_publications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("publication_id", "model", "kind", name=op.f("pk_post_embeddings")),
    )
    with op.batch_alter_table("publications") as batch_op:
        batch_op.drop_column("embedding")


def downgrade() -> None:
    with op.batch_alter_table("publications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "embedding",
                sa.JSON(none_as_null=True).with_variant(Vector(768), "postgresql"),
                nullable=True,
            )
        )
    op.drop_table("post_embeddings")
