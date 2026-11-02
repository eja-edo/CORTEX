"""WP39 tenant.ai_name (the name the AI introduces itself by); password reset by email

Revision ID: 0039
Revises: 0038
"""
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN IF NOT EXISTS ai_name text")
    op.execute("""CREATE TABLE password_reset (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenant(id),
        user_id uuid NOT NULL REFERENCES app_user(id),
        token_hash text NOT NULL UNIQUE,
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        ip text)""")
    op.execute("CREATE INDEX ix_password_reset_user ON password_reset (tenant_id, user_id, created_at DESC)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON password_reset TO cl_app")  # a used link is marked, never deleted
    op.execute("ALTER TABLE password_reset ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE password_reset FORCE ROW LEVEL SECURITY")  # DESIGN A1
    op.execute(f"CREATE POLICY tenant_isolation ON password_reset USING ({TENANT}) WITH CHECK ({TENANT})")
    # The one question asked before the business is known: whose link is this? Answered for exactly the row whose hash is named.
    op.execute("CREATE POLICY reset_lookup ON password_reset FOR SELECT USING "
               "(token_hash = nullif(current_setting('app.reset_token', true), ''))")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS password_reset")
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS ai_name")
