from datetime import datetime, timezone
from enum import Enum
import uuid

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

Base = declarative_base()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    PROCESSING = "processing"
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


class AttentionItemType(str, Enum):
    """What kind of thing was surfaced (Milestone 2.9).

    `attention_log.item_id` points at whichever table this names — it is
    polymorphic and therefore carries no foreign key.
    """
    TASK = "task"
    COMMITMENT = "commitment"
    SCHEDULE = "schedule"


class AttentionLevel(str, Enum):
    """The five levels of intervention (Product Requirement 13).

    `silent` is a real, recorded outcome — a decision not to speak, not the
    absence of a decision. See AttentionLog's docstring.
    """
    SILENT = "silent"
    INFORM = "inform"
    RECOMMEND = "recommend"
    ASK = "ask"
    ACT = "act"


class AttentionChannel(str, Enum):
    """Where the surfacing went.

    `telegram` and `email` have no delivery path until Phase 5; they are
    declared now so adding one later is a code change, not a migration on a
    table that by then holds history.
    """
    IN_APP = "in_app"
    PUSH = "push"
    TELEGRAM = "telegram"
    EMAIL = "email"


class AttentionResponse(str, Enum):
    """How the user reacted.

    `no_response` is the initial state of every row: nothing has come back
    *yet*. `ignored` is different and stronger — the user saw it and chose
    not to act. Collapsing the two would make 6.9's accuracy numbers
    meaningless.
    """
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    IGNORED = "ignored"
    NO_RESPONSE = "no_response"


