"""Migrate the AI company catalog, funnel overrides and quality inputs to DB.

Revision ID: 0014
Revises: 0013
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from fdc.models import UtcDateTime

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: None | Sequence[str] = None
depends_on: None | Sequence[str] = None


def upgrade() -> None:
    op.create_table(
        "ai_layer",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("name_en", sa.String(128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "ai_segment",
        sa.Column("layer_id", sa.String(32), sa.ForeignKey("ai_layer.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "ai_company",
        sa.Column("ticker", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sector", sa.String(128), nullable=False),
        sa.Column("industry", sa.String(128), nullable=False),
        sa.Column("layer_id", sa.String(32), sa.ForeignKey("ai_layer.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("segment", sa.String(128), nullable=False),
        sa.Column("also_in", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["layer_id", "segment"],
            ["ai_segment.layer_id", "ai_segment.name"],
            name="fk_ai_company_layer_id_segment_ai_segment",
        ),
    )
    op.create_index("ix_ai_company_layer_id", "ai_company", ["layer_id"])
    op.create_table(
        "funnel_override",
        sa.Column("ticker", sa.String(32), primary_key=True),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.CheckConstraint("tier in (1, 2, 3)", name="ck_funnel_override_tier_in_1_2_3"),
    )
    op.create_table(
        "quality_input_batch",
        sa.Column("id", sa.String(512), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("rating_cutoff", sa.Date()),
        sa.Column("rule_version", sa.String(64)),
        sa.Column("semantic_policy", sa.String(128)),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint("kind", "source", "sha256", name="uq_quality_input_batch_kind_source_sha256"),
    )
    op.create_table(
        "quality_annual_fact",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.String(512), sa.ForeignKey("quality_input_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("concept", sa.String(255), nullable=False),
        sa.Column("label", sa.String(512)),
        sa.Column("value", sa.Numeric(100, 30)),
        sa.Column("numeric_value", sa.Numeric(100, 30)),
        sa.Column("unit", sa.String(32)),
        sa.Column("period_type", sa.String(16)),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("fiscal_year", sa.Integer()),
        sa.Column("fiscal_period", sa.String(16)),
        sa.Column("accession", sa.String(32)),
        sa.Column("filing_date", sa.Date()),
        sa.Column("form_type", sa.String(16)),
        sa.Column("statement_type", sa.String(32)),
        sa.Column("taxonomy", sa.String(32)),
        sa.Column("scale", sa.String(32)),
        sa.Column("data_quality", sa.String(32)),
        sa.Column("is_audited", sa.Boolean()),
        sa.Column("confidence_score", sa.Numeric(100, 30)),
        sa.Column("period_days", sa.Integer()),
        sa.Column("period_shape", sa.String(16)),
        sa.Column("metric", sa.String(64)),
    )
    op.create_index(
        "ix_quality_annual_fact_batch_cik_metric_end",
        "quality_annual_fact",
        ["batch_id", "cik", "metric", "period_end"],
    )
    op.create_table(
        "quality_peer",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.String(512), sa.ForeignKey("quality_input_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_symbol", sa.String(32)),
        sa.Column("canonical_symbol", sa.String(32)),
        sa.Column("company_name", sa.String(255)),
        sa.Column("gics_sector", sa.String(64)),
        sa.Column("gics_sub_industry", sa.String(128)),
        sa.Column("cik", sa.String(10)),
        sa.Column("date_added", sa.Date()),
    )
    op.create_index("ix_quality_peer_batch_id", "quality_peer", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_quality_peer_batch_id", table_name="quality_peer")
    op.drop_table("quality_peer")
    op.drop_index("ix_quality_annual_fact_batch_cik_metric_end", table_name="quality_annual_fact")
    op.drop_table("quality_annual_fact")
    op.drop_table("quality_input_batch")
    op.drop_table("funnel_override")
    op.drop_index("ix_ai_company_layer_id", table_name="ai_company")
    op.drop_table("ai_company")
    op.drop_table("ai_segment")
    op.drop_table("ai_layer")
