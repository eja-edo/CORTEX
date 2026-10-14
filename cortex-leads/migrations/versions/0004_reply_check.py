"""WP16 (DESIGN §5.7 `turn`): conversation.reply_check_at / reply_waits, draft.needs_human

Idempotent like 0002/0003: on a fresh database 0001 already built the tables from current models.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversation ADD COLUMN IF NOT EXISTS reply_check_at timestamptz")
    op.execute("ALTER TABLE conversation ADD COLUMN IF NOT EXISTS reply_waits smallint NOT NULL DEFAULT 0")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_reply_check ON conversation "
               "(tenant_id, reply_check_at) WHERE reply_check_at IS NOT NULL")
    op.execute("ALTER TABLE draft ADD COLUMN IF NOT EXISTS needs_human boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE draft DROP COLUMN IF EXISTS needs_human")
    op.execute("DROP INDEX IF EXISTS ix_conversation_reply_check")
    op.execute("ALTER TABLE conversation DROP COLUMN IF EXISTS reply_waits")
    op.execute("ALTER TABLE conversation DROP COLUMN IF EXISTS reply_check_at")
