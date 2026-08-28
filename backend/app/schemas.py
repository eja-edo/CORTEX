from datetime import datetime, time
from typing import Any, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator, model_validator
from enum import Enum

from app.models import (
    AssetStatus,
    AssetType,
    AttentionChannel,
    AttentionItemType,
    AttentionLevel,
    AttentionResponse,
    ProjectOrigin,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
    UploadStatus,
)

MAX_NOTE_CONTENT_LENGTH = 50000

class ScheduleType(str, Enum):
    """Schedule type enumeration"""
    CLASS = "CLASS"
    DEADLINE = "DEADLINE"
    EXAM = "EXAM"
    PERSONAL = "PERSONAL"
    CRON_EVENT = "CRON_EVENT"


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
    workflow_id: Optional[str] = Field(default=None, description="Linked workflow ID")

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
    workflow_id: Optional[str] = None

class ScheduleResponse(BaseModel):
    """Schema for schedule response"""
    id: Optional[UUID] = None  # None for virtual instances
    user_id: UUID
    # Nullable và thường là NULL. Sự kiện chỉ được gắn dự án khi có tín
    # hiệu chắc chắn (DESIGN 4.2) — frontend dùng nó để tô màu, và NULL
    # phải hiện ra như "chưa thuộc dự án", không phải như một dự án nữa.
    project_id: Optional[UUID] = None
    title: str
    type: ScheduleType
    start_time: datetime
    end_time: datetime
    location: Optional[str]
    description: Optional[str]
    is_completed: bool
    recurrence: Optional[RecurrenceRuleInput] = None
    reminders: List[ReminderResponse] = []
    workflow_id: Optional[UUID] = None
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
    """Tạo ghi chú.

    `project_id` là container của ghi chú (DESIGN 11.4). Nó tuỳ chọn, và
    **thiếu nó là hợp lệ** — service khi đó rơi về dự án cá nhân,
    cùng đáy thang mà task đã dùng (3.5 bước 3). Bắt buộc một container ở
    tầng schema sẽ làm "ghi nhanh một ý" trở thành thao tác cần chọn chỗ
    trước, và đó là cách chắc nhất để không ai ghi gì.
    """

    project_id: UUID | None = None
    content: str = Field(..., min_length=1, max_length=MAX_NOTE_CONTENT_LENGTH)
    content_type: str = Field(default="markdown", max_length=20)
    parent_note_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
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
    title: str | None = Field(default=None, min_length=1, max_length=500)
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


class NoteProposalStatus(str, Enum):
    PENDING = "pending"
    APPLYING = "applying"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class NoteProposalCreatorType(str, Enum):
    USER = "USER"
    AGENT = "AGENT"
    WORKFLOW = "WORKFLOW"
    SYSTEM = "SYSTEM"


class NoteEditProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    note_id: UUID
    base_revision_id: UUID | None
    base_version: int
    patch: list[dict[str, Any]]
    creator_type: str
    creator_id: str
    status: str
    approved_by: UUID | None
    approved_at: datetime | None
    rejected_by: UUID | None
    rejected_at: datetime | None
    last_viewed_at: datetime | None
    expires_at: datetime
    conversation_id: UUID | None
    created_at: datetime
    updated_at: datetime
    # Computed fields (not stored in DB)
    old_content: str | None = None
    new_content: str | None = None


class NoteProposalApproveResponse(BaseModel):
    proposal_id: UUID
    note_id: UUID
    status: str
    version: int


class NoteProposalRejectResponse(BaseModel):
    proposal_id: UUID
    note_id: UUID
    status: str


class NoteProposalListResponse(BaseModel):
    items: list[NoteEditProposalResponse]
    total: int


