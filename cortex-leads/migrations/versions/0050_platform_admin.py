"""The platform admin page (WP47, DESIGN §5.16): the operator of the server signs in here, not as a person of a business

`platform_admin` has no `tenant_id` (it belongs to no business), so like `tenant` and `login_throttle` it has no row-level security. The
app role reads and writes it but never deletes: an admin is disabled, as people of a business are. Two-step sign-in columns match
`app_user`, so one TOTP implementation serves both.

Revision ID: 0050
Revises: 0049
"""
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE platform_admin (
        id uuid PRIMARY KEY,
        email text NOT NULL, display_name text NOT NULL,
        password_hash text NOT NULL,
        mfa_secret_enc text, mfa_pending_enc text, mfa_enabled_at timestamptz, mfa_last_step bigint, mfa_recovery jsonb,
        token_version integer NOT NULL DEFAULT 0,
        status text NOT NULL DEFAULT 'active',
        last_login_at timestamptz, created_by text,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_platform_admin_status CHECK (status in ('active', 'disabled')))""")
    op.execute("CREATE UNIQUE INDEX uq_platform_admin_email ON platform_admin (lower(email))")
    op.execute("GRANT SELECT, INSERT, UPDATE ON platform_admin TO cl_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_admin")
