"""add is_target_model to comparison_row

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-07-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_row",
        sa.Column("is_target_model", sa.Boolean(), nullable=True),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("comparison_row", "is_target_model", schema="analysis")
