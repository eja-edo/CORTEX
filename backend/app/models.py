from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID

Base = declarative_base()


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    """Persist enum .value labels to match existing PostgreSQL enum types."""
    return [member.value for member in enum_cls]

class ScheduleType(str, Enum):
    """Schedule type enumeration"""
    CLASS = "CLASS"          # Lịch học
    DEADLINE = "DEADLINE"    # Hạn nộp bài
    EXAM = "EXAM"            # Lịch thi
    PERSONAL = "PERSONAL"    # Cá nhân
    CRON_EVENT = "CRON_EVENT"  # Workflow cron schedule (liên kết với workflow)


class CalendarProvider(str, Enum):
    """Supported external calendar providers."""
    GOOGLE = "GOOGLE"


class SyncSource(str, Enum):
    """Identify which side produced the latest change."""
    INTERNAL = "INTERNAL"
    PROVIDER = "PROVIDER"


class RecurrenceFreq(str, Enum):
    """Recurrence frequency enumeration."""
    NONE = "NONE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class ReminderMethod(str, Enum):
    """Reminder notification method."""
    PUSH = "push"
    EMAIL = "email"


class ReminderStatus(str, Enum):
    """Reminder lifecycle status."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SyncOperation(str, Enum):
    """Sync queue operation type."""
    UPSERT = "UPSERT"
    DELETE = "DELETE"


class SyncQueueStatus(str, Enum):
    """Sync queue item status."""
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class EditScope(str, Enum):
    """Edit scope for recurring event instances."""
    THIS_ONLY = "this_only"
    THIS_AND_AFTER = "this_and_after"
    ALL = "all"


class WorkspaceRole(str, Enum):
    """Workspace membership role enumeration."""
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class AssetType(str, Enum):
    """Supported asset source types."""
    UPLOADED_VIDEO = "uploaded_video"
    SCREEN_RECORDING = "screen_recording"
    LIVE_SESSION = "live_session"


class AssetStatus(str, Enum):
    """Asset processing lifecycle state."""
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    COMPLETED = "completed"
    ARCHIVED = "archived"



class Asset(Base):
    """Uploaded or recorded media source tracked by processing pipeline."""
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(SQLEnum(AssetType, values_callable=_enum_values, name="assettype"), nullable=False)
    status = Column(SQLEnum(AssetStatus, values_callable=_enum_values, name="assetstatus"), nullable=False, default=AssetStatus.PENDING, server_default=text("'pending'"))
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    source_upload_id = Column(UUID(as_uuid=True), ForeignKey("uploads.id"), nullable=True, index=True)
    source_object_key = Column(String(1024), nullable=False)
    duration_ms = Column(BigInteger, nullable=True)
    frame_rate = Column(Numeric(8, 3), nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    checksum_sha256 = Column(String(64), nullable=True, index=True)
    captured_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    failed_reason = Column(Text, nullable=True)
    meta = Column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_assets_user_created", "user_id", "created_at"),
        Index("ix_assets_user_status", "user_id", "status"),
        Index("ix_assets_workspace_id", "workspace_id"),
    )





class Notification(Base):
    """User notification for ingest and knowledge events."""
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    content = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    actions = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    payload = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
    )




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
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    location = Column(String(255), nullable=True)  # Optional: classroom or meeting link
    description = Column(String(1000), nullable=True)  # Optional: notes
    is_completed = Column(Boolean, default=False)  # For DEADLINE type
    
    # Workflow link
    workflow_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # Recurrence fields
    recurrence_rule = Column(JSONB, nullable=True)
    recurrence_id = Column(UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="CASCADE"), nullable=True, index=True)
    original_start_time = Column(DateTime(timezone=True), nullable=True)
    is_exception = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_cancelled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    
    # Versioning for conflict detection
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    updated_by = Column(String(20), nullable=False, default="INTERNAL", server_default=text("'INTERNAL'"))
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    reminders = relationship("ScheduleReminder", back_populates="schedule", cascade="all, delete-orphan")
    instances = relationship("Schedule", foreign_keys="Schedule.recurrence_id")
    
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


class ScheduleReminder(Base):
    """Reminder configuration for schedule events."""
    __tablename__ = "schedule_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    minutes_before = Column(Integer, nullable=False, default=10)
    method = Column(SQLEnum(ReminderMethod, values_callable=_enum_values, name="remindermethod"), nullable=False, default=ReminderMethod.PUSH)
    status = Column(SQLEnum(ReminderStatus, values_callable=_enum_values, name="reminderstatus"), nullable=False, default=ReminderStatus.PENDING)
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    failed_reason = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    schedule = relationship("Schedule", back_populates="reminders")

    __table_args__ = (
        Index("ix_reminders_scheduled_at_status", "scheduled_at", "status", postgresql_where=text("status = 'pending'")),
        Index("ix_reminders_schedule_id", "schedule_id"),
    )


class ScheduleSyncQueue(Base):
    """Queue for async Google Calendar synchronization."""
    __tablename__ = "schedule_sync_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    operation = Column(SQLEnum(SyncOperation, values_callable=_enum_values, name="syncoperation"), nullable=False)
    priority = Column(Integer, nullable=False, default=5)
    status = Column(SQLEnum(SyncQueueStatus, values_callable=_enum_values, name="syncqueuestatus"), nullable=False, default=SyncQueueStatus.PENDING)
    retry_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_sync_queue_pending", "priority", "created_at", postgresql_where=text("status = 'pending'")),
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
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    parent_note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True, index=True)
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
    checkpoint_version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    is_deleted = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))
    # Vector embedding for semantic search
    # Stored as PostgreSQL vector type via pgvector extension
    embedding = Column(JSONB, nullable=True)  # Fallback: store as JSON array until proper vector type
    embedding_generated_at = Column(DateTime, nullable=True)  # Track when embedding was computed

    __table_args__ = (
        Index("ix_notes_user_id", "user_id"),
        Index("ix_notes_user_id_updated_at", "user_id", "updated_at"),
        Index("ix_notes_user_parent_updated_at", "user_id", "parent_note_id", "updated_at"),
        Index("ix_notes_workspace_id", "workspace_id"),
    )


class NoteRevision(Base):
    """Incremental delta record for note content edits."""
    __tablename__ = "note_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    base_version = Column(Integer, nullable=False)
    patch = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    patch_format = Column(String(32), nullable=False, default="text_diff", server_default=text("'text_diff'"))
    content_length = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("note_id", "version", name="uq_note_revisions_note_version"),
        Index("ix_note_revisions_note_id_version", "note_id", "version"),
    )


class NoteImage(Base):
    """Track images uploaded for a note."""
    __tablename__ = "note_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    object_key = Column(String(1024), nullable=False)
    original_filename = Column(String(255), nullable=True)
    content_type = Column(String(100), nullable=False, default="image/png")
    file_size = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_note_images_note_id", "note_id"),
    )


class UploadStatus(str, Enum):
    """Multipart upload lifecycle status."""
    INITIATED = "initiated"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


class Upload(Base):
    """Track multipart upload sessions owned by users."""
    __tablename__ = "uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    status = Column(
        SQLEnum(UploadStatus, values_callable=_enum_values, name="uploadstatus"),
        nullable=False,
        default=UploadStatus.INITIATED,
    )
    object_key = Column(String(1024), nullable=False, unique=True, index=True)
    upload_id = Column(String(255), nullable=False, unique=True, index=True)
    total_parts = Column(Integer, nullable=False)
    total_size = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=True)
    content_type = Column(String(255), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_uploads_user_status_created_at", "user_id", "status", "created_at"),
    )


class UploadPart(Base):
    """Track confirmed uploaded parts per upload session."""
    __tablename__ = "upload_parts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_record_id = Column(UUID(as_uuid=True), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    part_number = Column(Integer, nullable=False)
    etag = Column(String(255), nullable=False)
    size = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("upload_record_id", "part_number", name="uq_upload_parts_upload_part_number"),
        Index("ix_upload_parts_upload_part_number", "upload_record_id", "part_number"),
    )


class Workspace(Base):
    """Workspace: organizational unit for grouping notes and assets."""
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=True, unique=True)
    is_personal = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("NOW()"))

    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    """Workspace membership: which users belong to which workspace with what role."""
    __tablename__ = "workspace_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(SQLEnum(WorkspaceRole, values_callable=_enum_values, name="workspacerole"), nullable=False, default=WorkspaceRole.VIEWER)
    invited_by = Column(UUID(as_uuid=True), nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow, server_default=text("NOW()"))

    workspace = relationship("Workspace", back_populates="members")

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )


class AgentConversation(Base):
    """Multi-turn conversation thread with an AI agent."""
    __tablename__ = "agent_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)  # Stores compressed summary of older messages
    message_count = Column(Integer, nullable=False, default=0, server_default=text("0"))  # Track total messages
    total_token_count = Column(Integer, nullable=False, default=0, server_default=text("0"))  # Total tokens in conversation
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_agent_conversations_user_id", "user_id"),
        Index("ix_agent_conversations_user_created", "user_id", "created_at"),
        Index("ix_agent_conversations_workspace_id", "workspace_id"),
    )


class AgentMessage(Base):
    """Message in an agent conversation (user, assistant, or tool result)."""
    __tablename__ = "agent_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" | "assistant" | "tool"
    content = Column(Text, nullable=True)
    context = Column(JSONB, nullable=True)
    tool_name = Column(String(100), nullable=True)
    tool_input = Column(JSONB, nullable=True, default=dict, server_default=text("'{}'::jsonb"))
    tool_output = Column(JSONB, nullable=True, default=dict, server_default=text("'{}'::jsonb"))
    token_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_agent_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_agent_messages_conversation_role", "conversation_id", "role"),
    )
