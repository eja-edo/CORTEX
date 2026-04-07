from datetime import datetime
from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator
from enum import Enum

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
    user_id: UUID
    content: str = Field(..., min_length=1, max_length=MAX_NOTE_CONTENT_LENGTH)
    content_type: str = Field(default="markdown", max_length=20)
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
