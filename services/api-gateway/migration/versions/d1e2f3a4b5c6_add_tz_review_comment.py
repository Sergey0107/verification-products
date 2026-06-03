"""add comment to tz_characteristic_review

Revision ID: d1e2f3a4b5c6
Revises: c9f5e2b1a7d3
Create Date: 2026-06-02 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c9f5e2b1a7d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tz_characteristic_review",
        sa.Column("comment", sa.Text(), nullable=True),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("tz_characteristic_review", "comment", schema="analysis")
