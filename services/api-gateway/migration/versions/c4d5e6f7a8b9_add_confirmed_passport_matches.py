"""add confirmed_passport_matches to comparison_row

Оператор подтверждает, какие из найденных в паспорте вхождений действительно
относятся к требованию ТЗ, когда характеристика встречается в нескольких
местах. NULL — выбор ещё не делали.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comparison_row",
        sa.Column("confirmed_passport_matches", postgresql.JSONB(), nullable=True),
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_column(
        "comparison_row",
        "confirmed_passport_matches",
        schema="analysis",
    )
