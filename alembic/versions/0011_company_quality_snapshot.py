"""Reserve each quality scoring run with a database-unique ID."""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company_quality_snapshot",
        sa.Column("snapshot_id", sa.String(255), primary_key=True),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        "INSERT INTO company_quality_snapshot (snapshot_id, calculated_at) "
        "SELECT snapshot_id, MIN(calculated_at) FROM company_quality_score GROUP BY snapshot_id"
    )


def downgrade() -> None:
    op.drop_table("company_quality_snapshot")
