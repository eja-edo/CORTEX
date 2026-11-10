"""Two-step sign-in (TOTP) that each person turns on for themselves

`app_user` gains the TOTP secret (Fernet, the same key as the connector secrets), the secret waiting to be confirmed while it is being set up,
when it was turned on, the last time-step a code was accepted for (a code works once, not for its whole 30 seconds), and the hashes of the
unused recovery codes. Nothing changes for anyone until they turn it on.

Revision ID: 0049
Revises: 0048
"""
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app_user ADD COLUMN mfa_secret_enc text, ADD COLUMN mfa_pending_enc text, ADD COLUMN mfa_enabled_at timestamptz, "
               "ADD COLUMN mfa_last_step bigint, ADD COLUMN mfa_recovery jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE app_user DROP COLUMN mfa_secret_enc, DROP COLUMN mfa_pending_enc, DROP COLUMN mfa_enabled_at, "
               "DROP COLUMN mfa_last_step, DROP COLUMN mfa_recovery")
