"""Accounts are invited, not given a temporary password: drop must_change_password

A temporary password was a secret that existed in clear on the owner's screen and in whatever they copied it into. Accounts that still
hold one (created or reset, never signed in with a chosen password) are closed here: the password is made unusable and their sign-ins
end, so the owner sends them a link instead.

Revision ID: 0045
Revises: 0044
"""
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""UPDATE auth_session SET revoked_at = now(), revoked_reason = 'temporary_password_retired'
                  WHERE revoked_at IS NULL AND user_id IN (SELECT id FROM app_user WHERE must_change_password)""")
    op.execute("UPDATE app_user SET password_hash = '!' WHERE must_change_password")  # '!' is not a hash: nothing verifies against it
    op.execute("ALTER TABLE app_user DROP COLUMN must_change_password")


def downgrade() -> None:
    # Accounts waiting for an invitation keep their unusable password; the flag comes back false for everyone.
    op.execute("ALTER TABLE app_user ADD COLUMN must_change_password boolean NOT NULL DEFAULT false")
