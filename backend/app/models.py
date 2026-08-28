from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, Numeric, String, Text, Time, UniqueConstraint, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector

from app.ids import uuid7

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

    `USER` is the one exception to "points at a domain row": it names the
    user themselves, `item_id = users.id`, for a reason that isn't about
    any single task/schedule — e.g. `day.review` (A1), a per-user daily
    digest. Still a real row `attention_log`/`state_evaluator_flags` can
    point at, just not a domain-specific one.
    """
    TASK = "task"
    COMMITMENT = "commitment"
    SCHEDULE = "schedule"
    USER = "user"
    # Cấp dự án (DESIGN 6). Khác `USER` ở chỗ nó trỏ vào một hàng
    # `projects` thật, và khác `TASK` ở chỗ nhắc của nó đi về channel của
    # dự án chứ không về DM (DESIGN 8.1).
    PROJECT = "project"


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
    """A way of reaching the user.

    Used in two places with two different meanings, deliberately kept on
    one enum: `attention_log.channel` records the *surface* a Gate decision
    was made for, while `user_channels.channel` /
    `notification_deliveries.channel` record an actual **delivery route**
    (see those tables and app/services/delivery/).

    Only channels with an adapter registered in
    `app.services.delivery.registry` can actually deliver anything. The
    rest are declared ahead of their adapters on purpose: adding an enum
    *value* to PostgreSQL is a migration, and doing one migration per new
    channel while the delivery roadmap (web push → chat bot → email) is
    already known would be three migrations for no reason. A row naming a
    channel with no adapter is a defined state, not corruption — the
    dispatcher marks that delivery `skipped`.
    """
    IN_APP = "in_app"
    PUSH = "push"
    TELEGRAM = "telegram"
    EMAIL = "email"
    SLACK = "slack"
    MEZON = "mezon"
    WEBHOOK = "webhook"


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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    # Xem `Note.project_id` — cùng lý do.
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    )





class Notification(Base):
    """User notification for ingest and knowledge events."""
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    content = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    actions = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    payload = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    # Set only for notifications that went through the deterministic
    # Attention Gate pipeline (6.1 M2) — the pass-through branch (system
    # alerts with no domain item, e.g. "reconnect Google Calendar") leaves
    # all three null, which is a valid, permanent state, not a gap to
    # backfill. `reason_key` is what 4.5 M3's "đừng nhắc kiểu này nữa"
    # button downgrades; `attention_log_id` is what 6.9 joins back to the
    # surfacing decision (and its eventual response) that created this row.
    reason_key = Column(String(100), nullable=True)
    attention_level = Column(
        SQLEnum(AttentionLevel, values_callable=_enum_values, name="attentionlevel"),
        nullable=True,
    )
    attention_log_id = Column(
        UUID(as_uuid=True),
        ForeignKey("attention_log.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
    )




class User(Base):
    """User model for authentication and ownership"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    email = Column(String(255), nullable=False, unique=True, index=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class RefreshToken(Base):
    """Persisted refresh token metadata for rotation and logout revocation."""
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    jti = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

class AuthorizationCode(Base):
    """One-time authorization code for OAuth2 Authorization Code + PKCE."""
    __tablename__ = "authorization_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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
    # Nullable và ở lại như vậy. Bất đối xứng có chủ ý với `Task.project_id`
    # (NOT NULL): sự kiện chỉ được gắn dự án khi có tín hiệu chắc chắn từ
    # bot họp hoặc do người dùng gắn tay (DESIGN 4.2). Phần lớn sự kiện —
    # 1:1, ăn trưa, lịch cá nhân — sẽ mãi mãi NULL, và đó là đúng: lịch là
    # khung thời gian, không phải cấu trúc dự án.
    # Chỉ đặt trên HÀNG TEMPLATE của chuỗi (`recurrence_id IS NULL`).
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # `hangoutLink` của Google — mức khớp chính xác thứ hai trong thang ở
    # DESIGN 4.2. Google để link Meet ở đây, KHÔNG phải ở `location`.
    hangout_link = Column(String(1024), nullable=True)

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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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
        # `user_id` là phần bắt buộc của khoá này, không phải thừa:
        # `provider_calendar_id` mặc định `'primary'` cho MỌI người, nên nếu
        # thiếu `user_id` thì hai người cùng sync một cuộc họp sẽ đụng ràng
        # buộc và người thứ hai fail. Xem migration `b2c3d4e5f6a7`.
        UniqueConstraint("user_id", "provider", "provider_calendar_id", "provider_event_id", name="uq_schedule_external_maps_provider_event"),
        Index("ix_schedule_external_maps_user_provider", "user_id", "provider"),
        Index("ix_schedule_external_maps_provider_event_id", "provider_event_id"),
    )


