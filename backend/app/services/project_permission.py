"""Quyền truy cập theo dự án — bản thay thế `WorkspacePermission`.

`ProjectMember` **cố ý không có cột `role`** (DESIGN 3.1, QĐ-1). Đó không
phải thiếu sót đem sang từ workspace mà là điều phân biệt hai thứ:
`WorkspaceMember.role` trả lời *ai được đọc tài liệu*, còn thành viên dự án
trả lời *ai chịu trách nhiệm việc*. Ba mức owner/editor/viewer không ánh xạ
sang câu hỏi thứ hai, và bịa ra một ánh xạ sẽ tạo một hệ quyền không ai
thiết kế.

Nên module này chỉ có **một** câu hỏi: *người này có ở trong dự án không?*
Đọc và ghi dùng chung câu trả lời đó. Khi nào xuất hiện một quyết định cụ
thể cần phân biệt hơn — chưa có — thì mới thêm.

**404, không phải 403.** Không phải thành viên thì dự án coi như không tồn
tại; nói khác đi là xác nhận có một dự án id như vậy. Cùng lối với
`api/projects.py`, và khác `WorkspacePermission` (403) một cách có chủ ý.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ProjectMember


class ProjectPermission:
    @staticmethod
    def get_member(project_id: UUID, user_id: UUID, db: Session) -> ProjectMember | None:
        return (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
            .first()
        )

    @staticmethod
    def is_member(project_id: UUID, user_id: UUID, db: Session) -> bool:
        return ProjectPermission.get_member(project_id, user_id, db) is not None

    @staticmethod
    def require_member(project_id: UUID, user_id: UUID, db: Session) -> ProjectMember:
        member = ProjectPermission.get_member(project_id, user_id, db)
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return member
