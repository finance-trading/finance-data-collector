"""index statement_line.filing_parse_id for the read path

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        'CREATE INDEX IF NOT EXISTS "ix_statement_line_filing_parse_id" '
        'ON "statement_line" ("filing_parse_id")'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS "ix_statement_line_filing_parse_id"')