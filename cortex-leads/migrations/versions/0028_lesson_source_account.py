"""WP37: a watched recordings folder can be read with a Google account (and carries a name)

Revision ID: 0028
Revises: 0027
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE lesson_source ADD COLUMN google_account_id uuid REFERENCES google_account(id)")
    op.execute("ALTER TABLE lesson_source ADD COLUMN label text")


def downgrade() -> None:
    op.execute("DELETE FROM lesson_source WHERE secret_enc IS NULL AND kind = 'drive'")
    op.execute("ALTER TABLE lesson_source DROP COLUMN label")
    op.execute("ALTER TABLE lesson_source DROP COLUMN google_account_id")
