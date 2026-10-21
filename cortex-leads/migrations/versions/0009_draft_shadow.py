"""WP22 draft.status 'shadow' (a skill on trial: written, read by the owner, never shown to staff or sent)

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None
BASE = ("proposed", "approved", "sent", "edited", "self", "skipped", "expired", "blocked", "failed")


def _check(*values: str) -> None:
    op.execute("ALTER TABLE draft DROP CONSTRAINT IF EXISTS ck_draft_status")
    op.execute("ALTER TABLE draft ADD CONSTRAINT ck_draft_status CHECK (status in ("
               + ", ".join(f"'{v}'" for v in values) + "))")


def upgrade() -> None:
    _check(*BASE, "shadow")


def downgrade() -> None:
    op.execute("DELETE FROM draft WHERE status = 'shadow'")
    _check(*BASE)
