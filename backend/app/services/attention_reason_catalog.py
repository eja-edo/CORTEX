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
from enum import Enum

from app.models import AttentionLevel
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ReasonScope(str, Enum):
    """Ai là người nhận đúng của một lời nhắc — DESIGN 8.1.

    `PERSONAL` là mặc định và là phần lớn: một việc quá hạn là chuyện giữa
    Cortex và một người, và nó đi về DM.

    `PROJECT` là thứ *duy nhất* trong thiết kế tạo ra giá trị tập thể ở đúng
    chi phí tập thể. Nó gỡ chính lỗi cấu trúc đã giết hướng "bot nghe
    channel" (DESIGN 1.4): ở đó tập thể trả giá (cho bot vào nghe) còn cá
    nhân hưởng (nhắc riêng). Ở đây, thứ cả nhóm quan tâm — dự án đang trượt —
    về channel chung, còn thứ riêng của một người ở lại DM.

    Phạm vi nằm ở catalog, không nằm ở Gate: Gate quyết định **có nói không**,
    delivery layer quyết định **nói qua đâu** (P2). Đó cũng là lý do
    `attention_gate.py` không phải sửa một dòng nào cho mục 8.1.
    """

    PERSONAL = "personal"
    PROJECT = "project"


@dataclass(frozen=True)
class ReasonMeta:
    base_level: AttentionLevel
    description: str
    # Mặc định `PERSONAL`: một reason mới quên khai phạm vi sẽ về DM của
    # đúng một người, chứ không phát nhầm vào một channel chung. Sai theo
    # hướng ít ồn hơn (P5, P7).
    scope: ReasonScope = ReasonScope.PERSONAL


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
    "day.plan": ReasonMeta(
        base_level=AttentionLevel.INFORM,
        description="The work day is starting and there is work due or scheduled for today.",
    ),
    "project.slipping": ReasonMeta(
        base_level=AttentionLevel.RECOMMEND,
        description=(
            "A project's open work grew since the last evaluation while its deadline is "
            "inside two weeks — the goal-progress signal that died with `goals`."
        ),
        scope=ReasonScope.PROJECT,
    ),
    "project.will_miss": ReasonMeta(
        base_level=AttentionLevel.ASK,
        description=(
            "At the current completion rate the project finishes after its deadline. "
            "A warning *before* it is late, not after."
        ),
        scope=ReasonScope.PROJECT,
    ),
}


# ---------------------------------------------------------------------------
# Supersession
# ---------------------------------------------------------------------------
#
# Three of the task reasons above are nested predicates, not independent
# ones. `task.blocked_cascade` only fires for a task that is *already*
# overdue; `task.at_risk` only fires for one that is already overdue and
# whose risk score crossed the threshold. So a single urgent, late task
# with open subtasks satisfies all three at once.
#
# Dedup can't collapse them: it keys on `(item_id, reason_key)` on purpose
# (see attention_log.py — one item legitimately surfacing for two *different*
# reasons is the case that rule protects). But these are not different
# reasons, they are three descriptions of one situation at increasing
# severity, and the strongest one's text already contains everything the
# weaker ones would have said. Sending all three is the "N producers = N
# sources of spam" outcome the Gate exists to prevent, arriving from one
# producer instead of many.
#
# So: when a reason fires and something that outranks it already reached
# the user about the *same item* inside the dedup window, the weaker one
# stays silent. The reverse is deliberately not true — a task that was
# merely overdue yesterday and is at risk today has genuinely escalated,
# and that is news worth speaking.
#
# This only works if the strongest predicate is evaluated first, which is
# why `StateEvaluator._run_loop` runs at_risk → blocked_cascade → overdue
# rather than the other way round. That ordering is load-bearing; there is
# a test pinning it.
SUPERSEDES: dict[str, frozenset[str]] = {
    "task.at_risk": frozenset({"task.blocked_cascade", "task.overdue"}),
    "task.blocked_cascade": frozenset({"task.overdue"}),
}

# Inverted once at import: `reason -> the reasons whose arrival should
# silence it`. Built from SUPERSEDES so the two can't drift.
SUPERSEDED_BY: dict[str, frozenset[str]] = {}
for _stronger, _weaker_set in SUPERSEDES.items():
    for _weaker in _weaker_set:
        SUPERSEDED_BY[_weaker] = SUPERSEDED_BY.get(_weaker, frozenset()) | {_stronger}


def superseded_by(reason_key: str) -> frozenset[str]:
    """Reasons that, if already surfaced for the same item, make
    `reason_key` redundant. Empty for reasons that stand alone."""
    return SUPERSEDED_BY.get(reason_key, frozenset())


def scope_for(reason_key: str) -> ReasonScope:
    """Phạm vi của một reason. Reason chưa đăng ký → `PERSONAL`.

    Không log cảnh báo ở đây: `base_level_for` đã cảnh báo cho cùng một
    `reason_key`, và cảnh báo hai lần cho một sự việc chỉ làm log khó đọc.
    """
    entry = REASON_CATALOG.get(reason_key)
    return entry.scope if entry is not None else ReasonScope.PERSONAL


def base_level_for(reason_key: str) -> AttentionLevel:
    entry = REASON_CATALOG.get(reason_key)
    if entry is None:
        logger.warning("Unregistered attention reason_key %r — defaulting to INFORM", reason_key)
        return AttentionLevel.INFORM
    return entry.base_level
