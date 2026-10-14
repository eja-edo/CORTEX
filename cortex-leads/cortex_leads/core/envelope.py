from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

Status = Literal["ok", "proposed", "blocked", "not_found", "ambiguous", "error"]


class BlockedCode(StrEnum):
    WINDOW_CLOSED = "WINDOW_CLOSED"
    NO_CONSENT = "NO_CONSENT"
    TOUCH_LIMIT = "TOUCH_LIMIT"
    UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"
    FORBIDDEN_PHRASE = "FORBIDDEN_PHRASE"
    OWNER_IS_HUMAN = "OWNER_IS_HUMAN"
    OPTED_OUT = "OPTED_OUT"
    NO_NEW_INFO = "NO_NEW_INFO"
    EFFECT_CEILING = "EFFECT_CEILING"
    NOT_ALLOWED = "NOT_ALLOWED"
    BUDGET = "BUDGET"
    PAUSED = "PAUSED"


class ErrorCode(StrEnum):
    INVALID_ARGS = "INVALID_ARGS"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS_REF = "AMBIGUOUS_REF"
    CONFLICT = "CONFLICT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INTERNAL = "INTERNAL"


class Violation(BaseModel):
    code: BlockedCode
    span: str | None = None
    detail: str | None = None


class ErrorInfo(BaseModel):
    code: ErrorCode
    retryable: bool = False
    fields: list[str] = []


class ToolResult(BaseModel):
    status: Status
    data: Any = None
    note: str | None = None
    violations: list[Violation] = []
    error: ErrorInfo | None = None
    next_step: str | None = None
    action_id: UUID | None = None
    replayed: bool = False
