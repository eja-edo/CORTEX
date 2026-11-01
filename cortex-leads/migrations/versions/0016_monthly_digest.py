"""Monthly digest: digest.kind also takes 'monthly'

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE digest DROP CONSTRAINT IF EXISTS ck_digest_kind")
    op.execute("ALTER TABLE digest ADD CONSTRAINT ck_digest_kind CHECK (kind in ('weekly', 'monthly'))")


def downgrade() -> None:
    op.execute("DELETE FROM notification WHERE kind = 'digest' AND ref_id IN (SELECT id FROM digest WHERE kind = 'monthly')")
    op.execute("DELETE FROM digest WHERE kind = 'monthly'")
    op.execute("ALTER TABLE digest DROP CONSTRAINT IF EXISTS ck_digest_kind")
    op.execute("ALTER TABLE digest ADD CONSTRAINT ck_digest_kind CHECK (kind in ('weekly'))")
