"""Attention Gate (Milestone 6.1 M2+M3 — all five steps, deterministic).

Every notification-creation path in the backend goes through the two
functions here. Until M2 they were a pure pass-through to
NotificationService; this module now runs all five steps the planning doc
lays out for 6.1:

    1. Đáng nói không?      — importance, from the reason catalog plus (for
                               a task) its own priority/overdue standing.
    2. User đã biết chưa?   — dedup against attention_log (2.9).
    3. User có rảnh không?  — busy against `schedules` (seed of 3.3) OR
                               inside configured quiet hours (6.2) —
                               app.services.availability.should_stay_quiet.
    4. Gộp với gì?          — a step-3-silenced candidate is queued
                               (app.services.attention_bundle), not dropped.
    5. Thời điểm nào tốt?   — AttentionBundleWorker flushes the queue once
                               the user is free again — see that module.

A candidate that clears step 3 (available, or critical enough to interrupt
anyway) still becomes a Notification immediately here, one at a time —
steps 4-5 only apply to the ones step 3 silenced.

**The gated path only runs when the caller supplies `item_type` + `item_id`
+ `reason_key`.** Omit any of the three and this falls back to M1's
pass-through — that's the correct behaviour for candidates that don't name
a domain item (e.g. `google_calendar_sync`'s "reconnect Calendar" alert:
there is no task/goal/commitment/schedule row a revoked OAuth grant is
*about*, so there's nothing for `attention_log` to dedup against). Item-less
system alerts are the one legitimate permanent user of the pass-through
branch, not a migration debt.

Two independent implementations of steps 1-3 live below — `_sync` and
`_async` — because their callers hold different session types
(`request_attention_sync` serves `google_calendar_sync.py` and the
`/internal/attention/request` endpoint every workflow candidate ultimately
hits, on a plain `Session`; `request_attention_async` serves
`notification_subscribers.py`, on an `AsyncSession`). `AttentionLogService`
is async-only, so the sync path re-implements the same dedup rule directly
against `AttentionLog` rather than depending on it — deliberately small
(one SELECT, one INSERT) and this docstring is the flag to keep both in
step if the dedup rule ever changes.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AttentionChannel,
    AttentionItemType,
    AttentionLevel,
    AttentionLog,
    AttentionResponse,
    Notification,
    Task,
    TaskPriority,
)
from app.repositories.attention_log import AttentionLogRepository
from app.services.attention_bundle import enqueue_async, enqueue_sync
from app.services.attention_levels import LEVEL_RANK as _LEVEL_RANK
from app.services.attention_log import AttentionLogService
from app.services.attention_reason_catalog import base_level_for, superseded_by
from app.services.availability import should_stay_quiet_async, should_stay_quiet_sync
from app.services.feedback_loop import apply_downgrade, dismiss_count_async, dismiss_count_sync
from app.services.notifications import NotificationService, create_notification_async
from app.services.user_preferences import (
    get_preferences_async,
    get_preferences_sync,
    is_gate_bypassed,
    is_reason_disabled,
)
from app.schemas import AttentionSurfaceCreate
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ASK/ACT are the two levels that ask for or take a decision from the user —
# an overdue-urgent task, not "you have four hours free". Those two are
# worth interrupting a meeting for; INFORM/RECOMMEND aren't, and go quiet
# instead when the user is busy (step 3). SILENT never reaches this check —
# it's already the quietest outcome.
_CRITICAL_LEVELS = {AttentionLevel.ASK, AttentionLevel.ACT}


def _escalate(level: AttentionLevel, at_least: AttentionLevel) -> AttentionLevel:
    """Raise `level` to `at_least` if `at_least` outranks it. Never lowers —
    importance only escalates a reason's baseline, it doesn't undercut it."""
    return at_least if _LEVEL_RANK[at_least] > _LEVEL_RANK[level] else level


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _task_overdue_days(task: Task, today: date) -> int:
    if not task.due_date:
        return 0
    due_day = task.due_date.date()
    if due_day >= today:
        return 0
    return (today - due_day).days


def _escalate_for_task(level: AttentionLevel, task: Task | None) -> AttentionLevel:
    """Step 1's item-specific half: a task's own priority/overdue standing
    can raise the reason's baseline level, never lower it. No task found
    (deleted between detection and delivery) just means no escalation —
    attention_log outliving its target is expected, not an error."""
    if task is None:
        return level
    overdue_days = _task_overdue_days(task, _today())
    if task.priority is TaskPriority.URGENT or overdue_days >= 5:
        return _escalate(level, AttentionLevel.ASK)
    if task.priority is TaskPriority.HIGH or overdue_days >= 2:
        return _escalate(level, AttentionLevel.RECOMMEND)
    return level


def _is_gated_candidate(
    item_type: AttentionItemType | None, item_id: UUID | None, reason_key: str | None
) -> bool:
    if item_type is not None and item_id is not None and reason_key is not None:
        return True
    if item_type is not None or item_id is not None or reason_key is not None:
        logger.warning(
            "request_attention got a partial candidate (item_type=%r, item_id=%r, "
            "reason_key=%r) — need all three to gate, falling back to pass-through",
            item_type, item_id, reason_key,
        )
    return False


def _supersession_window_start() -> datetime:
    """`surfaced_at` is a naive UTC column — compare in the same shape, the
    same convention attention_log.py's `_naive_utcnow` uses."""
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        hours=settings.ATTENTION_DEDUP_WINDOW_HOURS
    )


