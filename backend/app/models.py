from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB, UUID

Base = declarative_base()

class ScheduleType(str, Enum):
    """Schedule type enumeration"""
    CLASS = "CLASS"          # Lịch học
    DEADLINE = "DEADLINE"    # Hạn nộp bài
    EXAM = "EXAM"            # Lịch thi
    PERSONAL = "PERSONAL"    # Cá nhân


class User(Base):
    """User model for authentication and ownership"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RefreshToken(Base):
    """Persisted refresh token metadata for rotation and logout revocation."""
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    jti = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class AuthorizationCode(Base):
    """One-time authorization code for OAuth2 Authorization Code + PKCE."""
    __tablename__ = "authorization_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    code_hash = Column(String(255), nullable=False, unique=True, index=True)
    client_id = Column(String(255), nullable=False)
    redirect_uri = Column(String(1000), nullable=False)
    code_challenge = Column(String(255), nullable=False)
    code_challenge_method = Column(String(10), nullable=False, default="S256")
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Schedule(Base):
    """Schedule/Event model"""
    __tablename__ = "schedules"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    type = Column(SQLEnum(ScheduleType), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    location = Column(String(255), nullable=True)  # Optional: classroom or meeting link
    description = Column(String(1000), nullable=True)  # Optional: notes
    is_completed = Column(Boolean, default=False)  # For DEADLINE type
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Schedule(id={self.id}, title={self.title}, type={self.type})>"


class Note(Base):
    __tablename__ = "notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    content = Column(Text, nullable=False)
    content_type = Column(String(20), nullable=False, default="markdown", server_default=text("'markdown'"))
    position = Column(
        JSONB,
        nullable=False,
        default=lambda: {"x": 0, "y": 0},
        server_default=text("jsonb_build_object('x', 0, 'y', 0)"),
    )
    size = Column(
        JSONB,
        nullable=False,
        default=lambda: {"width": 200, "height": 200},
        server_default=text("jsonb_build_object('width', 200, 'height', 200)"),
    )
    style = Column(
        JSONB,
        nullable=False,
        default=lambda: {"color": "yellow"},
        server_default=text("jsonb_build_object('color', 'yellow')"),
    )
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    is_deleted = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_notes_user_id", "user_id"),
        Index("ix_notes_user_id_updated_at", "user_id", "updated_at"),
    )
