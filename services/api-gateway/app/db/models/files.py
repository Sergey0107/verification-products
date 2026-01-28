from sqlalchemy import Column, String, BigInteger, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.db.base import Base


class File(Base):
    __tablename__ = "file"
    __table_args__ = {"schema": "files"}

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    file_type = Column(String, nullable=False)
    original_name = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    mime_type = Column(String)
    size_bytes = Column(BigInteger)
    uploaded_at = Column(DateTime, server_default=func.now(), nullable=False)


__all__ = ["File"]