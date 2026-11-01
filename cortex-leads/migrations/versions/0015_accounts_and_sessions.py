"""WP30 accounts: people sign in with email and password; sessions live on the server and can be revoked

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""CREATE TABLE app_user (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenant(id),
        email text NOT NULL, display_name text NOT NULL,
        role text NOT NULL, staff_ref text NOT NULL,
        password_hash text NOT NULL,
        must_change_password boolean NOT NULL DEFAULT false,
        password_changed_at timestamptz NOT NULL DEFAULT now(),
        status text NOT NULL DEFAULT 'active',
        last_login_at timestamptz, created_by text,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_app_user_role CHECK (role in ('owner', 'staff')),
        CONSTRAINT ck_app_user_status CHECK (status in ('active', 'disabled')))""")
    op.execute("CREATE UNIQUE INDEX uq_app_user_email ON app_user (lower(email))")  # one person, one business
    op.execute("CREATE UNIQUE INDEX uq_app_user_ref ON app_user (tenant_id, staff_ref)")
    op.execute("""CREATE TABLE auth_session (
        id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenant(id),
        user_id uuid NOT NULL REFERENCES app_user(id),
        secret_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        ip text, user_agent text,
        revoked_at timestamptz, revoked_reason text)""")
    op.execute("CREATE INDEX ix_auth_session_user ON auth_session (tenant_id, user_id, created_at DESC)")
    op.execute("""CREATE TABLE login_throttle (
        key text PRIMARY KEY, failures int NOT NULL DEFAULT 0,
        first_at timestamptz NOT NULL DEFAULT now(), locked_until timestamptz)""")  # hashed keys only; no tenant data
    for t in ("app_user", "auth_session"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {t} TO cl_app")  # never DELETE: accounts are disabled, sessions revoked
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")  # DESIGN A1
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({TENANT}) WITH CHECK ({TENANT})")
    # The two questions that must be asked before the tenant is known, each answered for exactly one row:
    op.execute("CREATE POLICY login_lookup ON app_user FOR SELECT USING "
               "(lower(email) = nullif(current_setting('app.login_email', true), ''))")
    op.execute("CREATE POLICY session_lookup ON auth_session FOR SELECT USING "
               "(id = nullif(current_setting('app.session_id', true), '')::uuid)")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON login_throttle TO cl_app")


def downgrade() -> None:
    for t in ("login_throttle", "auth_session", "app_user"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