class PlanProposalItemIn(BaseModel):
    """One draft item inside a plan proposal (3.2 AI Planner) — a task or
    an event that hasn't been created yet.

    `key` is a proposal-local id the caller invents (e.g. "t1"), used only
    to let a task's `parent_key` reference an earlier task in the SAME
    list — it is never a real Task/Schedule id. Fields not relevant to the
    item's `type` are rejected rather than silently ignored, since a typo'd
    field (e.g. `start_time` on a task) would otherwise be dropped and
    quietly do nothing.
    """
    key: str = Field(..., min_length=1, max_length=50)
    type: Literal["task", "event"]
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)

    # Task-only
    due_date: datetime | None = None
    priority: str | None = None
    parent_key: str | None = None
    related_event_key: str | None = Field(
        default=None,
        description="key of an EVENT item in this same proposal this task is a checklist item of",
    )

    # Event-only
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = None
    recurrence: dict[str, Any] | None = Field(
        default=None,
        description="{freq: DAILY|WEEKLY|MONTHLY, interval?, until?, count?, tzid?} — for a repeating block, don't propose N one-off events instead",
    )

    @model_validator(mode="after")
    def _fields_match_type(self) -> "PlanProposalItemIn":
        task_only = {
            "due_date": self.due_date,
            "priority": self.priority,
            "parent_key": self.parent_key,
            "related_event_key": self.related_event_key,
        }
        event_only = {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "location": self.location,
            "recurrence": self.recurrence,
        }
        if self.type == "task":
            set_event_fields = [name for name, value in event_only.items() if value is not None]
            if set_event_fields:
                raise ValueError(f"task item '{self.key}' cannot set event field(s): {set_event_fields}")
        else:
            set_task_fields = [name for name, value in task_only.items() if value is not None]
            if set_task_fields:
                raise ValueError(f"event item '{self.key}' cannot set task field(s): {set_task_fields}")
            if self.start_time is None or self.end_time is None:
                raise ValueError(f"event item '{self.key}' requires start_time and end_time")
        return self


class PlanProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    conversation_id: UUID | None
    items: list[dict[str, Any]]
    status: str
    creator_type: str
    creator_id: str
    created_at: datetime
    expires_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None


class PlanProposalListResponse(BaseModel):
    items: list[PlanProposalResponse]
    total: int


class PlanProposalApproveRequest(BaseModel):
    """Body for POST /plan-proposals/{id}/approve.

    `items` omitted (or null) means "create exactly what was proposed".
    When provided, it's the user-edited/filtered set actually applied —
    an item left out simply isn't created; it isn't a rejection of the
    whole proposal.
    """
    items: list[PlanProposalItemIn] | None = None


class PlanProposalItemResult(BaseModel):
    key: str
    type: Literal["task", "event"]
    outcome: Literal["created", "failed"]
    id: UUID | None = None
    error: str | None = None


class PlanProposalApproveResponse(BaseModel):
    proposal_id: UUID
    status: str
    results: list[PlanProposalItemResult]
    created_count: int
    failed_count: int


class PlanProposalRejectResponse(BaseModel):
    proposal_id: UUID
    status: str


class NoteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    # Container của ghi chú (DESIGN 11.4).
    project_id: UUID | None
    parent_note_id: UUID | None
    title: str
    content_type: str
    position: dict[str, Any]
    size: dict[str, Any]
    style: dict[str, Any]
    version: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    # Container của ghi chú (DESIGN 11.4).
    project_id: UUID | None
    parent_note_id: UUID | None
    title: str
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



class TodayReason(BaseModel):
    """Why a task is being suggested today (Milestone 2.7).

    `impact` is a full sentence naming a consequence — "Quá hạn 3 ngày, MVP
    còn 12 ngày và còn 4 việc chưa xong". It is never a label like
    "priority: high": a label makes the user do the interpreting, which is
    the thing this screen exists to stop.

    Composed server-side because it *is* the product's output. A client
    assembling its own sentence could show one that isn't true.
    """
    key: str = Field(..., description="Stable machine id for the reason, e.g. task.overdue")
    impact: str = Field(
        ...,
        min_length=1,
        description="The consequence, in one sentence the user can act on",
    )


class TodayNowAction(BaseModel):
    """One "should do now" card. Never valid without its reason."""
    task_id: UUID
    title: str
    reason: TodayReason
    due_date: datetime | None = None
    priority: TaskPriority | None = None