class TaskStatus(str, Enum):
    """Task lifecycle state (Milestone 2.5).

    The legal transitions between these live in
    `app.services.tasks.TASK_STATUS_TRANSITIONS` — the service rejects
    anything else, so the enum alone is not the contract.

    `PENDING_CONFIRM`/`REJECTED` exist for one source only: a task extracted
    from a conversation (formerly the separate `Commitment` entity — see
    `app.services.task_extraction`). The AI *guesses* these, so they need a
    human yes/no before they count as real work; every other creation path
    (the user typing it, a goal breakdown, an event checklist) starts
    straight at `TODO` because nobody needs to confirm their own input.
    `REJECTED` rows are kept, not deleted — the same reason `Commitment`
    kept them: it's what stops the extractor re-proposing the same guess.
    """
    PENDING_CONFIRM = "pending_confirm"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class TaskPriority(str, Enum):
    """User-set importance of a Task.

    Replaces the goal-derived importance Task used to rely on (see the
    Task docstring's former "no priority column" stance) — that signal
    went away with Goal, so this is a plain, user-entered field instead.
    Nullable on the column: unset ranks below every set value, it is not
    the same as `LOW`.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


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
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

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
    created_at = Column(DateTime, default=_utcnow, nullable=False)

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
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class RefreshToken(Base):
    """Persisted refresh token metadata for rotation and logout revocation."""
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    jti = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

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
    created_at = Column(DateTime, default=_utcnow)

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
    
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    
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
    needs_reauth = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    channel_id = Column(String(64), nullable=True)
    channel_resource_id = Column(String(255), nullable=True)
    channel_expiration = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

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
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

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
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

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
    created_at = Column(DateTime, default=_utcnow, nullable=False)
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
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_oauth_states_provider_expires_at", "provider", "expires_at"),
    )


class Note(Base):
    __tablename__ = "notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    parent_note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(500), nullable=False, server_default=text("'Untitled'"))
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
    created_at = Column(DateTime, default=_utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, server_default=text("NOW()"))
    # Vector embedding for semantic search
    embedding = Column(Vector(768), nullable=True)
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
    created_at = Column(DateTime, default=_utcnow, nullable=False)

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
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))

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
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

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
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

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
    created_at = Column(DateTime, default=_utcnow, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, server_default=text("NOW()"))

    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    """Workspace membership: which users belong to which workspace with what role."""
    __tablename__ = "workspace_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(SQLEnum(WorkspaceRole, values_callable=_enum_values, name="workspacerole"), nullable=False, default=WorkspaceRole.VIEWER)
    invited_by = Column(UUID(as_uuid=True), nullable=True)
    joined_at = Column(DateTime, default=_utcnow, server_default=text("NOW()"))

    workspace = relationship("Workspace", back_populates="members")

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )


class NoteEditProposal(Base):
    """Reviewable proposal for AI-generated note edits (not yet applied to the note)."""
    __tablename__ = "note_edit_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True)

    # Content reference: patch is applied on top of base_revision (or note.content if NULL)
    base_revision_id = Column(UUID(as_uuid=True), ForeignKey("note_revisions.id"), nullable=True)
    base_version = Column(Integer, nullable=False)
    patch = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))

    # Creator identity (supports USER / AGENT / WORKFLOW / SYSTEM)
    creator_type = Column(String(20), nullable=False, default="USER")
    creator_id = Column(String(255), nullable=False)

    # Status machine: pending → applying → approved
    status = Column(String(20), nullable=False, default="pending")

    # Audit trail
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    rejected_at = Column(DateTime, nullable=True)

    # Lifecycle
    last_viewed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    conversation_id = Column(UUID, nullable=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_proposals_note_status", "note_id", "status"),
        Index("ix_proposals_creator", "creator_type", "creator_id"),
        Index("ix_proposals_expires", "status", "expires_at"),
    )


class PlanProposal(Base):
    """Reviewable proposal for AI-generated Task/Event items (3.2 AI Planner).

    Simpler than `NoteEditProposal`: items describe rows to be *created*,
    not a patch to existing content, so there is no base_revision/version
    to optimistic-lock against and no "supersede the older pending one"
    concept — each proposal stands alone.
    """
    __tablename__ = "plan_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # List of draft {type: "task"|"event", key, title, ...} dicts — see
    # `PlanProposalItemIn` (schemas.py) for the shape. `key`/`parent_key`
    # are proposal-local ids, not real Task/Schedule ids.
    items = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))

    # Creator identity (supports USER / AGENT / WORKFLOW / SYSTEM, mirrors NoteEditProposal)
    creator_type = Column(String(20), nullable=False, default="AGENT")
    creator_id = Column(String(255), nullable=False)

    # Status machine: pending → approved | rejected | expired (no "applying"
    # intermediate state — each item's creation is its own Command, not a
    # single atomic patch application).
    status = Column(String(20), nullable=False, default="pending")

    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)

    expires_at = Column(DateTime, nullable=False)
    conversation_id = Column(UUID, nullable=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_plan_proposals_user_status", "user_id", "status"),
        Index("ix_plan_proposals_expires", "status", "expires_at"),
    )


class AgentConversation(Base):
    """Multi-turn conversation thread with an AI agent."""
    __tablename__ = "agent_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)
    message_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    total_token_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_extracted_at = Column(DateTime, nullable=True)
    last_summary_message_id = Column(UUID(as_uuid=True), ForeignKey("agent_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    tokens_since_last_summary = Column(Integer, nullable=False, default=0, server_default=text("0"))
    messages_since_last_summary = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

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
    tool_call_id = Column(String(100), nullable=True)
    turn_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    token_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_agent_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_agent_messages_conversation_role", "conversation_id", "role"),
    )


class Task(Base):
    """A unit of work (Milestone 2.5).

    Deliberately its own table, not `schedules` with `type=TASK`:
    **a schedule occupies time, a task consumes it**. Free-slot planning (3.3)
    and interruptibility (6.2) both answer "is the user busy?" by reading
    `schedules`; a task with a Friday deadline does not make Friday busy, and
    projecting tasks into that table would make every deadline read as a busy
    block. See the planning doc's "Ranh giới Task vs Schedule".

    `priority` is user-entered (see `TaskPriority`) — Goal, the thing
    importance used to be derived from, is gone. Nullable and unranked by
    default: an unset priority is not the same as `LOW`, it just doesn't
    push the task up in `app.services.today`'s ordering.

    No `related_project_id` either: 2.5's description line lists it, but the
    Phase 2 "Không làm" table defers the Project entity outright — an FK to a
    table that doesn't exist is debt, not forward-compatibility.
    """
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    status = Column(
        SQLEnum(TaskStatus, values_callable=_enum_values, name="taskstatus"),
        nullable=False,
        default=TaskStatus.TODO,
        server_default=text("'todo'"),
    )
    # When this task last transitioned *into* `done` — cleared the moment it
    # leaves `done` again (reopened). Distinct from `updated_at`, which also
    # moves on an unrelated edit (renaming a done task must not make it read
    # as "finished just now"). The one place a "Hôm nay" list tells "done
    # today" from "done on some earlier day" — see
    # `app.services.tasks.TaskService.update_task` for where it's set.
    completed_at = Column(DateTime, nullable=True)
    # A deadline, not a time block: "must be done before Friday", not
    # "occupies Friday". Usually midnight (a bare day, set via a plain date
    # string); a real time is optional, not the default — e.g. a checklist
    # item created inside an event (2.6) inherits that event's `end_time`
    # exactly. Carrying a time here still isn't "occupying" anything: it's
    # a point the task must be done by, not a span it books.
    #
    # No timezone, unlike `Schedule.start_time`/`end_time`: this is the
    # user's own wall-clock fact, not a real-world instant, and a tz-aware
    # column tempts exactly the reinterpretation the calendar feed already
    # avoids when reading it back (see `calendar_items.parseServerDay`'s
    # frontend counterpart). See migration `d0123456789z` for the concrete
    # bug that made this the deliberate choice, not an oversight.
    due_date = Column(DateTime(timezone=False), nullable=True)
    priority = Column(SQLEnum(TaskPriority, values_callable=_enum_values, name="taskpriority"), nullable=True)
    description = Column(Text, nullable=True)
    # Nullable and stays that way: the two dominant creation paths (chat,
    # and Cortex creating tasks itself) produce a task attached to nothing.
    # "Belongs to no event" is the common case here, not the exception.
    related_event_id = Column(
        UUID(as_uuid=True), ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # A task's own checklist. Self-referential and SET NULL on delete, same
    # reasoning as `related_event_id`: deleting the parent orphans its
    # sub-tasks into ordinary top-level tasks rather than deleting them too.
    parent_task_id = Column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Provenance for a task extracted from a conversation (formerly on
    # `Commitment` — see `app.services.task_extraction`). Null for every
    # other creation path: the user typing it, a goal breakdown, an event
    # checklist. So "where did Cortex get this?" is answerable the same way
    # Commitment answered it (2.4 M3).
    source_conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        # "What's on my plate" for the Hôm Nay screen (2.7).
        Index("ix_tasks_user_status_due_date", "user_id", "status", "due_date"),
        # The extraction fingerprint lookup (formerly
        # `ix_commitments_user_status_content`) — must stay identical to
        # `app.repositories.tasks.normalized()`'s expression, or the lookup
        # silently stops using the index and starts scanning.
        Index(
            "ix_tasks_user_status_content",
            "user_id",
            "status",
            text("lower(btrim(title))"),
        ),
    )

    def __repr__(self):
        return f"<Task(id={self.id}, title={self.title}, status={self.status})>"


class AttentionLog(Base):
    """One row per surfacing decision (Milestone 2.9).

    Answers "does the user already know about this?" — the question that
    separates an assistant from a machine that repeats itself.

    Two properties make this not a notifications table:

    1. **A silent decision is still a row.** `level = silent` means Cortex
       considered this item and chose not to speak. Without that row, the
       most important debugging question — *why did Cortex say nothing?* —
       has no answer, and 6.9 can't measure how often the silence was right.

    2. **Deduplication is per (item_id, reason_key), never per item_id.**
       The same task surfaced because it's overdue and, separately, because
       it's marked high priority, is two legitimate surfacings. Collapsing
       them to one would hide the second reason.

    `item_id` deliberately has no FK: it points at `tasks`, `commitments`
    (2.4) or `schedules` depending on `item_type`. It also outlives its
    target on purpose — the record that Cortex nagged about something is
    still true after that something is deleted.
    """
    __tablename__ = "attention_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    item_type = Column(
        SQLEnum(AttentionItemType, values_callable=_enum_values, name="attentionitemtype"),
        nullable=False,
    )
    item_id = Column(UUID(as_uuid=True), nullable=False)
    # A stable string naming *why*, e.g. "task.overdue",
    # "task.high_priority", "commitment.due_soon". Half of the
    # dedup key, so it must stay stable across releases once used.
    reason_key = Column(String(100), nullable=False)
    surfaced_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"), index=True)
    level = Column(
        SQLEnum(AttentionLevel, values_callable=_enum_values, name="attentionlevel"),
        nullable=False,
    )
    channel = Column(
        SQLEnum(AttentionChannel, values_callable=_enum_values, name="attentionchannel"),
        nullable=False,
        default=AttentionChannel.IN_APP,
        server_default=text("'in_app'"),
    )
    response = Column(
        SQLEnum(AttentionResponse, values_callable=_enum_values, name="attentionresponse"),
        nullable=False,
        default=AttentionResponse.NO_RESPONSE,
        server_default=text("'no_response'"),
    )
    responded_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # The dedup lookup, in its exact column order (2.9 M1).
        Index("ix_attention_log_user_item_reason_surfaced", "user_id", "item_id", "reason_key", "surfaced_at"),
        # 6.9 reads the other way round: "how did surfacings of this kind fare?"
        Index("ix_attention_log_user_reason_response", "user_id", "reason_key", "response"),
    )

    def __repr__(self):
        return (
            f"<AttentionLog(id={self.id}, item={self.item_type}:{self.item_id}, "
            f"reason={self.reason_key}, level={self.level})>"
        )


class StateEvaluatorFlag(Base):
    """One row per (item, condition) currently true (Milestone 4.6).

    The State Evaluator's own idempotency bookkeeping — deliberately not
    `attention_log` (2.9): that table answers "does the user already know
    about this", a delivery-layer question. This answers "did we already
    publish an event for this transition", a detection-layer question that
    has to exist even if nothing ever surfaces the event to a user. A row
    present means the condition (`flag_key`) is currently true for
    (`item_type`, `item_id`); the evaluator deletes it the moment the
    condition stops holding, so a later re-transition publishes again
    instead of being suppressed forever.
    """
    __tablename__ = "state_evaluator_flags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    item_type = Column(
        SQLEnum(AttentionItemType, values_callable=_enum_values, name="attentionitemtype"),
        nullable=False,
    )
    item_id = Column(UUID(as_uuid=True), nullable=False)
    flag_key = Column(String(100), nullable=False)
    first_detected_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("item_type", "item_id", "flag_key", name="uq_state_evaluator_flag"),
    )

    def __repr__(self):
        return f"<StateEvaluatorFlag(item={self.item_type}:{self.item_id}, flag={self.flag_key})>"


class ActionHistory(Base):
    """The PostgreSQL half of `ActionSnapshotStore` (Layer 7 audit trail).

    `ActionSnapshotStore` writes every revertable command's undo state twice:
    Redis (24h, hot — what `revert_command()` actually reads) and here
    (90-day-ish, cold — the audit record of what an AI-driven session did,
    surviving past Redis's TTL and past a restart). This table existed in
    name only until now: every INSERT into it had been silently failing
    since the day `action_snapshot_store.py` was written, because nothing
    had ever created it. `revert_action` still worked (Redis carries it),
    so the gap went unnoticed — the failure mode was losing history, not
    losing function.

    `action_id` is not typed as UUID even though it always holds one in
    practice: the application code treats it as an opaque string identifier
    everywhere (the Redis key, `Command.command_id`), never casts it, and
    this table shouldn't add a constraint the application layer doesn't
    itself enforce.

    No FK from `action_id` to anything — it names a `Command.command_id`,
    which has no table of its own to point at (commands are never persisted
    beyond this audit row and the Redis snapshot).
    """
    __tablename__ = "action_history"

    # Server-side default, not just Python-side: this table is written via a
    # raw SQL INSERT (action_snapshot_store.py), which never goes through
    # session.add() — a Column(default=...) only fires there, so without
    # gen_random_uuid() at the database level every insert would violate
    # this column's NOT NULL constraint.
    id = Column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=text("gen_random_uuid()"),
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    # SET NULL, not CASCADE: the audit record that a command ran must outlive
    # the conversation it happened in — same reasoning as Commitment's
    # source_conversation_id.
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_name = Column(String(100), nullable=False)
    action_type = Column(String(50), nullable=False, default="snapshot", server_default=text("'snapshot'"))
    action_id = Column(String(64), nullable=False, unique=True)
    before_state = Column(JSONB, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("NOW()"))
    is_reverted = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    reverted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_action_history_user_created", "user_id", "created_at"),
    )

    def __repr__(self):
        return f"<ActionHistory(action_id={self.action_id}, tool={self.tool_name}, reverted={self.is_reverted})>"
