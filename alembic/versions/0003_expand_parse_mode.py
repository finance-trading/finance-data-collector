"""allow composed parser mode names

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("filing_parse") as batch:
        batch.alter_column(
            "parse_mode",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("filing_parse") as batch:
        batch.alter_column(
            "parse_mode",
            existing_type=sa.String(length=128),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
