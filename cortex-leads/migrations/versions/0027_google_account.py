"""WP37: google_account (one Google sign-in per person, shared by the sources that use it)

Revision ID: 0027
Revises: 0026
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""CREATE TABLE google_account (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), label text NOT NULL, email text,
        scopes text[] NOT NULL DEFAULT '{}', secret_enc bytea NOT NULL, status text NOT NULL DEFAULT 'active',
        connected_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_google_account_status CHECK (status IN ('active', 'revoked')),
        CONSTRAINT uq_google_account_tenant_id_label UNIQUE (tenant_id, label))""")
    op.execute("GRANT SELECT, INSERT, UPDATE ON google_account TO cl_app")
    op.execute("ALTER TABLE google_account ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_account FORCE ROW LEVEL SECURITY")  # DESIGN A1
    op.execute(f"CREATE POLICY tenant_isolation ON google_account USING ({TENANT}) WITH CHECK ({TENANT})")
    for table in ("classroom_source", "drive_target"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN google_account_id uuid REFERENCES google_account(id)")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN secret_enc DROP NOT NULL")  # a source tied to an account has no secret of its own


def downgrade() -> None:
    for table in ("classroom_source", "drive_target"):
        op.execute(f"DELETE FROM {table} WHERE secret_enc IS NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN secret_enc SET NOT NULL")
        op.execute(f"ALTER TABLE {table} DROP COLUMN google_account_id")
    op.execute("DROP TABLE google_account")
