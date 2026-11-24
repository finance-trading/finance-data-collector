"""Persist collected news and broad-market index snapshots.

Revision ID: 0013
Revises: 0012
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from fdc.models import UtcDateTime

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_item",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("published_at", UtcDateTime()),
        sa.Column("collected_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_news_item_source_external_id"),
    )
    op.create_index("ix_news_item_published_at", "news_item", ["published_at"])
    op.create_table(
        "market_quote",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_quote")
    op.drop_index("ix_news_item_published_at", table_name="news_item")
    op.drop_table("news_item")
