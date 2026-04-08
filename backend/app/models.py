from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB, UUID

Base = declarative_base()

class ScheduleType(str, Enum):
    """Schedule type enumeration"""
    CLASS = "CLASS"          # Lịch học
    DEADLINE = "DEADLINE"    # Hạn nộp bài
    EXAM = "EXAM"            # Lịch thi
    PERSONAL = "PERSONAL"    # Cá nhân


class CalendarProvider(str, Enum):
    """Supported external calendar providers."""
    GOOGLE = "GOOGLE"


class SyncSource(str, Enum):
    """Identify which side produced the latest change."""
    INTERNAL = "INTERNAL"
    PROVIDER = "PROVIDER"


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


class CalendarConnection(Base):
    """Per-user external calendar connection state and sync cursor."""
    __tablename__ = "calendar_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(SQLEnum(CalendarProvider), nullable=False, default=CalendarProvider.GOOGLE)
    provider_calendar_id = Column(String(255), nullable=False, default="primary", server_default=text("'primary'"))
    refresh_token_encrypted = Column(Text, nullable=False)
    access_token_encrypted = Column(Text, nullable=True)
    access_token_expires_at = Column(DateTime, nullable=True)
    granted_scopes = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    sync_token = Column(Text, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_error = Column(Text, nullable=True)
    channel_id = Column(String(64), nullable=True)
    channel_resource_id = Column(String(255), nullable=True)
    channel_expiration = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "provider", "provider_calendar_id", name="uq_calendar_connections_user_provider_calendar"),
        Index("ix_calendar_connections_provider_last_synced_at", "provider", "last_synced_at"),
    )


class ScheduleExternalMap(Base):
    """Mapping between internal schedules and external provider events."""
    __tablename__ = "schedule_external_maps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(SQLEnum(CalendarProvider), nullable=False, default=CalendarProvider.GOOGLE)
    provider_calendar_id = Column(String(255), nullable=False, default="primary", server_default=text("'primary'"))
    provider_event_id = Column(String(1024), nullable=False)
    provider_etag = Column(String(255), nullable=True)
    provider_updated_at = Column(DateTime, nullable=True)
    last_sync_source = Column(SQLEnum(SyncSource), nullable=False, default=SyncSource.INTERNAL)
    last_synced_at = Column(DateTime, nullable=True)
    is_deleted_remote = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("schedule_id", "provider", name="uq_schedule_external_maps_schedule_provider"),
        UniqueConstraint("provider", "provider_calendar_id", "provider_event_id", name="uq_schedule_external_maps_provider_event"),
        Index("ix_schedule_external_maps_user_provider", "user_id", "provider"),
        Index("ix_schedule_external_maps_provider_event_id", "provider_event_id"),
    )


class OAuthState(Base):
    """One-time state values for external OAuth callbacks."""
    __tablename__ = "oauth_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(SQLEnum(CalendarProvider), nullable=False, default=CalendarProvider.GOOGLE)
    state_hash = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_oauth_states_provider_expires_at", "provider", "expires_at"),
    )


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
