"""Ordering of `AttentionLevel`, in one place.

The ladder SILENT < INFORM < RECOMMEND < ASK < ACT is consulted by three
independent modules — the Gate escalates along it (attention_gate.py), the
Feedback Loop walks down it (feedback_loop.py), and the delivery layer
compares a notification's level against each channel's `min_level`
(app/services/delivery/). Two of those already had their own copy of the
rank map; a third would have made a silent disagreement about what
outranks what into a delivery bug rather than a visible one.
"""

from app.models import AttentionLevel

LEVEL_RANK: dict[AttentionLevel, int] = {
    AttentionLevel.SILENT: 0,
    AttentionLevel.INFORM: 1,
    AttentionLevel.RECOMMEND: 2,
    AttentionLevel.ASK: 3,
    AttentionLevel.ACT: 4,
}


def meets_min_level(level: AttentionLevel, minimum: AttentionLevel) -> bool:
    """Is `level` important enough to clear a `minimum` floor?

    Used by the delivery layer: a channel with `min_level=ASK` takes ASK
    and ACT, and lets INFORM/RECOMMEND stay in-app. SILENT never reaches a
    channel — the Gate stops it long before — but the ordering below still
    gives the right answer if it ever did.
    """
    return LEVEL_RANK[level] >= LEVEL_RANK[minimum]