class TodayNeedsConfirmationItem(BaseModel):
    """One task the extraction pipeline guessed at, waiting on a yes/no.

    Kept off `now_actions`/`suggestions` on purpose: those two lists are
    already-real work Cortex is confident about, and a `pending_confirm`
    task hasn't earned that yet — showing it there would present an AI
    guess as validated fact. Replaces the old `TodayWaitingItem` (formerly
    fed by `Commitment`, folded into `Task`).
    """
    task_id: UUID
    title: str
    due_date: datetime | None = None


class TodayResponse(BaseModel):
    """Everything the "Hôm nay" screen renders."""
    state: Literal[
        "onboarding", "nothing_urgent", "all_clear", "has_actions"
    ] = Field(
        ...,
        description="Which design the screen shows. Served, not inferred, so no state "
                    "falls through to a default empty table.",
    )
    status_line: str | None = Field(
        None,
        description="The one sentence at the top. No data source in Phase 2 without Goal "
                    "and without 3.3's free-slot half, so this is omitted rather than guessed.",
    )
    now_actions: list[TodayNowAction] = Field(default_factory=list)
    suggestions: list[TodayNowAction] = Field(
        default_factory=list,
        description="Only for `nothing_urgent`: things the user *could* start. "
                    "Never urgency invented to fill the screen.",
    )
    needs_confirmation: list[TodayNeedsConfirmationItem] = Field(default_factory=list)


class NextActionAtRisk(BaseModel):
    """One task whose `compute_risk` score crossed the risk threshold
    (Milestone 6.8/4.4), surfaced on its own rather than folded into
    `now_actions` — 3.1 caps `now_actions` at `MAX_NOW_ACTIONS`, so a
    severely at-risk task can still get crowded out of that top-3 list by
    other overdue work. This is where it stays visible regardless."""
    task_id: UUID
    title: str
    risk_score: float
    impact: str = Field(
        ..., description="The consequence, in one sentence the user can act on — "
                          "same convention as TodayReason.impact",
    )


class NextActionResponse(BaseModel):
    """The "what should I do next?" entry point (Milestone 3.5) — 3.1's
    ranking plus 6.8/4.4's severity signal in one response, so a caller
    doesn't have to hit two endpoints and reconcile risk scores itself."""
    state: Literal[
        "onboarding", "nothing_urgent", "all_clear", "has_actions"
    ] = Field(..., description="Same state machine as TodayResponse.state.")
    now_actions: list[TodayNowAction] = Field(default_factory=list)
    suggestions: list[TodayNowAction] = Field(default_factory=list)
    needs_confirmation: list[TodayNeedsConfirmationItem] = Field(default_factory=list)
    at_risk: list[NextActionAtRisk] = Field(default_factory=list)


class CalendarItem(BaseModel):
    """One row on the calendar, from either table (Milestone 2.6).

    A single shape for both so the frontend never has to know there are two
    tables. `render_as` is served rather than derived: the client should not
    re-implement the kind→rendering mapping, because getting it wrong is how
    a task ends up drawn as a time block.

    The fields are deliberately per-kind and null otherwise — a task has no
    `start_time` because **a task does not occupy time**. That asymmetry is
    the point of the whole milestone, not an oversight.
    """
    id: UUID
    kind: Literal["schedule", "task"]
    render_as: Literal["block", "marker"] = Field(
        ...,
        description="block = occupies a time range in the grid; marker = a point in the day. "
                    "Served, not inferred, so the client can't get the mapping wrong.",
    )
    title: str
    # schedule only — the span it occupies.
    start_time: datetime | None = None
    end_time: datetime | None = None
    # task only. Usually that day at 00:00; can carry a real time (e.g. an
    # event checklist item inherits the event's end_time). Either way the
    # calendar still draws it as `render_as="marker"`, a day cell — never a
    # clock position — so it can't be mistaken for booked time.
    due_date: datetime | None = None
    status: str = Field(
        ...,
        description="schedule: scheduled | completed | cancelled. task: todo | in_progress | done | cancelled.",
    )
    location: str | None = None      # schedule only


