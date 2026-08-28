"""create projects, project_members and wire tasks/schedules to them

Xem `docs/DESIGN.md` mục 3 (mô hình dữ liệu), QĐ-1 và QĐ-2 ở mục 15.

Ba nhóm thay đổi, cố ý gộp một migration vì `tasks.project_id NOT NULL`
không đứng được nếu thiếu bất kỳ nhóm nào:

1. `projects` + `project_members` — project là thực thể **dùng chung**,
   neo vào một Mezon channel (`source_channel_id`). `owner_id` là *ai tạo
   ra*, không phải *ai sở hữu duy nhất*; truy vấn "dự án của tôi" đi qua
   `project_members`.

2. `schedules.project_id` (nullable) và `tasks.project_id` (NOT NULL).
   Bất đối xứng này là chủ ý: mọi task thuộc đúng một project, còn sự kiện
   chỉ được gắn khi có tín hiệu chắc chắn (DESIGN 4.2) — phần lớn sự kiện
   sẽ mãi mãi NULL, và đó là đúng.

3. Sửa `uq_schedule_external_maps_provider_event` để kèm `user_id`. Đây là
   một lỗi có sẵn, không liên quan tới project: `provider_calendar_id` mặc
   định `'primary'` cho *mọi* người, nên hai người cùng sync một cuộc họp
   đụng ràng buộc và người thứ hai fail. Chưa lộ ra vì hệ thống mới có một
   người dùng thật.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROJECT_STATUS = postgresql.ENUM(
    "active", "closed", name="projectstatus", create_type=False
)
PROJECT_ORIGIN = postgresql.ENUM(
    "derived", "manual", "personal", name="projectorigin", create_type=False
)
JOIN_SOURCE = postgresql.ENUM(
    "derived", "manual", name="projectjoinsource", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()

    PROJECT_STATUS.create(bind, checkfirst=True)
    PROJECT_ORIGIN.create(bind, checkfirst=True)
    JOIN_SOURCE.create(bind, checkfirst=True)

    # ── 1. projects ──────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            PROJECT_STATUS,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("deadline", sa.DateTime(), nullable=True),
        sa.Column(
            "deadline_is_manual",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # Mezon channel = danh tính chung của dự án (DESIGN 3.1.1).
        # NULL cho dự án cá nhân và dự án tạo tay.
        sa.Column("source_channel_id", sa.String(255), nullable=True),
        sa.Column("origin", PROJECT_ORIGIN, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    # Một channel sinh tối đa một project — đây là thứ khiến người thứ hai
    # nhận việc từ cùng channel *tìm thấy* project thay vì tạo bản thứ hai.
    op.create_index(
        "uq_projects_source_channel",
        "projects",
        ["source_channel_id"],
        unique=True,
        postgresql_where=sa.text("source_channel_id IS NOT NULL"),
    )
    # Đúng một dự án cá nhân cho mỗi người.
    op.create_index(
        "uq_projects_personal_per_user",
        "projects",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("origin = 'personal'"),
    )

    # ── project_members ──────────────────────────────────────────────────
    # Cố ý KHÔNG có cột `role`: đó là thứ làm `WorkspaceMember` sai ngữ
    # nghĩa (quyền *đọc tài liệu*, không phải *chịu trách nhiệm việc*).
    # Thêm role chỉ khi có một quyết định cụ thể cần tới nó.
    op.create_table(
        "project_members",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("joined_via", JOIN_SOURCE, nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_project_members_user", "project_members", ["user_id"])

    # ── 2a. schedules.project_id — nullable, chỉ gắn khi chắc chắn ────────
    op.add_column(
        "schedules",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_schedules_project_id", "schedules", ["project_id"])

    # `hangoutLink` của Google — mức khớp chính xác thứ hai trong thang ở
    # DESIGN 4.2. Google để link Meet ở đây, KHÔNG phải ở `location`, nên
    # sync hiện tại (chỉ đọc `location`) không dùng được cho việc khớp.
    op.add_column("schedules", sa.Column("hangout_link", sa.String(1024), nullable=True))

    # ── 2b. tasks.project_id — ba bước, vì bảng đã có dữ liệu ─────────────
    op.add_column(
        "tasks",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=True,
        ),
    )

    # Backfill: mỗi người có task -> tạo dự án cá nhân, dồn task vào đó.
    # `uuid7()` không có sẵn trong SQL nên dùng gen_random_uuid(); id của
    # hàng backfill không cần thứ tự thời gian.
    op.execute(
        """
        INSERT INTO projects (id, owner_id, name, status, deadline_is_manual,
                              source_channel_id, origin, created_at, updated_at)
        SELECT gen_random_uuid(),
               u.id,
               COALESCE(NULLIF(u.full_name, ''), u.email, 'Cá nhân'),
               'active', false, NULL, 'personal', NOW(), NOW()
          FROM users u
         WHERE EXISTS (SELECT 1 FROM tasks t WHERE t.user_id = u.id)
           AND NOT EXISTS (
                 SELECT 1 FROM projects p
                  WHERE p.owner_id = u.id AND p.origin = 'personal')
        """
    )
    op.execute(
        """
        INSERT INTO project_members (project_id, user_id, joined_via, joined_at)
        SELECT p.id, p.owner_id, 'derived', NOW()
          FROM projects p
         WHERE p.origin = 'personal'
           AND NOT EXISTS (
                 SELECT 1 FROM project_members m
                  WHERE m.project_id = p.id AND m.user_id = p.owner_id)
        """
    )
    op.execute(
        """
        UPDATE tasks t
           SET project_id = p.id
          FROM projects p
         WHERE p.owner_id = t.user_id
           AND p.origin = 'personal'
           AND t.project_id IS NULL
        """
    )

    op.alter_column("tasks", "project_id", nullable=False)
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    # ── 3. Sửa ràng buộc chặn hai người sync cùng một sự kiện ────────────
    op.drop_constraint(
        "uq_schedule_external_maps_provider_event",
        "schedule_external_maps",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_schedule_external_maps_provider_event",
        "schedule_external_maps",
        ["user_id", "provider", "provider_calendar_id", "provider_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_schedule_external_maps_provider_event",
        "schedule_external_maps",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_schedule_external_maps_provider_event",
        "schedule_external_maps",
        ["provider", "provider_calendar_id", "provider_event_id"],
    )

    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_column("tasks", "project_id")

    op.drop_column("schedules", "hangout_link")
    op.drop_index("ix_schedules_project_id", table_name="schedules")
    op.drop_column("schedules", "project_id")

    op.drop_index("ix_project_members_user", table_name="project_members")
    op.drop_table("project_members")

    op.drop_index("uq_projects_personal_per_user", table_name="projects")
    op.drop_index("uq_projects_source_channel", table_name="projects")
    op.drop_table("projects")

    bind = op.get_bind()
    JOIN_SOURCE.drop(bind, checkfirst=True)
    PROJECT_ORIGIN.drop(bind, checkfirst=True)
    PROJECT_STATUS.drop(bind, checkfirst=True)
