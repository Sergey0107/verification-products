"""add manual_characteristic table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-07 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manual_characteristic",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("linked_characteristic_id", sa.String(), nullable=True),
        sa.Column("product_name", sa.String(), server_default=sa.text("'Ручной ввод'"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bbox_units", sa.String(), server_default=sa.text("'normalized'"), nullable=False),
        sa.Column("created_by", postgresql.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.user.id"]),
        schema="analysis",
    )
    op.create_index(
        "ix_manual_characteristic_analysis_document",
        "manual_characteristic",
        ["analysis_id", "document_type"],
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manual_characteristic_analysis_document",
        table_name="manual_characteristic",
        schema="analysis",
    )
    op.drop_table("manual_characteristic", schema="analysis")
