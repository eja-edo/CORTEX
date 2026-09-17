"""normalize semantic_memories.category onto the canonical set

Revision ID: aa01mem0cat1
Revises: d0e1f2a3b4c5
Create Date: 2026-09-10

`semantic_memories.category` was written from a prompt literal that nothing
validated, and three places disagreed about what the legal values were (see
`app.services.memory_categories` for the full account). The column is
`String(30)`, so every one of those spellings inserted cleanly.

Measured on the dev database before this migration:

    fact 6 | decision 2 | routine 2 | preference 2 | policy 1 | goal 1

`policy` is the only stale spelling with rows here, but the mapping below
covers every name the three old sources could produce — a deployment that
ran a different mix of prompt versions will have a different mix of rows.

This is a data fix, not a schema change: no CHECK constraint is added. The
write path (`PgVectorMemoryProvider.add_semantic_memory`) now normalizes
every category before INSERT, and a constraint would turn a future unknown
spelling from "logged and mapped to `fact`" into "the memory is lost" —
losing a memory is worse than mislabelling one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "aa01mem0cat1"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Giữ đồng bộ với `_ALIASES` trong app/services/memory_categories.py.
_RENAMES = {
    "policy": "constraint",
    "project": "fact",
    "environment": "fact",
    "decision_pattern": "decision",
    "unknown": "fact",
}


def upgrade() -> None:
    conn = op.get_bind()
    for old, new in _RENAMES.items():
        conn.execute(
            sa.text(
                "UPDATE semantic_memories SET category = :new WHERE category = :old"
            ),
            {"old": old, "new": new},
        )

    # Bất kỳ tên nào còn lại ngoài tập chuẩn — kể cả tên model tự bịa sau
    # này — về `fact`, cùng đáy an toàn mà `normalize_category()` dùng.
    conn.execute(
        sa.text(
            "UPDATE semantic_memories SET category = 'fact' "
            "WHERE category NOT IN "
            "('routine', 'preference', 'constraint', 'goal', 'fact', 'decision')"
        )
    )


def downgrade() -> None:
    """Không đảo ngược được, và cố ý không giả vờ là được.

    `policy` → `constraint` là ánh xạ nhiều-về-một: sau khi chạy, không còn
    cách nào biết hàng `constraint` nào từng là `policy`. Viết một
    downgrade "khôi phục" sẽ đổi nhầm cả những hàng vốn đã là `constraint`.
    """
