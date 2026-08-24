"""
Task service (Milestone 2.5).

Owns three things beyond plain CRUD:

1. **The status state machine.** Validation lives here, not in the API layer,
   because there are three other ways into a task: the `task.*` commands the
   AI runs, conversation extraction (`app.services.task_extraction`), and the
   AI Planner (3.2). A rule enforced in a FastAPI route protects exactly one
   of those four paths.

2. **Which event a mutation publishes.** Exactly one event per mutation —
   a completion is `task.completed`, never also `task.updated`.

3. **Confirm/reject for extracted candidates.** A task the extraction
   pipeline guesses at starts `pending_confirm`, not `todo` — the same
   reasoning the removed `Commitment` entity had: the AI proposes, the user
   disposes. `confirm_task`/`reject_task` and the fingerprint dedup below
   mirror `app.services.commitments.CommitmentService`, which this replaces.
"""

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.event_bus import get_event_bus
from app.events.payloads import (
    TaskCompletedPayload,
    TaskCreatedPayload,
    TaskDeletedPayload,
    TaskUpdatedPayload,
)
from sqlalchemy import select

from app.events.schemas import EventEnvelope
from app.models import Schedule, Task, TaskStatus
from app.repositories.tasks import TaskRepository
from app.schemas import TaskCreate, TaskRejectionCheck, TaskResponse, TaskUpdate
from app.services.recurrence import RecurrenceService
from app.utils.logger import get_logger

logger = get_logger(__name__)


def content_fingerprint(title: str) -> str:
    """A stable id for "this suggested task".

    Normalised the same way `ix_tasks_user_status_content` and
    `TaskRepository.normalized()` do, so the fingerprint a caller compares
    and the row the database finds can never disagree. Mirrors the removed
    `app.services.commitments.content_fingerprint`.
    """
    return hashlib.sha256(title.strip().lower().encode("utf-8")).hexdigest()


# The legal status transitions, per 2.5 M3 (extended for extraction
# candidates — see the module docstring). Read as {from: {allowed to}}.
#
#   pending_confirm ──▶ todo               confirm (it's real, do it)
#   pending_confirm ──▶ rejected           reject (row kept as a fingerprint,
#                                          same reasoning Commitment had)
#   todo ──▶ in_progress ──▶ done          the normal path
#   todo ─────────────────▶ done           skipping in_progress is fine —
#                                          most tasks are one sitting
#   in_progress ──▶ todo                   "not actually started"
#   done ──▶ todo                          reopen
#   anything live ──▶ cancelled            give up from any state
#   cancelled ──▶ todo                     restore
#
# Not legal, and deliberately so: `done → in_progress` and `cancelled →
# in_progress`/`cancelled → done`. Coming back to a finished or abandoned
# task goes through `todo` — one extra step, and it keeps "in_progress"
# meaning "picked up from the backlog" rather than an ambiguous half-state.
# `rejected` is terminal, same as `Commitment`'s was: reopening a rejected
# suggestion isn't a described flow.
TASK_STATUS_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING_CONFIRM: frozenset({TaskStatus.TODO, TaskStatus.REJECTED}),
    TaskStatus.TODO: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.CANCELLED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.TODO, TaskStatus.DONE, TaskStatus.CANCELLED}),
    TaskStatus.DONE: frozenset({TaskStatus.TODO, TaskStatus.CANCELLED}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.TODO}),
    TaskStatus.REJECTED: frozenset(),
}


class InvalidTaskTransition(ValueError):
    """Raised when a status change isn't in TASK_STATUS_TRANSITIONS.

    A ValueError subclass so existing callers that catch ValueError (the
    command registry, the API's 400 handler) keep working, while a caller
    that wants to distinguish "illegal transition" from "not found" can.
    """

    def __init__(self, current: TaskStatus, requested: TaskStatus) -> None:
        allowed = sorted(s.value for s in TASK_STATUS_TRANSITIONS[current])
        super().__init__(
            f"Invalid task status transition: {current.value} → {requested.value}. "
            f"Allowed from {current.value}: {', '.join(allowed)}"
        )
        self.current = current
        self.requested = requested


