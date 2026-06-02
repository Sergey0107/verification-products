"""add product_model to analysis

Revision ID: c9f5e2b1a7d3
Revises: b8e4f1a2c3d4
Create Date: 2026-06-02 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9f5e2b1a7d3"
down_revision: Union[str, Sequence[str], None] = "b8e4f1a2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis",
        sa.Column("product_model", sa.String(), nullable=True),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("analysis", "product_model", schema="analysis")
