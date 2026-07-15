"""add passport_value_candidates to comparison_row

Revision ID: f8a9b0c1d2e3
Revises: d5e6f7a8b9c0
Create Date: 2026-07-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_row",
        sa.Column(
            "passport_value_candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("comparison_row", "passport_value_candidates", schema="analysis")
