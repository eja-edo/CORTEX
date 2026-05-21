"""
schedules.py — API router (sau khi refactor)

Tất cả business logic đã được chuyển sang ScheduleService.
Router chỉ làm 3 việc:
  1. Parse / validate request (FastAPI + Pydantic lo)
  2. Gọi ScheduleService
  3. Enqueue Google sync (async, fire-and-forget)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from uuid import UUID

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import Schedule, SyncOperation, User
from app.schemas import (
    ScheduleCreate,
    ScheduleUpdate,
    ScheduleResponse,
    ScheduleListResponse,
    ScheduleInstanceUpdate,
)
from app.services.schedule_service import ScheduleService
from app.services.redis.google_sync_task import enqueue_google_sync
from app.utils.logger import get_logger

router = APIRouter(prefix="/schedules", tags=["schedules"])
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper: Google sync (fire-and-forget, non-fatal)
# ---------------------------------------------------------------------------

async def _enqueue_google_sync(schedule: Schedule, operation: SyncOperation) -> None:
    try:
        await enqueue_google_sync(
            schedule_id=str(schedule.id),
            user_id=str(schedule.user_id),
            operation=operation.value,
        )
    except Exception as exc:
        logger.warning(
            "Failed to enqueue Google sync for schedule %s: %s",
            schedule.id,
            exc,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ScheduleResponse, status_code=201)
async def create_schedule(
    schedule_data: ScheduleCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    svc = ScheduleService(db)
    schedule = svc.create_schedule(user_id=current_user.id, data=schedule_data)
    await _enqueue_google_sync(schedule, SyncOperation.UPSERT)
    return schedule


@router.get("", response_model=ScheduleListResponse)
def get_schedules(
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        result = ScheduleService(db).list_schedules(
            user_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    schedule = ScheduleService(db).get_schedule_by_id(schedule_id, current_user.id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: UUID,
    schedule_update: ScheduleUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        schedule = ScheduleService(db).update_schedule(
            schedule_id=schedule_id,
            user_id=current_user.id,
            data=schedule_update,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await _enqueue_google_sync(schedule, SyncOperation.UPSERT)
    return schedule


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        schedule = ScheduleService(db).delete_schedule(
            schedule_id=schedule_id,
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await _enqueue_google_sync(schedule, SyncOperation.DELETE)
    return None


@router.get("/{schedule_id}/instances")
def get_schedule_instances(
    schedule_id: UUID,
    range_start: datetime = Query(...),
    range_end: datetime = Query(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        return ScheduleService(db).get_instances(
            schedule_id=schedule_id,
            user_id=current_user.id,
            range_start=range_start,
            range_end=range_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{schedule_id}/instances/{original_start_time}")
async def update_schedule_instance(
    schedule_id: UUID,
    original_start_time: datetime,
    instance_data: ScheduleInstanceUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        result = ScheduleService(db).update_instance(
            schedule_id=schedule_id,
            user_id=current_user.id,
            original_start_time=original_start_time,
            instance_data=instance_data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # "this_and_after" và "all" cần sync lên Google
    if instance_data.edit_scope.value in ("this_and_after", "all"):
        await _enqueue_google_sync(result, SyncOperation.UPSERT)
    return result


@router.delete("/{schedule_id}/instances/{original_start_time}", status_code=204)
async def cancel_schedule_instance(
    schedule_id: UUID,
    original_start_time: datetime,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        exception = ScheduleService(db).cancel_instance(
            schedule_id=schedule_id,
            user_id=current_user.id,
            original_start_time=original_start_time,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _enqueue_google_sync(exception, SyncOperation.UPSERT)
    return None


# ---------------------------------------------------------------------------
# Reminder endpoints (không thay đổi về business logic)
# ---------------------------------------------------------------------------

from app.schemas import ReminderResponse  # noqa: E402  (avoid circular at top)
from app.services.reminder_service import ReminderService  # noqa: E402
from app.models import ScheduleReminder  # noqa: E402


@router.get("/{schedule_id}/reminders")
def get_schedule_reminders(
    schedule_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    schedule = ScheduleService(db).get_schedule_by_id(schedule_id, current_user.id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    reminders = ReminderService().get_reminders_for_schedule(schedule_id, db)
    return {"reminders": reminders, "total": len(reminders)}


@router.post("/{schedule_id}/reminders", status_code=201)
def add_schedule_reminder(
    schedule_id: UUID,
    reminder_configs: list,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    schedule = ScheduleService(db).get_schedule_by_id(schedule_id, current_user.id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    reminders = ReminderService().create_reminders_for_schedule(
        schedule=schedule, reminder_configs=reminder_configs, db=db,
    )
    db.commit()
    return {"reminders": reminders, "total": len(reminders)}


@router.delete("/{schedule_id}/reminders/{reminder_id}", status_code=204)
def delete_schedule_reminder(
    schedule_id: UUID,
    reminder_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    reminder = (
        db.query(ScheduleReminder)
        .filter(
            ScheduleReminder.id == reminder_id,
            ScheduleReminder.schedule_id == schedule_id,
        )
        .first()
    )
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    db.delete(reminder)
    db.commit()
    return None