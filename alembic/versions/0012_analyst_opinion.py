"""Store per-firm sell-side analyst opinions.

Revision ID: 0012
Revises: 0011
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from fdc.models import UtcDateTime

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyst_opinion",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("firm", sa.String(128), nullable=False),
        sa.Column("action_at", UtcDateTime(), nullable=False),
        sa.Column("action", sa.String(16)),
        sa.Column("from_grade", sa.String(32)),
        sa.Column("to_grade", sa.String(32)),
        sa.Column("price_target_action", sa.String(32)),
        sa.Column("price_target", sa.Numeric(18, 4)),
        sa.Column("prior_price_target", sa.Numeric(18, 4)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint("ticker", "firm", "action_at", name="uq_analyst_opinion_ticker_firm_action_at"),
    )
    op.create_index("ix_analyst_opinion_ticker_action_at", "analyst_opinion", ["ticker", "action_at"])


def downgrade() -> None:
    op.drop_index("ix_analyst_opinion_ticker_action_at", table_name="analyst_opinion")
    op.drop_table("analyst_opinion")
