"""draft.route: 'offchannel' drafts are for staff to phone/Zalo when the channel window is closed

Idempotent like 0002: on a fresh database 0001 already built draft from the current models.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None
VIEW_COLS = ["tenant_id", "status", "route", "created_at"]


def upgrade() -> None:
    op.execute("ALTER TABLE draft ADD COLUMN IF NOT EXISTS route text NOT NULL DEFAULT 'channel'")
    op.execute("ALTER TABLE draft DROP CONSTRAINT IF EXISTS ck_draft_route")
    op.execute("ALTER TABLE draft ADD CONSTRAINT ck_draft_route "
               "CHECK (route in ('channel', 'offchannel'))")
    op.execute("DROP VIEW IF EXISTS supervisor_draft_view")  # counts only, no text (DESIGN §5.6)
    op.execute(f"CREATE VIEW supervisor_draft_view WITH (security_invoker = true) AS "
               f"SELECT {', '.join(VIEW_COLS)} FROM draft")
    op.execute(f"GRANT SELECT ({', '.join(VIEW_COLS)}) ON draft TO cl_supervisor")
    op.execute("GRANT SELECT ON supervisor_draft_view TO cl_supervisor")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS supervisor_draft_view")
    op.execute("ALTER TABLE draft DROP CONSTRAINT IF EXISTS ck_draft_route")
    op.execute("ALTER TABLE draft DROP COLUMN IF EXISTS route")
