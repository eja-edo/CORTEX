"""attention_bundle_queue.project_id — gộp lời nhắc theo dự án

`docs/DESIGN.md` mục 7.2: *"`attention_bundle` hiện gộp theo người + thời
điểm. Thêm project làm khoá gộp"* — ba lần rung về ba việc rời rạc thành
một câu *"Alpha có 3 việc cần chú ý"*. Đây là P5 thuần: cùng lượng thông
tin, ít lần làm phiền hơn.

**Vì sao là một cột, không phải một phép join lúc flush.** Bảng này cố ý
denormalized — `title`/`body`/`payload` được chép vào lúc xếp hàng chứ
không đọc lại từ item lúc flush, vì item có thể đổi hoặc bị xoá trong
khoảng giữa, và *"bundle nên nói điều đã đúng lúc Cortex quyết định im,
không phải trạng thái hiện tại có thể đã khác"* (xem docstring của
`AttentionBundleQueue`). Nhãn gộp là một phần của điều được nói ra, nên nó
theo cùng quy tắc: chốt lúc xếp hàng. Join lúc flush còn có một chế độ
hỏng cụ thể — task bị xoá trong lúc người dùng đang họp thì lời nhắc của
nó lặng lẽ rơi khỏi nhóm dự án và về cụm vô danh.

**`NULL` là giá trị hợp lệ và thường gặp**, không phải dữ liệu thiếu: item
cấp người dùng (`day.review`, `day.plan` — `item_type='user'`) không thuộc
dự án nào, và một sự kiện lịch chưa được gắn dự án cũng vậy (4.2 nói rõ
phần lớn sự kiện sẽ không bao giờ được gắn). Những hàng đó gộp đúng như
trước khi có cột này.

`ON DELETE SET NULL` chứ không CASCADE: xoá một dự án không được phép làm
bốc hơi lời nhắc đang chờ về những việc vẫn còn thật.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attention_bundle_queue",
        sa.Column("project_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_attention_bundle_queue_project",
        "attention_bundle_queue",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Khoá gộp của `flush_due_bundles`: mỗi lượt quét đọc các hàng chưa
    # flush của một người rồi phân theo cột này.
    op.create_index(
        "ix_attention_bundle_queue_user_project",
        "attention_bundle_queue",
        ["user_id", "project_id"],
        postgresql_where=sa.text("flushed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_attention_bundle_queue_user_project", table_name="attention_bundle_queue")
    op.drop_constraint(
        "fk_attention_bundle_queue_project", "attention_bundle_queue", type_="foreignkey"
    )
    op.drop_column("attention_bundle_queue", "project_id")
