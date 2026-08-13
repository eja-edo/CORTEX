"""
L0 task-suggestion signal scan.

Zero-token regex over every message, answering one narrow question: *might*
this conversation contain something the user needs to do? Nothing more. A
hit only schedules an extraction; the actual decision is made later by the
LLM plus the conditions in `app.services.task_extraction`. Replaces the
former `app.intents.commitment_signals` (Commitment folded into Task — see
"Xoá bỏ Commitment, gộp vào Task").

**A false positive here is free.** That inverts the usual bias in this
codebase, so it's worth being explicit about why. `app/intents/rule_detector.py`
is deliberately conservative and uses `re.match` — it fires *commands*, so a
wrong hit does something the user didn't ask for. This scanner fires nothing:
worst case, one conversation gets an LLM call it didn't need. What a miss
costs is much worse — a two-message conversation never reaches the
20-message threshold, so an unflagged task is lost permanently.

Hence the two differences from rule_detector:
  - `re.search`, not `re.match`: "ok, thứ 6 tôi gửi proposal nhé" carries the
    commitment in the middle of the sentence.
  - Permissive patterns. Precision is the *validator's* job, not this one's.

Real conversations mix Vietnamese and English, often inside one sentence
("thứ 6 tôi sẽ review PR đó"), so both languages are matched by the same
pass rather than by language detection.

Only first-person signals — unlike the removed `commitment_signals.py`,
there is no "someone else promised me" half here: that's not the user's own
work, and Task has no place to put it.
"""

import re
from dataclasses import dataclass

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TaskSignal:
    """A hit, kept with the pattern that produced it so an unexpected volume
    of flushes can be traced back to a specific pattern."""
    pattern_name: str
    matched_text: str


# Grouped by what they indicate, so a pattern that turns out to be too noisy
# in production can be removed without touching the rest.
_SIGNAL_PATTERNS: list[tuple[str, str]] = [
    # ── First-person promises ────────────────────────────────────────────
    ("vi.i_will", r"\b(?:tôi|mình|em|tớ)\s+(?:sẽ|se)\b"),
    ("vi.i_send", r"\b(?:sẽ|se)\s+(?:gửi|gui|làm|lam|nộp|nop|xong|hoàn thành|review|check|fix|deploy|call|ping)\b"),
    ("vi.promise", r"\b(?:hứa|hua|cam kết|cam ket|chốt|chot)\b"),
    ("en.i_will", r"\bi(?:'ll| will| shall)\b"),
    ("en.promise", r"\b(?:i promise|i'll make sure|will get (?:it|that) (?:done|to you))\b"),
    ("en.send_you", r"\b(?:send|deliver|share|submit|hand) (?:it |them |you )?(?:over |back )?(?:to you|by|before)\b"),

    # Broad future/intent markers. Deliberately unrestricted: enumerating
    # verbs meant "sẽ merge" and "sẽ approve" fell through, and a miss on a
    # two-message conversation is permanent. An extra flush on a
    # conversation that turns out to contain nothing costs one LLM call;
    # the validator is what protects precision.
    ("vi.will_any", r"\b(?:sẽ|se)\s+\w+"),
    ("en.will_any", r"\b(?:will|gonna|going to)\s+\w+"),
    ("vi.first_person_action", r"\b(?:tôi|mình|em|tớ)\s+(?:\w+\s+)?(?:gửi|gui|nộp|nop|làm|lam|viết|viet|review|fix|deploy|merge|approve|check|gọi|goi|book|chuẩn bị|chuan bi)\b"),

    # ── Deadline language ────────────────────────────────────────────────
    ("vi.before_day", r"\b(?:trước|truoc)\s+(?:thứ|thu|ngày|ngay|cuối|cuoi)\b"),
    ("vi.weekday", r"\b(?:thứ|thu)\s*[2-7]\b|\bchủ nhật\b|\bcn\b"),
    ("vi.deadline", r"\b(?:deadline|hạn chót|han chot|hạn cuối|han cuoi|đến hạn)\b"),
    ("vi.fix_date", r"\b(?:chốt ngày|chot ngay|hẹn|hen)\b"),
    ("en.by_day", r"\bby (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next week|eod|cob)\b"),
    ("en.deadline", r"\bdeadline\b"),
    ("en.before", r"\bbefore (?:friday|monday|tuesday|wednesday|thursday|the end of)\b"),
]

_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in _SIGNAL_PATTERNS]


def scan_message(text: str | None) -> list[TaskSignal]:
    """Every task-ish pattern in one message. Empty list = no signal."""
    if not text:
        return []
    return [
        TaskSignal(pattern_name=name, matched_text=match.group(0))
        for name, compiled in _COMPILED
        if (match := compiled.search(text))
    ]


def has_task_signal(text: str | None) -> bool:
    """True if this message is worth an extraction pass.

    Cheap enough to call on every message — no allocation beyond the regex
    scan, and it short-circuits on the first hit.
    """
    if not text:
        return False
    return any(compiled.search(text) for _, compiled in _COMPILED)


def scan_messages(texts: list[str | None]) -> list[TaskSignal]:
    """Signals across a batch — used by the idle flush to decide whether a
    conversation is worth an early LLM call."""
    signals: list[TaskSignal] = []
    for text in texts:
        signals.extend(scan_message(text))
    return signals
