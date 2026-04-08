"""add analysis extraction backend

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-04-08 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis",
        sa.Column("extraction_backend", sa.String(), nullable=False, server_default="openrouter"),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column("analysis", "extraction_backend", schema="analysis")
