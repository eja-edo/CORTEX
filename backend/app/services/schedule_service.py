"""
ScheduleService
---------------
Single source of truth cho toàn bộ business logic liên quan đến Schedule.

- API layer (schedules.py) gọi service này thay vì query DB trực tiếp.
- Agent tools (create_schedule, get_schedules, update_schedule) cũng gọi service này.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.events.event_bus import get_event_bus
from app.events.payloads import ScheduleCompletedPayload, ScheduleCreatedPayload, ScheduleUpdatedPayload
from app.events.schemas import EventEnvelope
from app.models import (
    CalendarProvider,
    Schedule,
    ScheduleExternalMap,
    ScheduleType,
    SyncOperation,
)
from app.schemas import (
    ScheduleCreate,
    ScheduleInstanceUpdate,
    ScheduleUpdate,
)
from app.services.recurrence import RecurrenceService
from app.services.reminder_service import ReminderService
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _safe_publish_event(event: EventEnvelope) -> None:
    """Publish via EventBus, swallowing all errors (never break the caller)."""
    try:
        bus = await get_event_bus()
        await bus.publish(event)
    except Exception as exc:
        logger.warning(f"Failed to publish {event.type} event: {exc}")


def _fire_event(event: EventEnvelope) -> None:
    """
    Fire-and-forget event publish from ScheduleService's sync methods.

    ScheduleService is called from both async contexts (agent tools, most API
    routes running inside FastAPI's event loop) and genuinely sync contexts
    (no running loop). Bridge accordingly; either way, publish failures never
    propagate to the caller.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        loop.create_task(_safe_publish_event(event))
    else:
        try:
            asyncio.run(_safe_publish_event(event))
        except Exception as exc:
            logger.warning(f"Failed to publish {event.type} event (sync fallback): {exc}")


# ---------------------------------------------------------------------------
# Helpers (internal)
# ---------------------------------------------------------------------------

def _attach_google_sync_flags(schedules: list[Schedule], db: Session) -> None:
    """Gán thuộc tính `google_synced` cho mỗi schedule object."""
    if not schedules:
        return
    schedule_ids = [s.id for s in schedules]
    mapped_ids = {
        row.schedule_id
        for row in db.query(ScheduleExternalMap.schedule_id)
        .filter(
            ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
            ScheduleExternalMap.schedule_id.in_(schedule_ids),
        )
        .all()
    }
    for s in schedules:
        setattr(s, "google_synced", s.id in mapped_ids)


def _attach_google_sync_flags_to_dicts(
    events: list[dict], db: Session
) -> None:
    """Gán key `google_synced` cho list dict (dùng trong get_schedules)."""
    schedule_ids = [e["id"] for e in events if e.get("id")]
    if not schedule_ids:
        return
    mapped_ids = {
        row.schedule_id
        for row in db.query(ScheduleExternalMap.schedule_id)
        .filter(
            ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
            ScheduleExternalMap.schedule_id.in_(schedule_ids),
        )
        .all()
    }
    for event in events:
        event["google_synced"] = event["id"] in mapped_ids if event.get("id") else False


def _schedule_to_dict(schedule: Schedule, is_virtual: bool = False) -> dict:
    """Chuyển Schedule ORM object thành dict chuẩn để trả về."""
    return {
        "id": str(schedule.id),
        "user_id": str(schedule.user_id),
        "title": schedule.title,
        "type": (
            schedule.type.value
            if hasattr(schedule.type, "value")
            else schedule.type
        ),
        "start_time": (
            schedule.start_time.isoformat() if schedule.start_time else None
        ),
        "end_time": (
            schedule.end_time.isoformat() if schedule.end_time else None
        ),
        "location": schedule.location,
        "description": schedule.description,
        "is_completed": schedule.is_completed,
        "recurrence": schedule.recurrence_rule,
        "is_recurring": False,
        "is_exception": False,
        "is_cancelled": False,
        "recurrence_id": None,
        "original_start_time": None,
        "is_virtual": is_virtual,
        "version": schedule.version,
        "created_at": (
            schedule.created_at.isoformat() if schedule.created_at else None
        ),
        "updated_at": (
            schedule.updated_at.isoformat() if schedule.updated_at else None
        ),
    }


# ---------------------------------------------------------------------------
# ScheduleService
# ---------------------------------------------------------------------------

def _serialize_recurrence_rule(rule) -> dict | None:
    """Convert RecurrenceRuleInput to JSON-serializable dict.
    The model_dump() keeps datetime objects which break JSON columns."""
    data = rule.model_dump()
    if isinstance(data.get("until"), datetime):
        data["until"] = data["until"].isoformat()
    return data


class ScheduleService:
    """Toàn bộ business logic cho Schedule.

    Nhận `db: Session` trực tiếp để dễ dùng trong cả sync API lẫn agent tools.
    Việc enqueue Google sync (async, fire-and-forget) được tách ra callback
    để service này không phụ thuộc vào async context.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._recurrence_svc = RecurrenceService()
        self._reminder_svc = ReminderService()

    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------

    def create_schedule(self, user_id: UUID, data: ScheduleCreate) -> Schedule:
        """Tạo mới một schedule. Trả về Schedule ORM object (đã commit)."""
        db_schedule = Schedule(
            user_id=user_id,
            title=data.title,
            type=data.type,
            start_time=data.start_time,
            end_time=data.end_time,
            location=data.location,
            description=data.description,
            is_completed=False,
            recurrence_rule=(
                _serialize_recurrence_rule(data.recurrence) if data.recurrence else None
            ),
            workflow_id=UUID(data.workflow_id) if data.workflow_id else None,
        )
        self.db.add(db_schedule)
        self.db.flush()

        if data.reminders:
            self._reminder_svc.create_reminders_for_schedule(
                schedule=db_schedule,
                reminder_configs=[r.model_dump() for r in data.reminders],
                db=self.db,
            )

        self.db.commit()
        self.db.refresh(db_schedule)
        _attach_google_sync_flags([db_schedule], self.db)
        _fire_event(EventEnvelope(
            type="schedule.created",
            source="ScheduleService",
            user_id=user_id,
            payload=ScheduleCreatedPayload(
                schedule_id=db_schedule.id,
                title=db_schedule.title,
                schedule_type=db_schedule.type.value,
                start_time=db_schedule.start_time,
                end_time=db_schedule.end_time,
                location=db_schedule.location,
                is_recurring=bool(db_schedule.recurrence_rule),
            ).model_dump(),
        ))
        return db_schedule

    def create_schedule_simple(
        self,
        *,
        user_id: UUID,
        title: str,
        schedule_type: ScheduleType,
        start_time: datetime,
        end_time: datetime,
        location: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Schedule:
        """Tạo schedule không qua Pydantic schema — dùng cho agent tools."""
        if start_time >= end_time:
            raise ValueError("start_time must be before end_time")

        db_schedule = Schedule(
            user_id=user_id,
            title=title,
            type=schedule_type,
            start_time=start_time,
            end_time=end_time,
            location=location,
            description=description,
            is_completed=False,
        )
        self.db.add(db_schedule)
        self.db.flush()
        self.db.commit()
        self.db.refresh(db_schedule)
        _fire_event(EventEnvelope(
            type="schedule.created",
            source="ScheduleService",
            user_id=user_id,
            payload=ScheduleCreatedPayload(
                schedule_id=db_schedule.id,
                title=db_schedule.title,
                schedule_type=db_schedule.type.value,
                start_time=db_schedule.start_time,
                end_time=db_schedule.end_time,
                location=db_schedule.location,
                is_recurring=False,
            ).model_dump(),
        ))
        return db_schedule

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------

    def get_schedule_by_id(
        self, schedule_id: UUID, user_id: UUID
    ) -> Optional[Schedule]:
        """Lấy một schedule theo ID. Trả về None nếu không tìm thấy."""
        schedule = (
            self.db.query(Schedule)
            .filter(
                Schedule.id == schedule_id,
                Schedule.user_id == user_id,
            )
            .first()
        )
        if schedule:
            _attach_google_sync_flags([schedule], self.db)
        return schedule

    def list_schedules(
        self,
        user_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> dict:
        """Lấy danh sách schedules trong khoảng thời gian.

        Trả về dict ``{"items": [...], "total": int}`` — các item là dict
        (không phải ORM object) để serialisation dễ hơn.
        """
        if start_date > end_date:
            raise ValueError("start_date must be before end_date")

        # Non-recurring schedules nằm trong range
        non_recurring = (
            self.db.query(Schedule)
            .filter(
                Schedule.user_id == user_id,
                Schedule.start_time >= start_date,
                Schedule.start_time <= end_date,
                Schedule.recurrence_id.is_(None),
            )
            .order_by(Schedule.start_time)
            .all()
        )
        non_recurring = [
            s
            for s in non_recurring
            if not self._recurrence_svc.is_recurring(s.recurrence_rule)
        ]

        # Root recurring schedules (không lọc theo range vì rule có thể kéo dài)
        root_recurring = (
            self.db.query(Schedule)
            .filter(
                Schedule.user_id == user_id,
                Schedule.recurrence_id.is_(None),
            )
            .order_by(Schedule.start_time)
            .all()
        )
        root_recurring = [
            s
            for s in root_recurring
            if self._recurrence_svc.is_recurring(s.recurrence_rule)
        ]

        expanded: list[dict] = [_schedule_to_dict(s) for s in non_recurring]

        for schedule in root_recurring:
            instances = self._recurrence_svc.generate_instances(
                root=schedule,
                range_start=start_date,
                range_end=end_date,
                db=self.db,
            )
            expanded.extend(instances)

        expanded.sort(key=lambda x: x.get("start_time", ""))
        _attach_google_sync_flags_to_dicts(expanded, self.db)

        return {"items": expanded, "total": len(expanded)}

    def list_schedules_for_agent(
        self,
        user_id: UUID,
        start_date: datetime,
        end_date: datetime,
        type_filter: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """Biến thể dùng cho agent tools: hỗ trợ type_filter và limit.

        Trả về dict ``{"count": int, "schedules": [...]}``.
        """
        if start_date > end_date:
            raise ValueError("start_date must be before end_date")

        query = self.db.query(Schedule).filter(
            Schedule.user_id == user_id,
            Schedule.is_cancelled.is_(False),
        )
        if type_filter:
            query = query.filter(Schedule.type == type_filter)

        root_schedules = query.all()

        all_instances: list[dict] = []
        for root in root_schedules:
            instances = self._recurrence_svc.generate_instances(
                root, start_date, end_date, self.db
            )
            all_instances.extend(instances)

        all_instances.sort(key=lambda x: x["start_time"])
        all_instances = all_instances[:limit]

        return {"count": len(all_instances), "schedules": all_instances}

    # ------------------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------------------

    def update_schedule(
        self, schedule_id: UUID, user_id: UUID, data: ScheduleUpdate
    ) -> Schedule:
        """Cập nhật schedule theo Pydantic schema. Dùng cho API layer."""
        schedule = self.get_schedule_by_id(schedule_id, user_id)
        if not schedule:
            raise ValueError("Schedule not found")

        update_data = data.model_dump(exclude_unset=True)
        fields_changed = list(update_data.keys())
        was_completed = schedule.is_completed

        if "recurrence" in update_data:
            recurrence_val = update_data.pop("recurrence")
            schedule.recurrence_rule = (
                _serialize_recurrence_rule(recurrence_val)
                if recurrence_val and hasattr(recurrence_val, "model_dump")
                else recurrence_val
            )

        for field, value in update_data.items():
            if field != "reminders":
                setattr(schedule, field, value)

        if data.reminders is not None:
            self._reminder_svc.create_reminders_for_schedule(
                schedule=schedule,
                reminder_configs=[r.model_dump() for r in data.reminders],
                db=self.db,
            )

        schedule.version += 1
        schedule.updated_by = "INTERNAL"
        schedule.updated_at = datetime.utcnow()
        self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        _attach_google_sync_flags([schedule], self.db)

        _fire_event(EventEnvelope(
            type="schedule.updated",
            source="ScheduleService",
            user_id=user_id,
            payload=ScheduleUpdatedPayload(schedule_id=schedule.id, fields_changed=fields_changed).model_dump(),
        ))
        if schedule.is_completed and not was_completed:
            _fire_event(EventEnvelope(
                type="schedule.completed",
                source="ScheduleService",
                user_id=user_id,
                payload=ScheduleCompletedPayload(schedule_id=schedule.id, completed_at=datetime.utcnow()).model_dump(),
            ))
        return schedule

    def update_schedule_fields(
        self,
        schedule_id: UUID,
        user_id: UUID,
        *,
        title: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        description: Optional[str] = None,
        is_completed: Optional[bool] = None,
    ) -> Schedule:
        """Cập nhật schedule bằng keyword args — dùng cho agent tools."""
        schedule = (
            self.db.query(Schedule)
            .filter(
                Schedule.id == schedule_id,
                Schedule.user_id == user_id,
            )
            .first()
        )
        if not schedule:
            raise ValueError(
                "Schedule not found or you don't have permission to update it"
            )

        fields_changed: list[str] = []
        was_completed = schedule.is_completed

        if title is not None:
            schedule.title = title
            fields_changed.append("title")
        if start_time is not None:
            schedule.start_time = start_time
            fields_changed.append("start_time")
        if end_time is not None:
            schedule.end_time = end_time
            fields_changed.append("end_time")
        if description is not None:
            schedule.description = description
            fields_changed.append("description")
        if is_completed is not None:
            schedule.is_completed = is_completed
            fields_changed.append("is_completed")

        if schedule.start_time >= schedule.end_time:
            raise ValueError("start_time must be before end_time")

        schedule.version += 1
        schedule.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(schedule)

        if fields_changed:
            _fire_event(EventEnvelope(
                type="schedule.updated",
                source="ScheduleService",
                user_id=user_id,
                payload=ScheduleUpdatedPayload(schedule_id=schedule.id, fields_changed=fields_changed).model_dump(),
            ))
            if schedule.is_completed and not was_completed:
                _fire_event(EventEnvelope(
                    type="schedule.completed",
                    source="ScheduleService",
                    user_id=user_id,
                    payload=ScheduleCompletedPayload(schedule_id=schedule.id, completed_at=datetime.utcnow()).model_dump(),
                ))
        return schedule

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def delete_schedule(self, schedule_id: UUID, user_id: UUID) -> Schedule:
        """Xoá schedule. Trả về schedule object (để caller enqueue Google sync).

        Raises ValueError nếu không tìm thấy.
        """
        schedule = (
            self.db.query(Schedule)
            .filter(
                Schedule.id == schedule_id,
                Schedule.user_id == user_id,
            )
            .first()
        )
        if not schedule:
            raise ValueError("Schedule not found")

        # Giữ reference trước khi xoá để caller có thể enqueue sync
        snapshot = schedule

        self._reminder_svc.cancel_reminders_for_schedule(schedule.id, self.db)
        self.db.commit()
        self.db.delete(schedule)
        self.db.commit()
        return snapshot

    # ------------------------------------------------------------------
    # INSTANCES (recurring)
    # ------------------------------------------------------------------

    def get_instances(
        self,
        schedule_id: UUID,
        user_id: UUID,
        range_start: datetime,
        range_end: datetime,
    ) -> dict:
        schedule = self.get_schedule_by_id(schedule_id, user_id)
        if not schedule:
            raise ValueError("Schedule not found")
        if not self._recurrence_svc.is_recurring(schedule.recurrence_rule):
            raise ValueError("Schedule is not recurring")

        instances = self._recurrence_svc.generate_instances(
            root=schedule,
            range_start=range_start,
            range_end=range_end,
            db=self.db,
        )
        return {"instances": instances, "total": len(instances)}

    def update_instance(
        self,
        schedule_id: UUID,
        user_id: UUID,
        original_start_time: datetime,
        instance_data: ScheduleInstanceUpdate,
    ) -> Schedule:
        """Cập nhật một instance của recurring schedule."""
        root = (
            self.db.query(Schedule)
            .filter(
                Schedule.id == schedule_id,
                Schedule.user_id == user_id,
            )
            .first()
        )
        if not root:
            raise ValueError("Schedule not found")
        if not self._recurrence_svc.is_recurring(root.recurrence_rule):
            raise ValueError("Schedule is not recurring")

        scope = instance_data.edit_scope.value

        if scope == "this_only":
            return self._update_instance_this_only(
                root, original_start_time, instance_data
            )
        elif scope == "this_and_after":
            return self._update_instance_this_and_after(
                root, original_start_time, instance_data
            )
        elif scope == "all":
            return self._update_instance_all(root, instance_data)
        else:
            raise ValueError(f"Invalid edit_scope: {scope}")

    def cancel_instance(
        self,
        schedule_id: UUID,
        user_id: UUID,
        original_start_time: datetime,
    ) -> Schedule:
        """Huỷ một instance của recurring schedule."""
        root = (
            self.db.query(Schedule)
            .filter(
                Schedule.id == schedule_id,
                Schedule.user_id == user_id,
            )
            .first()
        )
        if not root:
            raise ValueError("Schedule not found")
        if not self._recurrence_svc.is_recurring(root.recurrence_rule):
            raise ValueError("Schedule is not recurring")

        exception = (
            self.db.query(Schedule)
            .filter(
                Schedule.recurrence_id == root.id,
                Schedule.original_start_time == original_start_time,
            )
            .first()
        )

        if exception is None:
            exception = Schedule(
                user_id=root.user_id,
                title=root.title,
                type=root.type,
                start_time=original_start_time,
                end_time=original_start_time + (root.end_time - root.start_time),
                recurrence_id=root.id,
                original_start_time=original_start_time,
                is_exception=True,
                is_cancelled=True,
                recurrence_rule=None,
            )
            self.db.add(exception)
        else:
            exception.is_cancelled = True
            exception.version += 1

        self.db.commit()
        return exception

    # ------------------------------------------------------------------
    # Private helpers cho instance updates
    # ------------------------------------------------------------------

    def _update_instance_this_only(
        self,
        root: Schedule,
        original_start_time: datetime,
        instance_data: ScheduleInstanceUpdate,
    ) -> Schedule:
        exception = (
            self.db.query(Schedule)
            .filter(
                Schedule.recurrence_id == root.id,
                Schedule.original_start_time == original_start_time,
            )
            .first()
        )

        if exception is None:
            duration = root.end_time - root.start_time
            exception = Schedule(
                user_id=root.user_id,
                title=root.title,
                type=root.type,
                start_time=original_start_time,
                end_time=original_start_time + duration,
                location=root.location,
                description=root.description,
                recurrence_id=root.id,
                original_start_time=original_start_time,
                is_exception=True,
                recurrence_rule=None,
            )
            self.db.add(exception)

        update_data = instance_data.updates.model_dump(exclude_unset=True)
        update_data.pop("recurrence", None)

        for field, value in update_data.items():
            if field != "reminders":
                setattr(exception, field, value)

        if instance_data.updates.reminders is not None:
            self._reminder_svc.create_reminders_for_schedule(
                schedule=exception,
                reminder_configs=[
                    r.model_dump() for r in instance_data.updates.reminders
                ],
                db=self.db,
            )

        exception.version += 1
        self.db.commit()
        self.db.refresh(exception)
        _attach_google_sync_flags([exception], self.db)
        return exception

    def _update_instance_this_and_after(
        self,
        root: Schedule,
        original_start_time: datetime,
        instance_data: ScheduleInstanceUpdate,
    ) -> Schedule:
        new_until = original_start_time - timedelta(days=1)
        root.recurrence_rule["until"] = new_until.isoformat()

        duration = root.end_time - root.start_time
        new_root = Schedule(
            user_id=root.user_id,
            title=instance_data.updates.title or root.title,
            type=instance_data.updates.type or root.type,
            start_time=original_start_time,
            end_time=original_start_time + duration,
            location=instance_data.updates.location or root.location,
            description=instance_data.updates.description or root.description,
            recurrence_rule=root.recurrence_rule.copy(),
        )
        self.db.add(new_root)
        self.db.commit()
        self.db.refresh(new_root)
        _attach_google_sync_flags([new_root], self.db)
        return new_root

    def _update_instance_all(
        self,
        root: Schedule,
        instance_data: ScheduleInstanceUpdate,
    ) -> Schedule:
        update_data = instance_data.updates.model_dump(exclude_unset=True)
        if "recurrence" in update_data:
            recurrence_val = update_data.pop("recurrence")
            root.recurrence_rule = (
                _serialize_recurrence_rule(recurrence_val)
                if recurrence_val and hasattr(recurrence_val, "model_dump")
                else recurrence_val
            )

        for field, value in update_data.items():
            if field != "reminders":
                setattr(root, field, value)

        if instance_data.updates.reminders is not None:
            self._reminder_svc.create_reminders_for_schedule(
                schedule=root,
                reminder_configs=[
                    r.model_dump() for r in instance_data.updates.reminders
                ],
                db=self.db,
            )

        root.version += 1
        self.db.commit()
        self.db.refresh(root)
        _attach_google_sync_flags([root], self.db)
        return root