class ScheduleReminder(Base):
    """Reminder configuration for schedule events."""
    __tablename__ = "schedule_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    # Container của ghi chú. `workspace_id` đã bị gỡ hẳn cùng với toàn bộ
    # khái niệm workspace (DESIGN 11.4 — `projects` là container duy nhất).
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
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
    )


class NoteRevision(Base):
    """Incremental delta record for note content edits."""
    __tablename__ = "note_revisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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


class NoteEditProposal(Base):
    """Reviewable proposal for AI-generated note edits (not yet applied to the note)."""
    __tablename__ = "note_edit_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
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
    )


class AgentMessage(Base):
    """Message in an agent conversation (user, assistant, or tool result)."""
    __tablename__ = "agent_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" | "assistant" | "tool" | "system"
    content = Column(Text, nullable=True)
    context = Column(JSONB, nullable=True)
    tool_name = Column(String(100), nullable=True)
    tool_input = Column(JSONB, nullable=True, default=dict, server_default=text("'{}'::jsonb"))
    tool_output = Column(JSONB, nullable=True, default=dict, server_default=text("'{}'::jsonb"))
    tool_call_id = Column(String(100), nullable=True)
    turn_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    token_count = Column(Integer, nullable=True)
    # Which surface produced this row: "web" | "mezon" | "system". NULL means
    # "web" (every row before F2 existed). "system" marks a row the Attention
    # Gate delivered, not something either party said — see M2/R5 in
    # docs/mezon-bot-plan.md and migration p1234567890q.
    source = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_agent_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_agent_messages_conversation_role", "conversation_id", "role"),
    )


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class ProjectOrigin(str, Enum):
    """Nguồn của một project. Ba giá trị, không được gộp.

    `personal` KHÔNG được gộp vào `manual`: mục 4.4 của `docs/DESIGN.md` đo
    chất lượng quy tắc suy ra bằng tỷ lệ người dùng sửa quy gán, và dự án
    cá nhân lẫn vào sẽ làm con số đó vô nghĩa.
    """
    DERIVED = "derived"
    MANUAL = "manual"
    PERSONAL = "personal"


class ProjectJoinSource(str, Enum):
    DERIVED = "derived"
    MANUAL = "manual"


