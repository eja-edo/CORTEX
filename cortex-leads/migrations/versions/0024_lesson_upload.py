"""WP35: lessons can be uploaded in the console (lesson_source.kind 'upload') and say what language they are spoken in

Revision ID: 0024
Revises: 0023
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE lesson_source DROP CONSTRAINT IF EXISTS ck_lesson_source_kind")
    op.execute("ALTER TABLE lesson_source ADD CONSTRAINT ck_lesson_source_kind CHECK (kind in ('drive', 'local', 'upload'))")
    op.execute("ALTER TABLE lesson ADD COLUMN language text")


def downgrade() -> None:
    op.execute("ALTER TABLE lesson DROP COLUMN language")
    op.execute("DELETE FROM lesson WHERE source_id IN (SELECT id FROM lesson_source WHERE kind = 'upload')")
    op.execute("DELETE FROM lesson_source WHERE kind = 'upload'")
    op.execute("ALTER TABLE lesson_source DROP CONSTRAINT IF EXISTS ck_lesson_source_kind")
    op.execute("ALTER TABLE lesson_source ADD CONSTRAINT ck_lesson_source_kind CHECK (kind in ('drive', 'local'))")
