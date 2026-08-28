"""tasks.source_external_id — chống trùng cho webhook bot họp

`docs/DESIGN.md` mục 9.1 mô tả `POST /api/internal/tasks` nhưng không nói
gì về idempotency. Không có nó thì endpoint hỏng theo một cách biết trước:
webhook **luôn** được gửi lại — timeout, deploy, 5xx tạm thời — và mỗi lần
gửi lại đẻ thêm một bản sao của cùng một action item.

Với sản phẩm này, task trùng không phải phiền toái nhỏ. Mỗi bản sao là một
ứng viên riêng đi qua Attention Gate với `item_id` khác nhau, nên dedup ở
`attention_log` (khoá theo `item_id`, `reason_key`) **không** gộp chúng —
người dùng bị nhắc hai lần về một việc. Đó đúng là thất bại mà mục 1.2 định
nghĩa: nói một câu không đáng nói.

Unique index **có `user_id`** vì cùng một action item có thể giao cho nhiều
người: bot gửi một `external_id` cho mỗi người nhận, và hai hàng đó là hai
việc thật, không phải bản sao.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("source_external_id", sa.String(255), nullable=True))
    # Index một phần: mọi task tạo trong app đều `NULL` ở cột này, và chúng
    # là đa số tuyệt đối. Ràng buộc unique đầy đủ sẽ coi mọi `NULL` là khác
    # nhau (đúng theo SQL) nhưng vẫn tốn chỗ cho mọi hàng.
    op.create_index(
        "uq_tasks_source_external",
        "tasks",
        ["user_id", "source_external_id"],
        unique=True,
        postgresql_where=sa.text("source_external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tasks_source_external", table_name="tasks")
    op.drop_column("tasks", "source_external_id")
