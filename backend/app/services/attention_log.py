"""
Attention Log service (Milestone 2.9).

Two rules carry this whole milestone, and both are easy to get backwards:

**Dedup is per (item_id, reason_key), never per item_id.** One task can
legitimately surface twice for different reasons — once because it's
overdue, once because it's marked high priority. Deduplicating on the item
alone would silently drop the second reason, and the user would never learn
the more important of the two.

**A silent decision is still a row.** `level = silent` means Cortex looked at
this item and chose not to speak. That row is what makes "why did Cortex say
nothing?" answerable, and it's what lets 6.9 measure whether the silence was
right.

Those two rules meet at one question the doc leaves open: does a `silent`
row suppress a later real surfacing? **No.** A silent row records that the
user was *not* told, so treating it as a prior surfacing would invert the
table's purpose — one quiet evaluation would gag Cortex for the whole
window. Silent rows are therefore always written, never suppressed, and
never suppress anything.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AttentionItemType,
    AttentionLevel,
    AttentionLog,
    AttentionResponse,
)
from app.repositories.attention_log import AttentionLogRepository
from app.schemas import (
    AttentionItemHistory,
    AttentionLogResponse,
    AttentionReasonSummary,
    AttentionSurfaceCreate,
    AttentionSurfaceResult,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _naive_utcnow() -> datetime:
    """`surfaced_at` is a naive UTC column (same convention as every other
    timestamp in this schema) — compare against it in the same shape."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AttentionLogService:
    def __init__(self, session: AsyncSession, dedup_window_hours: int | None = None) -> None:
        self.session = session
        self.repository = AttentionLogRepository(session)
        # Config, not a constant: 24h is a starting guess, and 6.9 will have
        # the data to argue for a different number. Overridable per instance
        # so tests (and later, per-reason tuning) don't need env juggling.
        self.dedup_window_hours = (
            dedup_window_hours
            if dedup_window_hours is not None
            else settings.ATTENTION_DEDUP_WINDOW_HOURS
        )

    @property
    def dedup_window(self) -> timedelta:
        return timedelta(hours=self.dedup_window_hours)

    async def was_recently_surfaced(
        self, user_id: UUID, item_id: UUID, reason_key: str
    ) -> AttentionLog | None:
        """The prior surfacing that would suppress this one, if any.

        Exposed separately from `record_surface` so the Attention Gate can
        ask "would this be a repeat?" *before* doing the work of composing a
        message.
        """
        return await self.repository.find_last_spoken(
            user_id=user_id,
            item_id=item_id,
            reason_key=reason_key,
            since=_naive_utcnow() - self.dedup_window,
        )

    async def record_surface(
        self, payload: AttentionSurfaceCreate, user_id: UUID
    ) -> AttentionSurfaceResult:
        """Record a surfacing decision, applying the dedup rule.

        A `silent` decision is always written — it never counts as having
        told the user, so it is neither suppressed nor suppressing.
        """
        is_silent = payload.level is AttentionLevel.SILENT

        if not is_silent:
            previous = await self.was_recently_surfaced(
                user_id=user_id, item_id=payload.item_id, reason_key=payload.reason_key
            )
            if previous is not None:
                logger.info(
                    "Attention suppressed by dedup",
                    extra={
                        "user_id": str(user_id),
                        "item_id": str(payload.item_id),
                        "reason_key": payload.reason_key,
                        "previous_surfaced_at": previous.surfaced_at.isoformat(),
                    },
                )
                return AttentionSurfaceResult(
                    suppressed=True,
                    reason=(
                        f"Already surfaced for '{payload.reason_key}' at "
                        f"{previous.surfaced_at.isoformat()} — inside the "
                        f"{self.dedup_window_hours}h dedup window"
                    ),
                    dedup_window_hours=self.dedup_window_hours,
                    log=None,
                )

        entry = AttentionLog(
            user_id=user_id,
            item_type=payload.item_type,
            item_id=payload.item_id,
            reason_key=payload.reason_key,
            level=payload.level,
            channel=payload.channel,
            response=AttentionResponse.NO_RESPONSE,
        )
        try:
            created = await self.repository.create(entry)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return AttentionSurfaceResult(
            suppressed=False,
            dedup_window_hours=self.dedup_window_hours,
            log=AttentionLogResponse.model_validate(created),
        )

    async def record_response(
        self, log_id: UUID, user_id: UUID, response: AttentionResponse
    ) -> AttentionLog | None:
        """Attach the user's reaction. Stamps `responded_at` server-side —
        the client doesn't get to decide when it answered."""
        entry = await self.repository.get_by_id_and_user(log_id, user_id)
        if entry is None:
            return None

        entry.response = response
        entry.responded_at = _naive_utcnow()
        try:
            await self.session.commit()
            await self.session.refresh(entry)
        except Exception:
            await self.session.rollback()
            raise
        return entry

    async def get_log(self, log_id: UUID, user_id: UUID) -> AttentionLog | None:
        return await self.repository.get_by_id_and_user(log_id, user_id)

    async def list_logs(
        self,
        user_id: UUID,
        item_type: AttentionItemType | None = None,
        reason_key: str | None = None,
        level: AttentionLevel | None = None,
        response: AttentionResponse | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AttentionLog]:
        rows = await self.repository.list_by_user(
            user_id,
            item_type=item_type,
            reason_key=reason_key,
            level=level,
            response=response,
            since=since,
            limit=limit,
        )
        return list(rows)

    async def get_item_history(self, user_id: UUID, item_id: UUID) -> AttentionItemHistory:
        """2.9 M2's question in one call: has this item been surfaced, for
        what reasons, how many times, and how did the user respond?

        Grouped by `reason_key` rather than flattened, because the reason is
        half the identity of a surfacing — "shown 4 times" is not a useful
        answer if two of those were a different reason.
        """
        rows = await self.repository.list_for_item(user_id, item_id)

        grouped: dict[str, list[AttentionLog]] = {}
        for row in rows:
            grouped.setdefault(row.reason_key, []).append(row)

        reasons: list[AttentionReasonSummary] = []
        for reason_key, entries in grouped.items():
            responses: dict[str, int] = {}
            for entry in entries:
                responses[entry.response.value] = responses.get(entry.response.value, 0) + 1
            reasons.append(
                AttentionReasonSummary(
                    reason_key=reason_key,
                    surface_count=len(entries),
                    silent_count=sum(1 for e in entries if e.level is AttentionLevel.SILENT),
                    first_surfaced_at=entries[0].surfaced_at,
                    last_surfaced_at=entries[-1].surfaced_at,
                    last_level=entries[-1].level,
                    responses=responses,
                )
            )
        reasons.sort(key=lambda r: r.last_surfaced_at, reverse=True)

        return AttentionItemHistory(
            item_id=item_id,
            surfaced=bool(rows),
            total_surfacings=len(rows),
            reasons=reasons,
        )

    def to_response(self, entry: AttentionLog) -> AttentionLogResponse:
        return AttentionLogResponse.model_validate(entry)
