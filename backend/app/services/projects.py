"""Project resolution — deciding which project a task belongs to.

See `docs/DESIGN.md` section 3 (data model), 3.5 (the ladder below) and
4.1 (channel-derived projects). Two rules shape everything here:

**Every task belongs to exactly one project.** `tasks.project_id` is
NOT NULL, so this module can never return `None`. The bottom of the ladder
is the user's personal project, created lazily.

**Project identity comes from a Mezon channel, never from the calendar.**
Calendars don't sync across users, and inside one work calendar there is no
signal separating "this series is project Alpha" from "this is standup /
1:1 / lunch". Deriving a project from calendar shape would be a guess, and
a wrong project assignment is worse than none (P7). An *event* may later be
linked to a project, but only from hard evidence — see `DESIGN.md` 4.2.

Nothing in this module calls an LLM. It is ordinary lookup and one insert.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Project,
    ProjectJoinSource,
    ProjectMember,
    ProjectOrigin,
    ProjectStatus,
    Schedule,
    Task,
    TaskStatus,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Fallback name for a personal project when the account has neither a
# display name nor an email to borrow from.
PERSONAL_FALLBACK_NAME = "Cá nhân"


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Personal project — the bottom of the ladder
    # ------------------------------------------------------------------

    async def get_or_create_personal(self, user_id: UUID) -> Project:
        """The user's personal project, created on first need.

        Deliberately *not* created at registration. `workspaces` does that
        (`api/auth.py:136`) and the result is that every account — including
        the 94 rows integration tests leave behind — owns an empty container
        it never asked for. Creating on first need keeps the table a
        reflection of real work (P4).
        """
        existing = await self.session.scalar(
            select(Project).where(
                Project.owner_id == user_id,
                Project.origin == ProjectOrigin.PERSONAL,
            )
        )
        if existing is not None:
            return existing

        # Imported here rather than at module scope: `User` is only needed
        # for the display name, and importing it eagerly drags the whole
        # auth surface into every module that resolves a project.
        from app.models import User

        user = await self.session.get(User, user_id)
        name = (getattr(user, "full_name", None) or "").strip() or (
            getattr(user, "email", None) or ""
        ).strip() or PERSONAL_FALLBACK_NAME

        project = Project(
            owner_id=user_id,
            name=name,
            origin=ProjectOrigin.PERSONAL,
            # No channel and no deadline, and neither is an oversight:
            # `deadline IS NULL` is the load-bearing invariant that keeps a
            # personal project from ever emitting a project-level reminder
            # ("Cá nhân có 47 việc quá hạn" is exactly the noise P5 forbids).
            source_channel_id=None,
            deadline=None,
        )
        self.session.add(project)
        await self.session.flush()

        self.session.add(
            ProjectMember(
                project_id=project.id,
                user_id=user_id,
                joined_via=ProjectJoinSource.DERIVED,
            )
        )
        await self.session.flush()
        logger.info("created personal project", extra={"user_id": str(user_id)})
        return project

    # ------------------------------------------------------------------
    # Channel-derived project (DESIGN 4.1)
    # ------------------------------------------------------------------

    async def get_or_create_for_channel(
        self, *, channel_id: str, channel_name: str, user_id: UUID
    ) -> Project:
        """The project anchored to a Mezon channel, created on first task.

        A channel that never produces work never becomes a project, which is
        what keeps chit-chat and announcement channels out of the table.

        The second person to receive work from the same channel *finds* this
        project and joins it — they do not create a second copy. That is the
        whole reason project identity hangs off the channel: it is the only
        identifier every member sees the same way.
        """
        project = await self.session.scalar(
            select(Project).where(Project.source_channel_id == channel_id)
        )
        if project is None:
            project = Project(
                owner_id=user_id,
                name=channel_name or channel_id,
                origin=ProjectOrigin.DERIVED,
                source_channel_id=channel_id,
            )
            self.session.add(project)
            await self.session.flush()
            logger.info(
                "derived project from channel",
                extra={"channel_id": channel_id, "project_id": str(project.id)},
            )

        await self.ensure_member(project.id, user_id)
        return project

    async def ensure_member(
        self,
        project_id: UUID,
        user_id: UUID,
        via: ProjectJoinSource = ProjectJoinSource.DERIVED,
    ) -> None:
        """Membership is derived, not invited (P4).

        Receiving work from a project's channel is enough to be in it. There
        is no invite/approve flow in v1, and no `role` column — that is the
        thing that made `WorkspaceMember` the wrong shape to reuse: its role
        answers *who may read the documents*, not *who is on the hook*.
        """
        already = await self.session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if already is None:
            self.session.add(
                ProjectMember(project_id=project_id, user_id=user_id, joined_via=via)
            )
            await self.session.flush()

    # ------------------------------------------------------------------
    # The ladder (DESIGN 3.5)
    # ------------------------------------------------------------------

    async def resolve_for_task(
        self,
        *,
        user_id: UUID,
        explicit_project_id: UUID | None = None,
        related_event_id: UUID | None = None,
    ) -> UUID:
        """Decide a task's project once, at write time.

        Deliberately resolved on write rather than joined on read. An earlier
        draft computed the project through `related_event_id` at read time
        and stored nothing — but that model cannot express the most common
        case of all: a task that belongs to project Alpha and is attached to
        no meeting. It would have been filed under the personal project,
        which is wrong rather than a sensible default.

        Order matters and never changes:

          1. what the caller said explicitly — the open project in the UI,
             `project_ref` from a tool, `project_ref` on a webhook;
          2. the project already attached to the task's event series;
          3. the personal project.
        """
        if explicit_project_id is not None:
            await self.ensure_member(
                explicit_project_id, user_id, ProjectJoinSource.MANUAL
            )
            return explicit_project_id

        if related_event_id is not None:
            project_id = await self._project_of_event(related_event_id)
            if project_id is not None:
                await self.ensure_member(project_id, user_id)
                return project_id

        personal = await self.get_or_create_personal(user_id)
        return personal.id

    async def _project_of_event(self, schedule_id: UUID) -> UUID | None:
        """A schedule's project, read from the series template.

        An occurrence exception carries `recurrence_id` pointing at the
        template; the template is the only row that holds `project_id`, so
        that one series cannot drift into thirty different projects.
        """
        schedule = await self.session.get(Schedule, schedule_id)
        if schedule is None:
            return None
        if schedule.recurrence_id is None:
            return schedule.project_id
        template = await self.session.get(Schedule, schedule.recurrence_id)
        return template.project_id if template is not None else None

    # ------------------------------------------------------------------
    # Đọc — dự án kèm số liệu (DESIGN 9.1)
    # ------------------------------------------------------------------

    async def list_for_user(
        self, user_id: UUID, *, status: ProjectStatus | None = ProjectStatus.ACTIVE
    ) -> list[tuple[Project, dict]]:
        """Dự án của một người, kèm số liệu tóm tắt.

        *"Dự án của tôi"* đi qua `project_members`, **không** qua
        `owner_id` (QĐ-1): project là thực thể dùng chung, và `owner_id`
        chỉ nói ai tạo ra nó. Lọc theo owner sẽ làm người thứ hai nhận việc
        từ một channel không thấy dự án mà họ vừa được thêm vào.

        Số liệu tính bằng hai truy vấn gộp thay vì một vòng lặp: số dự án
        của một người nhỏ, nhưng N+1 ở đây chảy thẳng vào bộ chuyển dự án
        trên topbar — thứ dựng lại ở mỗi lần điều hướng.
        """
        stmt = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        if status is not None:
            stmt = stmt.where(Project.status == status)

        projects = list((await self.session.scalars(stmt)).all())
        if not projects:
            return []

        metrics = await self._metrics_for(projects, user_id)
        return [(p, metrics[p.id]) for p in projects]

    async def get_for_user(self, project_id: UUID, user_id: UUID) -> tuple[Project, dict] | None:
        """Một dự án, nếu người này ở trong nó. `None` nghĩa là không thấy.

        Trả `None` chứ không raise: tầng API quyết định 404 hay 403, và ở
        đây hai thứ đó là một — không phải thành viên thì dự án không tồn
        tại, và nói khác đi là tiết lộ có một dự án tên như vậy.
        """
        member = await self.session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if member is None:
            return None
        project = await self.session.get(Project, project_id)
        if project is None:
            return None
        metrics = await self._metrics_for([project], user_id)
        return project, metrics[project.id]

    async def _metrics_for(self, projects: list[Project], user_id: UUID) -> dict[UUID, dict]:
        """Số việc mở/xong, số thành viên, và `risk` cho một nhóm dự án.

        `risk` dùng lại `project_risk` (7.1) — cùng con số đã xếp hạng màn
        Hôm nay. Tính lại bằng công thức khác ở đây sẽ dẫn tới hai bề mặt
        nói hai điều khác nhau về cùng một dự án, và người dùng tin bề mặt
        nào thì tuỳ họ đang mở cái nào.

        **Việc mở đếm theo người đang hỏi**, không đếm toàn dự án: câu hỏi
        mà màn Việc và bộ chuyển dự án trả lời là *"tôi còn gì trong dự án
        này"*. Số liệu toàn dự án là chuyện của predicate cấp dự án (mục 6),
        và nó đi về channel chung chứ không về màn hình của một người.
        """
        from app.services.risk_detection import project_risk
        from app.services.today import OPEN_STATUSES, _today

        project_ids = [p.id for p in projects]

        open_tasks = list(
            (
                await self.session.scalars(
                    select(Task).where(
                        Task.project_id.in_(project_ids),
                        Task.user_id == user_id,
                        Task.status.in_(OPEN_STATUSES),
                        Task.recurrence_id.is_(None),
                    )
                )
            ).all()
        )

        done_counts = dict(
            (
                await self.session.execute(
                    select(Task.project_id, func.count(Task.id))
                    .where(
                        Task.project_id.in_(project_ids),
                        Task.user_id == user_id,
                        Task.status == TaskStatus.DONE,
                    )
                    .group_by(Task.project_id)
                )
            ).all()
        )
        member_counts = dict(
            (
                await self.session.execute(
                    select(ProjectMember.project_id, func.count(ProjectMember.user_id))
                    .where(ProjectMember.project_id.in_(project_ids))
                    .group_by(ProjectMember.project_id)
                )
            ).all()
        )

        open_by_project: dict[UUID, list[Task]] = {}
        open_subtask_counts: dict[UUID, int] = {}
        for task in open_tasks:
            open_by_project.setdefault(task.project_id, []).append(task)
            if task.parent_task_id:
                open_subtask_counts[task.parent_task_id] = (
                    open_subtask_counts.get(task.parent_task_id, 0) + 1
                )

        today = _today()
        return {
            p.id: {
                "open_task_count": len(open_by_project.get(p.id, [])),
                "completed_task_count": int(done_counts.get(p.id, 0)),
                "member_count": int(member_counts.get(p.id, 0)),
                "risk": project_risk(
                    p.deadline, open_by_project.get(p.id, []), open_subtask_counts, today
                ),
            }
            for p in projects
        }

    # ------------------------------------------------------------------
    # Ghi
    # ------------------------------------------------------------------

    async def create_manual(self, user_id: UUID, name: str, deadline=None) -> Project:
        """Tạo tay — lối phụ (DESIGN 9.1).

        `origin='manual'` chứ không phải `'derived'`, và phân biệt đó nuôi
        4.4: trộn dự án tạo tay vào mẫu số sẽ làm tỷ lệ sửa quy gán — chỉ
        số chất lượng của quy tắc suy ra — mất nghĩa.

        `deadline_is_manual=True` khi người dùng đặt hạn ngay lúc tạo: họ
        vừa nói ra một ý định, và suy ra ở 4.3 không được ghi đè nó vào
        sáng hôm sau.
        """
        project = Project(
            owner_id=user_id,
            name=name,
            origin=ProjectOrigin.MANUAL,
            deadline=deadline,
            deadline_is_manual=deadline is not None,
            source_channel_id=None,
        )
        self.session.add(project)
        await self.session.flush()
        await self.ensure_member(project.id, user_id, ProjectJoinSource.MANUAL)
        logger.info("created manual project", extra={"project_id": str(project.id)})
        return project

    async def update(self, project: Project, payload) -> Project:
        """Sửa `name` / `deadline` / `status`.

        `deadline` đọc qua `model_fields_set`, không qua `is not None`: đặt
        hạn về `None` là **bỏ hạn**, một ý định thật, và nó khác hẳn với
        việc client gửi lên một body chỉ đổi tên. Kiểm bằng `is not None`
        sẽ làm "bỏ hạn" thành thao tác không thể thực hiện.

        Mọi lượt chạm vào `deadline` đều bật `deadline_is_manual`, kể cả
        khi bỏ hạn — người dùng vừa nói họ muốn dự án này không có hạn, và
        suy ra ở 4.3 phải tôn trọng điều đó y như khi họ đặt một ngày.
        """
        fields = payload.model_fields_set
        if "name" in fields and payload.name is not None:
            project.name = payload.name
        if "status" in fields and payload.status is not None:
            project.status = payload.status
        if "deadline" in fields:
            project.deadline = payload.deadline
            project.deadline_is_manual = True
        await self.session.flush()
        return project

    async def move_task(self, task: Task, project_id: UUID, user_id: UUID) -> Task:
        """Chuyển một task sang dự án khác, và ghi nhãn cho 4.4.

        **Không đụng `related_event_id`** (DESIGN 9.1/9.2): nguồn gốc của
        task — nó sinh ra từ cuộc họp nào — không đổi vì nó được xếp lại
        vào dự án khác. Hai quan hệ độc lập, và gộp chúng sẽ làm mất câu
        trả lời cho "Cortex lấy việc này ở đâu ra".

        `project_id_corrected` chỉ bật khi project **thật sự đổi**: một
        request đặt lại đúng giá trị cũ không phải là người dùng sửa sai,
        và đếm nó vào sẽ làm tỷ lệ ở 4.4 phồng lên vì những lần bấm thừa.
        """
        if task.project_id != project_id:
            task.project_id = project_id
            task.project_id_corrected = True
            await self.ensure_member(project_id, user_id, ProjectJoinSource.MANUAL)
            await self.session.flush()
        return task
