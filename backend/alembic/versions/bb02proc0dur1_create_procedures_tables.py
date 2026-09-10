"""create procedures and procedure_runs

Revision ID: bb02proc0dur1
Revises: aa01mem0cat1
Create Date: 2026-09-10

Nâng "routine" từ một dòng chữ trong `semantic_memories` thành thứ có cấu
trúc và có trạng thái. Hai lý do, cả hai đều đo được — xem docstring của
`app.models.Procedure`:

* trigger phải được embed tách khỏi các bước (đoạn dài lấn át vế điều kiện:
  quy trình remote xếp hạng nhất ở 8/9 truy vấn, kể cả "giá bitcoin");
* một chuỗi không trả lời được "hôm nay còn bước nào chưa làm".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID


revision: str = "bb02proc0dur1"
down_revision: Union[str, None] = "aa01mem0cat1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Tạo type một lần ở đây, rồi tham chiếu bằng `create_type=False` bên
    # dưới. Truyền thẳng một `sa.Enum` vào `create_table` khiến SQLAlchemy
    # phát thêm một `CREATE TYPE` nữa cho cùng cái tên — DuplicateObject,
    # và cả migration rollback.
    sa.Enum(
        "user_stated", "inferred_from_behavior", name="proceduresource"
    ).create(op.get_bind(), checkfirst=True)
    sa.Enum(
        "active", "completed", "abandoned", name="procedurerunstatus"
    ).create(op.get_bind(), checkfirst=True)

    procedure_source = ENUM(name="proceduresource", create_type=False)
    run_status = ENUM(name="procedurerunstatus", create_type=False)

    op.create_table(
        "procedures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v7()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("trigger_text", sa.Text, nullable=False),
        sa.Column("steps", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source", procedure_source, nullable=False, server_default=sa.text("'user_stated'")),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False, server_default=sa.text("0.90")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("source_memory_id", UUID(as_uuid=True), nullable=True),
        sa.Column("last_confirmed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_procedures_user_id", "procedures", ["user_id"])
    op.create_index("ix_procedures_user_active", "procedures", ["user_id", "is_active"])

    # Mỗi cách nói của trigger là **một hàng, một embedding** — không phải
    # một chuỗi gộp.
    #
    # Đo 2026-09-10, cùng quy trình remote, cùng câu "hôm nay tôi remote":
    #
    #     trigger "khi tôi làm việc từ xa, remote"            0.7341  ✓
    #     trigger "remote, làm việc từ xa, làm ở nhà, wfh"    0.6741  ✗ trượt
    #
    # Nhồi thêm biến thể vào một chuỗi làm điểm **giảm**: embedding của
    # danh sách bốn từ khoá bị trung bình hoá, nên nó không còn gần với
    # bất kỳ cách nói cụ thể nào. Càng cố bao phủ, càng khớp kém.
    #
    # Nên tách hàng, và điểm của một quy trình là điểm cao nhất trong các
    # cách nói của nó (`ORDER BY score DESC LIMIT 1` bên dưới làm đúng
    # việc đó). Thêm một biến thể khi đó chỉ có thể tăng, không bao giờ
    # làm hụt cái đã khớp.
    op.create_table(
        "procedure_trigger_phrases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v7()")),
        sa.Column(
            "procedure_id", UUID(as_uuid=True),
            sa.ForeignKey("procedures.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("phrase", sa.Text, nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
    )
    op.create_index(
        "ix_procedure_trigger_phrases_procedure",
        "procedure_trigger_phrases", ["procedure_id"],
    )
    # `vector_cosine_ops` + toán tử `<=>` ở đường đọc. Cặp này phải khớp
    # nhau, nếu không planner bỏ qua index và quét tuần tự — đúng lỗi mà
    # `semantic_memories` mang suốt từ lúc sinh ra tới 2026-09-10, và chỉ
    # lộ ra khi có người chạy EXPLAIN.
    op.create_index(
        "ix_procedure_trigger_phrases_hnsw",
        "procedure_trigger_phrases",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "procedure_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v7()")),
        sa.Column(
            "procedure_id", UUID(as_uuid=True),
            sa.ForeignKey("procedures.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", run_status, nullable=False, server_default=sa.text("'active'")),
        sa.Column("step_states", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("started_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_procedure_runs_procedure_id", "procedure_runs", ["procedure_id"])
    op.create_index("ix_procedure_runs_user_id", "procedure_runs", ["user_id"])
    op.create_index("ix_procedure_runs_user_status", "procedure_runs", ["user_id", "status"])

    # **Bất biến: mỗi quy trình có tối đa một run đang chạy.**
    #
    # Ép ở DB, không chỉ ở service. Nếu chỉ là quy ước trong code thì hai
    # request gần nhau — chuyện thường ở một bot chat, người dùng gõ lại vì
    # tưởng tin nhắn chưa gửi — sẽ mở hai run song song, và run thứ hai
    # (danh sách trắng) sẽ che mất các bước người dùng vừa báo đã xong ở
    # run thứ nhất. Unique index bộ phận biến kiểu hỏng im lặng đó thành
    # một lỗi ghi mà tầng trên phải xử lý tường minh.
    op.create_index(
        "uq_procedure_runs_one_active",
        "procedure_runs",
        ["procedure_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("procedure_runs")
    op.drop_table("procedure_trigger_phrases")
    op.drop_table("procedures")
    sa.Enum(name="procedurerunstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="proceduresource").drop(op.get_bind(), checkfirst=True)