# ---------------------------------------------------------------------------
# Async path
# ---------------------------------------------------------------------------


async def _decide_level_async(
    session: AsyncSession, item_type: AttentionItemType, item_id: UUID, reason_key: str, user_id: UUID
) -> tuple[AttentionLevel, bool]:
    """Returns `(level, silenced_by_busy)`. The second value is what tells
    the caller whether a SILENT result should be queued for later (step 4)
    or just left silent — see module docstring.

    A user who turned `reason_key` off (`UserPreferences.disabled_reason_
    keys` — the redesigned 4.5/A2 follow-up) short-circuits everything
    below, including the escalation that would otherwise push an urgent
    task past the busy check: an explicit "don't tell me about this kind
    of thing" is an absolute off switch, not just a lower baseline.
    `silenced_by_busy=False` so it's recorded (attention_log's "silence is
    a decision too") but never queued for later — there is no "later" for
    a category the user turned off. The Feedback Loop's auto-downgrade
    (6.9, `apply_downgrade`) reaching SILENT gets the same treatment, for
    the same reason: repeated dismissal isn't a busy signal either."""
    prefs = await get_preferences_async(session, user_id)
    if is_reason_disabled(prefs, reason_key):
        return AttentionLevel.SILENT, False

    stronger = superseded_by(reason_key)
    if stronger:
        already = await AttentionLogRepository(session).find_last_spoken_any(
            user_id=user_id, item_id=item_id, reason_keys=stronger,
            since=_supersession_window_start(),
        )
        if already is not None:
            logger.info(
                "Attention superseded: %r for item %s already covered by %r",
                reason_key, item_id, already.reason_key,
            )
            # `silenced_by_busy=False`: there is no "later" worth queueing
            # for. The user has already been told about this item, in
            # stronger terms — replaying this one when they free up would
            # just be the duplicate arriving late.
            return AttentionLevel.SILENT, False

    level = base_level_for(reason_key)
    if item_type is AttentionItemType.TASK:
        task = await session.get(Task, item_id)
        level = _escalate_for_task(level, task)

    dismissals = await dismiss_count_async(session, user_id, reason_key)
    downgraded = apply_downgrade(level, dismissals)
    if downgraded is AttentionLevel.SILENT and level is not AttentionLevel.SILENT:
        return AttentionLevel.SILENT, False
    level = downgraded

    if level not in _CRITICAL_LEVELS and await should_stay_quiet_async(session, user_id):
        return AttentionLevel.SILENT, True
    return level, False


# ---------------------------------------------------------------------------
# Nhóm A của phép thử A/B — DESIGN 12.2
# ---------------------------------------------------------------------------


def _ungated_log_row(
    *, user_id: UUID, item_type: AttentionItemType, item_id: UUID, reason_key: str
) -> AttentionLog:
    """Hàng `attention_log` cho một lần nhắc **không qua Gate**.

    Ghi thẳng thay vì đi qua `record_surface`, và đó là điểm mấu chốt của
    phép thử: `record_surface` **có dedup**, mà dedup là một trong năm bước
    của Gate (12.2 liệt kê: dedup · im khi bận · quiet hours · gộp · chọn
    thời điểm). Cho nhóm A đi qua nó nghĩa là nhóm A vẫn được hưởng một
    phần năm giá trị đang đo, và hai con số ở 12.3 sẽ nói dối theo hướng
    làm Gate trông kém giá trị hơn thực tế.

    Vẫn ghi một hàng — không phải bỏ ghi — vì cả hai nhóm phải đọc số từ
    **cùng một bảng**. Nhóm A không có hàng thì nhóm A không có gì để so.
    """
    return AttentionLog(
        user_id=user_id,
        item_type=item_type,
        item_id=item_id,
        reason_key=reason_key,
        level=AttentionLevel.INFORM,
        channel=AttentionChannel.IN_APP,
        response=AttentionResponse.NO_RESPONSE,
    )