class Project(Base):
    """Một khối công việc có đích và có hạn — xem `docs/DESIGN.md` mục 3.

    Cố ý KHÔNG phải `Workspace` đổi tên. Workspace là hộp đựng *tài liệu*
    (`is_personal`, tự sinh lúc đăng ký, `WorkspaceMember.role` là quyền
    *đọc*); project là khối *công việc* và thành viên của nó là *ai chịu
    trách nhiệm*. Chi phí đo thật của việc đổi tên nằm ở DESIGN 3.6.

    **Dùng chung, không thuộc về một người** (QĐ-1). `owner_id` là *ai tạo
    ra*; "dự án của tôi" tra qua `ProjectMember`, không qua `owner_id`.
    """
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(
        SQLEnum(ProjectStatus, values_callable=_enum_values, name="projectstatus"),
        nullable=False,
        default=ProjectStatus.ACTIVE,
        server_default=text("'active'"),
    )
    # Suy ra (DESIGN 4.3), người dùng sửa được. `deadline_is_manual` khoá
    # lại để lần suy ra sau không ghi đè lựa chọn của họ.
    deadline = Column(DateTime, nullable=True)
    deadline_is_manual = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Mezon channel — danh tính CHUNG của dự án (QĐ-2, DESIGN 3.1.1).
    # Cố ý không neo vào chuỗi sự kiện lịch: lịch không sync chéo giữa
    # người dùng, và trong một lịch công việc không có tín hiệu nào phân
    # biệt "chuỗi này là dự án" với "chuỗi này là standup/1:1/ăn trưa".
    # NULL cho dự án cá nhân và dự án tạo tay.
    source_channel_id = Column(String(255), nullable=True)
    origin = Column(
        SQLEnum(ProjectOrigin, values_callable=_enum_values, name="projectorigin"),
        nullable=False,
    )
    created_at = Column(DateTime, default=_utcnow, server_default=text("NOW()"), nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, server_default=text("NOW()"), nullable=False)

    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        # Bất biến chịu lực của DESIGN 3.4, ở tầng DB chứ không chỉ ở một
        # câu `if`. Câu `if` đó đã từng thiếu, và một hàng thật nhận
        # `deadline` từ `max(due_date)` của các việc lẻ trong lúc nó thiếu.
        # Đây là thứ duy nhất ngăn dự án cá nhân sinh nhắc cấp dự án.
        CheckConstraint(
            "origin <> 'personal' OR deadline IS NULL",
            name="ck_projects_personal_has_no_deadline",
        ),
        Index(
            "uq_projects_source_channel",
            "source_channel_id",
            unique=True,
            postgresql_where=text("source_channel_id IS NOT NULL"),
        ),
        Index(
            "uq_projects_personal_per_user",
            "owner_id",
            unique=True,
            postgresql_where=text("origin = 'personal'"),
        ),
    )


class ProjectMember(Base):
    """Ai đang ở trong một dự án.

    **Cố ý không có cột `role`.** Đó chính là thứ làm `WorkspaceMember` sai
    ngữ nghĩa khi đem sang đây — role ở đó là quyền *đọc tài liệu*, không
    phải *chịu trách nhiệm việc*. Thêm role chỉ khi có một quyết định cụ
    thể cần tới nó; hiện chưa có.

    Thành viên được **suy ra, không mời** (P4): nhận việc từ channel của
    dự án là đủ để vào. Không có luồng mời/duyệt trong v1.
    """
    __tablename__ = "project_members"

    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    joined_via = Column(
        SQLEnum(ProjectJoinSource, values_callable=_enum_values, name="projectjoinsource"),
        nullable=False,
    )
    joined_at = Column(DateTime, default=_utcnow, server_default=text("NOW()"), nullable=False)

    project = relationship("Project", back_populates="members")

    __table_args__ = (Index("ix_project_members_user", "user_id"),)


