"""WP31 lesson_recap: recordings, their recaps, and the Mezon push target

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
NOTIFICATION_KINDS = "'handoff', 'booking', 'task', 'digest', 'proposal'"


def upgrade() -> None:
    op.execute("""CREATE TABLE lesson_source (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenant(id),
        sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        kind text NOT NULL, ref text NOT NULL, secret_enc bytea,
        active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_lesson_source_kind CHECK (kind in ('drive', 'local')),
        CONSTRAINT uq_lesson_source_tenant_id_sandbox_id_kind_ref UNIQUE (tenant_id, sandbox_id, kind, ref))""")
    op.execute("""CREATE TABLE lesson (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenant(id),
        sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        source_id uuid NOT NULL REFERENCES lesson_source(id),
        file_id text NOT NULL, name text NOT NULL,
        status text NOT NULL DEFAULT 'queued',
        attempts integer NOT NULL DEFAULT 0,
        claimed_at timestamptz, transcript text, recap jsonb, error text,
        created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
        CONSTRAINT ck_lesson_status CHECK (status in ('queued', 'working', 'done', 'failed')),
        CONSTRAINT uq_lesson_tenant_id_sandbox_id_file_id UNIQUE (tenant_id, sandbox_id, file_id))""")
    op.execute("CREATE INDEX ix_lesson_pick ON lesson (tenant_id, status, created_at)")
    for t in ("lesson_source", "lesson"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO cl_app")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({TENANT}) WITH CHECK ({TENANT})")
    op.execute("ALTER TABLE notification DROP CONSTRAINT IF EXISTS ck_notification_kind")
    op.execute(f"ALTER TABLE notification ADD CONSTRAINT ck_notification_kind CHECK (kind in ({NOTIFICATION_KINDS}, 'lesson'))")
    op.execute("ALTER TABLE notify_target DROP CONSTRAINT IF EXISTS ck_notify_target_kind")
    op.execute("ALTER TABLE notify_target ADD CONSTRAINT ck_notify_target_kind CHECK (kind in ('telegram', 'mezon'))")


def downgrade() -> None:
    op.execute("DELETE FROM notification WHERE kind = 'lesson'")
    op.execute("DELETE FROM notify_target WHERE kind = 'mezon'")
    op.execute("ALTER TABLE notify_target DROP CONSTRAINT IF EXISTS ck_notify_target_kind")
    op.execute("ALTER TABLE notify_target ADD CONSTRAINT ck_notify_target_kind CHECK (kind in ('telegram'))")
    op.execute("ALTER TABLE notification DROP CONSTRAINT IF EXISTS ck_notification_kind")
    op.execute(f"ALTER TABLE notification ADD CONSTRAINT ck_notification_kind CHECK (kind in ({NOTIFICATION_KINDS}))")
    op.execute("DROP TABLE lesson")
    op.execute("DROP TABLE lesson_source")
