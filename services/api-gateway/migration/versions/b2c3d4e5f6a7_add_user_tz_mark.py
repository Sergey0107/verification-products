"""add user_tz_mark to comparison_row

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-24 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_row",
        sa.Column("user_tz_mark", JSONB(), nullable=True),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("comparison_row", "user_tz_mark", schema="analysis")
