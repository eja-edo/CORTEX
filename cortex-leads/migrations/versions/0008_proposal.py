"""WP21 proposal (supervisor suggestions); notification kind proposal

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

RLS_USING = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""CREATE TABLE proposal (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        kind text NOT NULL, signal text NOT NULL, target jsonb NOT NULL DEFAULT '{}'::jsonb,
        evidence jsonb NOT NULL DEFAULT '{}'::jsonb, status text NOT NULL DEFAULT 'pending',
        decided_by text, decided_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_proposal_kind CHECK (kind in ('rollback_skill', 'pause_sandbox', 'review_skill')),
        CONSTRAINT ck_proposal_status CHECK (status in ('pending', 'accepted', 'dismissed', 'stale')))""")
    op.execute("CREATE UNIQUE INDEX uq_proposal_open ON proposal "
               "(tenant_id, sandbox_id, signal, (coalesce(target->>'skill', ''))) WHERE status = 'pending'")
    op.execute("GRANT SELECT, INSERT, UPDATE ON proposal TO cl_app")
    op.execute("ALTER TABLE proposal ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE proposal FORCE ROW LEVEL SECURITY")  # DESIGN A1
    op.execute(f"CREATE POLICY tenant_isolation ON proposal USING ({RLS_USING}) WITH CHECK ({RLS_USING})")
    op.execute("ALTER TABLE notification DROP CONSTRAINT IF EXISTS ck_notification_kind")
    op.execute("ALTER TABLE notification ADD CONSTRAINT ck_notification_kind "
               "CHECK (kind in ('handoff', 'booking', 'task', 'digest', 'proposal'))")


def downgrade() -> None:
    op.execute("DELETE FROM notification WHERE kind = 'proposal'")
    op.execute("ALTER TABLE notification DROP CONSTRAINT IF EXISTS ck_notification_kind")
    op.execute("ALTER TABLE notification ADD CONSTRAINT ck_notification_kind "
               "CHECK (kind in ('handoff', 'booking', 'task', 'digest'))")
    op.execute("DROP TABLE IF EXISTS proposal")
