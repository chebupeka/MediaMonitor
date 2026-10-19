"""Начальная схема: рабочие места, источники, поиски, публикации, события, выгрузки.

Revision ID: 0001
Revises:
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")  # векторы смысла (Р5, шаг 2)
    op.create_table(
        "platform_sources",
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("owner_id", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("district", sa.String(length=200), nullable=True),
        sa.Column("subscribers", sa.Integer(), nullable=True),
        sa.Column("regional", sa.Boolean(), nullable=False),
        sa.Column("in_catalog", sa.Boolean(), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("last_post_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_sources")),
        sa.UniqueConstraint("platform", "owner_id", name=op.f("uq_platform_sources_platform")),
    )
    op.create_table(
        "quota_usage",
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("resets_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warned", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("platform", "period", name=op.f("pk_quota_usage")),
    )
    op.create_table(
        "stand_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stand_events")),
    )
    op.create_index(op.f("ix_stand_events_at"), "stand_events", ["at"], unique=False)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_workspaces_key_hash")),
    )
    op.create_table(
        "import_previews",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=40), nullable=False),
        sa.Column(
            "payload",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_import_previews_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_previews")),
    )
    op.create_index(
        op.f("ix_import_previews_workspace_id"), "import_previews", ["workspace_id"], unique=False
    )

    op.create_table(
        "publications",
        sa.Column("id", sa.String(length=300), nullable=False),
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("owner_id", sa.String(length=200), nullable=False),
        sa.Column("post_id", sa.String(length=100), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column(
            "merged_urls",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column(
            "sentences",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_reliability", sa.String(length=12), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column(
            "repost_of",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("has_media", sa.Boolean(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("reactions", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("link_state", sa.String(length=12), nullable=False),
        sa.Column("link_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "embedding",
            sa.JSON(none_as_null=True).with_variant(Vector(768), "postgresql"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["platform_sources.id"],
            name=op.f("fk_publications_source_id_platform_sources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publications")),
        sa.UniqueConstraint(
            "platform", "owner_id", "post_id", name=op.f("uq_publications_platform")
        ),
    )
    op.create_index(
        op.f("ix_publications_content_hash"), "publications", ["content_hash"], unique=False
    )
    op.create_index(
        op.f("ix_publications_published_at"), "publications", ["published_at"], unique=False
    )

    op.create_table(
        "searches",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=40), nullable=False),
        sa.Column(
            "request",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "conditions",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column(
            "topic",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "release",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("ai_available", sa.Boolean(), nullable=False),
        sa.Column(
            "notices",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("arrival_seq", sa.Integer(), nullable=False),
        sa.Column("event_seq", sa.Integer(), nullable=False),
        sa.Column("in_recent", sa.Boolean(), nullable=False),
        sa.Column("result_total", sa.Integer(), nullable=False),
        sa.Column("status_summary", sa.Text(), nullable=False),
        sa.Column(
            "error",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_searches_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_searches")),
    )
    op.create_index(op.f("ix_searches_phase"), "searches", ["phase"], unique=False)
    op.create_index(
        "ix_searches_workspace_created", "searches", ["workspace_id", "created_at"], unique=False
    )

    op.create_table(
        "workspace_sources",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("workspace_id", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("district", sa.String(length=200), nullable=True),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "check",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["platform_sources.id"],
            name=op.f("fk_workspace_sources_source_id_platform_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_sources_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_sources")),
        sa.UniqueConstraint(
            "workspace_id", "source_id", name=op.f("uq_workspace_sources_workspace_id")
        ),
    )
    op.create_index(
        op.f("ix_workspace_sources_workspace_id"),
        "workspace_sources",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "exports",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("search_id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=40), nullable=False),
        sa.Column(
            "options",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["searches.id"],
            name=op.f("fk_exports_search_id_searches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_exports_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exports")),
    )
    op.create_index(op.f("ix_exports_search_id"), "exports", ["search_id"], unique=False)

    op.create_table(
        "platform_runs",
        sa.Column("search_id", sa.String(length=40), nullable=False),
        sa.Column("platform", sa.String(length=8), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("done", sa.Float(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=10), nullable=False),
        sa.Column(
            "problem",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "cap",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("current_source", sa.String(length=500), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["searches.id"],
            name=op.f("fk_platform_runs_search_id_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("search_id", "platform", name=op.f("pk_platform_runs")),
    )
    op.create_table(
        "search_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("search_id", sa.String(length=40), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column(
            "payload",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["searches.id"],
            name=op.f("fk_search_events_search_id_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_events")),
        sa.UniqueConstraint("search_id", "seq", name=op.f("uq_search_events_search_id")),
    )
    op.create_table(
        "search_groups",
        sa.Column("search_id", sa.String(length=40), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("cluster", sa.String(length=100), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["searches.id"],
            name=op.f("fk_search_groups_search_id_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("search_id", "id", name=op.f("pk_search_groups")),
        sa.UniqueConstraint("search_id", "cluster", name=op.f("uq_search_groups_search_id")),
    )
    op.create_table(
        "search_items",
        sa.Column("search_id", sa.String(length=40), nullable=False),
        sa.Column("publication_id", sa.String(length=300), nullable=False),
        sa.Column("relevance", sa.String(length=10), nullable=False),
        sa.Column("method", sa.String(length=14), nullable=False),
        sa.Column("method_note", sa.Text(), nullable=True),
        sa.Column(
            "region_reason",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "excerpt",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "evidence",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("placement_type", sa.String(length=10), nullable=True),
        sa.Column("is_original", sa.Boolean(), nullable=False),
        sa.Column(
            "citation",
            sa.JSON(none_as_null=True).with_variant(
                postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("group_id", sa.String(length=64), nullable=True),
        sa.Column("cluster", sa.String(length=100), nullable=True),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column("arrival", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_search_items_publication_id_publications"),
        ),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["searches.id"],
            name=op.f("fk_search_items_search_id_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("search_id", "publication_id", name=op.f("pk_search_items")),
    )
    op.create_index(
        "ix_search_items_search_arrival", "search_items", ["search_id", "arrival"], unique=False
    )


def downgrade() -> None:
    op.drop_table("search_items")
    op.drop_table("search_groups")
    op.drop_table("search_events")
    op.drop_table("platform_runs")
    op.drop_table("exports")
    op.drop_table("workspace_sources")
    op.drop_table("searches")
    op.drop_table("publications")
    op.drop_table("import_previews")
    op.drop_table("workspaces")
    op.drop_table("stand_events")
    op.drop_table("quota_usage")
    op.drop_table("platform_sources")
