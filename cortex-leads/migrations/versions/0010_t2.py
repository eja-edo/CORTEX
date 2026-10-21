"""WP23 T2: tool_connector kind 'mcp', proposal kind 'tune_skill' (strategy cards), outbox kind (add_tag / add_note)

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _check(table: str, name: str, col: str, *values: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_{name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_{name} CHECK ({col} in ("
               + ", ".join(f"'{v}'" for v in values) + "))")


def upgrade() -> None:
    _check("tool_connector", "kind", "kind", "http_readonly", "mcp")
    _check("proposal", "kind", "kind", "rollback_skill", "pause_sandbox", "review_skill", "tune_skill")
    op.execute("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'message'")
    _check("outbox", "kind", "kind", "message", "add_tag", "add_note")


def downgrade() -> None:
    op.execute("DELETE FROM outbox WHERE kind <> 'message'")
    op.execute("ALTER TABLE outbox DROP CONSTRAINT IF EXISTS ck_outbox_kind")
    op.execute("ALTER TABLE outbox DROP COLUMN IF EXISTS kind")
    op.execute("DELETE FROM proposal WHERE kind = 'tune_skill'")
    _check("proposal", "kind", "kind", "rollback_skill", "pause_sandbox", "review_skill")
    op.execute("DELETE FROM tool_connector WHERE kind = 'mcp'")
    _check("tool_connector", "kind", "kind", "http_readonly")
