"""update comparison row fields

Revision ID: b1c2d3e4f5a6
Revises: 9a8b2c1f4d3e
Create Date: 2026-02-03 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "9a8b2c1f4d3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("comparison_row", sa.Column("tz_quote", sa.Text(), nullable=True), schema="analysis")
    op.add_column("comparison_row", sa.Column("passport_quote", sa.Text(), nullable=True), schema="analysis")
    op.add_column("comparison_row", sa.Column("note", sa.String(), nullable=True), schema="analysis")
    op.execute(
        "ALTER TABLE analysis.comparison_row "
        "ALTER COLUMN tz_value TYPE TEXT USING tz_value::text"
    )
    op.execute(
        "ALTER TABLE analysis.comparison_row "
        "ALTER COLUMN passport_value TYPE TEXT USING passport_value::text"
    )
    op.drop_column("comparison_row", "source", schema="analysis")


def downgrade() -> None:
    op.add_column("comparison_row", sa.Column("source", sa.String(), nullable=True), schema="analysis")
    op.execute(
        "ALTER TABLE analysis.comparison_row "
        "ALTER COLUMN tz_value TYPE JSONB USING tz_value::jsonb"
    )
    op.execute(
        "ALTER TABLE analysis.comparison_row "
        "ALTER COLUMN passport_value TYPE JSONB USING passport_value::jsonb"
    )
    op.drop_column("comparison_row", "note", schema="analysis")
    op.drop_column("comparison_row", "passport_quote", schema="analysis")
    op.drop_column("comparison_row", "tz_quote", schema="analysis")
