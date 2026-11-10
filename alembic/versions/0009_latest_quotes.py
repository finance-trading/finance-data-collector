from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "latest_quote",
        sa.Column("ticker", sa.String(32), primary_key=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )
    op.create_table(
        "quote_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("quote_metadata")
    op.drop_table("latest_quote")
