"""add comparison row evidence

Revision ID: d4e5f6a7b8c9
Revises: 3b6f9c2a1d7e
Create Date: 2026-04-08 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "3b6f9c2a1d7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_row",
        sa.Column("tz_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="analysis",
    )
    op.add_column(
        "comparison_row",
        sa.Column("passport_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("comparison_row", "passport_evidence", schema="analysis")
    op.drop_column("comparison_row", "tz_evidence", schema="analysis")
