"""add file status and make uploaded_at nullable

Revision ID: c2f1b7a2c9d1
Revises: 70aac81f525f
Create Date: 2026-01-30
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c2f1b7a2c9d1"
down_revision = "70aac81f525f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file",
        sa.Column("status", sa.String(), nullable=False, server_default="uploading"),
        schema="files",
    )
    op.alter_column(
        "file",
        "uploaded_at",
        schema="files",
        server_default=None,
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "file",
        "uploaded_at",
        schema="files",
        server_default=sa.text("now()"),
        nullable=False,
    )
    op.drop_column("file", "status", schema="files")
