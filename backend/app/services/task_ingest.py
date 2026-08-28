"""Nhận action item từ bot họp — `docs/DESIGN.md` mục 5 và 9.1.

Đây là **tầng 1** của mô hình ba tầng, và điều quan trọng nhất về nó là
Cortex *không tự xây* nó (1.1). Bot họp đã làm khâu trích xuất; cạnh tranh
khâu đó là tự chọn trận thua (1.4). Module này chỉ nhận về, gom theo dự án,
và giao lại cho tầng 3 quyết định lúc nào nói.

Ba quy tắc chi phối mọi thứ dưới đây:

**Nghi ngờ thì bỏ (P7).** Người nhận không liên kết Mezon → bỏ qua item đó
và báo lại, không đoán xem nó thuộc về ai. Một action item gán nhầm người
tệ hơn nhiều một action item bị bỏ sót.

**Channel là danh tính dự án (QĐ-2).** Item đến từ channel C thì thuộc dự
án của C — tạo lười nếu chưa có (4.1). Đây là cửa chính để một dự án ra
đời; `create_project` chỉ là lối phụ.

**Lịch là khung thời gian, không phải cấu trúc dự án.** `provider_event_id`
dùng để ghi *nguồn gốc* (`related_event_id`) và làm đường dự phòng cho
project khi không có channel — không bao giờ để đoán dự án từ hình dạng
lịch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AttentionChannel,
    CalendarProvider,
    Schedule,
    ScheduleExternalMap,
    Task,
    TaskPriority,
    TaskStatus,
)
from app.services.projects import ProjectService
from app.services.user_channels import resolve_channel_async
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IngestedItem:
    """Một action item đã xử lý xong, ở dạng báo cáo lại cho người gửi.

    `skipped_reason` là trường quan trọng nhất: bot họp cần biết item nào
    **không** vào được, và vì sao, để nó nói lại với người dùng ở channel
    thay vì im lặng đánh rơi.
    """

    external_id: str | None
    task_id: UUID | None = None
    created: bool = False
    skipped_reason: str | None = None


@dataclass
class IngestResult:
    items: list[IngestedItem] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return sum(1 for i in self.items if i.created)

    @property
    def skipped_count(self) -> int:
        return sum(1 for i in self.items if i.skipped_reason is not None)


class TaskIngestService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest(self, items: list) -> IngestResult:
        """Nhận một lô action item. Một item hỏng không làm hỏng cả lô.

        Bot họp gửi cả cuộc họp một lần, nên fail toàn lô vì một người chưa
        liên kết Mezon sẽ đánh rơi mọi việc của cuộc họp đó. Mỗi item được
        báo cáo riêng và lô vẫn commit.
        """
        result = IngestResult()
        for item in items:
            try:
                result.items.append(await self._ingest_one(item))
            except Exception as exc:  # pragma: no cover - hàng rào cuối
                logger.exception("Failed to ingest action item: %s", exc)
                result.items.append(
                    IngestedItem(external_id=item.external_id, skipped_reason="error")
                )
        await self.session.commit()
        return result

    async def _ingest_one(self, item) -> IngestedItem:
        user_id = await self._resolve_assignee(item)
        if user_id is None:
            # P7. Không có "gán tạm cho người tạo cuộc họp" — một việc gán
            # nhầm người là một lời nhắc sai gửi tới một người không liên
            # quan, và nó phá niềm tin nhanh hơn bất kỳ việc bị sót nào.
            return IngestedItem(
                external_id=item.external_id, skipped_reason="assignee_not_linked"
            )

        if item.external_id:
            existing = await self.session.scalar(
                select(Task).where(
                    Task.user_id == user_id,
                    Task.source_external_id == item.external_id,
                )
            )
            if existing is not None:
                # Gửi lại, không phải việc mới. Trả về hàng đã có để bot
                # thấy 200 và ngừng thử lại.
                return IngestedItem(
                    external_id=item.external_id, task_id=existing.id, created=False
                )

        schedule = await self._resolve_schedule(item, user_id)
        project_id = await self._resolve_project(item, user_id, schedule)

        task = Task(
            user_id=user_id,
            project_id=project_id,
            title=item.title.strip(),
            description=item.description,
            # `TODO`, không phải `PENDING_CONFIRM`. Trạng thái chờ xác nhận
            # dành cho thứ **Cortex tự đoán** từ hội thoại; đây là output
            # của một hệ thống trích xuất khác, đã qua mắt người trong cuộc
            # họp. Bắt xác nhận lại là bắt làm hai lần một việc.
            status=TaskStatus.TODO,
            due_date=item.due_date,
            priority=TaskPriority(item.priority) if item.priority else None,
            related_event_id=schedule.id if schedule is not None else None,
            source_external_id=item.external_id,
        )
        self.session.add(task)
        await self.session.flush()

        logger.info(
            "ingested action item",
            extra={
                "task_id": str(task.id),
                "project_id": str(project_id),
                "from_channel": bool(item.source_channel_id),
                "matched_event": schedule is not None,
            },
        )
        return IngestedItem(external_id=item.external_id, task_id=task.id, created=True)

    # ------------------------------------------------------------------
    # Danh tính người nhận
    # ------------------------------------------------------------------

    async def _resolve_assignee(self, item) -> UUID | None:
        """Mezon user id → tài khoản Cortex, chỉ qua liên kết **đã xác minh**.

        `resolve_channel_async` cố ý chỉ khớp hàng đã verify: một Mezon id
        là con số ai trong clan cũng đọc được, nên sở hữu nó không chứng
        minh gì. Nhận item cho một liên kết chưa xác minh sẽ biến bước liên
        kết thành đồ trang trí.
        """
        if item.assignee_user_id:
            # Đường dành cho hệ thống nội bộ đã biết user id Cortex. Vẫn
            # phải là một tài khoản có thật.
            from app.models import User

            user = await self.session.get(User, item.assignee_user_id)
            return user.id if user is not None else None

        if not item.assignee_mezon_user_id:
            return None

        link = await resolve_channel_async(
            self.session,
            channel=AttentionChannel.MEZON,
            address=str(item.assignee_mezon_user_id),
        )
        return link.user_id if link is not None else None

    # ------------------------------------------------------------------
    # Sự kiện nguồn (DESIGN 4.2 mức 1)
    # ------------------------------------------------------------------

    async def _resolve_schedule(self, item, user_id: UUID) -> Schedule | None:
        """`provider_event_id` → `ScheduleExternalMap` → `Schedule` của *người này*.

        Lọc theo `user_id` không phải thừa: lịch không sync chéo, nên mỗi
        người dự cuộc họp có hàng `Schedule` riêng cho cùng một sự kiện
        Google. Bỏ bộ lọc đi thì task của người A trỏ vào hàng lịch của
        người B — và mọi thứ đọc `related_event_id` sau đó đều sai.
        """
        if not item.provider_event_id:
            return None

        mapping = await self.session.scalar(
            select(ScheduleExternalMap).where(
                ScheduleExternalMap.provider_event_id == item.provider_event_id,
                ScheduleExternalMap.user_id == user_id,
                ScheduleExternalMap.provider == CalendarProvider.GOOGLE,
            )
        )
        if mapping is None:
            return None
        return await self.session.get(Schedule, mapping.schedule_id)

    # ------------------------------------------------------------------
    # Dự án (DESIGN 3.5 + 4.1)
    # ------------------------------------------------------------------

    async def _resolve_project(self, item, user_id: UUID, schedule: Schedule | None) -> UUID:
        """Thang ba bước, dừng ở bước đầu tiên có kết quả.

        Bước 1 ở đây là **channel**, không phải một `project_ref` gõ tay:
        channel là danh tính chung của dự án (QĐ-2) và là cửa chính để dự
        án ra đời (4.1). Người thứ hai nhận việc từ cùng channel tìm thấy
        dự án đã có và tự vào làm thành viên — không tạo bản thứ hai.
        """
        service = ProjectService(self.session)

        if item.source_channel_id:
            project = await service.get_or_create_for_channel(
                channel_id=str(item.source_channel_id),
                channel_name=item.source_channel_name or "",
                user_id=user_id,
            )
            return project.id

        # Không có channel: rơi về thang chung. Sự kiện chỉ cho project khi
        # ai đó đã gắn chuỗi vào một dự án (4.2 mức 4) — không suy từ hình
        # dạng lịch, P7 cấm.
        return await service.resolve_for_task(
            user_id=user_id,
            related_event_id=schedule.id if schedule is not None else None,
        )
