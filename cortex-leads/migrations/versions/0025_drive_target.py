"""WP36: drive_target (a teacher's own Drive for recordings) and where a lesson's file went

Revision ID: 0025
Revises: 0024
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""CREATE TABLE drive_target (
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), sandbox_id uuid NOT NULL REFERENCES sandbox(id),
        label text NOT NULL, secret_enc bytea NOT NULL, folder_id text, active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_drive_target_tenant_id_sandbox_id_label UNIQUE (tenant_id, sandbox_id, label))""")
    op.execute("GRANT SELECT, INSERT, UPDATE ON drive_target TO cl_app")
    op.execute("ALTER TABLE drive_target ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE drive_target FORCE ROW LEVEL SECURITY")  # DESIGN A1
    op.execute(f"CREATE POLICY tenant_isolation ON drive_target USING ({TENANT}) WITH CHECK ({TENANT})")
    op.execute("ALTER TABLE lesson ADD COLUMN drive_target_id uuid REFERENCES drive_target(id)")
    op.execute("ALTER TABLE lesson ADD COLUMN drive_file_id text")
    op.execute("ALTER TABLE lesson ADD COLUMN drive_url text")


def downgrade() -> None:
    op.execute("ALTER TABLE lesson DROP COLUMN drive_url")
    op.execute("ALTER TABLE lesson DROP COLUMN drive_file_id")
    op.execute("ALTER TABLE lesson DROP COLUMN drive_target_id")
    op.execute("DROP TABLE drive_target")
