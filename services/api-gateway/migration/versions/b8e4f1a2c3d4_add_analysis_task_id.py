"""add task_id to analysis

Revision ID: b8e4f1a2c3d4
Revises: a7c9d2e4f6b1
Create Date: 2026-06-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8e4f1a2c3d4"
down_revision: Union[str, Sequence[str], None] = "a7c9d2e4f6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis",
        sa.Column("task_id", sa.String(), nullable=True),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("analysis", "task_id", schema="analysis")
