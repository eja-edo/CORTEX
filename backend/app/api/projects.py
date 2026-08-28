"""Project endpoints — `docs/DESIGN.md` mục 9.1.

Chỉ những gì cần, và cố ý thiếu một thứ: **không có endpoint xoá.**
`status='closed'` là đủ, và xoá sẽ mồ côi lịch sử `attention_log` — bảng
ghi lại việc Cortex đã nhắc gì, vốn vẫn đúng sau khi thứ được nhắc biến
mất (xem `AttentionLog` docstring).

Quyền truy cập đi qua `project_members`, không qua `owner_id` (QĐ-1):
project là thực thể dùng chung, `owner_id` chỉ nói ai tạo ra nó. Không
phải thành viên thì trả **404**, không phải 403 — nói "403" là xác nhận có
một dự án id như vậy tồn tại, và đó là rò rỉ không có lý do gì để chấp nhận.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.models import Project, ProjectStatus, Schedule, Task
from app.schemas import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    ScheduleProjectUpdate,
    ScheduleProjectUpdateResponse,
)
from app.services.projects import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_response(project: Project, metrics: dict) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        status=project.status,
        origin=project.origin,
        deadline=project.deadline,
        deadline_is_manual=project.deadline_is_manual,
        source_channel_id=project.source_channel_id,
        created_at=project.created_at,
        updated_at=project.updated_at,
        **metrics,
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    project_status: ProjectStatus | None = Query(
        ProjectStatus.ACTIVE,
        alias="status",
        description="Mặc định chỉ dự án đang mở. Truyền rỗng để lấy mọi trạng thái.",
    ),
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Dự án của người đang đăng nhập, kèm số liệu tóm tắt.

    Mặc định lọc `active`: một danh sách gộp cả dự án đã đóng là một kho
    lưu trữ, và bộ chuyển dự án ở topbar đọc thẳng endpoint này.
    """
    rows = await ProjectService(db).list_for_user(current_user.id, status=project_status)
    # Rủi ro cao trước, rồi tên — cùng thứ tự với ưu tiên của màn Hôm nay,
    # nên hai bề mặt không xếp cùng một tập dự án theo hai kiểu khác nhau.
    rows.sort(key=lambda pair: (-pair[1]["risk"], pair[0].name.lower()))
    return [_to_response(p, m) for p, m in rows]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Tạo tay — **lối phụ, không phải cửa chính** (DESIGN 9.1).

    Cửa chính là 4.1: channel có việc thì tự thành dự án, không ai bấm gì.
    """
    service = ProjectService(db)
    project = await service.create_manual(current_user.id, payload.name, payload.deadline)
    await db.commit()
    await db.refresh(project)
    _, metrics = await service.get_for_user(project.id, current_user.id)
    return _to_response(project, metrics)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    found = await ProjectService(db).get_for_user(project_id, current_user.id)
    if found is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_response(*found)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Sửa `name`, `deadline`, `status`.

    Chạm vào `deadline` — kể cả để bỏ hạn — bật `deadline_is_manual`, nên
    suy ra hằng ngày ở 4.3 không ghi đè lựa chọn của người dùng vào sáng
    hôm sau. Xem `ProjectService.update`.
    """
    service = ProjectService(db)
    found = await service.get_for_user(project_id, current_user.id)
    if found is None:
        raise HTTPException(status_code=404, detail="Project not found")

    project, _ = found
    await service.update(project, payload)
    await db.commit()
    await db.refresh(project)
    _, metrics = await service.get_for_user(project.id, current_user.id)
    return _to_response(project, metrics)


# ---------------------------------------------------------------------------
# Gán chuỗi sự kiện vào dự án — DESIGN 4.2 mức 4, "lối sửa, luôn có"
# ---------------------------------------------------------------------------
#
# Sống ở router này chứ không ở `schedules.py` vì nó là thao tác *về dự án*:
# thứ nó ghi là quan hệ lịch ↔ dự án, và mọi quy tắc chi phối nó (chỉ hàng
# template, không ghi đè task cũ) nằm ở mục 3.2/3.5 chứ không ở phần lịch.

schedule_project_router = APIRouter(prefix="/schedules", tags=["projects"])


@schedule_project_router.patch(
    "/{schedule_id}/project", response_model=ScheduleProjectUpdateResponse
)
async def set_schedule_project(
    schedule_id: UUID,
    payload: ScheduleProjectUpdate,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Gán một chuỗi sự kiện vào dự án. `project_id: null` gỡ liên kết.

    Hai ràng buộc, cả hai đều là chủ ý chứ không phải hạn chế kỹ thuật:

    **Chỉ hàng template** (`recurrence_id IS NULL`). Đặt lên occurrence
    exception thì một chuỗi 30 lần lặp sinh 30 hàng cùng project, và quy
    tắc suy ra ở 3.5 bước 2 sẽ trôi theo từng occurrence.

    **Không đổi project của task đã tạo từ chuỗi này.** Task đã có project
    riêng; ghi đè hàng loạt là hành vi phá hoại. Trả về số task bị ảnh
    hưởng để UI *hỏi* — *"chuyển N việc cũ sang theo không?"* — thay vì làm
    im lặng rồi để người dùng phát hiện sau (DESIGN 3.5, 10.1).
    """
    schedule = await db.get(Schedule, schedule_id)
    if schedule is None or schedule.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if schedule.recurrence_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Chỉ gán project trên hàng template của chuỗi. "
                "Hàng này là một occurrence exception."
            ),
        )

    if payload.project_id is not None:
        service = ProjectService(db)
        if await service.get_for_user(payload.project_id, current_user.id) is None:
            raise HTTPException(status_code=404, detail="Project not found")

    schedule.project_id = payload.project_id

    affected = int(
        await db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.related_event_id == schedule_id,
                Task.project_id != payload.project_id
                if payload.project_id is not None
                else True,
            )
        )
        or 0
    )

    await db.commit()
    return ScheduleProjectUpdateResponse(
        schedule_id=schedule_id,
        project_id=payload.project_id,
        affected_task_count=affected,
    )
