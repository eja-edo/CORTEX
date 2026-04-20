from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.ext.declarative import declarative_base
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


class CalendarProvider(str, Enum):
    """Supported external calendar providers."""
    GOOGLE = "GOOGLE"


class SyncSource(str, Enum):
    """Identify which side produced the latest change."""
    INTERNAL = "INTERNAL"
    PROVIDER = "PROVIDER"


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
    ARCHIVED = "archived"


class SegmentSource(str, Enum):
    """How the segment was produced."""
    OCR = "ocr"
    ASR = "asr"
    UI_DETECTION = "ui_detection"
    USER_HIGHLIGHT = "user_highlight"
    AI_DETECTION = "ai_detection"


class LinkType(str, Enum):
    """Relationship type between note and segment."""
    REFERENCE = "reference"
    HIGHLIGHT = "highlight"
    DERIVED = "derived"


class DerivativeType(str, Enum):
    """Generated asset derivative files."""
    THUMBNAIL = "thumbnail"
    WAVEFORM = "waveform"
    TRANSCRIPT = "transcript"
    KEYFRAMES = "keyframes"
    SUMMARY_CLIP = "summary_clip"


class Workspace(Base):
    """Team/personal logical container for shared content."""
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    plan = Column(String(32), nullable=False, default="free", server_default=text("'free'"))
    meta = Column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class WorkspaceMember(Base):
    """Workspace membership and role authorization."""
    __tablename__ = "workspace_members"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(32), nullable=False, default="member", server_default=text("'member'"))
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WorkspaceQuota(Base):
    """Workspace limits and utilization counters."""
    __tablename__ = "workspace_quotas"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    max_storage_bytes = Column(BigInteger, nullable=False, default=10737418240, server_default=text("10737418240"))
    used_storage_bytes = Column(BigInteger, nullable=False, default=0, server_default=text("0"))
    max_concurrent_jobs = Column(Integer, nullable=False, default=3, server_default=text("3"))
    max_assets = Column(Integer, nullable=False, default=100, server_default=text("100"))
    ai_tokens_monthly_limit = Column(BigInteger, nullable=False, default=1000000, server_default=text("1000000"))
    ai_tokens_used_month = Column(BigInteger, nullable=False, default=0, server_default=text("0"))
    quota_reset_at = Column(DateTime, nullable=False, server_default=text("date_trunc('month', now()) + interval '1 month'"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Asset(Base):
    """Uploaded or recorded media source tracked by processing pipeline."""
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True, index=True)
    type = Column(SQLEnum(AssetType, values_callable=_enum_values, name="assettype"), nullable=False)
    status = Column(SQLEnum(AssetStatus, values_callable=_enum_values, name="assetstatus"), nullable=False, default=AssetStatus.PENDING, server_default=text("'pending'"))
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    source_upload_id = Column(UUID(as_uuid=True), ForeignKey("uploads.id"), nullable=True, index=True)
    source_object_key = Column(String(1024), nullable=False)
    duration_ms = Column(BigInteger, nullable=True)
    frame_rate = Column(Numeric(8, 3), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
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
        Index("ix_assets_workspace_created", "workspace_id", "created_at"),
        Index("ix_assets_user_status", "user_id", "status"),
    )


class AssetDerivative(Base):
    """Generated derivative artifact associated with an asset."""
    __tablename__ = "asset_derivatives"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    derivative_type = Column(SQLEnum(DerivativeType, values_callable=_enum_values, name="derivativetype"), nullable=False)
    storage_key = Column(String(1024), nullable=False)
    format = Column(String(32), nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    duration_ms = Column(BigInteger, nullable=True)
    meta = Column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_id", "derivative_type", name="uq_asset_derivatives_asset_type"),
    )


class Segment(Base):
    """Atomic timeline chunk extracted from an asset."""
    __tablename__ = "segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    start_ms = Column(BigInteger, nullable=False)
    end_ms = Column(BigInteger, nullable=False)
    source = Column(SQLEnum(SegmentSource, values_callable=_enum_values, name="segmentsource"), nullable=False)
    confidence = Column(Numeric(5, 4), nullable=True)
    keyframe_url = Column(Text, nullable=True)
    language = Column(String(16), nullable=True)
    external_id = Column(String(255), nullable=True)
    meta = Column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_id", "external_id", name="uq_segments_asset_external_id"),
        Index("ix_segments_asset_start", "asset_id", "start_ms"),
        Index("ix_segments_user_created", "user_id", "created_at"),
    )


class SegmentContent(Base):
    """Normalized extracted content per segment and modality."""
    __tablename__ = "segment_contents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    segment_id = Column(UUID(as_uuid=True), ForeignKey("segments.id", ondelete="CASCADE"), nullable=False, index=True)
    content_type = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    language = Column(String(16), nullable=True)
    confidence = Column(Numeric(5, 4), nullable=True)
    meta = Column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("segment_id", "content_type", "language", name="uq_segment_contents_triplet"),
        Index("ix_segment_contents_segment_type", "segment_id", "content_type"),
    )


