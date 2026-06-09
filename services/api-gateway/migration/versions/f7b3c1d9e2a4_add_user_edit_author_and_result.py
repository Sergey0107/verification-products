"""add user_id and user_result to user_edit

Revision ID: f7b3c1d9e2a4
Revises: d1e2f3a4b5c6
Create Date: 2026-06-08 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "f7b3c1d9e2a4"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_edit",
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        schema="analysis",
    )
    op.add_column(
        "user_edit",
        sa.Column("user_result", sa.Boolean(), nullable=True),
        schema="analysis",
    )
    op.create_foreign_key(
        "fk_user_edit_user_id",
        source_table="user_edit",
        referent_table="user",
        local_cols=["user_id"],
        remote_cols=["id"],
        source_schema="analysis",
        referent_schema="users",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_user_edit_user_id", "user_edit", schema="analysis", type_="foreignkey"
    )
    op.drop_column("user_edit", "user_result", schema="analysis")
    op.drop_column("user_edit", "user_id", schema="analysis")
