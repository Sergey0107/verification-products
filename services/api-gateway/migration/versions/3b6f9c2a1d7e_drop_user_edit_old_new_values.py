"""drop old_value and new_value from user_edit

Revision ID: 3b6f9c2a1d7e
Revises: 7f2c9d1a4e8b
Create Date: 2026-02-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3b6f9c2a1d7e"
down_revision = "7f2c9d1a4e8b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("user_edit", "old_value", schema="analysis")
    op.drop_column("user_edit", "new_value", schema="analysis")


def downgrade() -> None:
    op.add_column(
        "user_edit",
        sa.Column("old_value", sa.JSON(), nullable=True),
        schema="analysis",
    )
    op.add_column(
        "user_edit",
        sa.Column("new_value", sa.JSON(), nullable=True),
        schema="analysis",
    )