class TaskCreate(BaseModel):
    """Request body for POST /tasks (Milestone 2.5).

    `related_event_id` is optional; a task attached to nothing is the
    common case. `priority` is optional too — unset just means it doesn't
    get a priority boost in `app.services.today`'s ranking.

    `source_conversation_id`/`source_message_id` are provenance for a task
    the extraction pipeline creates (formerly `Commitment`'s fields, see
    `app.services.task_extraction`) — a client creating a task directly
    leaves them null.
    """
    title: str = Field(..., min_length=1, max_length=255)
    status: TaskStatus = TaskStatus.TODO
    due_date: datetime | None = None
    priority: TaskPriority | None = None
    description: str | None = Field(default=None, max_length=10000)
    # Optional on the wire, never null on the row. The stored column is
    # NOT NULL; leaving this unset just means the caller has no opinion and
    # `ProjectService.resolve_for_task` picks — the event's project, else
    # the personal project (DESIGN 3.5).
    project_id: UUID | None = None
    related_event_id: UUID | None = None
    parent_task_id: UUID | None = None
    source_conversation_id: UUID | None = None
    source_message_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title cannot be empty")
        return stripped


class TaskUpdate(BaseModel):
    """Request body for PATCH /tasks/{id}.

    A `status` here is validated against the state machine in
    `app.services.tasks` — an illegal transition is rejected by the service,
    not merely by this schema.
    """
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: TaskStatus | None = None
    due_date: datetime | None = None
    priority: TaskPriority | None = None
    description: str | None = Field(default=None, max_length=10000)
    related_event_id: UUID | None = None
    parent_task_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title cannot be empty")
        return stripped


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    # Không nullable: mọi task thuộc đúng một project (DESIGN 3.3).
    # Frontend dùng trường này để tô màu và để lọc.
    project_id: UUID
    title: str
    status: TaskStatus
    due_date: datetime | None
    priority: TaskPriority | None
    description: str | None
    related_event_id: UUID | None
    parent_task_id: UUID | None
    source_conversation_id: UUID | None
    source_message_id: UUID | None
    completed_at: datetime | None
    # Per-occurrence completion on a recurring event's checklist task — see
    # `models.Task.recurrence_id`. `recurrence_id` set means this task IS an
    # exception row (its own status, distinct from the template it
    # overrides); unset on every ordinary task.
    recurrence_id: UUID | None = None
    original_start_time: datetime | None = None
    is_exception: bool = False
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    """Tạo tay — **lối phụ, không phải cửa chính** (DESIGN 9.1).

    Cửa chính là 4.1: một channel Mezon có việc thì tự thành dự án. Endpoint
    này tồn tại cho trường hợp người dùng biết chính xác họ muốn gì và
    không có channel nào — và cho `create_project` của agent, vốn bị hạn
    chế đúng vào tình huống người dùng nói thẳng tên và ý định (9.2).

    Không nhận `source_channel_id`: neo một dự án vào channel là việc của
    quy tắc suy ra, không phải của người dùng gõ tay một chuỗi id.
    """

    name: str = Field(..., min_length=1, max_length=255)
    deadline: datetime | None = None


