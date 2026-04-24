from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import (
    CalendarProvider,
    Schedule,
    ScheduleExternalMap,
    ScheduleSyncQueue,
    SyncOperation,
    User,
)
from app.schemas import (
    ScheduleCreate,
    ScheduleUpdate,
    ScheduleResponse,
    ScheduleListResponse,
    ScheduleInstanceUpdate,
    ReminderResponse,
)
from app.services.google_calendar_sync import GoogleCalendarSyncService
from app.services.recurrence import RecurrenceService
from app.services.reminder_service import ReminderService

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _attach_google_sync_flags(schedules: list[Schedule], db: Session) -> None:
    if not schedules:
        return

    schedule_ids = [item.id for item in schedules]
    mapped_ids = {
        row.schedule_id
        for row in db.query(ScheduleExternalMap.schedule_id).filter(
            ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
            ScheduleExternalMap.schedule_id.in_(schedule_ids),
        ).all()
    }

    for item in schedules:
        setattr(item, "google_synced", item.id in mapped_ids)


def _enqueue_google_sync(schedule: Schedule, operation: SyncOperation, db: Session):
    """Add to sync queue instead of calling directly."""
    entry = ScheduleSyncQueue(
        schedule_id=schedule.id,
        user_id=schedule.user_id,
        operation=operation,
    )
    db.add(entry)
    # Don't commit here, let caller commit with same transaction

