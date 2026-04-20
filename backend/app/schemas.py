from datetime import datetime
from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator
from enum import Enum

from app.models import AssetStatus, AssetType, IngestJobStatus, IngestJobType, LinkType, SegmentSource, UploadStatus

MAX_NOTE_CONTENT_LENGTH = 50000

class ScheduleType(str, Enum):
    """Schedule type enumeration"""
    CLASS = "CLASS"
    DEADLINE = "DEADLINE"
    EXAM = "EXAM"
    PERSONAL = "PERSONAL"

class ScheduleCreate(BaseModel):
    """Schema for creating a new schedule"""
    title: str = Field(..., min_length=1, max_length=255, description="Schedule title")
    type: ScheduleType = Field(..., description="Schedule type")
    start_time: datetime = Field(..., description="Start time")
    end_time: datetime = Field(..., description="End time")
    location: Optional[str] = Field(None, max_length=255, description="Location or meeting link")
    description: Optional[str] = Field(None, max_length=1000, description="Additional notes")

class ScheduleUpdate(BaseModel):
    """Schema for updating a schedule"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[ScheduleType] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_completed: Optional[bool] = None

class ScheduleResponse(BaseModel):
    """Schema for schedule response"""
    id: UUID
    user_id: UUID
    title: str
    type: ScheduleType
    start_time: datetime
    end_time: datetime
    location: Optional[str]
    description: Optional[str]
    is_completed: bool
    google_synced: bool = False
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ScheduleListResponse(BaseModel):
    """Schema for list of schedules"""
    items: list[ScheduleResponse]
    total: int


class UserCreate(BaseModel):
    """Schema for user registration"""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)


class UserResponse(BaseModel):
    """Schema for user response"""
    id: UUID
    email: EmailStr
    full_name: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """JWT token pair response"""
    access_token: str
    refresh_token: str
    token_type: str


class RefreshTokenRequest(BaseModel):
    """Schema for refresh/logout request payload"""
    refresh_token: str


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str


class AuthorizeRequest(BaseModel):
    """Request body for authorization code generation with PKCE."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    client_id: str = Field(..., min_length=1, max_length=255)
    redirect_uri: str = Field(..., min_length=1, max_length=1000)
    code_challenge: str = Field(..., min_length=43, max_length=255)
    code_challenge_method: str = Field(default="S256", pattern="^(S256|plain|PLAIN)$")
    state: Optional[str] = Field(default=None, max_length=255)


class AuthorizeResponse(BaseModel):
    """Authorization code response."""
    code: str
    expires_in: int
    state: Optional[str] = None


class TokenExchangeRequest(BaseModel):
    """Request body for exchanging authorization code + verifier for tokens."""
    code: str
    code_verifier: str = Field(..., min_length=43, max_length=128)
    client_id: str = Field(..., min_length=1, max_length=255)
    redirect_uri: str = Field(..., min_length=1, max_length=1000)


class NoteCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=MAX_NOTE_CONTENT_LENGTH)
    content_type: str = Field(default="markdown", max_length=20)
    parent_note_id: UUID | None = None
    position: dict[str, Any] = Field(default_factory=lambda: {"x": 0, "y": 0})
    size: dict[str, Any] = Field(default_factory=lambda: {"width": 200, "height": 200})
    style: dict[str, Any] = Field(default_factory=lambda: {"color": "yellow"})

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        if value.lower() != "markdown":
            raise ValueError("Only markdown content_type is supported")
        return "markdown"


class NoteUpdate(BaseModel):
    version: int = Field(..., ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=MAX_NOTE_CONTENT_LENGTH)
    content_type: str | None = Field(default=None, max_length=20)
    parent_note_id: UUID | None = None
    position: dict[str, Any] | None = None
    size: dict[str, Any] | None = None
    style: dict[str, Any] | None = None

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.lower() != "markdown":
            raise ValueError("Only markdown content_type is supported")
        return "markdown"