class ProjectUpdate(BaseModel):
    """Sửa `name`, `deadline`, `status`. Tất cả tuỳ chọn.

    `deadline` dùng `Field(default=...)` chứ không mặc định `None` ngầm, vì
    ở đây `None` là một giá trị **có nghĩa** — "bỏ hạn" — khác hẳn với
    "không nhắc tới hạn". `model_fields_set` là thứ phân biệt hai cái, và
    service đọc nó (xem `ProjectService.update`).
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    deadline: datetime | None = None
    status: ProjectStatus | None = None


class ProjectResponse(BaseModel):
    """Một dự án kèm số liệu tóm tắt — DESIGN 9.1.

    Số liệu đi kèm chứ không nằm ở endpoint riêng: mọi chỗ hiển thị một dự
    án đều cần chúng cùng lúc (bộ chuyển dự án, màn Việc, `list_projects`
    của agent), và tách ra chỉ tạo N+1 ở phía client.

    `risk` là `project_risk` (7.1) — cùng con số đã xếp hạng màn Hôm nay,
    nên hai bề mặt không thể nói hai điều khác nhau về cùng một dự án.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: ProjectStatus
    origin: ProjectOrigin
    # Suy ra từ `max(due_date)` mỗi ngày một lần, trừ khi người dùng khoá
    # (DESIGN 4.3). `None` là hợp lệ và phổ biến — dự án cá nhân **luôn**
    # `None`, và đó là bất biến chịu lực ở 3.4.
    deadline: datetime | None
    deadline_is_manual: bool
    # Channel Mezon của dự án. Frontend không hiển thị nó; nó có mặt để
    # trả lời "nhắc cấp dự án sẽ về đâu" (8.1) mà không phải đoán.
    source_channel_id: str | None
    open_task_count: int
    completed_task_count: int
    member_count: int
    risk: float
    created_at: datetime
    updated_at: datetime


class TaskProjectUpdate(BaseModel):
    """Chuyển một task sang dự án khác — `PATCH /tasks/{id}/project`.

    Cố ý là endpoint riêng chứ không phải một trường trong `TaskUpdate`:
    đổi dự án ghi thêm một nhãn cho 4.4, còn sửa tiêu đề thì không. Trộn
    hai thứ vào một đường ghi nghĩa là mọi lần sửa tiêu đề đều phải đi qua
    nhánh quyết định "đây có phải một lượt sửa quy gán không".
    """

    project_id: UUID


class ScheduleProjectUpdate(BaseModel):
    """Gán một chuỗi sự kiện vào dự án — `PATCH /schedules/{id}/project`.

    `None` gỡ liên kết. Chỉ hợp lệ trên hàng template (DESIGN 3.2): đặt lên
    occurrence exception thì một chuỗi 30 lần lặp sinh 30 hàng cùng project
    và quy tắc suy ra ở 3.5 bước 2 sẽ trôi.
    """

    project_id: UUID | None


class ScheduleProjectUpdateResponse(BaseModel):
    """Kết quả gán chuỗi, kèm **số task cũ bị ảnh hưởng**.

    Gán chuỗi **không** tự đổi project của các task đã tạo từ nó (DESIGN
    3.5) — task đã có project riêng, ghi đè hàng loạt là hành vi phá hoại.
    Con số này để UI hỏi *"chuyển N việc cũ sang theo không?"* thay vì làm
    im lặng rồi để người dùng phát hiện sau.
    """

    schedule_id: UUID
    project_id: UUID | None
    affected_task_count: int


class InternalTaskItem(BaseModel):
    """Một action item từ bot họp — `docs/DESIGN.md` mục 9.1.

    Mọi trường định danh đều **tuỳ chọn trừ `title`**, và mỗi cái vắng mặt
    làm hệ thống lùi một nấc chứ không làm nó hỏng:

    - không `assignee_*` → item bị bỏ qua và báo lại (P7: không đoán người);
    - không `source_channel_id` → không có dự án từ channel, rơi về thang
      3.5 (dự án của sự kiện, rồi dự án cá nhân);
    - không `provider_event_id` → task không gắn cuộc họp nào, và đó là
      trạng thái bình thường của phần lớn task.

    `external_id` là thứ duy nhất nên coi là bắt buộc trên thực tế dù schema
    cho phép thiếu: không có nó, mỗi lần webhook được gửi lại sẽ đẻ một bản
    sao, và bản sao không bị dedup của Attention Gate gộp.
    """

    title: str = Field(..., min_length=1, max_length=255)
    external_id: str | None = Field(
        default=None,
        max_length=255,
        description="Id của action item ở hệ thống nguồn. Bỏ qua item đã nhận.",
    )
    assignee_mezon_user_id: str | None = Field(
        default=None,
        description="Người nhận việc, theo Mezon user id. Phải là liên kết đã xác minh.",
    )
    assignee_user_id: UUID | None = Field(
        default=None, description="Người nhận theo Cortex user id, nếu bên gửi đã biết."
    )
    source_channel_id: str | None = Field(
        default=None,
        description="Channel Mezon cuộc họp được đăng vào — danh tính dự án (QĐ-2).",
    )
    source_channel_name: str | None = Field(
        default=None, description="Tên channel, dùng đặt tên dự án khi tạo lười."
    )
    provider_event_id: str | None = Field(
        default=None, description="Id sự kiện Google của cuộc họp, để ghi nguồn gốc."
    )
    due_date: datetime | None = None
    priority: TaskPriority | None = None
    description: str | None = Field(default=None, max_length=10000)


