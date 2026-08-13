from collections.abc import Sequence
from datetime import date, datetime, time
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task, TaskStatus


def normalized(column_or_value):
    """The one normalisation used for content matching.

    Must stay identical to `ix_tasks_user_status_content`'s expression
    (`lower(btrim(...))`) — if these two drift, the lookup silently stops
    using the index and starts scanning. Mirrors
    `app.repositories.commitments.normalized`, which this replaces.
    """
    return func.lower(func.btrim(column_or_value))


class TaskRepository:
    """Data access for `tasks`. Every query is scoped by `user_id` — tasks
    are personal in Phase 2."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, task: Task) -> Task:
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def list_by_user(
        self,
        user_id: UUID,
        status: TaskStatus | None = None,
        related_event_id: UUID | None = None,
        parent_task_id: UUID | None = None,
        due_before: date | None = None,
    ) -> Sequence[Task]:
        stmt = select(Task).where(Task.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if related_event_id is not None:
            stmt = stmt.where(Task.related_event_id == related_event_id)
        if parent_task_id is not None:
            stmt = stmt.where(Task.parent_task_id == parent_task_id)
        if due_before is not None:
            # End of that day, not its midnight — `due_date` can carry a real
            # time now, and "due on or before this date" must still include
            # a task due later that same day.
            stmt = stmt.where(Task.due_date <= datetime.combine(due_before, time.max))
        # due_date NULLs last: a task with no deadline is the least pressing.
        stmt = stmt.order_by(Task.due_date.asc().nullslast(), Task.created_at.asc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id_and_user(self, task_id: UUID, user_id: UUID) -> Task | None:
        stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_rejected_with_content(self, user_id: UUID, title: str) -> Task | None:
        """The most recent rejected task matching this title.

        This is why rejected rows are kept rather than deleted: without them
        the extractor would re-propose the same guess from the same
        conversation, which reads as the assistant not listening. Runs on
        `ix_tasks_user_status_content`. Mirrors
        `CommitmentRepository.find_rejected_with_content`.
        """
        stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.status == TaskStatus.REJECTED,
                normalized(Task.title) == normalized(title),
            )
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def update_fields(self, task_id: UUID, user_id: UUID, updates: dict) -> Task | None:
        if not updates:
            return await self.get_by_id_and_user(task_id, user_id)

        stmt = (
            update(Task)
            .where(Task.id == task_id, Task.user_id == user_id)
            .values(**updates, updated_at=func.now())
            .returning(Task.id)
        )
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is None:
            return None
        return await self.get_by_id_and_user(task_id, user_id)

    async def delete(self, task_id: UUID, user_id: UUID) -> bool:
        """Hard delete. `cancelled` is the "I'm not doing this but keep the
        record" state, so an actual delete means "this task shouldn't exist"."""
        task = await self.get_by_id_and_user(task_id, user_id)
        if task is None:
            return False
        await self.session.delete(task)
        await self.session.flush()
        return True
