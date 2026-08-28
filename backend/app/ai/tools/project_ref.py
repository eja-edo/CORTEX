"""Giải `project_ref` — chỗ dễ hỏng nhất của mục 9.2.

Quyết định nền tảng của 9.2: **không có "dự án hiện tại" ở mức phiên hội
thoại.** Nếu tồn tại ngữ cảnh project ngầm thì sẽ gặp đúng lỗi kinh điển —
người dùng nói *"đánh dấu xong việc gửi spec"*, agent lặng lẽ thao tác nhầm
dự án, và không ai biết cho tới lúc quá muộn. Nên mọi lời gọi tool mang
`project_ref` tường minh, và nó được giải **ngay tại thời điểm gọi**, ở đây.

Ba nhánh, và nhánh thứ ba là toàn bộ lý do module này tồn tại:

    khớp đúng 1 tên   → dùng
    khớp nhiều tên    → ask_user_choice (tool đã có sẵn)
    không khớp gì     → trả danh sách dự án, KHÔNG đoán, KHÔNG tự tạo

Nhánh cuối là **P7**. Agent tự tạo dự án `"Alpah"` vì người dùng gõ sai
chính tả là kiểu hỏng im lặng tệ nhất: nó tạo dữ liệu rác mà không ai nhận
ra cho tới khi một báo cáo cấp dự án nói sai — và lúc đó không truy được vì
sao.

Module này **không** gọi LLM. Khớp tên là so chuỗi thường hoá; khi so chuỗi
không quyết được thì hỏi người dùng, không đoán bằng model (P3).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, ProjectMember, ProjectOrigin, ProjectStatus

# Trần số dòng trả về khi phải liệt kê. Trả 50 dự án kèm task là thổi bay
# context (DESIGN 9.2) — và một danh sách dài hơn thế cũng không giúp người
# dùng chọn nhanh hơn.
MAX_LISTED_PROJECTS = 20


@dataclass(frozen=True)
class ProjectRefResolution:
    """Kết quả giải một `project_ref`.

    Ba trạng thái loại trừ nhau, và tool gọi phải xử lý cả ba. Trả về một
    dataclass thay vì raise: "nhiều dự án cùng tên" không phải lỗi, nó là
    một câu hỏi cần hỏi người dùng — và exception là cách diễn đạt sai cho
    một nhánh hội thoại bình thường.
    """

    project: Project | None = None
    ambiguous: list[Project] | None = None
    not_found: list[Project] | None = None

    @property
    def resolved(self) -> bool:
        return self.project is not None


def _normalise(name: str) -> str:
    return " ".join(name.strip().lower().split())


async def visible_projects(
    session: AsyncSession,
    user_id: UUID,
    *,
    include_personal: bool = False,
    status: ProjectStatus | None = ProjectStatus.ACTIVE,
) -> list[Project]:
    """Dự án agent được nhìn thấy.

    Đi qua `project_members`, không qua `owner_id` (QĐ-1): project là thực
    thể dùng chung và `owner_id` chỉ nói ai tạo ra nó.

    **Dự án cá nhân bị ẩn mặc định** (DESIGN 9.2). Không phải vì nó bí mật —
    mà vì nó là nơi mọi việc lẻ rơi vào, nên nó xuất hiện trong *mọi* lần
    liệt kê và chiếm chỗ trong ngữ cảnh của mỗi lượt. Người dùng hỏi thẳng
    thì `include_personal=True`.
    """
    stmt = (
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
    )
    if status is not None:
        stmt = stmt.where(Project.status == status)
    if not include_personal:
        stmt = stmt.where(Project.origin != ProjectOrigin.PERSONAL)
    return list((await session.scalars(stmt)).all())


async def resolve_project_ref(
    session: AsyncSession,
    user_id: UUID,
    project_ref: str,
    *,
    include_personal: bool = True,
) -> ProjectRefResolution:
    """Tên (hoặc id) → một dự án cụ thể, hoặc một câu hỏi.

    `include_personal=True` ở đây trong khi `visible_projects` mặc định ẩn
    nó: liệt kê và giải tên là hai việc khác nhau. Ẩn dự án cá nhân khỏi
    danh sách là để tiết kiệm ngữ cảnh; ẩn nó khỏi việc *giải tên* sẽ làm
    câu "chuyển việc này về Cá nhân" không thực hiện được.

    Khớp theo ba mức, dừng ở mức đầu tiên có kết quả: id chính xác → tên
    chính xác → tên chứa. Mức "chứa" cố ý đứng cuối và cố ý không có
    fuzzy/khoảng cách sửa: `Alpha` và `Alpha v2` là hai dự án khác nhau, và
    một thuật toán "gần đúng" sẽ tự tin nhất đúng vào lúc nó sai nhất (P7).
    """
    candidates = await visible_projects(
        session, user_id, include_personal=include_personal, status=None
    )
    ref = _normalise(project_ref)

    try:
        as_uuid = UUID(project_ref)
    except (ValueError, AttributeError, TypeError):
        as_uuid = None
    if as_uuid is not None:
        exact_id = [p for p in candidates if p.id == as_uuid]
        if exact_id:
            return ProjectRefResolution(project=exact_id[0])

    exact = [p for p in candidates if _normalise(p.name) == ref]
    partial = [p for p in candidates if ref and ref in _normalise(p.name)]
    matches = exact or partial

    if len(matches) == 1:
        return ProjectRefResolution(project=matches[0])
    if len(matches) > 1:
        return ProjectRefResolution(ambiguous=matches[:MAX_LISTED_PROJECTS])

    # Không khớp gì. Trả danh sách để agent hỏi lại — không đoán, không tạo.
    active = [p for p in candidates if p.status == ProjectStatus.ACTIVE]
    return ProjectRefResolution(not_found=active[:MAX_LISTED_PROJECTS])


def brief(project: Project) -> dict:
    """Một dự án ở dạng gọn nhất còn đủ để người dùng nhận ra nó."""
    return {
        "id": str(project.id),
        "name": project.name,
        "deadline": project.deadline.isoformat() if project.deadline else None,
    }


def unresolved_result(resolution: ProjectRefResolution, project_ref: str) -> dict:
    """Câu trả lời chuẩn cho hai nhánh chưa giải được.

    Dùng chung ở cả bốn tool để agent luôn nhận cùng một hình dạng — và để
    câu hướng dẫn *"đừng đoán, đừng tự tạo"* chỉ được viết một lần, thay vì
    bốn lần với bốn cách diễn đạt hơi khác nhau.
    """
    if resolution.ambiguous is not None:
        return {
            "success": False,
            "error": "ambiguous_project_ref",
            "project_ref": project_ref,
            "matches": [brief(p) for p in resolution.ambiguous],
            "next_step": (
                "Nhiều dự án khớp tên này. Gọi ask_user_choice để người dùng "
                "chọn một, rồi gọi lại tool này với tên hoặc id họ chọn. "
                "Không tự chọn hộ."
            ),
        }
    return {
        "success": False,
        "error": "project_not_found",
        "project_ref": project_ref,
        "projects": [brief(p) for p in (resolution.not_found or [])],
        "next_step": (
            "Không có dự án nào tên như vậy. Hỏi lại người dùng ý họ là dự án "
            "nào trong danh sách trên. KHÔNG đoán, và KHÔNG tự tạo dự án mới — "
            "chỉ tạo khi người dùng nói thẳng rằng họ muốn một dự án mới."
        ),
    }