class InternalTaskBatch(BaseModel):
    """Cả cuộc họp một lần.

    Lô chứ không phải từng item, vì đó là hình dạng dữ liệu thật: bot chốt
    biên bản rồi đẩy toàn bộ action item. `MAX_ITEMS` chặn một biên bản
    hỏng biến thành vài nghìn task.
    """

    items: list[InternalTaskItem] = Field(..., min_length=1, max_length=100)


class InternalTaskItemResult(BaseModel):
    external_id: str | None
    task_id: UUID | None
    created: bool
    # `None` nghĩa là vào được. Có giá trị thì bot cần nói lại với người
    # dùng ở channel, thay vì im lặng đánh rơi việc.
    skipped_reason: str | None


class InternalTaskBatchResult(BaseModel):
    created_count: int
    skipped_count: int
    items: list[InternalTaskItemResult]


class TaskRejectionCheck(BaseModel):
    """Answer to "has the user already rejected this suggestion?" — the
    guard that stops the extractor re-proposing a task the user turned
    down. Mirrors the removed `CommitmentRejectionCheck`."""
    fingerprint: str
    rejected_before: bool
    rejected_task_id: UUID | None = None
    rejected_at: datetime | None = None


class AttentionSurfaceCreate(BaseModel):
    """Request body for POST /attention-log — record one surfacing decision.

    `level=silent` is a legitimate, expected value here: a decision not to
    speak is still a decision, and recording it is the whole point of this
    table (2.9).
    """
    item_type: AttentionItemType
    item_id: UUID
    reason_key: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Stable string naming why this surfaced, e.g. 'task.overdue'. "
                    "Half of the dedup key — keep it stable across releases.",
    )
    level: AttentionLevel
    channel: AttentionChannel = AttentionChannel.IN_APP

    @field_validator("reason_key")
    @classmethod
    def reason_key_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason_key cannot be empty")
        return stripped


class AttentionResponseUpdate(BaseModel):
    """Request body for POST /attention-log/{id}/response.

    `no_response` is rejected: it's the initial state of every row, not
    something a user can report. Allowing it would let a real response be
    silently erased, and 6.9 would count that as "never answered".
    """
    response: AttentionResponse

    @field_validator("response")
    @classmethod
    def must_be_an_actual_response(cls, value: AttentionResponse) -> AttentionResponse:
        if value is AttentionResponse.NO_RESPONSE:
            raise ValueError(
                "no_response is the initial state, not a response — use "
                "accepted, dismissed, or ignored"
            )
        return value


class AttentionLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    item_type: AttentionItemType
    item_id: UUID
    reason_key: str
    surfaced_at: datetime
    level: AttentionLevel
    channel: AttentionChannel
    response: AttentionResponse
    responded_at: datetime | None


class AttentionSurfaceResult(BaseModel):
    """What happened to a surfacing request.

    `suppressed=True` means an identical (item_id, reason_key) is still
    inside the dedup window, so nothing was written and `log` is null. The
    caller gets a 200, not an error — being told "already surfaced" is a
    normal answer, not a failure.
    """
    suppressed: bool
    reason: str | None = Field(
        default=None, description="Why it was suppressed, when it was"
    )
    dedup_window_hours: int
    log: AttentionLogResponse | None = None


