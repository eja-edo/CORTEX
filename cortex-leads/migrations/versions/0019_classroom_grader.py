"""WP33 classroom_grader: Classroom sources, grading guides, graded submissions, assignment drafts; notification kind `grading`

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
OLD = "'handoff', 'booking', 'task', 'digest', 'proposal', 'lesson'"


def upgrade() -> None:
    op.execute("""CREATE TABLE classroom_source (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        course_id text NOT NULL, auth_kind text NOT NULL, subject text, secret_enc bytea NOT NULL, label text,
        active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_classroom_source_auth_kind CHECK (auth_kind in ('delegated', 'oauth')),
        CONSTRAINT uq_classroom_source_tenant_id_sandbox_id_course_id UNIQUE (tenant_id, sandbox_id, course_id))""")
    op.execute("""CREATE TABLE grading_guide (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        source_id uuid NOT NULL REFERENCES classroom_source(id), coursework_id text NOT NULL, title text NOT NULL,
        max_points numeric(8,2) NOT NULL, criteria jsonb NOT NULL, answer_key text, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_grading_guide_tenant_id_source_id_coursework_id UNIQUE (tenant_id, source_id, coursework_id))""")
    op.execute("""CREATE TABLE grade_item (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        source_id uuid NOT NULL REFERENCES classroom_source(id), coursework_id text NOT NULL, submission_id text NOT NULL,
        student_ref text NOT NULL, student_name text, work_title text NOT NULL, max_points numeric(8,2),
        ours boolean NOT NULL DEFAULT false, status text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
        claimed_at timestamptz, content text, proposal jsonb, final jsonb, error text,
        created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, decided_by text, decided_at timestamptz,
        written_at timestamptz,
        CONSTRAINT ck_grade_item_status CHECK (status in ('queued', 'working', 'proposed', 'approved', 'rejected', 'skipped', 'failed')),
        CONSTRAINT uq_grade_item_tenant_id_sandbox_id_source_id_submission_id UNIQUE (tenant_id, sandbox_id, source_id, submission_id))""")
    op.execute("CREATE INDEX ix_grade_item_pick ON grade_item (tenant_id, status, created_at)")
    op.execute("""CREATE TABLE assignment_draft (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        source_id uuid NOT NULL REFERENCES classroom_source(id), title text NOT NULL, description text NOT NULL,
        max_points integer NOT NULL, due timestamptz, publish boolean NOT NULL DEFAULT false, criteria jsonb NOT NULL,
        answer_key text, origin text NOT NULL DEFAULT 'teacher', status text NOT NULL DEFAULT 'draft', coursework_id text,
        error text, created_by text, decided_by text, created_at timestamptz NOT NULL DEFAULT now(), decided_at timestamptz,
        CONSTRAINT ck_assignment_draft_status CHECK (status in ('draft', 'created', 'rejected', 'failed')),
        CONSTRAINT ck_assignment_draft_origin CHECK (origin in ('teacher', 'ai')))""")
    for t in ("classroom_source", "grading_guide", "grade_item", "assignment_draft"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO cl_app")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({TENANT}) WITH CHECK ({TENANT})")
    op.execute("ALTER TABLE notification DROP CONSTRAINT IF EXISTS ck_notification_kind")
    op.execute(f"ALTER TABLE notification ADD CONSTRAINT ck_notification_kind CHECK (kind in ({OLD}, 'grading'))")


def downgrade() -> None:
    op.execute("DELETE FROM notification WHERE kind = 'grading'")
    op.execute("ALTER TABLE notification DROP CONSTRAINT IF EXISTS ck_notification_kind")
    op.execute(f"ALTER TABLE notification ADD CONSTRAINT ck_notification_kind CHECK (kind in ({OLD}))")
    for t in ("assignment_draft", "grade_item", "grading_guide", "classroom_source"):
        op.execute(f"DROP TABLE {t}")