async def request_attention_async(
    db: AsyncSession,
    *,
    user_id: UUID,
    title: str,
    body: str = "",
    type: str = "system",
    content: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    item_type: AttentionItemType | None = None,
    item_id: UUID | None = None,
    reason_key: str | None = None,
) -> Notification | None:
    """Returns the created Notification, or `None` if the Gate decided not
    to surface anything (suppressed as a repeat, or silenced by importance
    + busy). `None` is a normal outcome, not a failure — see module
    docstring."""
    if not _is_gated_candidate(item_type, item_id, reason_key):
        return await create_notification_async(
            db, user_id=user_id, type=type, title=title, body=body,
            content=content, actions=actions, payload=payload,
        )

    # Nhóm A của phép thử A/B (DESIGN 12.2): "đến hạn → ping một lần".
    #
    # Đặt **trước** mọi bước của Gate, không phải bên trong: điều đang đo là
    # giá trị của cả năm bước cộng lại (dedup · im khi bận · quiet hours ·
    # gộp · chọn thời điểm), nên bỏ qua một phần rồi giữ phần còn lại sẽ
    # cho ra một con số không trả lời được câu hỏi nào.
    #
    # Vẫn ghi `attention_log` với `level=inform`: phép thử cần **cùng một
    # nguồn số liệu** cho cả hai nhóm — tỷ lệ dismiss và tỷ lệ làm trong
    # 24h (12.3) đều đọc từ bảng này. Bỏ ghi cho nhóm A nghĩa là nhóm A
    # không có số để so.
    if is_gate_bypassed(await get_preferences_async(db, user_id)):
        entry = _ungated_log_row(
            user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key
        )
        db.add(entry)
        await db.flush()
        return await create_notification_async(
            db, user_id=user_id, type=type, title=title, body=body,
            content=content, actions=actions, payload=payload,
            reason_key=reason_key, attention_level=AttentionLevel.INFORM,
            attention_log_id=entry.id,
        )

    level, silenced_by_busy = await _decide_level_async(db, item_type, item_id, reason_key, user_id)

    result = await AttentionLogService(db).record_surface(
        AttentionSurfaceCreate(
            item_type=item_type, item_id=item_id, reason_key=reason_key,
            level=level, channel=AttentionChannel.IN_APP,
        ),
        user_id=user_id,
    )
    if result.suppressed:
        return None
    if level is AttentionLevel.SILENT:
        if silenced_by_busy:
            await enqueue_async(
                db, user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key,
                title=title, body=body, payload=payload, actions=actions,
                attention_log_id=result.log.id if result.log else None,
            )
        return None

    return await create_notification_async(
        db, user_id=user_id, type=type, title=title, body=body,
        content=content, actions=actions, payload=payload,
        reason_key=reason_key, attention_level=level, attention_log_id=result.log.id,
    )


# ---------------------------------------------------------------------------
# Sync path
# ---------------------------------------------------------------------------