class NoteSegmentLink(Base):
    """Many-to-many mapping between knowledge notes and timeline segments."""
    __tablename__ = "note_segment_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_id = Column(UUID(as_uuid=True), ForeignKey("segments.id", ondelete="CASCADE"), nullable=False, index=True)
    linked_asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True)
    linked_start_ms = Column(BigInteger, nullable=False)
    linked_end_ms = Column(BigInteger, nullable=False)
    link_type = Column(SQLEnum(LinkType, values_callable=_enum_values, name="linktype"), nullable=False, default=LinkType.REFERENCE, server_default=text("'reference'"))
    weight = Column(Numeric(5, 4), nullable=False, default=1.0, server_default=text("1.0"))
    anchor_text = Column(Text, nullable=True)
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    meta = Column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("note_id", "segment_id", "link_type", name="uq_note_segment_links_unique"),
        Index("ix_note_segment_links_note_type", "note_id", "link_type"),
        Index("ix_note_segment_links_segment_type", "segment_id", "link_type"),
        Index("ix_note_segment_links_asset_time", "linked_asset_id", "linked_start_ms"),
    )


class Bookmark(Base):
    """User bookmarks for fast recall of notable timeline points."""
    __tablename__ = "bookmarks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_id = Column(UUID(as_uuid=True), ForeignKey("segments.id", ondelete="SET NULL"), nullable=True, index=True)
    label = Column(String(255), nullable=True)
    color = Column(String(32), nullable=True)
    meta = Column("metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "asset_id", "segment_id", name="uq_bookmarks_user_asset_segment"),
        Index("ix_bookmarks_user_asset_created", "user_id", "asset_id", "created_at"),
    )


class AssetTimelineCache(Base):
    """Precomputed merged timeline view used for low-latency playback navigation."""
    __tablename__ = "asset_timeline_cache"

    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    is_dirty = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    timeline = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Tag(Base):
    """User or workspace-scoped label."""
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    color = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_tags_workspace_name"),
        UniqueConstraint("user_id", "name", name="uq_tags_user_name"),
    )


class EntityTag(Base):
    """Join table for tags applied to typed entities."""
    __tablename__ = "entity_tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=True, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=True, index=True)
    segment_id = Column(UUID(as_uuid=True), ForeignKey("segments.id", ondelete="CASCADE"), nullable=True, index=True)
    concept_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class IngestJobStatus(str, Enum):
    """Async ingestion job state."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    DEAD = "dead"


class IngestJobType(str, Enum):
    """Pipeline job type."""
    INGEST = "ingest"
    OCR = "ocr"
    ASR = "asr"
    DETECT_UI = "detect_ui"
    SUMMARIZE = "summarize"
    EMBED = "embed"
    CACHE = "cache"


class IngestJob(Base):
    """Worker-dispatched job with cost and progress tracking."""
    __tablename__ = "ingest_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    job_type = Column(SQLEnum(IngestJobType, values_callable=_enum_values, name="ingestjobtype"), nullable=False)
    stage = Column(String(32), nullable=True)
    parent_job_id = Column(UUID(as_uuid=True), ForeignKey("ingest_jobs.id"), nullable=True, index=True)
    status = Column(SQLEnum(IngestJobStatus, values_callable=_enum_values, name="ingestjobstatus"), nullable=False, default=IngestJobStatus.QUEUED, server_default=text("'queued'"))
    attempt = Column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts = Column(Integer, nullable=False, default=3, server_default=text("3"))
    progress = Column(Numeric(5, 2), nullable=False, default=0, server_default=text("0"))
    error_message = Column(Text, nullable=True)
    provider = Column(String(32), nullable=True)
    tokens_used = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(10, 6), nullable=True)
    idempotency_key = Column(String(255), nullable=True, unique=True, index=True)
    payload = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_ingest_jobs_asset_job_stage", "asset_id", "job_type", "stage"),
        Index("ix_ingest_jobs_status_created_at", "status", "created_at"),
    )


class Notification(Base):
    """User notification for ingest and knowledge events."""
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    payload = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
    )


class NoteEmbedding(Base):
    """Vector embedding for a note."""
    __tablename__ = "note_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id = Column(UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    embedding = Column(Text, nullable=False)
    is_current = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("note_id", "model", name="uq_note_embeddings_note_model"),
        Index("ix_note_embeddings_note_current", "note_id", "is_current"),
    )


class SegmentEmbedding(Base):
    """Vector embedding for a segment."""
    __tablename__ = "segment_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    segment_id = Column(UUID(as_uuid=True), ForeignKey("segments.id", ondelete="CASCADE"), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    embedding = Column(Text, nullable=False)
    is_current = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("segment_id", "model", name="uq_segment_embeddings_segment_model"),
        Index("ix_segment_embeddings_segment_current", "segment_id", "is_current"),
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

    __table_args__ = (
        Index("ix_notes_user_id", "user_id"),
        Index("ix_notes_user_id_updated_at", "user_id", "updated_at"),
        Index("ix_notes_user_parent_updated_at", "user_id", "parent_note_id", "updated_at"),
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