class ProjectSnapshot(Base):
    """Số liệu của một dự án tại một lần đánh giá — DESIGN 6.1.

    Tồn tại vì `StateEvaluatorFlag` chỉ trả lời *"điều kiện này đang đúng"*,
    không trả lời *"lần trước là bao nhiêu"*. `project.slipping` cần cái
    sau: nó phát khi số việc mở **tăng** so với lần đánh giá trước, và
    không có chỗ nào khác trong hệ thống lưu con số đó.

    Bảng riêng thay vì một cột JSONB trên bảng cờ: cùng dữ liệu này là đầu
    vào của `project.will_miss`, và bảng cờ thì mọi predicate đều đọc — làm
    nó phình ra là trả giá ở chỗ nóng nhất.
    """
    __tablename__ = "project_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    open_count = Column(Integer, nullable=False)
    completed_last_14d = Column(Integer, nullable=False, default=0, server_default=text("0"))
    evaluated_at = Column(DateTime, default=_utcnow, server_default=text("NOW()"), nullable=False)

    __table_args__ = (
        Index("ix_project_snapshots_project_evaluated", "project_id", "evaluated_at"),
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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
    # Bắt buộc: mọi task thuộc đúng một project (DESIGN 3.3). Task có thể
    # không gắn sự kiện nào, nhưng không bao giờ không có project — khi
    # không có ngữ cảnh nào khác thì rơi về dự án cá nhân (DESIGN 3.4).
    #
    # `project_id` và `related_event_id` là HAI quan hệ độc lập: project
    # nói *việc này thuộc về đâu*, related_event nói *nó sinh ra từ cuộc
    # họp nào*. Đổi project không đụng tới related_event.
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    # Người dùng đã phải sửa quy gán project của task này (DESIGN 4.4).
    # Một nhãn âm cho quy tắc suy ra ở 3.5 bước 2: tỷ lệ cột này trên tổng
    # số task thuộc dự án `origin='derived'` là chỉ số chất lượng của quy
    # tắc. Ngưỡng ở 4.4: >20% nghĩa là quy tắc sai — sửa quy tắc, không
    # thêm UI.
    #
    # Không reset khi task đổi dự án lần nữa: nó ghi "quy gán tự động cho
    # task này từng sai", và việc đó không hết đúng vì có lần sửa thứ hai.
    project_id_corrected = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Id của action item ở hệ thống đã sinh ra nó (bot họp). `NULL` cho mọi
    # task tạo trong app, và đó là đa số tuyệt đối.
    #
    # Tồn tại vì webhook **luôn** được gửi lại. Không có nó, mỗi lần gửi lại
    # đẻ thêm một bản sao — và bản sao không bị dedup ở `attention_log` gộp,
    # vì dedup khoá theo `item_id`. Kết quả là người dùng bị nhắc hai lần về
    # một việc, đúng thất bại mà DESIGN 1.2 định nghĩa.
    source_external_id = Column(String(255), nullable=True)
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
    # Per-occurrence completion for a checklist task on a *recurring* event
    # (`related_event_id` pointing at a Schedule with a recurrence rule).
    # Every occurrence of that event shares one root id (see
    # `RecurrenceService.generate_instances`), so without this a task's
    # `status` would be identical no matter which occurrence's checklist you
    # opened. Mirrors `Schedule`'s own exception-row mechanism exactly: the
    # task most callers see is the template (these three columns null); an
    # "exception" row is created lazily, on first write to one occurrence,
    # with its own status/title/description and these three columns set —
    # see `TaskService.complete_task_occurrence`/`update_task_occurrence`.
    recurrence_id = Column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    original_start_time = Column(DateTime(timezone=True), nullable=True)
    is_exception = Column(Boolean, nullable=False, default=False, server_default=text("false"))
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
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


class AttentionBundleQueue(Base):
    """One row per candidate the Attention Gate silenced for being busy,
    not for any other reason (Milestone 6.1 M3).

    Step 3 of the Gate (attention_gate.py) can downgrade a non-critical
    candidate to SILENT while the user is in a meeting — `attention_log`
    (2.9) records that decision, but by itself a SILENT decision is just
    "not delivered", not "held for later". This table is the "held for
    later" half: `AttentionBundleWorker` polls for users who are no longer
    busy and have unflushed rows here, and turns every one of them into a
    single bundled Notification — the plan's own acceptance scenario ("8
    candidates during a meeting -> 0 during, 1 bundled after").

    Denormalized (`title`/`body`/`payload`/`actions` copied in rather than
    re-read from the item at flush time) because the item can change or be
    deleted in the gap between being silenced and being flushed, and the
    bundle should say what was true when Cortex decided to stay quiet, not
    re-derive a possibly-different current state.
    """
    __tablename__ = "attention_bundle_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    item_type = Column(
        SQLEnum(AttentionItemType, values_callable=_enum_values, name="attentionitemtype"),
        nullable=False,
    )
    item_id = Column(UUID(as_uuid=True), nullable=False)
    reason_key = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    actions = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    attention_log_id = Column(
        UUID(as_uuid=True), ForeignKey("attention_log.id", ondelete="SET NULL"), nullable=True
    )
    queued_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    flushed_at = Column(DateTime, nullable=True)
    bundle_notification_id = Column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_attention_bundle_queue_user_flushed", "user_id", "flushed_at"),
    )

    def __repr__(self):
        return f"<AttentionBundleQueue(user_id={self.user_id}, item={self.item_type}:{self.item_id})>"


