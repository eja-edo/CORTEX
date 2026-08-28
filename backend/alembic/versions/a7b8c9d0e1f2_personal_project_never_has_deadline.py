"""Bất biến 3.4 xuống tầng DB: dự án cá nhân không bao giờ có deadline

`docs/DESIGN.md` 3.4 gọi `deadline IS NULL` của dự án cá nhân là **bất biến
chịu lực**: nó là thứ *duy nhất* ngăn dự án cá nhân sinh thông báo cấp dự
án (6.1, 6.2, 7.1 đều guard theo nó). Không có nó, sớm muộn xuất hiện câu
"Cá nhân có 47 việc quá hạn" — đúng loại nhiễu P5 cấm.

Cho tới giờ bất biến đó chỉ được giữ bằng một câu `if` trong
`StateEvaluator._project_metrics`. Câu `if` đó **đã từng thiếu**, và trong
khoảng thời gian thiếu, một hàng thật trong DB dev nhận `deadline =
2027-02-24` từ `max(due_date)` của các việc lẻ. Test khoá bắt được lỗi
code; nó không dọn được hàng đã ghi, và nó không chặn đường ghi thứ hai.

Migration này làm hai việc:

1. **Dọn** — mọi dự án cá nhân về `deadline = NULL`.
2. **Chặn** — CHECK constraint để không đường ghi nào (worker, API, tool,
   một script chạy tay) đặt được deadline lên dự án cá nhân nữa.

Guard trong code vẫn giữ: constraint biến một giá trị sai âm thầm thành
một lỗi ồn ào, còn guard là thứ làm vận hành bình thường không chạm tới
lỗi đó.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE projects SET deadline = NULL, deadline_is_manual = false "
        "WHERE origin = 'personal' AND deadline IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_projects_personal_has_no_deadline",
        "projects",
        "origin <> 'personal' OR deadline IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_projects_personal_has_no_deadline", "projects", type_="check")