class NotePatchOp(BaseModel):
    op: str = Field(..., pattern="^(insert|delete|replace)$")
    pos: int = Field(..., ge=0)
    length: int | None = Field(default=None, ge=0)
    text: str | None = None


class NotePatchRequest(BaseModel):
    version: int = Field(..., ge=1)
    patch: list[NotePatchOp]
    position: dict[str, Any] | None = None
    size: dict[str, Any] | None = None
    style: dict[str, Any] | None = None


class NoteRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    note_id: UUID
    user_id: UUID
    version: int
    base_version: int
    patch: list[dict[str, Any]]
    patch_format: str
    content_length: int
    created_at: datetime


class NotePartialUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=MAX_NOTE_CONTENT_LENGTH)
    content_type: str | None = Field(default=None, max_length=20)
    position: dict[str, Any] | None = None
    size: dict[str, Any] | None = None
    style: dict[str, Any] | None = None

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.lower() != "markdown":
            raise ValueError("Only markdown content_type is supported")
        return "markdown"


class BatchUpdateItem(BaseModel):
    id: UUID
    version: int = Field(..., ge=1)
    updates: NotePartialUpdate


class BatchUpdateResponse(BaseModel):
    success: list[UUID]
    failed: list[UUID]


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    parent_note_id: UUID | None
    content: str
    content_type: str
    position: dict[str, Any]
    size: dict[str, Any]
    style: dict[str, Any]
    version: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    rendered_html: str | None = None


class GoogleConnectUrlResponse(BaseModel):
    authorization_url: str
    state: str
    expires_in: int


class GoogleCalendarConnectionStatus(BaseModel):
    connected: bool
    provider: str = "GOOGLE"
    calendar_id: str | None = None
    granted_scopes: list[str] = Field(default_factory=list)
    last_synced_at: datetime | None = None
    has_sync_token: bool = False
    channel_expiration: datetime | None = None
    last_sync_error: str | None = None


class UploadInitRequest(BaseModel):
    filename: str | None = Field(default=None, max_length=255)
    content_type: str | None = Field(default="video/webm", max_length=255)
    # Set 0 for live streaming mode when final size/parts are unknown at init time.
    total_parts: int = Field(default=0, ge=0)
    total_size: int = Field(default=0, ge=0)


class UploadInitResponse(BaseModel):
    upload_id: UUID
    object_key: str
    total_parts: int
    expires_in_seconds: int


class UploadPresignedResponse(BaseModel):
    upload_id: UUID
    part_number: int
    url: str
    expires_in_seconds: int


class UploadPartConfirmRequest(BaseModel):
    upload_id: UUID
    part_number: int = Field(..., ge=1)
    etag: str = Field(..., min_length=1, max_length=255)
    size: int = Field(..., ge=1)
    is_last_part: bool = False


class UploadPartConfirmResponse(BaseModel):
    upload_id: UUID
    part_number: int
    status: str


class UploadCompleteRequest(BaseModel):
    upload_id: UUID
    # Required for live streaming mode where init total_parts == 0.
    total_parts: int | None = Field(default=None, ge=1)
    total_size: int | None = Field(default=None, ge=1)


class UploadCompleteResponse(BaseModel):
    upload_id: UUID
    asset_id: UUID
    object_key: str
    status: UploadStatus


class UploadSessionResponse(BaseModel):
    id: UUID
    status: UploadStatus
    object_key: str
    total_parts: int
    total_size: int
    uploaded_parts: list[int]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class UploadListItemResponse(BaseModel):
    id: UUID
    object_key: str
    filename: str | None
    content_type: str | None
    media_type: str
    total_size: int
    created_at: datetime
    completed_at: datetime | None


class UploadListResponse(BaseModel):
    items: list[UploadListItemResponse]
    total: int
    limit: int
    offset: int


class UploadAccessUrlResponse(BaseModel):
    upload_id: UUID
    object_key: str
    url: str
    expires_in_seconds: int


class AssetCreate(BaseModel):
    type: AssetType
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    source_upload_id: UUID | None = None
    source_object_key: str = Field(..., min_length=1, max_length=1024)
    workspace_id: UUID | None = None


class AssetUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: AssetStatus | None = None
    metadata: dict[str, Any] | None = None


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    workspace_id: UUID | None
    type: AssetType
    status: AssetStatus
    title: str | None
    description: str | None
    source_upload_id: UUID | None
    source_object_key: str
    duration_ms: int | None
    frame_rate: float | None
    width: int | None
    height: int | None
    size_bytes: int | None
    checksum_sha256: str | None
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime
    updated_at: datetime


class SegmentContentInput(BaseModel):
    content_type: str = Field(..., min_length=1, max_length=16)
    content: str = Field(..., min_length=1)
    language: str | None = Field(default=None, max_length=16)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SegmentCreate(BaseModel):
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=1)
    source: SegmentSource
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    keyframe_url: str | None = None
    language: str | None = Field(default=None, max_length=16)
    external_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)
    contents: list[SegmentContentInput] = Field(default_factory=list)

    @field_validator("end_ms")
    @classmethod
    def validate_end_ms(cls, value: int, info):
        start_ms = info.data.get("start_ms")
        if start_ms is not None and value <= start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return value


class SegmentBatchUpsertRequest(BaseModel):
    asset_id: UUID
    segments: list[SegmentCreate]


class SegmentBatchUpsertResponse(BaseModel):
    created: int
    updated: int
    skipped: int


class SegmentContentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content_type: str
    content: str
    language: str | None
    confidence: float | None
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime


class SegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    asset_id: UUID
    start_ms: int
    end_ms: int
    source: SegmentSource
    confidence: float | None
    keyframe_url: str | None
    language: str | None
    external_id: str | None
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime
    updated_at: datetime
    contents: list[SegmentContentResponse] = Field(default_factory=list)


class NoteSegmentLinkInput(BaseModel):
    segment_id: UUID
    linked_asset_id: UUID
    linked_start_ms: int = Field(..., ge=0)
    linked_end_ms: int = Field(..., ge=1)
    link_type: LinkType = LinkType.REFERENCE
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    anchor_text: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("linked_end_ms")
    @classmethod
    def validate_linked_end_ms(cls, value: int, info):
        start_ms = info.data.get("linked_start_ms")
        if start_ms is not None and value <= start_ms:
            raise ValueError("linked_end_ms must be greater than linked_start_ms")
        return value


class NoteSegmentLinkRemoveItem(BaseModel):
    segment_id: UUID
    link_type: LinkType


class NoteSegmentLinkPatchRequest(BaseModel):
    add: list[NoteSegmentLinkInput] = Field(default_factory=list)
    remove: list[NoteSegmentLinkRemoveItem] = Field(default_factory=list)


class NoteSegmentLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    note_id: UUID
    segment_id: UUID
    linked_asset_id: UUID
    linked_start_ms: int
    linked_end_ms: int
    link_type: LinkType
    weight: float
    anchor_text: str | None
    start_offset: int | None
    end_offset: int | None
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime
    updated_at: datetime


class SegmentNoteLinkView(BaseModel):
    note_id: UUID
    link: NoteSegmentLinkResponse


class NoteLinksByAssetResponse(BaseModel):
    note_id: UUID
    by_asset: dict[str, list[NoteSegmentLinkResponse]]


class IngestJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    asset_id: UUID
    job_type: IngestJobType
    stage: str | None
    parent_job_id: UUID | None
    status: IngestJobStatus
    attempt: int
    max_attempts: int
    progress: float
    error_message: str | None
    provider: str | None
    tokens_used: int | None
    cost_usd: float | None
    idempotency_key: str | None
    payload: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SearchResultItem(BaseModel):
    type: str
    id: UUID
    score: float
    snippet: str
    asset_id: UUID | None = None
    asset_title: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    note_title: str | None = None


class SearchResponse(BaseModel):
    query: str
    semantic: bool
    items: list[SearchResultItem]
    total: int


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    type: str
    title: str
    body: str | None
    payload: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