class UserPreferences(Base):
    """Per-user delivery preferences (Milestone 6.2) — quiet hours, the
    cheapest, highest-impact half of interruptibility the planning doc
    calls out: `schedules` already answers "is the user busy right now"
    (app.services.availability); this answers the other half, "is it
    just a bad time of day regardless of the calendar" — no new signal,
    two columns.

    A missing row means "no quiet hours configured", not "not set up yet"
    — `get_preferences` treats it as all-null defaults rather than
    requiring a write on first read, matching boundary #2 (a preferences
    page a user never opens must not degrade the product).

    Both columns are UTC time-of-day. There is no per-user timezone
    anywhere else in this schema (`User` has none), so this is the same
    UTC-everywhere convention the rest of the codebase already uses, not a
    scope cut specific to this table — adding real per-user timezone
    support is its own feature.
    """
    __tablename__ = "user_preferences"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    quiet_hours_start = Column(Time, nullable=True)
    quiet_hours_end = Column(Time, nullable=True)
    # Per-user opt-out of a `reason_key` (the same string attention_log
    # and the reason catalog use — e.g. "task.stale", "day.review"),
    # checked by the Attention Gate before it computes a level at all
    # (app.services.attention_gate._decide_level_async/_sync). Empty list
    # (the default) means every reason is on — matches boundary #2 ("trang
    # cấu hình là nơi tắt, không phải nơi bật"): this column only ever
    # turns something off from its on-by-default state, a missing row is
    # never why a nudge doesn't fire.
    #
    # This exists because A1 wired 6 predicates straight from the backend
    # to the Gate with zero workflow involved (see notification_
    # subscribers.py's DIRECT_DELIVERY_HANDLERS) — there's no
    # WorkflowDefinition row A2/4.5 could toggle for them, so the on/off
    # switch has to live here instead. See docs/planning-v3.md's A2
    # section for why the original "toggle via system workflow" design
    # doesn't apply to these events.
    disabled_reason_keys = Column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Which model this user's chat turns run on when the caller doesn't
    # name one — set from the Mezon bot's `*model` command, since a chat
    # surface with no settings screen needs somewhere to put the choice
    # that survives a bot restart.
    #
    # Deliberately **not** read by the web: the web has its own picker
    # (localStorage) whose "Auto" would otherwise silently mean "the model
    # I once chose in Mezon", making the dropdown lie about what is
    # running. `AgentService.handle_streaming_generator` applies this only
    # for surface="mezon".
    #
    # NULL means "no choice recorded" → the catalogue default. An id that
    # has since left the catalogue resolves the same way (see
    # `ModelClient._resolve`), so retiring a model cannot strand a user on
    # something the provider no longer serves.
    chat_model = Column(String(120), nullable=True)
    # Nhóm A của phép thử A/B ở DESIGN mục 12: bỏ qua Attention Gate và gọi
    # thẳng `create_notification_*` — "đến hạn → ping một lần", đúng cách
    # một công cụ nhắc ngây thơ làm.
    #
    # Đây là hạ tầng của cổng nghiệm thu **duy nhất** của cả sản phẩm. Giả
    # định đang đặt cược (12.1): nhắc qua Gate hơn nhắc ngây thơ đủ nhiều
    # để người dùng cảm nhận được. Sai thì bot họp thêm chức năng nhắc
    # trong hai tuần và Cortex không còn sản phẩm.
    #
    # Cờ đặt theo hướng **"bỏ qua"**, không phải "bật Gate": hàng thiếu,
    # tài khoản mới, hay một lỗi đọc preferences đều rơi về hành vi *có
    # Gate* — tức là im hơn. Đặt ngược lại thì mọi trường hợp biên rơi về
    # nhắc nhiều hơn, và đó là hướng sai để sai (P5).
    gate_bypass = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

    def __repr__(self):
        return f"<UserPreferences(user_id={self.user_id}, quiet_hours={self.quiet_hours_start}-{self.quiet_hours_end})>"


