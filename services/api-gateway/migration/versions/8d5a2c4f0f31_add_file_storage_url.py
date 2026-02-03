"""add file storage url

Revision ID: 8d5a2c4f0f31
Revises: 3e1b6b9f1a9d
Create Date: 2026-02-03 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8d5a2c4f0f31"
down_revision: Union[str, Sequence[str], None] = "3e1b6b9f1a9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "file",
        sa.Column("storage_url", sa.String(), nullable=True),
        schema="files",
    )


def downgrade() -> None:
    op.drop_column("file", "storage_url", schema="files")