class AttentionReasonSummary(BaseModel):
    """One reason_key's history for a single item."""
    reason_key: str
    surface_count: int = Field(..., description="Times surfaced, including silent decisions")
    silent_count: int = Field(..., description="How many of those were decisions NOT to speak")
    first_surfaced_at: datetime
    last_surfaced_at: datetime
    last_level: AttentionLevel
    responses: dict[str, int] = Field(
        default_factory=dict, description="Count per response value"
    )


class AttentionItemHistory(BaseModel):
    """Answers 2.9 M2 in one payload: has this item been surfaced, for what
    reasons, how many times, and how did the user respond?"""
    item_id: UUID
    surfaced: bool
    total_surfacings: int
    reasons: list[AttentionReasonSummary]


class UserPreferencesResponse(BaseModel):
    """Quiet hours null means none configured — see UserPreferences'
    docstring in app.models."""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    quiet_hours_start: time | None
    quiet_hours_end: time | None
    # None = no choice recorded → the catalogue default. Set from the
    # Mezon bot's `*model` command; see UserPreferences.chat_model.
    chat_model: str | None = None


class UserPreferencesUpdate(BaseModel):
    """Both fields required together: partial update would leave a start
    with no end (or vice versa), which `is_in_quiet_hours` can't interpret.
    Send both as null to clear quiet hours entirely."""
    quiet_hours_start: time | None
    quiet_hours_end: time | None

    @model_validator(mode="after")
    def _both_or_neither(self) -> "UserPreferencesUpdate":
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet_hours_start and quiet_hours_end must be set together, or both null")
        return self


class ChatModelUpdate(BaseModel):
    """Body for PUT /api/preferences/chat-model.

    Its own endpoint rather than a field on `UserPreferencesUpdate`,
    because that one requires both quiet-hours fields together — a caller
    changing the model would have to send quiet hours it has no business
    knowing about, and would clear them by omission.

    `null` clears the choice, which is not the same as picking the default
    model explicitly only in that it keeps following the default if the
    default ever changes.
    """
    model_config = ConfigDict(protected_namespaces=())

    chat_model: str | None


class ReasonPreference(BaseModel):
    """One row of the redesigned 4.5 audit/toggle list — see A2's section
    in docs/planning-v3.md for why this is a per-user column instead of a
    system-workflow toggle. `base_level`/`description` come from the
    catalog (app.services.attention_reason_catalog), `enabled` from
    `UserPreferences.disabled_reason_keys`.

    `dismiss_count`/`effective_level` are the Feedback Loop's visibility
    half (6.9 M2): `effective_level` is what `base_level` actually becomes
    after `app.services.feedback_loop.apply_downgrade` — the same
    computation the Gate itself runs, surfaced here so a user can see
    *why* a reason quieted down, not just that it did."""
    reason_key: str
    description: str
    base_level: AttentionLevel
    enabled: bool
    dismiss_count: int
    effective_level: AttentionLevel


class ReasonPreferenceUpdate(BaseModel):
    enabled: bool


