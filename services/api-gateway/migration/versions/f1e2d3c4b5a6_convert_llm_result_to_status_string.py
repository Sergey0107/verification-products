"""convert comparison_row.llm_result from boolean is_match to status string

Revision ID: f1e2d3c4b5a6
Revises: 50f33df1ffbc
Create Date: 2026-08-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, Sequence[str], None] = "50f33df1ffbc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_row",
        sa.Column("llm_result_status", sa.String(), nullable=True),
        schema="analysis",
    )
    # is_match=true -> confident, is_match=false -> not_found (недостающие
    # пары LLM-ответа дозаполнялись false и по смыслу соответствуют
    # not_found), NULL остаётся NULL (сравнение не выполнялось).
    op.execute(
        """
        UPDATE analysis.comparison_row
        SET llm_result_status = CASE
            WHEN llm_result IS TRUE THEN 'confident'
            WHEN llm_result IS FALSE THEN 'not_found'
            ELSE NULL
        END
        """
    )
    op.drop_column("comparison_row", "llm_result", schema="analysis")
    op.alter_column(
        "comparison_row",
        "llm_result_status",
        new_column_name="llm_result",
        schema="analysis",
    )


def downgrade() -> None:
    op.add_column(
        "comparison_row",
        sa.Column("llm_result_bool", sa.Boolean(), nullable=True),
        schema="analysis",
    )
    op.execute(
        """
        UPDATE analysis.comparison_row
        SET llm_result_bool = CASE
            WHEN llm_result = 'confident' THEN TRUE
            WHEN llm_result IN ('uncertain', 'not_found') THEN FALSE
            ELSE NULL
        END
        """
    )
    op.drop_column("comparison_row", "llm_result", schema="analysis")
    op.alter_column(
        "comparison_row",
        "llm_result_bool",
        new_column_name="llm_result",
        schema="analysis",
    )
