"""Sign-in by signed token: a version per person instead of a secret per session

`app_user.token_version` is the number every sign-in token carries; raising it signs the person out everywhere at once. The per-device
rows in `auth_session` stay (the list of devices, signing one out, the activity clock) but no longer hold a secret: the cookie is now a
token, so `secret_hash` goes. Sign-ins made with the old cookie stop working: everyone signs in once more.

Revision ID: 0047
Revises: 0046
"""
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app_user ADD COLUMN token_version integer NOT NULL DEFAULT 0")
    op.execute("UPDATE auth_session SET revoked_at = now(), revoked_reason = 'token_format_changed' WHERE revoked_at IS NULL")
    op.execute("ALTER TABLE auth_session DROP COLUMN secret_hash")


def downgrade() -> None:
    op.execute("ALTER TABLE auth_session ADD COLUMN secret_hash text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE app_user DROP COLUMN token_version")
