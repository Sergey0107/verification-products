"""add extraction jobs

Revision ID: 3e1b6b9f1a9d
Revises: c2f1b7a2c9d1
Create Date: 2026-02-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3e1b6b9f1a9d"
down_revision: Union[str, Sequence[str], None] = "c2f1b7a2c9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extraction_job",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(), nullable=False),
        sa.Column("file_id", postgresql.UUID(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "file_id", "file_type", name="uq_extraction_job"),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_table("extraction_job", schema="analysis")
