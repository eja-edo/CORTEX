from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.models import TaskStatus
from app.schemas import TaskCreate, TaskRejectionCheck, TaskResponse, TaskUpdate
from app.services.tasks import InvalidTaskTransition, TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = TaskService(db)
    created = await service.create_task(payload=payload, user_id=current_user.id)
    return service.to_response(created)


@router.get("", response_model=list[TaskResponse])
async def get_tasks(
    task_status: TaskStatus | None = Query(
        None, alias="status", description="Filter by status; omit for all statuses"
    ),
    related_event_id: UUID | None = Query(
        None, description="Only tasks attached to this event — the checklist widget's query (2.6)"
    ),
    parent_task_id: UUID | None = Query(
        None, description="Only sub-tasks of this task — a task's own checklist"
    ),
    due_before: date | None = Query(None, description="Only tasks due on or before this date"),
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = TaskService(db)
    tasks = await service.get_tasks(
        current_user.id,
        status=task_status,
        related_event_id=related_event_id,
        parent_task_id=parent_task_id,
        due_before=due_before,
    )
    return [service.to_response(task) for task in tasks]


@router.get("/rejected-check", response_model=TaskRejectionCheck)
async def check_rejected(
    title: str = Query(..., min_length=1, max_length=255),
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Has the user already rejected this exact suggested task?

    The extraction pipeline calls this before proposing a candidate;
    re-suggesting something the user turned down reads as not listening.
    Declared above `/{task_id}` so the literal path wins the route match.
    """
    service = TaskService(db)
    return await service.check_rejected(user_id=current_user.id, title=title)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = TaskService(db)
    task = await service.get_task(task_id=task_id, user_id=current_user.id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return service.to_response(task)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = TaskService(db)
    try:
        updated = await service.update_task(task_id=task_id, user_id=current_user.id, payload=payload)
    except InvalidTaskTransition as exc:
        # 409, not 422: the body is well-formed, it's the task's current state
        # that makes the change impossible.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return service.to_response(updated)


@router.post("/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: UUID,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Tick the box. Separate from PATCH because it's the single most common
    write (checklist in an event, 2.6) and shouldn't require a body."""
    service = TaskService(db)
    try:
        completed = await service.complete_task(task_id=task_id, user_id=current_user.id)
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if completed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return service.to_response(completed)


@router.post("/{task_id}/complete_with_subtasks", response_model=list[TaskResponse])
async def complete_task_with_subtasks(
    task_id: UUID,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Tick the box and cascade to every sub-task beneath it (recursively).

    The confirm-dialog flow for a parent task that has its own checklist —
    called once the user's answered "yes, all of it's done." Returns every
    task that changed (descendants first, root last) so the caller can patch
    its cache without a full refetch.
    """
    service = TaskService(db)
    try:
        updated = await service.complete_task_cascade(task_id=task_id, user_id=current_user.id)
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return [service.to_response(t) for t in updated]


@router.post("/{task_id}/confirm", response_model=TaskResponse)
async def confirm_task(
    task_id: UUID,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Confirm a suggested task: pending_confirm → todo."""
    service = TaskService(db)
    try:
        confirmed = await service.confirm_task(task_id=task_id, user_id=current_user.id)
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if confirmed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return service.to_response(confirmed)


@router.post("/{task_id}/reject", response_model=TaskResponse)
async def reject_task(
    task_id: UUID,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Reject a suggested task. The row is kept, not deleted — it's what
    stops the extractor proposing the same thing again."""
    service = TaskService(db)
    try:
        rejected = await service.reject_task(task_id=task_id, user_id=current_user.id)
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if rejected is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return service.to_response(rejected)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    service = TaskService(db)
    deleted = await service.delete_task(task_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return None
