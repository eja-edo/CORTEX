"""tasks.project_id_corrected — nhãn đo chất lượng quy tắc suy ra

`docs/DESIGN.md` mục 4.4: mỗi lần người dùng sửa quy gán project là một
nhãn âm, và tỷ lệ sửa trên tổng số gán vào dự án `origin='derived'` là chỉ
số chất lượng của quy tắc ở 3.5 bước 2.

**Một cột boolean là đủ, không cần bảng lịch sử.** Mẫu số — "tổng số gán
`origin='derived'`" — đọc được bằng join sang `projects.origin`; tử số là
đúng cột này. Ghi lại từng lượt sửa (ai, lúc nào, từ dự án nào) sẽ trả lời
được nhiều câu hỏi hơn, nhưng chưa câu nào trong số đó dẫn tới một quyết
định — và 4.4 chỉ cần một ngưỡng: >20% thì quy tắc sai, sửa quy tắc chứ
không thêm UI.

Cột **không** reset khi task đổi dự án lần nữa: nó đánh dấu "quy gán tự
động cho task này từng sai", và điều đó không hết đúng vì người dùng sửa
thêm lần thứ hai.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "project_id_corrected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Index một phần: truy vấn duy nhất cột này phục vụ là đếm hàng `true`,
    # và đó là thiểu số tuyệt đối — index đầy đủ sẽ chỉ tốn chỗ.
    op.create_index(
        "ix_tasks_project_id_corrected",
        "tasks",
        ["project_id"],
        postgresql_where=sa.text("project_id_corrected"),
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_project_id_corrected", table_name="tasks")
    op.drop_column("tasks", "project_id_corrected")
