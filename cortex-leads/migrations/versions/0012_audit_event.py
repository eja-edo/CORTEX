"""WP28 audit_event: append-only, hash-chained record of who did what, when, from where

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

RLS = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""CREATE TABLE audit_event (
        id uuid PRIMARY KEY,
        seq bigint GENERATED ALWAYS AS IDENTITY,
        tenant_id uuid,
        at timestamptz NOT NULL DEFAULT now(),
        actor text NOT NULL, actor_role text NOT NULL DEFAULT 'system',
        category text NOT NULL, action text NOT NULL, result text NOT NULL DEFAULT 'success',
        object_type text, object_id text, object_label text,
        summary text NOT NULL,
        ip text, user_agent text, request_id text, session_id text,
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        prev_hash text, hash text NOT NULL,
        CONSTRAINT ck_audit_event_result CHECK (result in ('success', 'denied', 'failed', 'pending')))""")
    op.execute("CREATE INDEX ix_audit_tenant_seq ON audit_event (tenant_id, seq DESC)")
    op.execute("CREATE INDEX ix_audit_tenant_actor ON audit_event (tenant_id, actor, seq DESC)")
    op.execute("CREATE INDEX ix_audit_tenant_object ON audit_event (tenant_id, object_type, object_id, seq DESC)")
    op.execute("GRANT SELECT, INSERT ON audit_event TO cl_app")  # no UPDATE, no DELETE
    op.execute("ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_event FORCE ROW LEVEL SECURITY")  # DESIGN A1
    op.execute(f"CREATE POLICY tenant_isolation ON audit_event FOR SELECT USING ({RLS})")
    op.execute(f"CREATE POLICY tenant_insert ON audit_event FOR INSERT WITH CHECK ({RLS})")
    op.execute("CREATE POLICY platform_insert ON audit_event FOR INSERT WITH CHECK (tenant_id IS NULL)")  # unknown-key sign-ins
    op.execute("""CREATE FUNCTION audit_event_immutable() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN RAISE EXCEPTION 'audit_event is append-only'; END $$""")
    op.execute("CREATE TRIGGER audit_event_no_change BEFORE UPDATE OR DELETE ON audit_event "
               "FOR EACH ROW EXECUTE FUNCTION audit_event_immutable()")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_event")
    op.execute("DROP FUNCTION IF EXISTS audit_event_immutable()")
