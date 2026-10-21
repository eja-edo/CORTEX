"""WP19 staff_task + digest (cron outputs); notification kinds task / digest

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

RLS_USING = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = ("staff_task", "digest")


def upgrade() -> None:
    op.execute("""CREATE TABLE staff_task (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        kind text NOT NULL, for_date date NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        status text NOT NULL DEFAULT 'open', done_by text, done_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_staff_task_tenant_id_sandbox_id_kind_for_date UNIQUE (tenant_id, sandbox_id, kind, for_date),
        CONSTRAINT ck_staff_task_kind CHECK (kind in ('morning_list')),
        CONSTRAINT ck_staff_task_status CHECK (status in ('open', 'done')))""")
    op.execute("""CREATE TABLE digest (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        kind text NOT NULL, period_start date NOT NULL, period_end date NOT NULL,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_digest_tenant_id_sandbox_id_kind_period_start UNIQUE (tenant_id, sandbox_id, kind, period_start),
        CONSTRAINT ck_digest_kind CHECK (kind in ('weekly')))""")
    for t in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO cl_app")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({RLS_USING}) WITH CHECK ({RLS_USING})")
    op.execute("ALTER TABLE notification DROP CONSTRAINT IF EXISTS ck_notification_kind")
    op.execute("ALTER TABLE notification ADD CONSTRAINT ck_notification_kind "
               "CHECK (kind in ('handoff', 'booking', 'task', 'digest'))")


def downgrade() -> None:
    op.execute("DELETE FROM notification WHERE kind in ('task', 'digest')")
    op.execute("ALTER TABLE notification DROP CONSTRAINT IF EXISTS ck_notification_kind")
    op.execute("ALTER TABLE notification ADD CONSTRAINT ck_notification_kind "
               "CHECK (kind in ('handoff', 'booking'))")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