@router.post("", response_model=ScheduleResponse, status_code=201)
def create_schedule(
    schedule_data: ScheduleCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new schedule with optional recurrence and reminders."""
    db_schedule = Schedule(
        user_id=current_user.id,
        title=schedule_data.title,
        type=schedule_data.type,
        start_time=schedule_data.start_time,
        end_time=schedule_data.end_time,
        location=schedule_data.location,
        description=schedule_data.description,
        is_completed=False,
        recurrence_rule=schedule_data.recurrence.model_dump() if schedule_data.recurrence else None,
    )
    db.add(db_schedule)
    db.flush()  # Get ID first

    # Create reminders if provided
    if schedule_data.reminders:
        ReminderService().create_reminders_for_schedule(
            schedule=db_schedule,
            reminder_configs=[r.model_dump() for r in schedule_data.reminders],
            db=db,
        )

    db.commit()
    db.refresh(db_schedule)

    # Enqueue async sync (doesn't block response)
    _enqueue_google_sync(db_schedule, SyncOperation.UPSERT, db)
    db.commit()

    _attach_google_sync_flags([db_schedule], db)
    return db_schedule

@router.get("", response_model=ScheduleListResponse)
def get_schedules(
    start_date: datetime = Query(..., description="Start date (ISO format)"),
    end_date: datetime = Query(..., description="End date (ISO format)"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get list of schedules within a date range.
    Expands recurring events into individual instances.
    
    Query Parameters:
    - start_date: Start date in ISO format (required)
    - end_date: End date in ISO format (required)
    - user_id: Automatically inferred from access token
    
    Example: /api/schedules?start_date=2026-04-01T00:00:00&end_date=2026-04-30T23:59:59
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")
    
    # Get non-recurring events in range
    non_recurring_schedules = db.query(Schedule).filter(
        Schedule.user_id == current_user.id,
        Schedule.start_time >= start_date,
        Schedule.start_time <= end_date,
        Schedule.recurrence_id.is_(None),  # Only root events
        Schedule.recurrence_rule.is_(None),  # Non-recurring only
    ).order_by(Schedule.start_time).all()
    
    # Get ALL root recurring events (need to generate instances for the range)
    # Don't filter by start_time - recurring events may have started before the range
    root_recurring_schedules = db.query(Schedule).filter(
        Schedule.user_id == current_user.id,
        Schedule.recurrence_id.is_(None),  # Only root events
        Schedule.recurrence_rule.isnot(None),  # Has recurrence rule
    ).order_by(Schedule.start_time).all()
    
    # Filter out NONE frequency in Python (JSONB query is tricky)
    root_recurring_schedules = [
        s for s in root_recurring_schedules 
        if s.recurrence_rule and s.recurrence_rule.get("freq") != "NONE"
    ]
    
    # Expand recurring events into instances
    expanded_events = []
    recurrence_service = RecurrenceService()
    
    # Process non-recurring events
    for schedule in non_recurring_schedules:
        expanded_events.append({
            "id": str(schedule.id),
            "user_id": str(schedule.user_id),
            "title": schedule.title,
            "type": schedule.type.value if hasattr(schedule.type, 'value') else schedule.type,
            "start_time": schedule.start_time.isoformat() if schedule.start_time else None,
            "end_time": schedule.end_time.isoformat() if schedule.end_time else None,
            "location": schedule.location,
            "description": schedule.description,
            "is_completed": schedule.is_completed,
            "recurrence": schedule.recurrence_rule,
            "is_recurring": False,
            "is_exception": False,
            "is_cancelled": False,
            "recurrence_id": None,
            "original_start_time": None,
            "is_virtual": False,
            "version": schedule.version,
            "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
            "updated_at": schedule.updated_at.isoformat() if schedule.updated_at else None,
        })
    
    # Process recurring events - generate instances for the date range
    for schedule in root_recurring_schedules:
        if schedule.recurrence_rule and schedule.recurrence_rule.get("freq") != "NONE":
            # This is a recurring event - generate instances
            instances = recurrence_service.generate_instances(
                root=schedule,
                range_start=start_date,
                range_end=end_date,
                db=db,
            )
            expanded_events.extend(instances)
    
    # Sort by start_time
    expanded_events.sort(key=lambda x: x.get("start_time", ""))
    
    # Attach google_synced flags (only for non-virtual events)
    schedule_ids = [e["id"] for e in expanded_events if e["id"]]
    if schedule_ids:
        mapped_ids = {
            row.schedule_id
            for row in db.query(ScheduleExternalMap.schedule_id).filter(
                ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
                ScheduleExternalMap.schedule_id.in_(schedule_ids),
            ).all()
        }
        for event in expanded_events:
            if event["id"]:
                event["google_synced"] = event["id"] in mapped_ids
            else:
                event["google_synced"] = False
    
    return {
        "items": expanded_events,
        "total": len(expanded_events)
    }

@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get a specific schedule by ID"""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    _attach_google_sync_flags([schedule], db)
    return schedule

@router.put("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: UUID,
    schedule_update: ScheduleUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update a schedule"""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    update_data = schedule_update.model_dump(exclude_unset=True)

    # Handle recurrence field separately
    if "recurrence" in update_data:
        schedule.recurrence_rule = update_data.pop("recurrence")
        if schedule.recurrence_rule:
            schedule.recurrence_rule = schedule.recurrence_rule.model_dump()

    # Apply other updates
    for field, value in update_data.items():
        if field != "reminders":  # Handle reminders separately
            setattr(schedule, field, value)

    # Update reminders if provided
    if schedule_update.reminders is not None:
        ReminderService().create_reminders_for_schedule(
            schedule=schedule,
            reminder_configs=[r.model_dump() for r in schedule_update.reminders],
            db=db,
        )

    schedule.version += 1
    schedule.updated_by = "INTERNAL"
    schedule.updated_at = datetime.utcnow()
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    # Enqueue async sync
    _enqueue_google_sync(schedule, SyncOperation.UPSERT, db)
    db.commit()

    _attach_google_sync_flags([schedule], db)
    return schedule

@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete a schedule"""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Cancel pending reminders
    ReminderService().cancel_reminders_for_schedule(schedule.id, db)
    db.commit()

    # Enqueue async delete
    _enqueue_google_sync(schedule, SyncOperation.DELETE, db)
    db.commit()

    db.delete(schedule)
    db.commit()
    return None


# Recurring-specific endpoints
@router.get("/{schedule_id}/instances")
def get_schedule_instances(
    schedule_id: UUID,
    range_start: datetime = Query(..., description="Start of date range"),
    range_end: datetime = Query(..., description="End of date range"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get instances of a recurring event within a date range."""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if not schedule.recurrence_rule or schedule.recurrence_rule.get("freq") == "NONE":
        raise HTTPException(status_code=400, detail="Schedule is not recurring")

    instances = RecurrenceService().generate_instances(
        root=schedule,
        range_start=range_start,
        range_end=range_end,
        db=db,
    )

    return {"instances": instances, "total": len(instances)}


@router.put("/{schedule_id}/instances/{original_start_time}")
def update_schedule_instance(
    schedule_id: UUID,
    original_start_time: datetime,
    instance_data: ScheduleInstanceUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update a recurring event instance (this_only, this_and_after, or all)."""
    root = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not root:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if not root.recurrence_rule or root.recurrence_rule.get("freq") == "NONE":
        raise HTTPException(status_code=400, detail="Schedule is not recurring")

    # Handle based on edit_scope
    if instance_data.edit_scope.value == "this_only":
        # Find or create exception record
        exception = db.query(Schedule).filter(
            Schedule.recurrence_id == root.id,
            Schedule.original_start_time == original_start_time,
        ).first()

        if exception is None:
            # Create new exception from root template
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
                recurrence_rule=None,  # Exceptions don't have rules
            )
            db.add(exception)

        # Apply updates to exception
        update_data = instance_data.updates.model_dump(exclude_unset=True)
        if "recurrence" in update_data:
            update_data.pop("recurrence")  # Exceptions can't have recurrence

        for field, value in update_data.items():
            if field != "reminders":
                setattr(exception, field, value)

        if instance_data.updates.reminders is not None:
            ReminderService().create_reminders_for_schedule(
                schedule=exception,
                reminder_configs=[r.model_dump() for r in instance_data.updates.reminders],
                db=db,
            )

        exception.version += 1
        db.commit()
        db.refresh(exception)
        _attach_google_sync_flags([exception], db)
        return exception

    elif instance_data.edit_scope.value == "this_and_after":
        # Truncate original series until before original_start_time
        from datetime import timedelta
        new_until = original_start_time - timedelta(days=1)
        root.recurrence_rule["until"] = new_until.isoformat()

        # Create new series from original_start_time
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
        db.add(new_root)
        db.commit()
        db.refresh(new_root)
        _enqueue_google_sync(new_root, SyncOperation.UPSERT, db)
        db.commit()
        _attach_google_sync_flags([new_root], db)
        return new_root

    elif instance_data.edit_scope.value == "all":
        # Update root series directly
        update_data = instance_data.updates.model_dump(exclude_unset=True)
        if "recurrence" in update_data:
            root.recurrence_rule = update_data.pop("recurrence")
            if root.recurrence_rule:
                root.recurrence_rule = root.recurrence_rule.model_dump()

        for field, value in update_data.items():
            if field != "reminders":
                setattr(root, field, value)

        if instance_data.updates.reminders is not None:
            ReminderService().create_reminders_for_schedule(
                schedule=root,
                reminder_configs=[r.model_dump() for r in instance_data.updates.reminders],
                db=db,
            )

        root.version += 1
        db.commit()
        db.refresh(root)
        _enqueue_google_sync(root, SyncOperation.UPSERT, db)
        db.commit()
        _attach_google_sync_flags([root], db)
        return root

    else:
        raise HTTPException(status_code=400, detail="Invalid edit_scope")


@router.delete("/{schedule_id}/instances/{original_start_time}", status_code=204)
def cancel_schedule_instance(
    schedule_id: UUID,
    original_start_time: datetime,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Cancel a single instance of a recurring event."""
    root = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not root:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if not root.recurrence_rule or root.recurrence_rule.get("freq") == "NONE":
        raise HTTPException(status_code=400, detail="Schedule is not recurring")

    # Find or create exception and mark as cancelled
    exception = db.query(Schedule).filter(
        Schedule.recurrence_id == root.id,
        Schedule.original_start_time == original_start_time,
    ).first()

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
        db.add(exception)
    else:
        exception.is_cancelled = True
        exception.version += 1

    db.commit()
    _enqueue_google_sync(exception, SyncOperation.UPSERT, db)
    db.commit()
    return None


# Reminder endpoints
@router.get("/{schedule_id}/reminders")
def get_schedule_reminders(
    schedule_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get all reminders for a schedule."""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    reminders = ReminderService().get_reminders_for_schedule(schedule_id, db)
    return {
        "reminders": reminders,
        "total": len(reminders),
    }


@router.post("/{schedule_id}/reminders", status_code=201)
def add_schedule_reminder(
    schedule_id: UUID,
    reminder_configs: list,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Add reminders to a schedule."""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    reminders = ReminderService().create_reminders_for_schedule(
        schedule=schedule,
        reminder_configs=reminder_configs,
        db=db,
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
    """Delete a reminder."""
    from app.models import ScheduleReminder

    reminder = db.query(ScheduleReminder).filter(
        ScheduleReminder.id == reminder_id,
        ScheduleReminder.schedule_id == schedule_id,
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    db.delete(reminder)
    db.commit()
    return None
