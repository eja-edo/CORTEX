from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.schemas import CalendarItem, TaskResponse
from app.services.calendar_items import CalendarItemService
from app.services.tasks import TaskService

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/items", response_model=list[CalendarItem])
async def get_calendar_items(
    range_start: datetime = Query(..., alias="from", description="Start of the visible window"),
    range_end: datetime = Query(..., alias="to", description="End of the visible window"),
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Everything on the calendar between `from` and `to`, in one shape.

    Schedules and tasks come back merged and time-sorted, each carrying
    `render_as` so the client draws them correctly without knowing there are
    two tables behind this: `block` occupies a span in the time grid,
    `marker` is a point in the day.

    Read-only, and deliberately so — no task is ever written into
    `schedules`. That table means "time that is actually taken", which is
    what free-slot planning (3.3) and interruptibility (6.2) depend on.
    """
    if range_end < range_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`to` must not be earlier than `from`",
        )

    service = CalendarItemService(db)
    return await service.get_items(
        user_id=current_user.id, range_start=range_start, range_end=range_end
    )


@router.get("/events/{event_id}/checklist", response_model=list[TaskResponse])
async def get_event_checklist(
    event_id: UUID,
    occurrence_start_time: datetime | None = Query(
        None,
        description=(
            "The specific occurrence being viewed. Only matters when the event "
            "is recurring — see CalendarItemService.get_event_checklist."
        ),
    ),
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """The checklist inside an event: `tasks WHERE related_event_id = event_id`.

    The widget renders these as checkable lines. It never parses the event's
    description — checklist state lives in `tasks`, and the description stays
    prose. Each user action maps to one command (task.create / task.complete /
    task.delete / task.update), so there is nothing to diff or reconcile.
    """
    service = TaskService(db)
    tasks = await CalendarItemService(db).get_event_checklist(
        user_id=current_user.id,
        event_id=event_id,
        occurrence_start_time=occurrence_start_time,
    )
    return [service.to_response(task) for task in tasks]
