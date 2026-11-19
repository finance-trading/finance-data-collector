"""Persist company quality score snapshots.

Revision ID: 0010
Revises: 0009
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from fdc.models import UtcDateTime

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company_quality_score",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot_id", sa.String(255), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("cik", sa.String(10)),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("sector", sa.String(128)),
        sa.Column("rating_cutoff", sa.Date(), nullable=False),
        sa.Column("calculated_at", UtcDateTime(), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("semantic_policy", sa.String(128), nullable=False),
        sa.Column("source_facts_sha256", sa.String(64)),
        sa.Column("quality_score", sa.Numeric(24, 6)),
        sa.Column("score_available", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("dimension_count", sa.Integer()),
        sa.Column("peer_count", sa.Integer()),
        sa.Column("period_ends", sa.JSON()),
        sa.Column("revenue_growth_dimension", sa.Numeric(24, 6)),
        sa.Column("operating_margin_dimension", sa.Numeric(24, 6)),
        sa.Column("cash_conversion_dimension", sa.Numeric(24, 6)),
        sa.Column("capital_efficiency_dimension", sa.Numeric(24, 6)),
        sa.Column("financial_strength_dimension", sa.Numeric(24, 6)),
        sa.Column("unknown_reasons", sa.JSON(), nullable=False),
        sa.Column("v2_hard_status", sa.String(32)),
        sa.Column("v2_unknown_reasons", sa.JSON(), nullable=False),
        sa.Column("v2_hard_gate_count", sa.Integer()),
        sa.Column("v2_hard_gate_total", sa.Integer()),
        sa.Column("v2_net_debt_ebitda", sa.Numeric(30, 6)),
        sa.Column("v2_interest_coverage", sa.Numeric(30, 6)),
        sa.Column("v2_cumulative_net_income", sa.Numeric(30, 6)),
        sa.Column("v2_cumulative_cfo", sa.Numeric(30, 6)),
        sa.Column("v2_positive_operating_income_years", sa.Integer()),
        sa.Column("v2_positive_cfo_years", sa.Integer()),
        sa.UniqueConstraint("snapshot_id", "ticker", name="uq_company_quality_score_snapshot_id_ticker"),
    )
    op.create_index("ix_company_quality_score_ticker_calculated_at", "company_quality_score", ["ticker", "calculated_at"])
    op.create_index("ix_company_quality_score_snapshot_id", "company_quality_score", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_company_quality_score_snapshot_id", table_name="company_quality_score")
    op.drop_index("ix_company_quality_score_ticker_calculated_at", table_name="company_quality_score")
    op.drop_table("company_quality_score")
