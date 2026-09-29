"""Expand variable parser payload fields to unbounded text.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("evidence_locator", "locator_value", 1024),
    ("extracted_table", "caption", 512),
    ("xbrl_fact", "unit", 32),
    ("statement_line", "unit", 32),
)


def upgrade() -> None:
    for table, column, length in _COLUMNS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.String(length=length),
                type_=sa.Text(),
                existing_nullable=True,
            )


def downgrade() -> None:
    for table, column, length in reversed(_COLUMNS):
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.Text(),
                type_=sa.String(length=length),
                existing_nullable=True,
            )
