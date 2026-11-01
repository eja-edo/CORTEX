"""WP38 Lớp học, step 2: nothing reads lesson_source / classroom_source / grading_guide / assignment_draft any more

0037 copied them into `class` and `assignment` and moved lesson and grade_item to the new keys. This drops what is left, so a class
exists in one place. There is no way back: restore from a dump taken before this revision.

Revision ID: 0038
Revises: 0037
"""
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE assignment_draft")
    op.execute("DROP TABLE grading_guide")
    for col in ("source_id", "coursework_id", "work_title", "max_points", "ours", "course_name"):
        op.execute(f"ALTER TABLE grade_item DROP COLUMN {col}")  # the assignment holds them (and the unique key on source_id goes with its column)
    op.execute("ALTER TABLE lesson DROP COLUMN source_id")
    op.execute("DROP TABLE classroom_source")
    op.execute("DROP TABLE lesson_source")


def downgrade() -> None:
    raise NotImplementedError("0038 drops data that 0037 already copied; restore from a dump taken before it")
