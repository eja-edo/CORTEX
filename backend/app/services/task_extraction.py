"""
Task extraction from conversation.

Replaces the former `app.services.commitment_extraction` (Commitment folded
into Task — see "Xoá bỏ Commitment, gộp vào Task"). The riskiest thing this
pipeline does, and the reason is the same asymmetry the removed module
stated: **a wrong suggestion costs far more than a missed one.** A user
asked to confirm a task they never actually meant to do loses trust in the
feature immediately; a missed one is a gap they may not even notice. Every
judgement call here goes the same way — when in doubt, drop it.

Two conditions, all required (one fewer than `Commitment` had — see below):

  1. **the speaker owns it** — stated in the first person, never a
     third-person statement about someone else's plans;
  2. a **concrete action**, stated **explicitly** — never inferred, never a
     vague intention.

`Commitment` additionally required a *named counterparty* (condition 1 in
its own docstring) — every candidate needed someone to attribute the
promise to. That requirement is dropped here on purpose: a task is "what I
need to do", and plenty of real tasks ("tôi sẽ nộp báo cáo thuế") name no
one at all. `counterparty`, when the LLM does extract one, still folds into
the task's title for context ("nộp proposal (John)") — it just no longer
gates whether the candidate survives.

The LLM proposes; this module disposes. The validator below re-checks the
conditions deterministically and drops anything that fails, because a
prompt is a request and not a guarantee: the same prompt drifts with model
versions, and precision that depends only on wording can't be tested in CI.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskStatus
from app.repositories.tasks import TaskRepository
from app.schemas import TaskCreate
from app.services.tasks import TaskService, content_fingerprint
from app.utils.logger import get_logger

logger = get_logger(__name__)

# How long an unanswered candidate waits before it stops asking.
CANDIDATE_EXPIRY_DAYS = 7

MIN_ACTION_WORDS = 2
MAX_ACTION_LENGTH = 2000
MAX_TITLE_LENGTH = 255


@dataclass(frozen=True)
class RejectedCandidate:
    """A proposal that failed validation, kept for the logs.

    Recording *why* something was dropped is what makes a precision
    regression debuggable — otherwise a prompt change that starts emitting
    junk looks identical to a prompt change that emits nothing.
    """
    raw: dict
    rule: str
    detail: str


# ── Not stated explicitly ────────────────────────────────────────────────
#
# Hedging. "Chắc tuần sau xong" is a guess, and a guess recorded as a task
# is exactly the failure that makes users turn the feature off.
_HEDGE_PATTERNS = [
    r"\bchắc\b", r"\bchac\b", r"\bcó lẽ\b", r"\bco le\b", r"\bhình như\b",
    r"\bchắc là\b", r"\bvalid\b(?!\w)", r"\bmaybe\b", r"\bprobably\b",
    r"\bperhaps\b", r"\bi think\b", r"\bmight\b", r"\bpossibly\b",
    r"\bhopefully\b", r"\bcó thể\b", r"\bco the\b", r"\bkhả năng\b",
]

# Conditionals. "Nếu kịp thì tôi làm luôn phần đó" is contingent, and a
# contingent statement isn't a task yet.
_CONDITIONAL_PATTERNS = [
    r"\bnếu\b", r"\bneu\b", r"\btùy\b", r"\btuy thuộc\b", r"\bmiễn là\b",
    r"\bif\b", r"\bin case\b", r"\bdepending on\b", r"\bas long as\b",
    r"\bshould i\b", r"\bunless\b",
]

# Intentions with no concrete action. "Tôi nên tập thể dục nhiều hơn" names
# no deliverable and no deadline.
_VAGUE_INTENT_PATTERNS = [
    r"\bnên\b", r"\bnen\b", r"\bmuốn\b", r"\bmuon\b", r"\bcố gắng\b",
    r"\bhy vọng\b", r"\bdự định\b", r"\bshould\b", r"\bwant to\b",
    r"\bi'd like to\b", r"\btry to\b", r"\bhope to\b", r"\bplan to\b",
    r"\bthinking about\b",
]

# An event is not a task. "Deadline dự án là 15/9" states a fact about the
# world; nobody undertook anything.
_EVENT_NOT_PROMISE_PATTERNS = [
    r"^\s*deadline\b[^.]*\b(?:là|is|:)\b",
    r"^\s*(?:the )?(?:project|sprint|release|launch)\s+deadline\b",
    r"^\s*hạn (?:chót|cuối)\s+(?:của|dự án|project)\b",
    r"^\s*(?:cuộc họp|meeting|event)\s+(?:là|lúc|at|is)\b",
]

_COMPILED_HEDGE = [re.compile(p, re.IGNORECASE) for p in _HEDGE_PATTERNS]
_COMPILED_CONDITIONAL = [re.compile(p, re.IGNORECASE) for p in _CONDITIONAL_PATTERNS]
_COMPILED_VAGUE = [re.compile(p, re.IGNORECASE) for p in _VAGUE_INTENT_PATTERNS]
_COMPILED_EVENT = [re.compile(p, re.IGNORECASE) for p in _EVENT_NOT_PROMISE_PATTERNS]

# Counterparty placeholders the model reaches for when it doesn't actually
# know who is involved. Used only to keep junk out of the title now — see
# the module docstring for why an unnamed counterparty no longer rejects
# the candidate outright.
_UNNAMED_COUNTERPARTIES = {
    "", "someone", "somebody", "unknown", "n/a", "na", "none", "null",
    "ai đó", "ai do", "người khác", "nguoi khac", "khách hàng", "team",
    "everyone", "họ", "ho", "they", "the team", "others",
}

# A concrete action needs a verb. Without one there's nothing to do.
_ACTION_VERB_PATTERNS = [
    r"\b(?:gửi|gui|làm|lam|nộp|nop|viết|viet|review|check|fix|deploy|gọi|goi|"
    r"trả lời|tra loi|hoàn thành|hoan thanh|chuẩn bị|chuan bi|đặt|dat|book|"
    r"chốt|chot|ký|ky|thanh toán|thanh toan|cập nhật|cap nhat|share|họp|hop)\b",
    r"\b(?:send|deliver|submit|write|review|check|fix|deploy|call|reply|"
    r"finish|complete|prepare|book|sign|pay|update|share|ship|merge|draft)\b",
]
_COMPILED_ACTION_VERBS = [re.compile(p, re.IGNORECASE) for p in _ACTION_VERB_PATTERNS]

# First-person markers. The speaker has to actually be the one doing this —
# a third-person statement about someone else's plans is not the user's task.
_FIRST_PERSON_PATTERNS = [
    r"\b(?:tôi|toi|mình|minh|em|tớ|to)\b",
    r"\b(?:i|i'll|i'm|we|we'll|my|me)\b",
]
_COMPILED_FIRST_PERSON = [re.compile(p, re.IGNORECASE) for p in _FIRST_PERSON_PATTERNS]


def _matches_any(compiled: list[re.Pattern], text: str) -> str | None:
    for pattern in compiled:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def validate_candidate(raw: dict) -> tuple[TaskCreate | None, RejectedCandidate | None]:
    """Apply the extraction conditions to one LLM proposal.

    Returns `(payload, None)` when it survives, `(None, rejection)` when it
    doesn't. Never raises: a malformed proposal is a rejection, not an
    error, because one bad item must not discard the whole extraction.
    """
    counterparty = (raw.get("counterparty") or "").strip()
    action = (raw.get("expected_action") or "").strip()
    quote = (raw.get("source_quote") or "").strip()

    # The quote is what the checks below are actually tested against — the
    # model's paraphrase can smooth over a hedge that the user really said.
    # No quote means nothing to verify, so it fails by default.
    if not quote:
        return None, RejectedCandidate(raw, "no_source_quote", "no verbatim quote to verify against")

    # ── Is this a task at all? ───────────────────────────────────────────
    #
    # Checked first, and against the quote, so the rejection reason names the
    # most specific reason it failed. Rule attribution is what makes a
    # precision regression debuggable later — "rejected as an event" and
    # "rejected for having no owner" point at very different prompt bugs.
    event_hit = _matches_any(_COMPILED_EVENT, quote)
    if event_hit:
        return None, RejectedCandidate(raw, "event_not_promise", f"matched {event_hit!r}")

    vague_hit = _matches_any(_COMPILED_VAGUE, quote)
    if vague_hit:
        return None, RejectedCandidate(raw, "vague_intent", f"matched {vague_hit!r}")

    # ── Explicit, not hedged and not conditional ─────────────────────────
    hedge_hit = _matches_any(_COMPILED_HEDGE, quote)
    if hedge_hit:
        return None, RejectedCandidate(raw, "hedged", f"matched {hedge_hit!r}")

    conditional_hit = _matches_any(_COMPILED_CONDITIONAL, quote)
    if conditional_hit:
        return None, RejectedCandidate(raw, "conditional", f"matched {conditional_hit!r}")

    # ── The speaker owns it ───────────────────────────────────────────────
    if not _matches_any(_COMPILED_FIRST_PERSON, quote):
        return None, RejectedCandidate(
            raw, "no_first_person_owner", f"quote has no first-person speaker: {quote!r}"
        )

    # ── A concrete action ─────────────────────────────────────────────────
    if not action or len(action.split()) < MIN_ACTION_WORDS:
        return None, RejectedCandidate(raw, "action_too_vague", f"action={action!r}")
    if len(action) > MAX_ACTION_LENGTH:
        return None, RejectedCandidate(raw, "action_too_long", f"{len(action)} chars")
    if not _matches_any(_COMPILED_ACTION_VERBS, action):
        return None, RejectedCandidate(raw, "no_action_verb", f"action={action!r}")

    deadline = _parse_deadline(raw.get("deadline"))

    named_counterparty = (
        counterparty if counterparty.lower() not in _UNNAMED_COUNTERPARTIES else ""
    )
    title = f"{action} ({named_counterparty})" if named_counterparty else action

    return TaskCreate(
        title=title[:MAX_TITLE_LENGTH],
        # Everything from extraction is a candidate. It becomes real work
        # only when the user confirms it.
        status=TaskStatus.PENDING_CONFIRM,
        # Kept as parsed rather than truncated to a bare day: `due_date`
        # accepts a time now, and an extracted deadline occasionally has one
        # ("thứ 6 lúc 15h"). Most extractions have no time, so this still
        # lands at midnight the same as before.
        due_date=deadline,
    ), None


def _parse_deadline(value) -> datetime | None:
    """Deadlines are optional and never guessed — an unparseable one is
    dropped rather than approximated onto today."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.info(f"Ignoring unparseable task deadline: {value!r}")
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


