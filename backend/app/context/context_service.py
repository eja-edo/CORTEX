"""
ContextService: central context building, replacing the fully-ad-hoc parts
of context handling scattered across AgentService/ConversationService.

⚠️ 2026-08-06: this does NOT replace `_inject_context_into_text` (the
existing per-message pills/page/runtime injection in
conversation_service.py) — that mechanism also feeds skill retrieval and
runs on every historical message, not just the current one; replacing it
outright would be a much larger, riskier change to the live chat pipeline
than Milestone 1.7 warrants. ContextService is additive: it builds the
project/recent-notes/recent-schedules sections that don't exist anywhere
today, surfaced via `UnifiedContext.to_llm_string()` appended to the system
prompt (see ConversationService.build_system_prompt).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.schemas import (
    ActiveProcedure,
    ContextPill,
    ProjectContext,
    RecalledMemory,
    UnifiedContext,
)
from app.models import Note, Project, ProjectMember, Schedule
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ContextService:
    """Aggregates context from multiple sources into a single UnifiedContext."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build_context(
        self,
        user_id: UUID,
        project_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,
        runtime_context: Optional[dict] = None,
        intent: Optional[str] = None,
        message: str = "",
    ) -> UnifiedContext:
        """
        Build unified context for a user/request.

        Args:
            user_id: User ID
            project_id: Dự án đang mở, nếu có
            conversation_id: Current conversation, if any (unused today —
                accepted for forward-compat, e.g. a future
                ConversationContext section)
            runtime_context: The frontend's raw context dict (pills/page/runtime)
            intent: Detected intent (Milestone 1.8) — when given, filters
                recent_notes/recent_schedules by relevance
            message: Lượt nói hiện tại của người dùng, dùng làm truy vấn
                recall bộ nhớ dài hạn. Rỗng thì bỏ qua bước recall.

        Returns:
            UnifiedContext. Never raises — DB lookups that fail are logged
            and simply omitted, since context is an enrichment, not a
            requirement, for the chat flow to function.
        """
        runtime_context = runtime_context or {}

        pills = self._extract_pills(runtime_context)
        page = runtime_context.get("page") if isinstance(runtime_context.get("page"), dict) else {}
        runtime = runtime_context.get("runtime") if isinstance(runtime_context.get("runtime"), dict) else {}

        project = None
        if project_id is not None:
            project = await self._get_project_context(project_id, user_id)

        recent_notes = await self._get_recent_notes(user_id, limit=5)
        recent_schedules = await self._get_upcoming_schedules(user_id, limit=5)
        recalled_memories = await self._recall_memories(user_id, message, limit=5)
        active_procedure = await self._match_procedure(user_id, message)

        context = UnifiedContext(
            pills=pills,
            page=page,
            runtime=runtime,
            project=project,
            recent_notes=recent_notes,
            recent_schedules=recent_schedules,
            recalled_memories=recalled_memories,
            active_procedure=active_procedure,
        )

        if intent:
            context = self._filter_by_relevance(context, intent)

        logger.debug(
            f"Context built for user {user_id}",
            extra={
                "user_id": str(user_id),
                "project_id": str(project_id) if project_id else None,
                "pills_count": len(context.pills),
                "recent_notes_count": len(context.recent_notes),
                "recent_schedules_count": len(context.recent_schedules),
                "recalled_memories_count": len(context.recalled_memories),
                "active_procedure": bool(context.active_procedure),
            },
        )

        return context

    def _extract_pills(self, raw: dict) -> list[ContextPill]:
        pills_data = raw.get("pills") or []
        pills = []
        for pill_data in pills_data:
            if not isinstance(pill_data, dict) or not pill_data.get("text"):
                continue
            pills.append(ContextPill(text=pill_data["text"], source=pill_data.get("source", "user")))
        return pills

    async def _get_project_context(self, project_id: UUID, user_id: UUID) -> Optional[ProjectContext]:
        try:
            project = (
                await self.db.execute(select(Project).where(Project.id == project_id))
            ).scalar_one_or_none()
            if project is None:
                return None

            # Không phải thành viên thì coi như không có dự án nào đang mở —
            # cùng lối "404, không 403" của `api/projects.py`: dựng ngữ cảnh
            # cho một dự án người này không ở trong là rò nội dung của nó
            # vào prompt.
            member = (
                await self.db.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == project_id,
                        ProjectMember.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                return None

            member_count = (
                await self.db.execute(
                    select(func.count()).select_from(ProjectMember).where(
                        ProjectMember.project_id == project_id
                    )
                )
            ).scalar_one()

            return ProjectContext(
                project_id=project.id,
                project_name=project.name,
                member_count=member_count,
            )
        except Exception as exc:
            logger.warning(f"Failed to build project context (non-fatal): {exc}")
            return None

    async def _get_recent_notes(self, user_id: UUID, limit: int = 5) -> list[dict]:
        try:
            stmt = (
                select(Note)
                .where(Note.user_id == user_id, Note.is_deleted.is_(False))
                .order_by(Note.updated_at.desc())
                .limit(limit)
            )
            notes = (await self.db.execute(stmt)).scalars().all()
            return [
                {
                    "id": str(note.id),
                    "title": note.title,
                    "updated_at": note.updated_at.isoformat() if note.updated_at else None,
                }
                for note in notes
            ]
        except Exception as exc:
            logger.warning(f"Failed to fetch recent notes (non-fatal): {exc}")
            return []

    async def _get_upcoming_schedules(self, user_id: UUID, limit: int = 5) -> list[dict]:
        try:
            now = datetime.now(timezone.utc)
            future = now + timedelta(days=7)
            stmt = (
                select(Schedule)
                .where(
                    Schedule.user_id == user_id,
                    Schedule.start_time >= now,
                    Schedule.start_time <= future,
                    Schedule.is_completed.is_(False),
                )
                .order_by(Schedule.start_time.asc())
                .limit(limit)
            )
            schedules = (await self.db.execute(stmt)).scalars().all()
            return [
                {
                    "id": str(schedule.id),
                    "title": schedule.title,
                    "start_time": schedule.start_time.isoformat(),
                    "type": schedule.type.value if hasattr(schedule.type, "value") else str(schedule.type),
                }
                for schedule in schedules
            ]
        except Exception as exc:
            logger.warning(f"Failed to fetch upcoming schedules (non-fatal): {exc}")
            return []

    async def _recall_memories(
        self, user_id: UUID, message: str, limit: int = 5
    ) -> list[RecalledMemory]:
        """Kéo bộ nhớ dài hạn liên quan lên, **mỗi lượt**, không đợi model xin.

        Đây là chỗ sửa kiểu hỏng đắt nhất của tầng bộ nhớ: trước đây tool
        `extract_memory` là đường **duy nhất** chạm tới kho ngữ nghĩa, và nó
        là một tool do model tự quyết định gọi. Nên cùng một người dùng,
        cùng một dữ liệu, lượt nào model nhớ gọi thì thấy "nó hiểu mình",
        lượt nào quên thì phải giải thích lại từ đầu. Chất lượng giữa các
        phiên lệch nhau không vì kho bộ nhớ, mà vì một quyết định ngẫu nhiên
        của model — và system prompt đã phải dành hẳn một mục dài để dạy nó
        đừng quên. Khi một việc là bắt buộc, nó thuộc về code.

        `extract_memory` vẫn còn nguyên và vẫn có ích: nó tra được thứ *khác*
        với lượt nói hiện tại ("lần trước mình chốt gì về X"), thứ recall
        theo message không với tới.

        Không bao giờ ném lỗi: bộ nhớ là phần làm giàu ngữ cảnh, không phải
        điều kiện để trả lời được.
        """
        if not message or not message.strip():
            return []

        try:
            from app.services.semantic_memory_provider import (
                MIN_RELEVANCE_SCORE,
                get_semantic_memory_provider,
            )

            provider = get_semantic_memory_provider(self.db)
            results = await provider.search_semantic_memories(
                # Bộ nhớ khoá theo **người** — cùng khoá
                # `memory_extraction_service` ghi vào. Xem docstring của
                # `SemanticMemoryProvider`.
                user_id=str(user_id),
                query=message,
                limit=limit,
                min_score=MIN_RELEVANCE_SCORE,
            )
            return [
                RecalledMemory(
                    content=r.get("content", ""),
                    category=r.get("category", "fact"),
                    score=float(r.get("score", 0.0)),
                )
                for r in results
                if r.get("content")
            ]
        except Exception as exc:
            logger.warning(f"Memory recall failed (non-fatal): {exc}")
            return []

    async def _match_procedure(
        self, user_id: UUID, message: str
    ) -> Optional[ActiveProcedure]:
        """Quy trình khớp hoàn cảnh vừa nêu, kèm tiến độ của lần chạy hôm nay.

        Khác với `_recall_memories` ở chỗ nó **ghi**: khớp trigger sẽ mở
        một `ProcedureRun` nếu chưa có. Đó là chủ ý — "hôm nay tôi remote"
        chính là lúc lần chạy bắt đầu, và nếu đợi người dùng nói thêm một
        câu nữa thì bước đầu tiên họ báo xong sẽ không có chỗ nào để ghi.

        Ngưỡng khớp ở đây chặt (0.70, xem `MIN_TRIGGER_SCORE`) chính vì nó
        ghi: một lần khớp nhầm không chỉ làm nhiễu ngữ cảnh mà còn tạo ra
        một run rác.

        Không bao giờ ném lỗi — như mọi phần khác của ngữ cảnh.
        """
        try:
            from app.services.procedures import ProcedureService

            service = ProcedureService(self.db)

            # Nhánh 1 — người dùng **đang ở giữa** một quy trình.
            #
            # Ưu tiên hơn khớp trigger, và đó là điểm mấu chốt: "daily xong
            # rồi nhé" không chứa từ nào khớp trigger "remote". Khi khối
            # quy trình phụ thuộc trigger, câu đó làm khối biến mất, agent
            # mất `procedure_id`, và nó **bịa ra một id** —
            # `remote_work_2026-09-10` — rồi lời gọi tool hỏng. Đang ở
            # giữa một quy trình là một trạng thái, không phải một câu nói.
            current = await service.current_run_for_user(user_id)
            if current is not None:
                procedure, run = current
                score = 1.0
            else:
                # Nhánh 2 — chưa có run nào; lượt này có mở một cái không.
                if not message or not message.strip():
                    return None
                matched = await service.match(user_id, message)
                if matched is None:
                    return None
                procedure, score = matched
                run = await service.get_or_open_run(procedure)

            pending = service.pending_steps(procedure, run)
            pending_orders = {s["order"] for s in pending}
            done = [s for s in (procedure.steps or []) if s["order"] not in pending_orders]

            return ActiveProcedure(
                procedure_id=str(procedure.id),
                title=procedure.title,
                trigger_text=procedure.trigger_text,
                score=score,
                pending=pending,
                done=done,
                run_id=str(run.id),
            )
        except Exception as exc:
            logger.warning(f"Procedure matching failed (non-fatal): {exc}")
            return None

    def _filter_by_relevance(self, context: UnifiedContext, intent: str) -> UnifiedContext:
        """Simple keyword-based relevance filter (Milestone 1.8 will pass a
        real detected intent here). Drops the section that's clearly
        off-topic rather than trying to rank/score every item."""
        intent_lower = intent.lower()

        if any(kw in intent_lower for kw in ("schedule", "calendar", "remind")):
            context.recent_notes = []
        elif any(kw in intent_lower for kw in ("note", "write", "document")):
            context.recent_schedules = []

        return context
