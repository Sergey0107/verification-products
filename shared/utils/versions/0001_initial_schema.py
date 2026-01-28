"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-01-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # =========================
    # EXTENSIONS
    # =========================
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # =========================
    # SCHEMAS
    # =========================
    op.execute("CREATE SCHEMA IF NOT EXISTS users")
    op.execute("CREATE SCHEMA IF NOT EXISTS files")
    op.execute("CREATE SCHEMA IF NOT EXISTS analysis")
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")

    # =========================
    # USERS
    # =========================
    op.create_table(
        "user",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("login", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="users",
    )

    # =========================
    # FILES
    # =========================
    op.create_table(
        "file",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False),
        sa.Column("original_name", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String()),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column(
            "uploaded_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="files",
    )

    # =========================
    # ANALYSIS
    # =========================
    op.create_table(
        "analysis",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="analysis",
    )

    op.create_table(
        "comparison_row",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("characteristic", sa.String(), nullable=False),
        sa.Column("tz_value", postgresql.JSONB()),
        sa.Column("passport_value", postgresql.JSONB()),
        sa.Column("llm_result", sa.Boolean()),
        sa.Column("user_result", sa.Boolean()),
        sa.Column("source", sa.String()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="analysis",
    )

    op.create_table(
        "user_edit",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("comparison_row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("old_value", postgresql.JSONB()),
        sa.Column("new_value", postgresql.JSONB()),
        sa.Column(
            "edited_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="analysis",
    )

    # =========================
    # KNOWLEDGE
    # =========================
    op.create_table(
        "knowledge_entry",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="knowledge",
    )


def downgrade():
    # Drop tables (reverse order!)
    op.drop_table("knowledge_entry", schema="knowledge")

    op.drop_table("user_edit", schema="analysis")
    op.drop_table("comparison_row", schema="analysis")
    op.drop_table("analysis", schema="analysis")

    op.drop_table("file", schema="files")

    op.drop_table("user", schema="users")

    # Drop schemas
    op.execute("DROP SCHEMA IF EXISTS knowledge CASCADE")
    op.execute("DROP SCHEMA IF EXISTS analysis CASCADE")
    op.execute("DROP SCHEMA IF EXISTS files CASCADE")
    op.execute("DROP SCHEMA IF EXISTS users CASCADE")

    # Extensions intentionally NOT dropped