class TaskCandidateService:
    """Turns validated proposals into `pending_confirm` tasks."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TaskRepository(session)
        self.tasks = TaskService(session)

    async def store_candidates(
        self,
        raw_candidates: list[dict],
        user_id: UUID,
        conversation_id: UUID | None = None,
        message_id: UUID | None = None,
    ) -> dict:
        """Validate, de-duplicate, and store.

        Returns a summary rather than the rows: the caller is the memory
        extraction pipeline, which logs the outcome and moves on.
        """
        created: list[UUID] = []
        rejected: list[RejectedCandidate] = []
        skipped_duplicate = 0
        skipped_previously_rejected = 0

        for raw in raw_candidates or []:
            if not isinstance(raw, dict):
                rejected.append(RejectedCandidate({"raw": str(raw)}, "not_an_object", ""))
                continue

            payload, rejection = validate_candidate(raw)
            if payload is None:
                rejected.append(rejection)
                continue

            # Never propose something the user already turned down. Without
            # this the same suggestion resurfaces after every extraction —
            # a different flavour of notification fatigue, and the fastest
            # way to make someone disable the feature.
            previously_rejected = await self.repository.find_rejected_with_content(
                user_id=user_id, title=payload.title
            )
            if previously_rejected is not None:
                skipped_previously_rejected += 1
                logger.info(
                    "Skipping candidate the user already rejected",
                    extra={
                        "fingerprint": content_fingerprint(payload.title),
                        "rejected_task_id": str(previously_rejected.id),
                    },
                )
                continue

            if await self._already_open(user_id, payload.title):
                skipped_duplicate += 1
                continue

            payload.source_conversation_id = conversation_id
            payload.source_message_id = message_id
            task = await self.tasks.create_task(payload, user_id)
            created.append(task.id)

        for rejection in rejected:
            logger.info(
                f"Task candidate rejected by {rejection.rule}: {rejection.detail}",
                extra={"rule": rejection.rule},
            )

        return {
            "created": [str(tid) for tid in created],
            "created_count": len(created),
            "rejected_count": len(rejected),
            "rejected_rules": [r.rule for r in rejected],
            "skipped_duplicate": skipped_duplicate,
            "skipped_previously_rejected": skipped_previously_rejected,
        }

    async def _already_open(self, user_id: UUID, title: str) -> bool:
        """Same suggestion already pending or todo — asking twice is asking
        twice, regardless of which extraction pass produced it."""
        existing = await self.repository.list_by_user(user_id)
        target = title.strip().lower()
        return any(
            t.title.strip().lower() == target
            and t.status in (TaskStatus.PENDING_CONFIRM, TaskStatus.TODO)
            for t in existing
        )

    async def expire_stale_candidates(self, user_id: UUID | None = None) -> int:
        """Retire candidates nobody answered within CANDIDATE_EXPIRY_DAYS.

        Recorded as `cancelled`, the same terminal state a task reaches from
        anywhere else — reusing it rather than inventing a sixth status for
        "expired" specifically, mirroring the reasoning
        `Commitment.expire_stale_candidates` used.
        """
        from sqlalchemy import select

        from app.models import Task

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - _expiry_delta()

        stmt = select(Task).where(
            Task.status == TaskStatus.PENDING_CONFIRM,
            Task.created_at < cutoff,
        )
        if user_id is not None:
            stmt = stmt.where(Task.user_id == user_id)

        stale = (await self.session.execute(stmt)).scalars().all()
        for task in stale:
            task.status = TaskStatus.CANCELLED
            logger.info(
                f"Candidate expired after {CANDIDATE_EXPIRY_DAYS} days unanswered",
                extra={"task_id": str(task.id)},
            )

        if stale:
            await self.session.commit()
        return len(stale)


def _expiry_delta():
    from datetime import timedelta

    return timedelta(days=CANDIDATE_EXPIRY_DAYS)
