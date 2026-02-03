"""add comment to user_edit and default user_result

Revision ID: 7f2c9d1a4e8b
Revises: b1c2d3e4f5a6
Create Date: 2026-02-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "7f2c9d1a4e8b"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_edit",
        sa.Column("comment", sa.Text(), nullable=True),
        schema="analysis",
    )
    op.execute(
        "UPDATE analysis.comparison_row SET user_result = true WHERE user_result IS NULL"
    )
    op.alter_column(
        "comparison_row",
        "user_result",
        server_default=sa.text("true"),
        existing_type=sa.Boolean(),
        schema="analysis",
    )


def downgrade() -> None:
    op.alter_column(
        "comparison_row",
        "user_result",
        server_default=None,
        existing_type=sa.Boolean(),
        schema="analysis",
    )
    op.drop_column("user_edit", "comment", schema="analysis")
