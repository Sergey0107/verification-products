"""add indexes on analysis_id / comparison_row_id for hot lookup tables

Основные запросы просмотрщика (viewer-context, comparison rows, files по
анализу) фильтруют по analysis_id, но comparison_row, file и
manual_characteristic не имели ни PK, ни unique constraint на этой колонке —
только Seq Scan. comparison_job/extraction_result/extraction_job/
tz_characteristic_review/hidden_characteristic уже покрыты существующими
unique constraint (analysis_id — первая колонка), им новый индекс не нужен.

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_comparison_row_analysis_id",
        "comparison_row",
        ["analysis_id"],
        schema="analysis",
    )
    op.create_index(
        "ix_user_edit_comparison_row_id",
        "user_edit",
        ["comparison_row_id"],
        schema="analysis",
    )
    op.create_index(
        "ix_manual_characteristic_analysis_id",
        "manual_characteristic",
        ["analysis_id"],
        schema="analysis",
    )
    op.create_index(
        "ix_file_analysis_id",
        "file",
        ["analysis_id"],
        schema="files",
    )


def downgrade() -> None:
    op.drop_index("ix_file_analysis_id", table_name="file", schema="files")
    op.drop_index(
        "ix_manual_characteristic_analysis_id",
        table_name="manual_characteristic",
        schema="analysis",
    )
    op.drop_index(
        "ix_user_edit_comparison_row_id",
        table_name="user_edit",
        schema="analysis",
    )
    op.drop_index(
        "ix_comparison_row_analysis_id",
        table_name="comparison_row",
        schema="analysis",
    )
