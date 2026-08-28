"""user_preferences.gate_bypass — cờ per-user cho phép thử A/B ở mục 12

`docs/DESIGN.md` mục 12.2: *"Cơ chế: một cờ per-user bỏ qua Gate và gọi
thẳng `create_notification_*`."*

Đây là hạ tầng của **cổng nghiệm thu duy nhất** của cả sản phẩm. Giả định
đang đặt cược (12.1) là *"nhắc qua Attention Gate hơn nhắc ngây thơ đủ
nhiều để người dùng cảm nhận được"*, và nếu sai thì bot họp thêm chức năng
nhắc trong hai tuần và Cortex không còn sản phẩm. Không có phòng thủ nào
khác — nên cột này quan trọng hơn hình dạng của nó gợi ý.

**Mặc định `false` nghĩa là Gate BẬT.** Cờ đặt theo hướng "bỏ qua" chứ
không phải "bật Gate" để một hàng thiếu, một tài khoản mới, hay một lỗi
đọc preferences đều rơi về hành vi *có Gate* — tức là im hơn. Đặt ngược
lại thì mọi trường hợp biên đều rơi về nhắc nhiều hơn, và đó là hướng sai
để sai (P5).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column(
            "gate_bypass",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "gate_bypass")
