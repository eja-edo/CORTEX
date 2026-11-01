"""WP37: sources made on the command line with a key of their own are switched off; Google accounts are the only way now

Revision ID: 0029
Revises: 0028

Rows and their history stay (lessons and grades point at them); they are only switched off, because the code no longer reads them.
"""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, extra in (("classroom_source", ""), ("drive_target", ""), ("lesson_source", " AND kind = 'drive'")):
        op.execute(f"UPDATE {table} SET active = false WHERE google_account_id IS NULL AND secret_enc IS NOT NULL{extra}")


def downgrade() -> None:
    pass  # which rows were on before is not recorded; they cannot be told apart from ones switched off by hand