class UserChannelResponse(BaseModel):
    """One registered delivery route (bước 0 — app/services/delivery/).

    `address` is echoed back masked, never in full: these are push
    endpoints and chat ids, and the settings list only needs to let a user
    tell their three browsers apart — which is what `label` is for.
    `last_error` is here because a channel that silently stops working is
    worse than one that says why.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel: AttentionChannel
    label: str | None
    address_hint: str
    enabled: bool
    verified: bool
    min_level: AttentionLevel
    last_used_at: datetime | None
    created_at: datetime


class UserChannelCreate(BaseModel):
    channel: AttentionChannel
    address: str = Field(min_length=1, max_length=2048)
    label: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    # Omit to take the adapter's default floor. Boundary #2: registering a
    # device must work without the user choosing anything.
    min_level: AttentionLevel | None = None


class ChannelLinkCodeResponse(BaseModel):
    """What the web app shows the user to type into the chat."""
    code: str
    channel: AttentionChannel
    expires_in: int
    # The exact string to send, so the UI never has to hardcode the bot's
    # command syntax and drift from it.
    instruction: str


class ChannelLinkCodeRequest(BaseModel):
    channel: AttentionChannel


class ChannelResolveResponse(BaseModel):
    """Answer to "who is this chat account?".

    `linked: false` instead of a 404 so the bot can distinguish "not linked
    yet" — which deserves friendly instructions — from a transport failure,
    which deserves an apology and a retry.
    """
    linked: bool
    user_id: UUID | None = None
    channel_id: UUID | None = None
    enabled: bool | None = None


class ChannelRedeemRequest(BaseModel):
    """Sent by the bot, never by a browser — see `redeem_link_code`."""
    code: str = Field(min_length=1, max_length=12)
    channel: AttentionChannel
    address: str = Field(min_length=1, max_length=2048)
    label: str | None = Field(default=None, max_length=120)


class UserChannelUpdate(BaseModel):
    """Every field optional — this endpoint is how a user turns a channel
    off or raises its floor, and neither should require restating the
    other."""
    enabled: bool | None = None
    min_level: AttentionLevel | None = None
    label: str | None = Field(default=None, max_length=120)


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
    needs_reauth: bool = False


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
    project_id: UUID | None = None
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
    project_id: UUID | None = None
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


class NotificationBlock(BaseModel):
    type: str  # text, image, html, code, markdown, etc.
    text: str | None = None
    url: str | None = None
    html: str | None = None
    language: str | None = None
    content: str | None = None


class NotificationAction(BaseModel):
    label: str
    action: str = "navigate"  # navigate, dismiss, callback
    url: str | None = None
    payload: dict[str, Any] | None = None


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    type: str
    title: str
    body: str | None
    content: list[NotificationBlock] = []
    actions: list[NotificationAction] = []
    payload: dict[str, Any]
    read_at: datetime | None
    created_at: datetime
    # Null for notifications created outside the Attention Gate's gated
    # path (pass-through system alerts — see attention_gate.py's module
    # docstring). When set, `attention_log_id` is what the client should
    # send back to POST /attention-log/{id}/response on dismiss/click —
    # the raw material for the Feedback Loop (6.9).
    reason_key: str | None = None
    attention_level: AttentionLevel | None = None
    attention_log_id: UUID | None = None


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int


class AgentChatRequest(BaseModel):
    """Request body for agent chat endpoint."""
    message: str = Field(..., min_length=1, max_length=5000, description="User message")
    conversation_id: UUID | None = Field(default=None, description="Existing conversation ID, or null to start new")
    project_id: UUID | None = Field(default=None, description="Dự án đang mở, nếu có")
    context: dict | None = Field(default=None, description="Structured context (pills, runtime info) to include for LLM but not display as user text")
    model: str | None = Field(default=None, description="Model id to run this turn on. Omitted, 'auto', or an unknown id all mean the default model — see ModelClient._resolve")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="Sampling temperature override")
    # 'mezon' when the Mezon bot calls this on a user's behalf (F2/M3) — the
    # conversation then resolves to that user's one long-running Mezon DM
    # conversation instead of always creating a new one. None (the default,
    # and the only value the web frontend ever sends) is completely
    # unaffected — see `AgentService.handle_streaming_generator`.
    surface: str | None = Field(default=None, description="'mezon' when called by the bot on a user's behalf; omit for web (default)")


class AgentChatResponse(BaseModel):
    """Response body for agent chat endpoint."""
    conversation_id: UUID = Field(..., description="Conversation ID")
    reply: str = Field(..., description="Agent's text response")


class AgentStreamingStartResponse(BaseModel):
    """Response body for streaming chat endpoint."""
    status: str = Field(default="streaming_started", description="Status indicating streaming has begun")
    conversation_id: UUID | None = Field(default=None, description="Conversation ID if available")
    message: str = Field(default="Events will be streamed via SSE", description="Informational message")
