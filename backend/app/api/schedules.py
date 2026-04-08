from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import CalendarProvider, Schedule, ScheduleExternalMap, User
from app.schemas import ScheduleCreate, ScheduleUpdate, ScheduleResponse, ScheduleListResponse
from app.services.google_calendar_sync import GoogleCalendarSyncService

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

@router.post("", response_model=ScheduleResponse, status_code=201)
def create_schedule(
    schedule: ScheduleCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a new schedule"""
    db_schedule = Schedule(
        user_id=current_user.id,
        title=schedule.title,
        type=schedule.type,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        location=schedule.location,
        description=schedule.description,
        is_completed=False
    )
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    GoogleCalendarSyncService(db).sync_upsert_schedule(db_schedule)
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
    
    Query Parameters:
    - start_date: Start date in ISO format (required)
    - end_date: End date in ISO format (required)
    - user_id: Automatically inferred from access token
    
    Example: /api/schedules?start_date=2026-04-01T00:00:00&end_date=2026-04-30T23:59:59
    """
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")
    
    schedules = db.query(Schedule).filter(
        Schedule.user_id == current_user.id,
        Schedule.start_time >= start_date,
        Schedule.start_time <= end_date
    ).order_by(Schedule.start_time).all()
    _attach_google_sync_flags(schedules, db)
    
    return {
        "items": schedules,
        "total": len(schedules)
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
    db: Session = Depends(get_db)
):
    """Update a schedule"""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    update_data = schedule_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(schedule, field, value)
    
    schedule.updated_at = datetime.utcnow()
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    GoogleCalendarSyncService(db).sync_upsert_schedule(schedule)
    _attach_google_sync_flags([schedule], db)
    return schedule

@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a schedule"""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.id,
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    GoogleCalendarSyncService(db).sync_delete_schedule(schedule)
    db.delete(schedule)
    db.commit()
    return None