class DeliveryStatus(str, Enum):
    """Lifecycle of one attempt to push one Notification down one channel.

    `skipped` is not a failure: it is the recorded decision that this
    channel was not used (no adapter registered for it, or the
    notification's level sat below the channel's `min_level`). Keeping it
    as a row rather than simply not writing one preserves the same property
    `attention_log` was built for — *why did nothing arrive?* has an
    answer, instead of an absence that could equally mean "not attempted"
    or "lost".

    `failed` is terminal: either the adapter reported a permanent error
    (a revoked push subscription, a bot blocked by the user) or retries ran
    out. `pending` rows are what `DeliveryWorker` claims.
    """
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class UserChannel(Base):
    """One route Cortex can reach a user through (bước 0 of the delivery
    plan — see docs/planning-v3.md).

    Until this table existed, `notifications` + SSE *was* the whole delivery
    story: a nudge computed while the user had no tab open sat in the
    database until they came back on their own, which quietly cancelled the
    entire point of a proactive assistant. This is the registry of the other
    ways out; `app/services/delivery/` is what uses it.

    **`min_level` is the product-critical column, not `address`.** A
    delivery layer without a per-channel importance floor turns every
    INFORM ("you have four hours free this afternoon") into a phone
    vibration, which is exactly the behaviour the Attention Gate's five
    steps exist to prevent — it would undo that work at the last inch. The
    default comes from the adapter (`DeliveryChannelAdapter.
    default_min_level`) and is applied at registration time, so a user who
    never opens the settings page still gets a sane floor: boundary #2
    ("trang cấu hình là nơi tắt, không phải nơi bật") holds.

    `address` is whatever identifies the user on that channel — a push
    endpoint, a Telegram chat id, an email. Opaque to everything except the
    channel's own adapter; anything structured the adapter needs beyond it
    (push p256dh/auth keys, a bot token scope) goes in `config`.

    `verified_at` gates delivery for channels where an address can be
    claimed without proof (email, a chat id typed by hand). Channels whose
    registration is itself proof of possession — a browser handing over its
    own push subscription — set it at creation. `enabled` is the user's own
    off switch and is deliberately separate: turning a channel off must not
    lose the verification and force re-linking to turn it back on.
    """
    __tablename__ = "user_channels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(
        SQLEnum(AttentionChannel, values_callable=_enum_values, name="attentionchannel"),
        nullable=False,
    )
    address = Column(Text, nullable=False)
    # Human label for the settings list ("Chrome trên laptop", "Telegram cá
    # nhân") — one user with three browsers needs to know which row to
    # revoke. Nullable: the API falls back to the channel name.
    label = Column(String(120), nullable=True)
    config = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    verified_at = Column(DateTime, nullable=True)
    min_level = Column(
        SQLEnum(AttentionLevel, values_callable=_enum_values, name="attentionlevel"),
        nullable=False,
    )
    # Last successful send. Drives "this device hasn't been reached in 90
    # days" cleanup later; also the cheapest signal for debugging a channel
    # that looks registered but never arrives.
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        # Re-registering the same browser or re-linking the same chat must
        # update the existing row, never create a duplicate that then
        # double-delivers every notification.
        UniqueConstraint("user_id", "channel", "address", name="uq_user_channels_user_channel_address"),
        Index("ix_user_channels_user_enabled", "user_id", "enabled"),
    )

    def __repr__(self):
        return f"<UserChannel(user_id={self.user_id}, channel={self.channel}, enabled={self.enabled})>"


