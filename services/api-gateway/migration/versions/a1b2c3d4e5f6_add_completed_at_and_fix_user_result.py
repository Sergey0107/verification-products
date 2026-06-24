"""add completed_at to analysis, change user_result default to null

Revision ID: a1b2c3d4e5f6
Revises: f7b3c1d9e2a4
Create Date: 2026-06-24 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f7b3c1d9e2a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis",
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        schema="analysis",
    )
    op.alter_column(
        "comparison_row",
        "user_result",
        server_default=None,
        schema="analysis",
    )
    op.execute(
        "UPDATE analysis.comparison_row SET user_result = NULL "
        "WHERE id NOT IN ("
        "  SELECT DISTINCT comparison_row_id FROM analysis.user_edit "
        "  WHERE user_result IS NOT NULL"
        ")"
    )
    op.execute(
        "UPDATE analysis.analysis SET completed_at = updated_at "
        "WHERE status IN ('ready', 'tz_review', 'failed')"
    )


def downgrade() -> None:
    op.alter_column(
        "comparison_row",
        "user_result",
        server_default=sa.text("true"),
        schema="analysis",
    )
    op.drop_column("analysis", "completed_at", schema="analysis")
