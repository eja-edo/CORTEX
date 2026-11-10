"""The teacher role (WP46): an account that runs only the classes it was given, and the table that says which

Revision ID: 0044
Revises: 0043
"""
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("ALTER TABLE app_user DROP CONSTRAINT ck_app_user_role")
    op.execute("ALTER TABLE app_user ADD CONSTRAINT ck_app_user_role CHECK (role in ('owner', 'staff', 'teacher'))")
    op.execute("""CREATE TABLE class_teacher (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id),
        class_id uuid NOT NULL REFERENCES "class"(id) ON DELETE CASCADE, user_id uuid NOT NULL REFERENCES app_user(id),
        assigned_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_class_teacher_class_id_user_id UNIQUE (class_id, user_id))""")
    op.execute("CREATE INDEX ix_class_teacher_user ON class_teacher (tenant_id, user_id)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON class_teacher TO cl_app")
    op.execute("ALTER TABLE class_teacher ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE class_teacher FORCE ROW LEVEL SECURITY")  # DESIGN A1
    op.execute(f"CREATE POLICY tenant_isolation ON class_teacher USING ({TENANT}) WITH CHECK ({TENANT})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS class_teacher")
    op.execute("UPDATE app_user SET role = 'staff' WHERE role = 'teacher'")  # the role is going away: the narrowest one that is left, not the account
    op.execute("ALTER TABLE app_user DROP CONSTRAINT ck_app_user_role")
    op.execute("ALTER TABLE app_user ADD CONSTRAINT ck_app_user_role CHECK (role in ('owner', 'staff'))")