class ChannelLinkCode(Base):
    """A one-time code that proves a chat account belongs to a Cortex user.

    Same shape and lifecycle as `OAuthState` (one-time, expiring, `used_at`
    kept rather than deleted) because it does the same job for a channel
    that has no OAuth to lean on: a Mezon user id is just a number the bot
    receives, and nothing about receiving it proves the sender owns *this*
    Cortex account.

    **Direction matters.** The code is minted in the web app, where the
    person is already authenticated, and typed into the chat. The reverse —
    typing a Mezon id into the web app — would let anyone claim anyone
    else's chat account, since ids are visible to everyone in a clan.

    Six digits is deliberately short enough to retype from memory. That is
    only safe because the row is single-use, expires in minutes, and is
    scoped to one user_id — brute force gets one guess per issued code, not
    a search space to grind. `attempts` exists so a code being hammered can
    be spotted and burned.
    """
    __tablename__ = "channel_link_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(
        SQLEnum(AttentionChannel, values_callable=_enum_values, name="attentionchannel"),
        nullable=False,
    )
    code = Column(String(12), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    # What the code was redeemed *to* — kept for the audit question "which
    # chat account got attached to this person, and when".
    redeemed_address = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_channel_link_codes_code_channel", "code", "channel"),
    )

    def __repr__(self):
        return f"<ChannelLinkCode(user_id={self.user_id}, channel={self.channel}, used={self.used_at is not None})>"


class NotificationDelivery(Base):
    """The outbox: one row per (notification, channel) delivery attempt.

    Written in the **same transaction** as the `Notification` itself
    (app/services/delivery/dispatcher.py), which is the whole reason this
    is a table and not a direct call. Sending inside `create_notification_*`
    would mean either sending before the commit (and delivering a
    notification a rollback then erases) or after it (and losing the
    delivery if the process dies in between) — the classic dual-write
    problem, made worse here because two of the five call sites run inside
    background workers where an exception is swallowed and retried later.
    An INSERT next to the INSERT has neither failure mode, and gives retry
    state somewhere to live.

    In-app/SSE is dispatched inline rather than by the worker
    (`DeliveryChannelAdapter.inline`) — it is in-process, sub-millisecond,
    and its failure mode ("no tab connected") is not retryable, it is
    precisely the condition the other channels exist for. It still gets a
    row, so `SELECT ... GROUP BY channel, status` answers "where did this
    notification actually go" for every channel uniformly.

    `attempts`/`next_attempt_at` carry the backoff; `last_error` is kept
    for the settings UI ("Telegram: bot bị chặn"), because a channel that
    silently stops working is worse than one that says why.
    """
    __tablename__ = "notification_deliveries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    notification_id = Column(
        UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(
        SQLEnum(AttentionChannel, values_callable=_enum_values, name="attentionchannel"),
        nullable=False,
    )
    # Null for channels that aren't user-registered rows — in-app is the
    # standing example: every user has it implicitly, there is nothing to
    # register and nothing to revoke.
    user_channel_id = Column(
        UUID(as_uuid=True), ForeignKey("user_channels.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(
        SQLEnum(DeliveryStatus, values_callable=_enum_values, name="deliverystatus"),
        nullable=False,
        default=DeliveryStatus.PENDING,
    )
    # Why a row is `skipped`, or which of the two it was — "below
    # min_level" and "no adapter" are very different bugs to chase.
    skip_reason = Column(String(64), nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error = Column(Text, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True, index=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        # Idempotency: a retry sweep, a duplicated event, or two workers
        # racing must not produce two sends of the same notification to the
        # same registered channel. `user_channel_id` is nullable so this
        # constraint does not cover in-app (Postgres treats NULLs as
        # distinct) — in-app is dispatched exactly once, inline, by the
        # same call that creates the row, so there is no second writer to
        # race with.
        UniqueConstraint("notification_id", "user_channel_id", name="uq_notification_deliveries_notif_channel"),
        Index("ix_notification_deliveries_claimable", "status", "next_attempt_at"),
    )

    def __repr__(self):
        return f"<NotificationDelivery(notification_id={self.notification_id}, channel={self.channel}, status={self.status})>"


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
    # uuid_generate_v7() at the database level every insert would violate
    # this column's NOT NULL constraint.
    id = Column(
        UUID(as_uuid=True), primary_key=True,
        default=uuid7, server_default=text("uuid_generate_v7()"),
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
