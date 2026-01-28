from sqlalchemy import Column, String, DateTime, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    __tablename__ = "user"
    __table_args__ = {"schema": "users"}

    id = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    login = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
