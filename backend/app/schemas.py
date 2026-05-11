from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator, model_validator
from enum import Enum

from app.models import AssetStatus, AssetType, UploadStatus

MAX_NOTE_CONTENT_LENGTH = 50000

class ScheduleType(str, Enum):
    """Schedule type enumeration"""
    CLASS = "CLASS"
    DEADLINE = "DEADLINE"
    EXAM = "EXAM"
    PERSONAL = "PERSONAL"


class EditScope(str, Enum):
    """Edit scope for recurring event instances."""
    THIS_ONLY = "this_only"
    THIS_AND_AFTER = "this_and_after"
    ALL = "all"


class ReminderConfig(BaseModel):
    """Reminder configuration input."""
    minutes_before: int = Field(..., ge=1, le=43200, description="Minutes before event to trigger reminder")
    method: str = Field(default="push", pattern="^(push|email)$")


class ReminderResponse(BaseModel):
    """Reminder response schema."""
    id: UUID
    minutes_before: int
    method: str
    scheduled_at: datetime
    status: str

    class Config:
        from_attributes = True


class RecurrenceRuleInput(BaseModel):
    """Recurrence rule input schema."""
    freq: str = Field(..., pattern="^(NONE|DAILY|WEEKLY|MONTHLY)$")
    interval: int = Field(default=1, ge=1, le=365)
    until: Optional[datetime] = None
    count: Optional[int] = Field(default=None, ge=1, le=730)
    tzid: str = Field(default="Asia/Ho_Chi_Minh")

    @model_validator(mode="after")
    def validate_recurrence(self):
        # No byday validation needed - uses start_time's weekday automatically
        if self.until and self.count:
            raise ValueError("Use only one of 'until' or 'count'")
        return self

class ScheduleCreate(BaseModel):
    """Schema for creating a new schedule"""
    title: str = Field(..., min_length=1, max_length=255, description="Schedule title")
    type: ScheduleType = Field(..., description="Schedule type")
    start_time: datetime = Field(..., description="Start time")
    end_time: datetime = Field(..., description="End time")
    location: Optional[str] = Field(None, max_length=255, description="Location or meeting link")
    description: Optional[str] = Field(None, max_length=1000, description="Additional notes")
    recurrence: Optional[RecurrenceRuleInput] = Field(default=None, description="Recurrence rule")
    reminders: Optional[List[ReminderConfig]] = Field(default=None, max_length=5, description="Reminder configurations")

class ScheduleUpdate(BaseModel):
    """Schema for updating a schedule"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[ScheduleType] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_completed: Optional[bool] = None
    recurrence: Optional[RecurrenceRuleInput] = None
    reminders: Optional[List[ReminderConfig]] = None

class ScheduleResponse(BaseModel):
    """Schema for schedule response"""
    id: Optional[UUID] = None  # None for virtual instances
    user_id: UUID
    title: str
    type: ScheduleType
    start_time: datetime
    end_time: datetime
    location: Optional[str]
    description: Optional[str]
    is_completed: bool
    recurrence: Optional[RecurrenceRuleInput] = None
    reminders: List[ReminderResponse] = []
    is_recurring: bool = False
    is_exception: bool = False
    is_cancelled: bool = False
    recurrence_id: Optional[UUID] = None
    original_start_time: Optional[datetime] = None
    is_virtual: bool = False  # True if instance not yet persisted
    google_synced: bool = False
    version: int = 1
    created_at: Optional[datetime] = None  # Optional for virtual instances
    updated_at: Optional[datetime] = None  # Optional for virtual instances
    
    class Config:
        from_attributes = True

class ScheduleListResponse(BaseModel):
    """Schema for list of schedules"""
    items: list[ScheduleResponse]
    total: int


class ScheduleInstanceUpdate(BaseModel):
    """Schema for updating a recurring event instance."""
    edit_scope: EditScope = Field(..., description="this_only | this_and_after | all")
    updates: ScheduleUpdate


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
    workspace_id: UUID  # Required: which workspace this note belongs to
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
    workspace_id: UUID | None
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
    workspace_id: UUID | None = Field(default=None, description="Optional: workspace to associate uploaded asset with")


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
    workspace_id: UUID | None = Field(default=None, description="Workspace to assign asset to. If not provided, uses personal workspace.")
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
    workspace_id: UUID  # Required: which workspace this asset belongs to
    type: AssetType
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    source_upload_id: UUID | None = None
    source_object_key: str = Field(..., min_length=1, max_length=1024)


class AssetUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: AssetStatus | None = None
    metadata: dict[str, Any] | None = None


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    workspace_id: UUID
    type: AssetType
    status: AssetStatus
    title: str | None
    description: str | None
    source_upload_id: UUID | None
    source_object_key: str
    duration_ms: int | None
    frame_rate: float | None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None
    checksum_sha256: str | None
    metadata: dict[str, Any] = Field(validation_alias="meta")
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


class AgentChatRequest(BaseModel):
    """Request body for agent chat endpoint."""
    message: str = Field(..., min_length=1, max_length=5000, description="User message")
    conversation_id: UUID | None = Field(default=None, description="Existing conversation ID, or null to start new")
    workspace_id: UUID | None = Field(default=None, description="Optional workspace context")


class AgentChatResponse(BaseModel):
    """Response body for agent chat endpoint."""
    conversation_id: UUID = Field(..., description="Conversation ID")
    reply: str = Field(..., description="Agent's text response")


class AgentStreamingStartResponse(BaseModel):
    """Response body for streaming chat endpoint."""
    status: str = Field(default="streaming_started", description="Status indicating streaming has begun")
    conversation_id: UUID | None = Field(default=None, description="Conversation ID if available")
    message: str = Field(default="Events will be streamed via SSE", description="Informational message")
