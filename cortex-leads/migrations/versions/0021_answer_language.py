"""WP34: grading_guide.language and assignment_draft.language: the language a spoken answer is recognised in

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE grading_guide ADD COLUMN language text")
    op.execute("ALTER TABLE assignment_draft ADD COLUMN language text")


def downgrade() -> None:
    op.execute("ALTER TABLE assignment_draft DROP COLUMN language")
    op.execute("ALTER TABLE grading_guide DROP COLUMN language")
