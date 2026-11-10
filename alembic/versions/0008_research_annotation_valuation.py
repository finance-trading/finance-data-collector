"""add intrinsic_value and 3-scenario prices to research_annotation

Revision ID: 0008
Revises: 0007

Model-derived forward value and three scenario prices per share (Bear/Base/Bull),
written only by the local read/write API alongside the price bands.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("research_annotation", sa.Column("intrinsic_value", sa.Float(), nullable=True))
    op.add_column("research_annotation", sa.Column("scen_bear", sa.Float(), nullable=True))
    op.add_column("research_annotation", sa.Column("scen_base", sa.Float(), nullable=True))
    op.add_column("research_annotation", sa.Column("scen_bull", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("research_annotation", "scen_bull")
    op.drop_column("research_annotation", "scen_base")
    op.drop_column("research_annotation", "scen_bear")
    op.drop_column("research_annotation", "intrinsic_value")
