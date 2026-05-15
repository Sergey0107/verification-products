"""add standard sessions and analysis owner

Revision ID: f1a2b3c4d5e6
Revises: e6f7a8b9c0d1
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis", sa.Column("user_id", sa.UUID(), nullable=True), schema="analysis")
    op.create_foreign_key(
        "fk_analysis_user_id",
        "analysis",
        "user",
        ["user_id"],
        ["id"],
        source_schema="analysis",
        referent_schema="users",
    )
    op.create_index("ix_analysis_user_id", "analysis", ["user_id"], schema="analysis")
    op.execute(
        """
        UPDATE analysis.analysis
        SET user_id = (SELECT id FROM users."user" ORDER BY created_at ASC LIMIT 1)
        WHERE user_id IS NULL
          AND EXISTS (SELECT 1 FROM users."user")
        """
    )

    op.create_table(
        "session",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="users",
    )
    op.create_index("ix_users_session_user_id", "session", ["user_id"], schema="users")
    op.create_index("ix_users_session_token_hash", "session", ["token_hash"], unique=True, schema="users")


def downgrade() -> None:
    op.drop_index("ix_users_session_token_hash", table_name="session", schema="users")
    op.drop_index("ix_users_session_user_id", table_name="session", schema="users")
    op.drop_table("session", schema="users")

    op.drop_index("ix_analysis_user_id", table_name="analysis", schema="analysis")
    op.drop_constraint("fk_analysis_user_id", "analysis", schema="analysis", type_="foreignkey")
    op.drop_column("analysis", "user_id", schema="analysis")
