"""index foreign-key columns used by parser cleanup and retention jobs

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEXES = (
    ("ix_filing_parse_parse_run_id", "filing_parse", ["parse_run_id"]),
    ("ix_xbrl_fact_evidence_filing", "xbrl_fact", ["evidence_locator_id", "source_filing_id"]),
    ("ix_statement_line_parse_run_id", "statement_line", ["parse_run_id"]),
    (
        "ix_statement_line_evidence_filing",
        "statement_line",
        ["evidence_locator_id", "source_filing_id"],
    ),
    ("ix_filing_section_parse_run_id", "filing_section", ["parse_run_id"]),
    (
        "ix_filing_section_evidence_filing",
        "filing_section",
        ["evidence_locator_id", "source_filing_id"],
    ),
    (
        "ix_extracted_table_evidence_filing",
        "extracted_table",
        ["evidence_locator_id", "source_filing_id"],
    ),
)


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        op.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({quoted_columns})')


def downgrade() -> None:
    for name, table, _columns in reversed(_INDEXES):
        op.execute(f'DROP INDEX IF EXISTS "{name}"')
