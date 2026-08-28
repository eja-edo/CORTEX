"""notes.project_id + assets.project_id — chuyển container sang project

`docs/DESIGN.md` mục 11.4 đã chốt đích: `projects` là container duy nhất cho
cả việc lẫn tài liệu, và điều kiện nó chờ — *"khi Notes hoặc Assets hồi
sinh"* — vừa xảy ra khi hai bề mặt đó quay lại nav.

**Thêm trước, gỡ sau.** Migration này chỉ *thêm* đường mới và giữ nguyên
`workspace_id`. Làm ngược lại sẽ đứt hai thứ cùng lúc: khối Ghi chú/Bản ghi
trong sidebar gác theo workspace hiện tại, và `notes.workspace_id` đang
NOT NULL nên đường tạo note gãy ngay khi không còn workspace.

`project_id` nullable trong bước này, dù đích đến là NOT NULL. Lý do: cột
NOT NULL buộc mọi đường ghi phải sửa xong *trước* khi migration chạy, tức là
một lượt thay đổi lớn không chia nhỏ được. Nullable cho phép hai tầng đi
lệch pha nhau một nhịp, và bước siết lại là một migration riêng khi mọi
đường ghi đã chuyển.

Backfill đưa mọi hàng hiện có về **dự án cá nhân của chủ sở hữu** — cùng
đáy thang mà `tasks` đã dùng (DESIGN 3.5 bước 3). Nó là giá trị mặc định
khi không có ngữ cảnh nào khác, không phải nơi chứa đồ thất lạc.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Dùng chung cho cả hai bảng: tạo dự án cá nhân cho ai còn thiếu, rồi trỏ
# các hàng chưa có project về đó. `gen_random_uuid()` thay cho `uuid7()` vì
# uuid7 không có sẵn trong SQL; id của hàng backfill không cần thứ tự.
_ENSURE_PERSONAL = """
INSERT INTO projects (id, owner_id, name, status, deadline_is_manual,
                      source_channel_id, origin, created_at, updated_at)
SELECT gen_random_uuid(),
       u.id,
       COALESCE(NULLIF(u.full_name, ''), u.email, 'Cá nhân'),
       'active', false, NULL, 'personal', NOW(), NOW()
  FROM users u
 WHERE EXISTS (SELECT 1 FROM {table} t WHERE t.user_id = u.id)
   AND NOT EXISTS (
         SELECT 1 FROM projects p
          WHERE p.owner_id = u.id AND p.origin = 'personal')
"""

_ENSURE_MEMBER = """
INSERT INTO project_members (project_id, user_id, joined_via, joined_at)
SELECT p.id, p.owner_id, 'derived', NOW()
  FROM projects p
 WHERE p.origin = 'personal'
   AND NOT EXISTS (
         SELECT 1 FROM project_members m
          WHERE m.project_id = p.id AND m.user_id = p.owner_id)
"""

_BACKFILL = """
UPDATE {table} t
   SET project_id = p.id
  FROM projects p
 WHERE p.owner_id = t.user_id
   AND p.origin = 'personal'
   AND t.project_id IS NULL
"""


def upgrade() -> None:
    for table in ("notes", "assets"):
        op.add_column(
            table,
            sa.Column(
                "project_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
        op.execute(_ENSURE_PERSONAL.format(table=table))
        op.execute(_ENSURE_MEMBER)
        op.execute(_BACKFILL.format(table=table))

    # Nới `workspace_id` ở cả hai bảng: đường ghi mới không được buộc phải
    # bịa một workspace chỉ để thoả ràng buộc — đó đúng là cách một cột "đã
    # bỏ" sống dai thêm nhiều tháng.
    #
    # `notes.workspace_id` đáng chú ý: **model đã khai `nullable=True` từ
    # trước, DB thì không.** Lệch đó không lộ ra chừng nào mọi đường ghi còn
    # gửi kèm workspace, và nó lộ ra ngay ở lần ghi đầu tiên không gửi.
    op.alter_column("notes", "workspace_id", nullable=True)
    op.alter_column("assets", "workspace_id", nullable=True)


def downgrade() -> None:
    op.alter_column("assets", "workspace_id", nullable=False)
    op.alter_column("notes", "workspace_id", nullable=False)
    for table in ("notes", "assets"):
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.drop_column(table, "project_id")
