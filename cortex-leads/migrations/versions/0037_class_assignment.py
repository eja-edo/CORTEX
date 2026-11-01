"""WP38 Lớp học: `class` replaces lesson_source + classroom_source, `assignment` replaces assignment_draft + grading_guide

Additive step: the old tables and columns stay (the legacy columns of lesson / grade_item are made nullable) so 0038 can drop them
once the code no longer reads them.

Revision ID: 0037
Revises: 0036
"""
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""CREATE TABLE class (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), name text NOT NULL,
        active boolean NOT NULL DEFAULT true, listed boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
        recap_sandbox_id uuid REFERENCES sandbox(id), grader_sandbox_id uuid REFERENCES sandbox(id),
        source_kind text, source_ref text, drive_account_id uuid REFERENCES google_account(id),
        owned boolean NOT NULL DEFAULT false, source_secret_enc bytea,
        notify_target_id uuid REFERENCES notify_target(id),
        classroom_account_id uuid REFERENCES google_account(id), course_id text, course_name text,
        auth_kind text, subject text, classroom_secret_enc bytea,
        recap_mode text NOT NULL DEFAULT 'review', grading_mode text NOT NULL DEFAULT 'review',
        assignment_post_mode text NOT NULL DEFAULT 'manual',
        CONSTRAINT ck_class_source_kind CHECK (source_kind IS NULL OR source_kind in ('drive', 'local', 'upload')),
        CONSTRAINT ck_class_auth_kind CHECK (auth_kind IS NULL OR auth_kind in ('delegated', 'oauth')),
        CONSTRAINT ck_class_recap_mode CHECK (recap_mode in ('auto', 'review')),
        CONSTRAINT ck_class_grading_mode CHECK (grading_mode in ('manual', 'review', 'auto_write')),
        CONSTRAINT ck_class_assignment_post_mode CHECK (assignment_post_mode in ('manual')),
        CONSTRAINT ck_class_has_sandbox CHECK (recap_sandbox_id IS NOT NULL OR grader_sandbox_id IS NOT NULL),
        CONSTRAINT ck_class_recap_source CHECK (recap_sandbox_id IS NULL OR (source_kind IS NOT NULL AND source_ref IS NOT NULL)),
        CONSTRAINT ck_class_grader_course CHECK (grader_sandbox_id IS NULL OR (course_id IS NOT NULL AND auth_kind IS NOT NULL)),
        CONSTRAINT uq_class_tenant_id_recap_sandbox_id_source_kind_source_ref UNIQUE (tenant_id, recap_sandbox_id, source_kind, source_ref),
        CONSTRAINT uq_class_tenant_id_grader_sandbox_id_course_id UNIQUE (tenant_id, grader_sandbox_id, course_id))""")

    # One class per lesson_source. A classroom_source joins the lesson_source of its course (the oldest, when several share it);
    # one nobody claims becomes a class that only grades.
    op.execute("""CREATE TEMP TABLE _pair ON COMMIT DROP AS
        SELECT DISTINCT ON (cs.id) ls.id AS lsid, cs.id AS csid
        FROM lesson_source ls JOIN classroom_source cs ON cs.tenant_id = ls.tenant_id AND cs.course_id = ls.classroom_course_id
        ORDER BY cs.id, ls.created_at, ls.id""")
    op.execute("""INSERT INTO class (id, tenant_id, name, active, listed, created_at, recap_sandbox_id, grader_sandbox_id, source_kind, source_ref,
            drive_account_id, owned, source_secret_enc, notify_target_id, classroom_account_id, course_id, course_name, auth_kind, subject,
            classroom_secret_enc)
        SELECT ls.id, ls.tenant_id, coalesce(ls.label, cs.label, ls.classroom_course_name, ls.ref), ls.active AND coalesce(cs.active, true),
            ls.kind = 'drive' AND coalesce(ls.label, '') <> '' AND (ls.google_account_id IS NOT NULL OR ls.secret_enc IS NULL),
            ls.created_at, ls.sandbox_id, cs.sandbox_id, ls.kind, ls.ref, ls.google_account_id, ls.owned, ls.secret_enc, ls.notify_target_id,
            CASE WHEN ls.classroom_course_id IS NULL THEN NULL
                 ELSE coalesce(cs.google_account_id, ls.classroom_account_id, ls.google_account_id) END,
            ls.classroom_course_id, ls.classroom_course_name, cs.auth_kind, cs.subject, cs.secret_enc
        FROM lesson_source ls LEFT JOIN _pair p ON p.lsid = ls.id LEFT JOIN classroom_source cs ON cs.id = p.csid""")
    op.execute("""INSERT INTO class (id, tenant_id, name, active, created_at, grader_sandbox_id, classroom_account_id, course_id, auth_kind,
            subject, classroom_secret_enc)
        SELECT cs.id, cs.tenant_id, coalesce(cs.label, cs.course_id), cs.active, cs.created_at, cs.sandbox_id, cs.google_account_id,
            cs.course_id, cs.auth_kind, cs.subject, cs.secret_enc
        FROM classroom_source cs WHERE cs.id NOT IN (SELECT csid FROM _pair)""")
    op.execute("""CREATE TEMP TABLE _cmap ON COMMIT DROP AS
        SELECT csid, lsid AS class_id FROM _pair
        UNION ALL SELECT id, id FROM classroom_source WHERE id NOT IN (SELECT csid FROM _pair)""")

    op.execute("""CREATE TABLE assignment (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), class_id uuid NOT NULL REFERENCES class(id),
        coursework_id text, origin text NOT NULL DEFAULT 'app', authored_by text, state text NOT NULL DEFAULT 'draft',
        title text NOT NULL, description text, max_points numeric(8,2), due_at timestamptz, publish boolean NOT NULL DEFAULT false,
        materials jsonb NOT NULL DEFAULT '[]'::jsonb, criteria jsonb, answer_key text, language text, check_prompt text,
        error text, created_by text, decided_by text, decided_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_assignment_origin CHECK (origin in ('app', 'classroom')),
        CONSTRAINT ck_assignment_authored_by CHECK (authored_by IS NULL OR authored_by in ('teacher', 'ai')),
        CONSTRAINT ck_assignment_state CHECK (state in ('draft', 'created', 'rejected', 'failed')),
        CONSTRAINT uq_assignment_tenant_id_class_id_coursework_id UNIQUE (tenant_id, class_id, coursework_id))""")
    op.execute("CREATE INDEX ix_assignment_class ON assignment (tenant_id, class_id, created_at)")

    # a) every grading guide (a guide exists for work already in Classroom)
    op.execute("""INSERT INTO assignment (id, tenant_id, class_id, coursework_id, origin, state, title, max_points, criteria, answer_key,
            language, check_prompt, created_at)
        SELECT gen_random_uuid(), g.tenant_id, m.class_id, g.coursework_id,
            CASE WHEN EXISTS (SELECT 1 FROM assignment_draft d WHERE d.source_id = g.source_id AND d.coursework_id = g.coursework_id)
                   OR EXISTS (SELECT 1 FROM grade_item i WHERE i.source_id = g.source_id AND i.coursework_id = g.coursework_id AND i.ours)
                 THEN 'app' ELSE 'classroom' END,
            'created', g.title, g.max_points, g.criteria, g.answer_key, g.language, g.check_prompt, g.created_at
        FROM grading_guide g JOIN _cmap m ON m.csid = g.source_id""")
    # b) drafts the guide already covers: carry the draft's own fields over
    op.execute("""UPDATE assignment a SET authored_by = d.origin, description = d.description, due_at = d.due, publish = d.publish,
            materials = d.materials, created_by = d.created_by, decided_by = d.decided_by, decided_at = d.decided_at
        FROM assignment_draft d JOIN _cmap m ON m.csid = d.source_id
        WHERE a.class_id = m.class_id AND a.coursework_id = d.coursework_id""")
    # c) drafts without a guide (not yet in Classroom, or rejected / failed)
    op.execute("""INSERT INTO assignment (id, tenant_id, class_id, coursework_id, origin, authored_by, state, title, description, max_points,
            due_at, publish, materials, criteria, answer_key, language, check_prompt, error, created_by, decided_by, decided_at, created_at)
        SELECT gen_random_uuid(), d.tenant_id, m.class_id, d.coursework_id, 'app', d.origin, d.status, d.title, d.description, d.max_points,
            d.due, d.publish, d.materials, d.criteria, d.answer_key, d.language, d.check_prompt, d.error, d.created_by, d.decided_by,
            d.decided_at, d.created_at
        FROM assignment_draft d JOIN _cmap m ON m.csid = d.source_id
        WHERE NOT EXISTS (SELECT 1 FROM assignment a WHERE a.class_id = m.class_id AND a.coursework_id = d.coursework_id)""")
    # d) work only seen through its submissions (no guide: it cannot be graded)
    op.execute("""INSERT INTO assignment (id, tenant_id, class_id, coursework_id, origin, state, title, max_points, created_at)
        SELECT gen_random_uuid(), i.tenant_id, m.class_id, i.coursework_id, CASE WHEN bool_or(i.ours) THEN 'app' ELSE 'classroom' END,
            'created', (array_agg(i.work_title ORDER BY i.created_at))[1], max(i.max_points), min(i.created_at)
        FROM grade_item i JOIN _cmap m ON m.csid = i.source_id
        WHERE NOT EXISTS (SELECT 1 FROM assignment a WHERE a.class_id = m.class_id AND a.coursework_id = i.coursework_id)
        GROUP BY i.tenant_id, m.class_id, i.coursework_id""")

    op.execute("ALTER TABLE lesson ADD COLUMN class_id uuid REFERENCES class(id)")
    op.execute("UPDATE lesson SET class_id = source_id")
    op.execute("ALTER TABLE lesson ALTER COLUMN class_id SET NOT NULL")
    op.execute("ALTER TABLE lesson ALTER COLUMN source_id DROP NOT NULL")
    op.execute("ALTER TABLE lesson ADD COLUMN released_at timestamptz, ADD COLUMN released_by text")
    op.execute("UPDATE lesson SET released_at = coalesce(finished_at, created_at), released_by = 'migration' WHERE status = 'done'")
    op.execute("CREATE INDEX ix_lesson_class ON lesson (tenant_id, class_id, created_at)")

    op.execute("ALTER TABLE grade_item ADD COLUMN assignment_id uuid REFERENCES assignment(id)")
    op.execute("""UPDATE grade_item i SET assignment_id = a.id FROM assignment a JOIN _cmap m ON m.class_id = a.class_id
        WHERE m.csid = i.source_id AND a.coursework_id = i.coursework_id""")
    op.execute("ALTER TABLE grade_item ALTER COLUMN assignment_id SET NOT NULL")
    for col in ("source_id", "coursework_id", "work_title"):
        op.execute(f"ALTER TABLE grade_item ALTER COLUMN {col} DROP NOT NULL")
    op.execute("ALTER TABLE grade_item ADD COLUMN write_mode text")
    op.execute("ALTER TABLE grade_item ADD CONSTRAINT ck_grade_item_write_mode CHECK (write_mode IS NULL OR write_mode in ('none', 'draft', 'return'))")
    op.execute("ALTER TABLE grade_item DROP CONSTRAINT ck_grade_item_status")
    op.execute("""ALTER TABLE grade_item ADD CONSTRAINT ck_grade_item_status CHECK
        (status in ('pending', 'queued', 'working', 'proposed', 'approved', 'rejected', 'skipped', 'failed'))""")
    op.execute("""ALTER TABLE grade_item ADD CONSTRAINT uq_grade_item_tenant_id_sandbox_id_assignment_id_submission_id
        UNIQUE (tenant_id, sandbox_id, assignment_id, submission_id)""")
    op.execute("CREATE INDEX ix_grade_item_assignment ON grade_item (tenant_id, assignment_id, status)")

    for t in ("class", "assignment"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO cl_app")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({TENANT}) WITH CHECK ({TENANT})")


def downgrade() -> None:
    op.execute("DELETE FROM grade_item WHERE status = 'pending'")
    op.execute("DROP INDEX ix_grade_item_assignment")
    op.execute("ALTER TABLE grade_item DROP CONSTRAINT uq_grade_item_tenant_id_sandbox_id_assignment_id_submission_id")
    op.execute("ALTER TABLE grade_item DROP CONSTRAINT ck_grade_item_status")
    op.execute("""ALTER TABLE grade_item ADD CONSTRAINT ck_grade_item_status CHECK
        (status in ('queued', 'working', 'proposed', 'approved', 'rejected', 'skipped', 'failed'))""")
    op.execute("ALTER TABLE grade_item DROP CONSTRAINT ck_grade_item_write_mode")
    op.execute("ALTER TABLE grade_item DROP COLUMN write_mode")
    op.execute("ALTER TABLE grade_item DROP COLUMN assignment_id")
    op.execute("DROP INDEX ix_lesson_class")
    op.execute("ALTER TABLE lesson DROP COLUMN released_by, DROP COLUMN released_at, DROP COLUMN class_id")
    op.execute("DROP TABLE assignment")
    op.execute("DROP TABLE class")
