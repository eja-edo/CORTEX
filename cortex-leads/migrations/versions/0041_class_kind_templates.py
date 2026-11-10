"""Class kinds (loại lớp) and the assignment templates (bài tập mẫu) that belong to each kind

A class has at most one kind; a kind has many templates. A template holds the fields of the "compose an assignment" form so
a teacher picks one and the form is filled in. Deleting a kind takes its templates with it and leaves its classes without a kind.

Revision ID: 0041
Revises: 0040
"""
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = ("class_kind", "assignment_template")


def upgrade() -> None:
    op.execute("""CREATE TABLE class_kind (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), name text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_class_kind_tenant_id_name UNIQUE (tenant_id, name))""")
    op.execute("""CREATE TABLE assignment_template (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id),
        kind_id uuid NOT NULL REFERENCES class_kind(id) ON DELETE CASCADE, name text NOT NULL,
        title text, description text, max_points integer, criteria jsonb, answer_key text, check_prompt text, language text,
        topic_name text, materials jsonb NOT NULL DEFAULT '[]'::jsonb,
        created_by text, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_assignment_template_kind_id_name UNIQUE (kind_id, name))""")
    op.execute("CREATE INDEX ix_assignment_template_kind ON assignment_template (tenant_id, kind_id, created_at)")
    op.execute('ALTER TABLE "class" ADD COLUMN IF NOT EXISTS kind_id uuid REFERENCES class_kind(id) ON DELETE SET NULL')
    for t in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO cl_app")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({TENANT}) WITH CHECK ({TENANT})")


def downgrade() -> None:
    op.execute('ALTER TABLE "class" DROP COLUMN IF EXISTS kind_id')
    op.execute("DROP TABLE IF EXISTS assignment_template")
    op.execute("DROP TABLE IF EXISTS class_kind")
