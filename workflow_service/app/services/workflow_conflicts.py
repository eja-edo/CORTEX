"""Workflow conflict detection (Milestone A3).

The real incident this exists for: a user created a workflow *"Nhắc việc
quá hạn"* whose trigger was `task.overdue` and whose action was
`action.request_attention` — the same event, the same action type the
backend's own `notification_subscribers.py` already handles directly (see
`backend/app/services/notification_subscribers.py`'s `DIRECT_DELIVERY_
HANDLERS`). Every overdue task then fired two notifications. That
workflow was paused by hand on 2026-08-13; nothing detected the overlap
before it shipped.

Two distinct kinds of duplication are in scope, both keyed on
"same event + same action type":

1. **backend_direct** — the trigger event is one of the ~7 events the
   backend already delivers directly (`has_direct_backend_delivery` in
   `event_vocabulary.json`, generated from `DIRECT_DELIVERY_HANDLERS`),
   and the workflow has an `action.request_attention` node. Any workflow
   on one of these events will double up with the backend's own path —
   there's no workflow-side way to avoid it other than not building it.

2. **workflow** — another *active* workflow (owned by the same user, or a
   system workflow — the two sets of workflows that actually fire for
   this user, per `internal_event_listener._event_belongs_to_workflow_
   owner`/`is_system_workflow_active_for_workspace`) already listens for
   the same event and has a node of the same action type.

Scope cuts, deliberate: only the *primary* trigger (`trigger_config`) is
checked, not supplementary `WorkflowTrigger` rows (multi-trigger support)
— the incident that motivated this was a primary-trigger collision, and
covering supplementary triggers too is a straightforward extension once
this is proven useful, not a correctness gap for what exists today.
Workspace-scoped ownership is approximated as "same user or system",
matching `_event_belongs_to_workflow_owner`'s fallback — no event today
carries `workspace_id` (see that function's own docstring), so the fuller
workspace-member check would never actually diverge from this anyway.

This only *detects* — see `docs/planning-v3.md`'s A3 section: "M2: cảnh
báo trong UI thay vì âm thầm nhân đôi". A conflict is a warning attached
to the API response, not a save-blocking error; the two failure modes
("this used to work and now I can't save it" vs "I still built the
duplicate, just with my eyes open") are not equally bad.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import SYSTEM_WORKFLOW_USER_ID, TriggerType, WorkflowDefinition, WorkflowStatus

VOCABULARY_PATH = Path(__file__).resolve().parent.parent / "triggers" / "event_vocabulary.json"

# The one action type the backend's direct-delivery path is equivalent to.
# A workflow that reaches the same outcome some other way (e.g. a future
# email/webhook action) isn't a duplicate of the Gate path and is out of
# scope for the backend_direct check specifically — see class 2 for
# workflow-vs-workflow overlap on any action type.
_ATTENTION_ACTION_TYPE = "action.request_attention"


@dataclass(frozen=True)
class WorkflowConflict:
    kind: str  # "backend_direct" | "workflow"
    event_type: str
    action_type: str
    message: str
    conflicting_workflow_id: UUID | None = None
    conflicting_workflow_name: str | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "event_type": self.event_type,
            "action_type": self.action_type,
            "message": self.message,
            "conflicting_workflow_id": str(self.conflicting_workflow_id) if self.conflicting_workflow_id else None,
            "conflicting_workflow_name": self.conflicting_workflow_name,
        }


def _action_types(definition: dict | None) -> set[str]:
    """Every `action.*` node type in a workflow's graph, except
    `action.wait` — a delay has no user-visible output of its own to
    duplicate, so two workflows both waiting on the same event isn't the
    class of bug this module exists to catch."""
    nodes = (definition or {}).get("nodes", [])
    return {
        n.get("type", "")
        for n in nodes
        if n.get("type", "").startswith("action.") and n.get("type") != "action.wait"
    }


def _direct_delivery_events() -> set[str]:
    with open(VOCABULARY_PATH) as f:
        data = json.load(f)
    return {e["event_type"] for e in data["event_types"] if e.get("has_direct_backend_delivery")}


async def find_trigger_conflicts(
    db: AsyncSession,
    *,
    user_id: str | UUID,
    event_type: str,
    action_types: set[str],
    exclude_workflow_id: UUID | None = None,
) -> list[WorkflowConflict]:
    """Conflicts a workflow triggering on `event_type` with these
    `action_types` would create, for `user_id`. Pass the workflow's own id
    as `exclude_workflow_id` when checking an existing (e.g. being
    activated) workflow so it doesn't "conflict" with itself."""
    if not action_types or not event_type:
        return []

    conflicts: list[WorkflowConflict] = []

    if _ATTENTION_ACTION_TYPE in action_types and event_type in _direct_delivery_events():
        conflicts.append(WorkflowConflict(
            kind="backend_direct",
            event_type=event_type,
            action_type=_ATTENTION_ACTION_TYPE,
            message=(
                f"Cortex đã tự xử lý sự kiện '{event_type}' và gửi nhắc nhở qua Attention Gate. "
                "Bật workflow này sẽ khiến mỗi lần xảy ra bắn thêm một thông báo trùng."
            ),
        ))

    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.status == WorkflowStatus.ACTIVE,
            WorkflowDefinition.trigger_type == TriggerType.INTERNAL_EVENT,
            WorkflowDefinition.is_deleted == False,
            WorkflowDefinition.trigger_config["event"].as_string() == event_type,
            WorkflowDefinition.user_id.in_([str(user_id), str(SYSTEM_WORKFLOW_USER_ID)]),
        )
    )
    for other in result.scalars().all():
        if exclude_workflow_id is not None and other.id == exclude_workflow_id:
            continue
        overlap = action_types & _action_types(other.definition)
        for action_type in sorted(overlap):
            conflicts.append(WorkflowConflict(
                kind="workflow",
                event_type=event_type,
                action_type=action_type,
                message=(
                    f"Workflow '{other.name}' cũng đang nghe '{event_type}' và có cùng hành động "
                    f"'{action_type}' — bật cả hai sẽ bắn trùng."
                ),
                conflicting_workflow_id=other.id,
                conflicting_workflow_name=other.name,
            ))

    return conflicts