def is_valid_transition(current: TaskStatus, requested: TaskStatus) -> bool:
    """Same status is always accepted — a no-op write (e.g. ticking an
    already-done checkbox twice) is idempotent, not an error."""
    if current == requested:
        return True
    return requested in TASK_STATUS_TRANSITIONS[current]


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TaskRepository(session)
        self._event_bus = None  # Lazy init, avoids connecting to Redis unless needed

    async def _get_event_bus(self):
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus

    async def _publish_event(self, event_type: str, user_id: UUID, payload: dict) -> None:
        """Publish a task.* event. Never raises — a broken EventBus must not
        break task mutations (same contract as NoteService)."""
        try:
            bus = await self._get_event_bus()
            await bus.publish(EventEnvelope(
                type=event_type,
                source="TaskService",
                user_id=user_id,
                payload=payload,
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish {event_type} event: {exc}")

    async def create_task(self, payload: TaskCreate, user_id: UUID) -> Task:
        task = Task(
            user_id=user_id,
            title=payload.title,
            # The state machine governs *transitions*; the initial status is
            # free (logging already-finished work is legitimate).
            status=payload.status,
            due_date=payload.due_date,
            priority=payload.priority,
            description=payload.description,
            related_event_id=payload.related_event_id,
            parent_task_id=payload.parent_task_id,
            source_conversation_id=payload.source_conversation_id,
            source_message_id=payload.source_message_id,
            # Logging already-finished work still needs a real completed_at —
            # otherwise it would never age out of a "done today" list. Naive
            # UTC, same as `due_date`/`created_at`: this column has no tz.
            completed_at=datetime.utcnow() if payload.status is TaskStatus.DONE else None,
        )
        try:
            created = await self.repository.create(task)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        await self._publish_event(
            "task.created",
            user_id=user_id,
            payload=TaskCreatedPayload(
                task_id=created.id,
                title=created.title,
                status=created.status.value,
                due_date=created.due_date,
                priority=created.priority.value if created.priority else None,
                related_event_id=created.related_event_id,
            ).model_dump(mode="json"),
        )
        return created

    async def get_tasks(
        self,
        user_id: UUID,
        status: TaskStatus | None = None,
        related_event_id: UUID | None = None,
        parent_task_id: UUID | None = None,
        due_before=None,
    ) -> list[Task]:
        tasks = await self.repository.list_by_user(
            user_id,
            status=status,
            related_event_id=related_event_id,
            parent_task_id=parent_task_id,
            due_before=due_before,
        )
        return list(tasks)

    async def get_task(self, task_id: UUID, user_id: UUID) -> Task | None:
        return await self.repository.get_by_id_and_user(task_id, user_id)

    async def update_task(self, task_id: UUID, user_id: UUID, payload: TaskUpdate) -> Task | None:
        """Apply a partial update.

        Returns None if the task doesn't exist (or isn't this user's).
        Raises InvalidTaskTransition if `status` isn't reachable from the
        task's current status.
        """
        current = await self.repository.get_by_id_and_user(task_id, user_id)
        if current is None:
            return None

        # exclude_unset so an omitted field is left alone while an explicit
        # null clears it (due_date, priority, description and related_event_id
        # are all nullable).
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return current

        # Read the "before" value now, not after the write. The repository's
        # ORM-enabled UPDATE synchronizes the identity map, so this very
        # instance carries the *new* status the moment the UPDATE returns —
        # reading it afterwards would make every completion look like a plain
        # update and nothing would ever see a task.completed.
        previous_status = current.status

        requested_status = updates.get("status")
        if requested_status is not None and not is_valid_transition(current.status, requested_status):
            raise InvalidTaskTransition(current.status, requested_status)

        # completed_at tracks *this* transition, not `updated_at` (which also
        # moves on an unrelated field edit) — set the instant a task first
        # becomes done, cleared the instant it leaves done again. A done→done
        # no-op write (ticking an already-done box) leaves it untouched.
        if requested_status is not None and requested_status != previous_status:
            if requested_status is TaskStatus.DONE:
                updates["completed_at"] = datetime.utcnow()
            elif previous_status is TaskStatus.DONE:
                updates["completed_at"] = None

        try:
            updated = await self.repository.update_fields(task_id, user_id, updates)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        if updated is None:
            return None

        await self._publish_update_event(
            updated,
            user_id=user_id,
            fields_changed=sorted(updates.keys()),
            previous_status=previous_status,
        )
        return updated

    async def complete_task(self, task_id: UUID, user_id: UUID) -> Task | None:
        """Transition a task to `done`.

        Thin wrapper over update_task so completion goes through the same
        state machine — completing a `cancelled` task is rejected, and
        completing an already-`done` one is a no-op.
        """
        return await self.update_task(task_id, user_id, TaskUpdate(status=TaskStatus.DONE))

    async def is_linked_to_recurring_event(self, task: Task) -> bool:
        """Whether `task.related_event_id` points at a recurring `Schedule`
        — the condition that makes `occurrence_start_time`/`edit_scope`
        required on a write to this task (both `PATCH /tasks/{id}` and the
        `task.update`/`task.complete` commands check this before deciding
        whether to route through `update_task`/`complete_task` directly or
        through the occurrence-scoped variants below)."""
        if task.related_event_id is None:
            return False
        result = await self.session.execute(
            select(Schedule).where(Schedule.id == task.related_event_id)
        )
        event = result.scalar_one_or_none()
        if event is None:
            return False
        return RecurrenceService().is_recurring(event.recurrence_rule)

    async def _resolve_occurrence_target(
        self,
        task_id: UUID,
        user_id: UUID,
        occurrence_start_time: datetime,
        edit_scope: str,
    ) -> UUID | None:
        """Which row a `this_only`/`all` write on one occurrence should
        actually land on. Mirrors `ScheduleService.update_instance`'s
        `this_only`/`all` handling, minus `this_and_after` — a task doesn't
        own a recurrence rule (the event does), so there's no `until` to
        split on.

        `all`: the template itself — every occurrence without its own
        exception keeps reading this row (same as
        `_instance_dict_to_item` reading `root.is_completed` directly).

        `this_only`: find-or-create the occurrence's exception row (a
        normal `tasks` row, copied from the template, with `recurrence_id`/
        `original_start_time`/`is_exception` set), then target that. Created
        lazily, on first write — exactly `ScheduleService
        ._update_instance_this_only`'s pattern.
        """
        template = await self.repository.get_by_id_and_user(task_id, user_id)
        if template is None:
            return None
        if edit_scope == "all":
            return template.id

        exception = await self.repository.get_exception(template.id, user_id, occurrence_start_time)
        if exception is not None:
            return exception.id

        exception = Task(
            user_id=user_id,
            title=template.title,
            status=template.status,
            due_date=template.due_date,
            priority=template.priority,
            description=template.description,
            related_event_id=template.related_event_id,
            parent_task_id=template.parent_task_id,
            recurrence_id=template.id,
            original_start_time=occurrence_start_time,
            is_exception=True,
        )
        try:
            created = await self.repository.create(exception)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return created.id

    async def complete_task_occurrence(
        self,
        task_id: UUID,
        user_id: UUID,
        occurrence_start_time: datetime,
        edit_scope: str,
    ) -> Task | None:
        """`complete_task`, scoped to one occurrence of a checklist task tied
        to a recurring event — see `_resolve_occurrence_target`."""
        target_id = await self._resolve_occurrence_target(
            task_id, user_id, occurrence_start_time, edit_scope
        )
        if target_id is None:
            return None
        return await self.complete_task(target_id, user_id)

    async def update_task_occurrence(
        self,
        task_id: UUID,
        user_id: UUID,
        occurrence_start_time: datetime,
        edit_scope: str,
        payload: TaskUpdate,
    ) -> Task | None:
        """`update_task`, scoped to one occurrence — see
        `_resolve_occurrence_target`."""
        target_id = await self._resolve_occurrence_target(
            task_id, user_id, occurrence_start_time, edit_scope
        )
        if target_id is None:
            return None
        return await self.update_task(target_id, user_id, payload)

    async def complete_task_cascade(self, task_id: UUID, user_id: UUID) -> list[Task] | None:
        """Complete a task and every sub-task beneath it, however deep.

        The confirm-dialog flow: a parent with its own checklist asks "were
        all of these actually finished?" before ticking itself, and this is
        what runs if the answer is yes. Walks `parent_task_id` the same way
        the frontend's `flattenTaskTree` does, just over the *whole* user
        list rather than one already-filtered view, so a sub-task that
        doesn't happen to be in today's list (a future due date, say) is
        still reached.

        A descendant that can't legally reach `done` (`cancelled`,
        `rejected`) is left alone rather than failing the whole cascade —
        same "skip, don't abort" reasoning as a single bad row shouldn't
        block completing everything else.
        """
        root = await self.repository.get_by_id_and_user(task_id, user_id)
        if root is None:
            return None

        all_tasks = await self.repository.list_by_user(user_id)
        children_by_parent: dict[UUID, list[Task]] = {}
        for candidate in all_tasks:
            if candidate.parent_task_id is not None:
                children_by_parent.setdefault(candidate.parent_task_id, []).append(candidate)

        descendant_ids: list[UUID] = []
        stack = [task_id]
        while stack:
            current_id = stack.pop()
            for child in children_by_parent.get(current_id, []):
                descendant_ids.append(child.id)
                stack.append(child.id)

        updated: list[Task] = []
        for descendant_id in descendant_ids:
            try:
                result = await self.update_task(descendant_id, user_id, TaskUpdate(status=TaskStatus.DONE))
            except InvalidTaskTransition:
                continue
            if result is not None:
                updated.append(result)

        completed_root = await self.complete_task(task_id, user_id)
        if completed_root is not None:
            updated.append(completed_root)
        return updated

    async def confirm_task(self, task_id: UUID, user_id: UUID) -> Task | None:
        """pending_confirm → todo.

        Thin wrapper over update_task, same as complete_task — the
        extraction pipeline's guess becomes real work once a person says
        yes, and that's just a normal (validated, event-publishing) status
        transition. Raises InvalidTaskTransition from a terminal state.
        """
        return await self.update_task(task_id, user_id, TaskUpdate(status=TaskStatus.TODO))

    async def reject_task(self, task_id: UUID, user_id: UUID) -> Task | None:
        """pending_confirm → rejected. The row stays: it is the record that
        stops the extractor proposing this same suggestion again."""
        return await self.update_task(task_id, user_id, TaskUpdate(status=TaskStatus.REJECTED))

    async def check_rejected(self, user_id: UUID, title: str) -> TaskRejectionCheck:
        """Has the user already turned down this exact suggestion?

        The extraction pipeline calls this before proposing a candidate;
        re-suggesting something the user rejected reads as not listening.
        Mirrors the removed `CommitmentService.check_rejected`.
        """
        fingerprint = content_fingerprint(title)
        previous = await self.repository.find_rejected_with_content(user_id=user_id, title=title)
        if previous is None:
            return TaskRejectionCheck(fingerprint=fingerprint, rejected_before=False)
        return TaskRejectionCheck(
            fingerprint=fingerprint,
            rejected_before=True,
            rejected_task_id=previous.id,
            rejected_at=previous.created_at,
        )

    async def delete_task(self, task_id: UUID, user_id: UUID) -> bool:
        existing = await self.repository.get_by_id_and_user(task_id, user_id)
        if existing is None:
            return False

        deleted_payload = TaskDeletedPayload(
            task_id=existing.id,
            status=existing.status.value,
        )

        try:
            deleted = await self.repository.delete(task_id, user_id)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        if deleted:
            await self._publish_event(
                "task.deleted", user_id=user_id, payload=deleted_payload.model_dump(mode="json")
            )
        return deleted

    async def _publish_update_event(
        self,
        task: Task,
        *,
        user_id: UUID,
        fields_changed: list[str],
        previous_status: TaskStatus,
    ) -> None:
        """One event per mutation: `task.completed` for a transition into
        `done`, `task.updated` for everything else — never both."""
        became_done = task.status is TaskStatus.DONE and previous_status is not TaskStatus.DONE
        if became_done:
            await self._publish_event(
                "task.completed",
                user_id=user_id,
                payload=TaskCompletedPayload(
                    task_id=task.id,
                    completed_at=datetime.now(timezone.utc),
                    fields_changed=fields_changed,
                ).model_dump(mode="json"),
            )
            return

        await self._publish_event(
            "task.updated",
            user_id=user_id,
            payload=TaskUpdatedPayload(
                task_id=task.id,
                status=task.status.value,
                fields_changed=fields_changed,
            ).model_dump(mode="json"),
        )

    def to_response(self, task: Task) -> TaskResponse:
        return TaskResponse.model_validate(task)
