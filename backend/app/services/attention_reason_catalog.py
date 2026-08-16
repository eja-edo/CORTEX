"""
Attention Reason Catalog — the baseline importance of each `reason_key`.

Step 1 of the Attention Gate (6.1) is "is this worth mentioning at all?".
This module is the deterministic half of that answer: a lookup from a
stable `reason_key` (the same string `attention_log.reason_key` stores) to
a baseline `AttentionLevel`. The Gate then adjusts the baseline using
signals specific to the item (e.g. a task's priority and how overdue it
is) — this catalog only says where a *reason* starts before that
adjustment, not the final level for any specific item.

This is a seed of the Trigger Catalog (4.2): 4.2 turns each of these into a
user-facing entry a workflow builder can pick from. Kept as its own module
now, rather than folded into `attention_gate.py`, so 4.2 has one place to
read from instead of scraping gate logic later.

Unregistered `reason_key`s don't fail — they fall back to INFORM (the
mildest non-silent level) so a new producer that forgets to register its
reason still surfaces, deliberately erring toward "shown once too often"
over "silently dropped". They log a warning, because an unregistered
reason is a sign the catalog fell behind, not a normal state.
"""

from dataclasses import dataclass

from app.models import AttentionLevel
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReasonMeta:
    base_level: AttentionLevel
    description: str


REASON_CATALOG: dict[str, ReasonMeta] = {
    "schedule.reminder.due": ReasonMeta(
        base_level=AttentionLevel.INFORM,
        description="A schedule reminder the user set is due.",
    ),
    "task.overdue": ReasonMeta(
        base_level=AttentionLevel.RECOMMEND,
        description="A task passed its due date without being completed.",
    ),
    "task.due_soon": ReasonMeta(
        base_level=AttentionLevel.INFORM,
        description="A task's due date is coming up and it hasn't been started.",
    ),
    "task.stale": ReasonMeta(
        base_level=AttentionLevel.INFORM,
        description="An open, undated task hasn't been touched in a while.",
    ),
    "task.blocked_cascade": ReasonMeta(
        base_level=AttentionLevel.RECOMMEND,
        description="An overdue task still has unfinished subtasks under it.",
    ),
    "task.at_risk": ReasonMeta(
        base_level=AttentionLevel.ASK,
        description=(
            "A task's combined priority, lateness, and blocked subtasks crossed the risk "
            "threshold — worse than a plain overdue nudge accounts for."
        ),
    ),
    "schedule.starts_soon": ReasonMeta(
        base_level=AttentionLevel.INFORM,
        description="A scheduled event is about to start.",
    ),
    "day.review": ReasonMeta(
        base_level=AttentionLevel.INFORM,
        description="The day is winding down and work is still open.",
    ),
}


def base_level_for(reason_key: str) -> AttentionLevel:
    entry = REASON_CATALOG.get(reason_key)
    if entry is None:
        logger.warning("Unregistered attention reason_key %r — defaulting to INFORM", reason_key)
        return AttentionLevel.INFORM
    return entry.base_level
