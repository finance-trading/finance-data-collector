"""add research_annotation for per-company editable research data

Revision ID: 0007
Revises: 0006

One row per ticker, written only by the local read/write API.  Holds the
price-action bands (observe / entry / add / reduce, each low–high) and the
ongoing watch items a reader wants to keep in front of them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from fdc.models import UtcDateTime

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_annotation",
        sa.Column("ticker", sa.String(length=8), nullable=False),
        sa.Column("observe_low", sa.Float(), nullable=True),
        sa.Column("observe_high", sa.Float(), nullable=True),
        sa.Column("entry_low", sa.Float(), nullable=True),
        sa.Column("entry_high", sa.Float(), nullable=True),
        sa.Column("add_low", sa.Float(), nullable=True),
        sa.Column("add_high", sa.Float(), nullable=True),
        sa.Column("reduce_low", sa.Float(), nullable=True),
        sa.Column("reduce_high", sa.Float(), nullable=True),
        sa.Column("watch_items", sa.JSON(), nullable=False),
        sa.Column("created_at", UtcDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", UtcDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ticker", name=op.f("pk_research_annotation")),
    )


def downgrade() -> None:
    op.drop_table("research_annotation")
