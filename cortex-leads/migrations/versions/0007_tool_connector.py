"""WP20 tool_connector (T1 http_readonly)

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

RLS_USING = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""CREATE TABLE tool_connector (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        name text NOT NULL, kind text NOT NULL DEFAULT 'http_readonly',
        source jsonb NOT NULL DEFAULT '{}'::jsonb, description text NOT NULL DEFAULT '',
        secret_enc bytea, pin_sha256 text NOT NULL, status text NOT NULL DEFAULT 'active',
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_tool_connector_tenant_id_sandbox_id_name UNIQUE (tenant_id, sandbox_id, name),
        CONSTRAINT ck_tool_connector_kind CHECK (kind in ('http_readonly')),
        CONSTRAINT ck_tool_connector_status CHECK (status in ('active', 'disabled')))""")
    op.execute("GRANT SELECT, INSERT, UPDATE ON tool_connector TO cl_app")
    op.execute("ALTER TABLE tool_connector ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tool_connector FORCE ROW LEVEL SECURITY")  # DESIGN A1
    op.execute(f"CREATE POLICY tenant_isolation ON tool_connector USING ({RLS_USING}) WITH CHECK ({RLS_USING})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tool_connector")
