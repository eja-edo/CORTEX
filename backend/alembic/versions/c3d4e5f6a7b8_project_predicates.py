"""project_snapshots + 'project' as an attention item type

Nền cho hai predicate cấp dự án ở `docs/DESIGN.md` mục 6.

**Vì sao là bảng riêng, không phải một cột `snapshot JSONB` trên
`state_evaluator_flags`.** `project.slipping` cần biết *lần đánh giá trước
có bao nhiêu việc mở* — `StateEvaluatorFlag` chỉ lưu "điều kiện này đang
đúng", không lưu số. Hai cách làm được, và bảng riêng thắng vì cùng dữ liệu
đó là đầu vào của `project.will_miss` và của biểu đồ tiến độ sau này, còn
nhét JSONB vào bảng cờ thì làm phình đúng cái bảng mọi predicate đều đọc.

`AttentionItemType` phải có `'project'` trước khi cờ cấp dự án ghi được:
`state_evaluator_flags.item_type` và `attention_log.item_type` dùng chung
enum đó.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `ADD VALUE` không chạy trong transaction khối trên Postgres < 12 và
    # không revert được — nên nó ở riêng, chạy trước mọi thứ khác.
    op.execute("ALTER TYPE attentionitemtype ADD VALUE IF NOT EXISTS 'project'")

    op.create_table(
        "project_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Số việc mở tại thời điểm đánh giá. `project.slipping` so số này
        # với lần trước; tăng lên nghĩa là việc sinh ra nhanh hơn việc xong.
        sa.Column("open_count", sa.Integer(), nullable=False),
        # Số việc hoàn thành trong 14 ngày trước thời điểm đánh giá — tử số
        # của "tốc độ" trong `project.will_miss` (DESIGN 6.2). Lưu lại thay
        # vì tính lại mỗi lần để lịch sử đọc được mà không cần quét
        # `completed_at` toàn bảng.
        sa.Column("completed_last_14d", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    # Truy vấn duy nhất bảng này phục vụ là "bản gần nhất của dự án P", nên
    # index đúng theo hình dạng đó.
    op.create_index(
        "ix_project_snapshots_project_evaluated",
        "project_snapshots",
        ["project_id", sa.text("evaluated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_project_snapshots_project_evaluated", table_name="project_snapshots")
    op.drop_table("project_snapshots")
    # Giá trị enum cố ý không gỡ: `ALTER TYPE ... DROP VALUE` không tồn tại
    # trong Postgres, và dựng lại cả type thì phải viết lại mọi cột đang
    # dùng nó. Một nhãn thừa trong enum vô hại.
