from sqlalchemy import Column, String, DateTime, ForeignKey, text
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


class UserSession(Base):
    __tablename__ = "session"
    __table_args__ = {"schema": "users"}

    id = Column(UUID, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID, ForeignKey("users.user.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    csrf_token_hash = Column(String(64), nullable=False)
    user_agent = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
