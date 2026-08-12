"""add tz_product_name to comparison_row

Revision ID: 50f33df1ffbc
Revises: e7f8a9b0c1d2
Create Date: 2026-08-11 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "50f33df1ffbc"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_row",
        sa.Column("tz_product_name", sa.String(), nullable=True),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("comparison_row", "tz_product_name", schema="analysis")