def _find_last_spoken_sync(
    session: Session, user_id: UUID, item_id: UUID, reason_key: str, since: datetime
) -> AttentionLog | None:
    """Sync twin of `AttentionLogRepository.find_last_spoken` — see module
    docstring for why this isn't just a call to the async service."""
    stmt = (
        select(AttentionLog)
        .where(
            AttentionLog.user_id == user_id,
            AttentionLog.item_id == item_id,
            AttentionLog.reason_key == reason_key,
            AttentionLog.surfaced_at >= since,
            AttentionLog.level != AttentionLevel.SILENT,
        )
        .order_by(AttentionLog.surfaced_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def _find_last_spoken_any_sync(
    session: Session, user_id: UUID, item_id: UUID, reason_keys: frozenset[str], since: datetime
) -> AttentionLog | None:
    """Sync twin of `AttentionLogRepository.find_last_spoken_any` — see
    module docstring for why this isn't just a call to the async service."""
    if not reason_keys:
        return None
    stmt = (
        select(AttentionLog)
        .where(
            AttentionLog.user_id == user_id,
            AttentionLog.item_id == item_id,
            AttentionLog.reason_key.in_(list(reason_keys)),
            AttentionLog.surfaced_at >= since,
            AttentionLog.level != AttentionLevel.SILENT,
        )
        .order_by(AttentionLog.surfaced_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def _record_surface_sync(
    session: Session,
    *,
    user_id: UUID,
    item_type: AttentionItemType,
    item_id: UUID,
    reason_key: str,
    level: AttentionLevel,
    dedup_window_hours: int,
) -> AttentionLog | None:
    """Sync twin of `AttentionLogService.record_surface`. Same two rules:
    dedup on (item_id, reason_key), and a silent decision is always written
    and never itself suppressed or suppressing."""
    is_silent = level is AttentionLevel.SILENT
    if not is_silent:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=dedup_window_hours)
        previous = _find_last_spoken_sync(session, user_id, item_id, reason_key, since)
        if previous is not None:
            return None

    entry = AttentionLog(
        user_id=user_id,
        item_type=item_type,
        item_id=item_id,
        reason_key=reason_key,
        level=level,
        channel=AttentionChannel.IN_APP,
        response=AttentionResponse.NO_RESPONSE,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def _decide_level_sync(
    session: Session, item_type: AttentionItemType, item_id: UUID, reason_key: str, user_id: UUID
) -> tuple[AttentionLevel, bool]:
    """Sync twin of `_decide_level_async` — see its docstring for the
    `silenced_by_busy` contract and the disabled-reason short-circuit."""
    prefs = get_preferences_sync(session, user_id)
    if is_reason_disabled(prefs, reason_key):
        return AttentionLevel.SILENT, False

    stronger = superseded_by(reason_key)
    if stronger and _find_last_spoken_any_sync(
        session, user_id, item_id, stronger, _supersession_window_start()
    ) is not None:
        return AttentionLevel.SILENT, False

    level = base_level_for(reason_key)
    if item_type is AttentionItemType.TASK:
        task = session.get(Task, item_id)
        level = _escalate_for_task(level, task)

    dismissals = dismiss_count_sync(session, user_id, reason_key)
    downgraded = apply_downgrade(level, dismissals)
    if downgraded is AttentionLevel.SILENT and level is not AttentionLevel.SILENT:
        return AttentionLevel.SILENT, False
    level = downgraded

    if level not in _CRITICAL_LEVELS and should_stay_quiet_sync(session, user_id):
        return AttentionLevel.SILENT, True
    return level, False


def request_attention_sync(
    db: Session,
    *,
    user_id: UUID,
    title: str,
    body: str = "",
    type: str = "system",
    content: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    item_type: AttentionItemType | None = None,
    item_id: UUID | None = None,
    reason_key: str | None = None,
) -> Notification | None:
    """Sync twin of `request_attention_async` — see its docstring for the
    return-value contract (`None` is a normal, silent-or-suppressed outcome)."""
    if not _is_gated_candidate(item_type, item_id, reason_key):
        return NotificationService(db).create(
            user_id=user_id, type=type, title=title, body=body,
            content=content, actions=actions, payload=payload,
        )

    # Nhóm A của phép thử A/B — bản sync. Phải có ở **cả hai** đường vào,
    # nếu không cùng một người dùng đi qua Gate hay không tuỳ vào predicate
    # nào phát ra lời nhắc (ReminderWorker chạy sync, StateEvaluator chạy
    # async), và phép thử đo một thứ trộn lẫn thay vì đo Gate.
    if is_gate_bypassed(get_preferences_sync(db, user_id)):
        entry = _ungated_log_row(
            user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return NotificationService(db).create(
            user_id=user_id, type=type, title=title, body=body,
            content=content, actions=actions, payload=payload,
            reason_key=reason_key, attention_level=AttentionLevel.INFORM,
            attention_log_id=entry.id,
        )

    level, silenced_by_busy = _decide_level_sync(db, item_type, item_id, reason_key, user_id)
    log_entry = _record_surface_sync(
        db,
        user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key,
        level=level, dedup_window_hours=settings.ATTENTION_DEDUP_WINDOW_HOURS,
    )
    if log_entry is None:
        return None
    if level is AttentionLevel.SILENT:
        if silenced_by_busy:
            enqueue_sync(
                db, user_id=user_id, item_type=item_type, item_id=item_id, reason_key=reason_key,
                title=title, body=body, payload=payload, actions=actions,
                attention_log_id=log_entry.id,
            )
        return None

    return NotificationService(db).create(
        user_id=user_id, type=type, title=title, body=body,
        content=content, actions=actions, payload=payload,
        reason_key=reason_key, attention_level=level, attention_log_id=log_entry.id,
    )
