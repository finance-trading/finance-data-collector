"""preserve parse attempts and lossless financial decimals

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from fdc.models import ExactNumeric

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("filing_parse") as batch:
        batch.drop_constraint("uq_filing_parse_identity", type_="unique")
        batch.add_column(
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1")
        )
        batch.create_unique_constraint(
            "uq_filing_parse_identity",
            [
                "filing_id",
                "artifact_set_hash",
                "parser_version",
                "parser_modules_hash",
                "attempt_number",
            ],
        )

    with op.batch_alter_table("xbrl_fact") as batch:
        batch.alter_column(
            "value_numeric",
            existing_type=sa.Numeric(precision=38, scale=6),
            type_=ExactNumeric(),
            existing_nullable=True,
        )
    with op.batch_alter_table("statement_line") as batch:
        batch.alter_column(
            "value_numeric",
            existing_type=sa.Numeric(precision=38, scale=6),
            type_=ExactNumeric(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("statement_line") as batch:
        batch.alter_column(
            "value_numeric",
            existing_type=ExactNumeric(),
            type_=sa.Numeric(precision=38, scale=6),
            existing_nullable=True,
        )
    with op.batch_alter_table("xbrl_fact") as batch:
        batch.alter_column(
            "value_numeric",
            existing_type=ExactNumeric(),
            type_=sa.Numeric(precision=38, scale=6),
            existing_nullable=True,
        )
    with op.batch_alter_table("filing_parse") as batch:
        batch.drop_constraint("uq_filing_parse_identity", type_="unique")
        batch.drop_column("attempt_number")
        batch.create_unique_constraint(
            "uq_filing_parse_identity",
            ["filing_id", "artifact_set_hash", "parser_version", "parser_modules_hash"],
        )
