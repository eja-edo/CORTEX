"""Khai tử workspaces — `projects` là container duy nhất

Bước cuối của DESIGN 11.4. Ba migration trước đã mở đường (`notes.project_id`,
`assets.project_id`, nới `workspace_id` thành nullable) và mọi đường ghi đã
chuyển; đây là lúc gỡ.

**`agent_conversations.workspace_id` bị xoá chứ không đổi thành `project_id`.**
Hội thoại thuộc về một *người*, không thuộc container nào. DESIGN 9.2 đã bác
bỏ chính ý tưởng "mọi hội thoại thuộc một dự án": một ngữ cảnh container ngầm
ở mức phiên là thứ khiến agent lặng lẽ thao tác nhầm chỗ, và người dùng nói
chuyện với Cortex chứ không nói chuyện với một thư mục.

Thứ tự trong `upgrade()` là thứ tự FK, không phải thứ tự tuỳ ý: cột trỏ tới
`workspaces` phải biến mất trước khi bảng bị xoá.

**Không có đường lùi trung thực.** `downgrade()` dựng lại được cấu trúc
nhưng không dựng lại được dữ liệu: hàng `workspaces`/`workspace_members` đã
mất, và `notes.workspace_id` cũ không suy ra được từ `project_id`. Ghi rõ ở
đây thay vì để một `downgrade` trông như hoàn tác được.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("notes", "assets", "agent_conversations"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_workspace_id")
        op.drop_column(table, "workspace_id")

    op.drop_table("workspace_members")
    op.drop_table("workspaces")

    # `workspacerole` chỉ phục vụ bảng vừa xoá.
    op.execute("DROP TYPE IF EXISTS workspacerole")


def downgrade() -> None:
    raise NotImplementedError(
        "Không hoàn tác được: hàng workspaces/workspace_members đã mất, và "
        "notes.workspace_id cũ không suy ra được từ project_id. Khôi phục "
        "từ bản sao lưu nếu cần."
    )
