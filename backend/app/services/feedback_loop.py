"""Feedback Loop (Milestone 6.9).

The data this reads already exists — `attention_log.response`, written by
`POST /attention-log/{id}/response` since 2.9 — so this module is only the
"read and adjust" half Bản 2's 6.9 note called out: no new storage, just a
count query (the `ix_attention_log_user_reason_response` index was already
shaped for exactly this read) and a small step function.

The rule (6.9 M3): every `FEEDBACK_LOOP_DISMISS_THRESHOLD` dismissals of a
`reason_key` drops it one rung down the level ladder for that user —
`ACT → ASK → RECOMMEND → INFORM → SILENT`. This is the automatic version of
the manual "don't tell me about this kind of thing" toggle (redesigned 4.5,
`UserPreferences.disabled_reason_keys`): that one is an explicit, immediate
off switch; this one is Cortex noticing the same thing on its own, one step
at a time, from behavior instead of a setting.

Per-user, not global: one user dismissing `task.stale` a lot must not
quiet it for everyone. `apply_downgrade` never *raises* a level (same
one-directional contract as `_escalate`/`_escalate_for_task` in
attention_gate.py) — accepting a surfacing doesn't undo an earlier
downgrade, it just stops adding to it.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AttentionLevel, AttentionLog, AttentionResponse

# Low to high — the same order attention_gate.py's `_LEVEL_RANK` encodes,
# duplicated here as a plain list because downgrading needs to walk it by
# index, not just compare two levels.
_LEVEL_LADDER = [
    AttentionLevel.SILENT,
    AttentionLevel.INFORM,
    AttentionLevel.RECOMMEND,
    AttentionLevel.ASK,
    AttentionLevel.ACT,
]


def _dismiss_count_stmt(user_id: UUID, reason_key: str):
    return (
        select(func.count())
        .select_from(AttentionLog)
        .where(
            AttentionLog.user_id == user_id,
            AttentionLog.reason_key == reason_key,
            AttentionLog.response == AttentionResponse.DISMISSED,
        )
    )


async def dismiss_count_async(session: AsyncSession, user_id: UUID, reason_key: str) -> int:
    result = await session.execute(_dismiss_count_stmt(user_id, reason_key))
    return result.scalar_one()


def dismiss_count_sync(session: Session, user_id: UUID, reason_key: str) -> int:
    result = session.execute(_dismiss_count_stmt(user_id, reason_key))
    return result.scalar_one()


def apply_downgrade(level: AttentionLevel, dismiss_count: int) -> AttentionLevel:
    """`level` after `dismiss_count` dismissals of its reason_key have
    pushed it down the ladder. Never raises `level` — a fresh reason_key
    (`dismiss_count=0`) always returns `level` unchanged."""
    threshold = settings.FEEDBACK_LOOP_DISMISS_THRESHOLD
    if threshold <= 0:
        return level
    steps = dismiss_count // threshold
    if steps <= 0:
        return level
    index = _LEVEL_LADDER.index(level)
    return _LEVEL_LADDER[max(0, index - steps)]
