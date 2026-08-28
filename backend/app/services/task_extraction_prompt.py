"""
The task half of the extraction prompt.

Appended to the memory extraction prompt that already runs — the same
trigger, the same LLM call, one extra section in the request. No per-turn
extraction and no separate job, because the marginal cost of asking a call
that is already happening for one more field is close to zero. Replaces the
former `app.services.commitment_extraction_prompt` (Commitment folded into
Task — see "Xoá bỏ Commitment, gộp vào Task").

The rows below appear as few-shot examples, ❌ rows included — showing the
model what *not* to return is what pushes precision up. The deterministic
validator in `task_extraction.py` then enforces the same rules again,
because a prompt is a request and not a guarantee.
"""

TASK_EXTRACTION_INSTRUCTIONS = """
=== TASKS (additional extraction task) ===

Find things the user has committed to doing. A task is a statement where
the speaker themselves undertook to do something specific.

TWO CONDITIONS. Both must hold. If even one is missing, skip it:

  1. YOU (the speaker) OWN IT — stated in the first person. A statement
     about what someone else will do ("John will send the API spec") is not
     the user's own task.
  2. STATED EXPLICITLY, with a CONCRETE ACTION — actually said, never
     inferred, never assumed from context, and specific enough to tick off.
     A general aspiration ("exercise more", "be better at X") is not
     concrete. Hedged ("maybe", "chắc", "probably") and conditional ("if",
     "nếu") statements do NOT count.

WHEN IN DOUBT, LEAVE IT OUT. A task you invent costs the user's trust in
this feature; a task you miss costs much less. Returning an empty list is a
good answer and is expected most of the time.

Examples (these are the rules, not illustrations):

  "Thứ 6 tôi gửi proposal cho John"           → YES. action "gửi proposal",
                                                 counterparty "John"
  "Tôi sẽ nộp báo cáo thuế cuối tháng"        → YES. action "nộp báo cáo
                                                 thuế", no counterparty —
                                                 that's fine, not every task
                                                 involves another person
  "John sẽ gửi API spec cho tôi tuần sau"     → NO. that's John's task, not
                                                 the user's — no first-person
                                                 owner
  "Tôi nên tập thể dục nhiều hơn"             → NO. no concrete action, no
                                                 deadline
  "Chắc tuần sau xong"                        → NO. "chắc" is a guess, not
                                                 explicit
  "Nếu kịp thì tôi làm luôn phần đó"          → NO. conditional, not a
                                                 commitment
  "Deadline dự án là 15/9"                    → NO. an event, nobody
                                                 committed to anything

`counterparty`, when there is one, is who the task is *for* or *about* —
"John" in the first example. Leave it empty when the task doesn't involve
anyone else.

Conversations mix Vietnamese and English, sometimes within one sentence
("thứ 6 tôi sẽ review PR đó"). Handle both. Write `expected_action` in the
language the user used.

Add a `tasks` key to your JSON response:

  "tasks": [
    {
      "counterparty": "John" or "",
      "expected_action": "gửi proposal",
      "deadline": "2026-09-11T00:00:00" or null,
      "source_quote": "the exact sentence from the conversation"
    }
  ]

`source_quote` must be copied verbatim from the conversation. It is checked
against the conditions after you answer, so a paraphrase that smooths over
a "chắc" or a "nếu" will simply be discarded. Use an empty list when there
are no tasks — that is the normal case.
"""


def append_task_instructions(user_content: str) -> str:
    """Add the task-extraction task to an already-built extraction request."""
    from app.services.memory_extraction_prompt import response_shape

    return (
        f"{user_content}\n\n{TASK_EXTRACTION_INSTRUCTIONS}\n"
        + response_shape(',\n  "tasks": [ ... as described above ... ]')
    )
