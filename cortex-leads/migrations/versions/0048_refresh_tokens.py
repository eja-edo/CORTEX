"""Refresh tokens: a short access token and a long, rotating refresh token per sign-in

`auth_session` gains the hash of the current refresh token's secret, the one before it (to tell two tabs racing from a stolen copy), when it was
rotated and when it ends. Sign-ins made before this have no refresh token and would be asked for one at their first expiry, so they are ended:
everyone signs in once more.

Revision ID: 0048
Revises: 0047
"""
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE auth_session ADD COLUMN refresh_hash text, ADD COLUMN refresh_prev_hash text, "
               "ADD COLUMN refresh_rotated_at timestamptz, ADD COLUMN refresh_expires_at timestamptz")
    op.execute("UPDATE auth_session SET revoked_at = now(), revoked_reason = 'refresh_tokens_introduced' WHERE revoked_at IS NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE auth_session DROP COLUMN refresh_hash, DROP COLUMN refresh_prev_hash, DROP COLUMN refresh_rotated_at, DROP COLUMN refresh_expires_at")
