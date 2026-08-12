"""add external_job_id to extraction_job

Async-режим для backend yandex_vision_ocr (paddleocr-vl-service возвращает
202+job_id сразу вместо ожидания всей обработки в одном HTTP-запросе, см.
job_queue.py на стороне paddleocr-vl-service) — external_job_id сопоставляет
входящий callback на /internal/extraction-callback с нужной строкой
extraction_job, и позволяет fallback-поллингу спросить статус напрямую, если
callback потерялся.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "extraction_job",
        sa.Column("external_job_id", sa.String(), nullable=True),
        schema="analysis",
    )
    op.create_index(
        "ix_extraction_job_external_job_id",
        "extraction_job",
        ["external_job_id"],
        schema="analysis",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extraction_job_external_job_id",
        table_name="extraction_job",
        schema="analysis",
    )
    op.drop_column("extraction_job", "external_job_id", schema="analysis")
