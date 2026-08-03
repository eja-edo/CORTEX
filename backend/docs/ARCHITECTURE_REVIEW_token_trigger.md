# Architecture Review — Token-Based Conversation Summary Trigger

## 1 Review Summary

The previous proposal is directionally correct but unnecessarily complex.

It introduces a new accumulated counter (`tokens_since_last_summary`) that
duplicates state already derivable from existing fields. The same goal can be
achieved with zero new columns, fewer code paths, and better consistency
guarantees.

Three specific issues in the previous proposal:

1. **Unnecessary new column** — `tokens_since_last_summary` duplicates
   information already available via `SUM(AgentMessage.token_count)` filtered by
   `AgentConversation.last_extracted_at`. The existing column is already the
   authoritative pointer for incremental extraction.

2. **Missing collapse handling** — `save_message()` has a same-role collapse
   path that mutates `content` on an existing row (line 181) without
   recalculating `token_count`. Any proposal that populates `token_count` at
   save time must also update it on collapse.

3. **Duplicated configuration** — The proposal hard-codes `TOKEN_THRESHOLD =
   20000` on `ConversationSummarizer`, but `SUMMARY_TRIGGER_TOKEN_COUNT` already
   exists in `config.py:153` (default 8000). Reuse it.

The following sections justify each recommendation with code evidence.

---

## 2 Single Source of Truth

### Option A — SUM(token_count) with last_extracted_at pointer

The threshold check becomes:

```
SELECT COALESCE(SUM(token_count), 0)
FROM agent_messages
WHERE conversation_id = :cid
  AND created_at > :last_extracted_at
```

If `last_extracted_at IS NULL` (first summary), sum all messages.

### Option B — Incremental counter (previous proposal)

Add `tokens_since_last_summary` to `AgentConversation`, increment atomically on
each `save_message()`, reset on successful summary.

### Comparison

| Criterion | Option A (SUM) | Option B (counter) |
|---|---|---|
| **Correctness** | Uses `last_extracted_at` — the same pointer `extract_and_store` uses for incremental message selection. Perfect alignment. | Independent counter must be manually reset. Divergence possible if reset fails. |
| **Consistency** | Single authoritative pointer. Cannot get out of sync. | Two independent pointers (`last_extracted_at` + counter). Must be kept in sync. |
| **Crash recovery** | `last_extracted_at` is the last committed extraction. SUM recomputes correctly on restart. Zero state loss. | Counter survives crash at committed value. But if summary committed and reset not, counter over-counts permanently. |
| **Transaction safety** | `extract_and_store` updates `last_extracted_at` in the same transaction as `conv.summary` (line 155). SUM is naturally transaction-consistent. | Reset must happen in the same transaction. Extra mutation on `AgentConversation`. |
| **Debugging** | `SELECT SUM(token_count) WHERE created_at > last_extracted_at` gives exact current state. Fully introspectable. | Opaque integer. To verify, must query messages anyway. |
| **Maintenance** | Zero new columns. Zero reset logic. Less code. | One new column. Reset logic. Migration. |
| **Complexity** | Populate `token_count` on save + single SUM query in trigger. | Populate `token_count` on save + increment at call sites + reset on summary + migration. |
| **Performance** | Covered in Section 3. | O(1) per message. |
| **Retry behaviour** | Same query after retry. `last_extracted_at` unchanged until success. Naturally correct. | Counter not reset on failure. Same as SUM behaviour. But if reset is missed, counter stays wrong. |

### Recommendation

**Option A** — use `SUM(token_count)` with `last_extracted_at`.

`last_extracted_at` already exists, already drives the incremental extraction
window, and is already updated atomically with `conv.summary`. Adding a separate
counter duplicates both the state and the reset logic. The only real difference
is one `SELECT SUM(...)` query per trigger check — which is trivially fast
(Section 3).

---

## 3 Performance Analysis

### Query cost

```sql
SELECT COALESCE(SUM(token_count), 0)
FROM agent_messages
WHERE conversation_id = '...'
  AND created_at > '2026-07-01 12:00:00';
```

### Index support

The existing index `ix_agent_messages_conversation_created`
(`(conversation_id, created_at)`, `models.py:609`) covers the WHERE clause
exactly. PostgreSQL will index-narrow to the conversation's rows, then seq-scan
only those rows.

### Row count per summary

- Threshold: ~20,000 tokens (configurable via `SUMMARY_TRIGGER_TOKEN_COUNT`)
- Average message tokens (estimate): ~50-200 for short user messages, ~500-2000
  for assistant replies, up to ~1143 for tool outputs (4000 chars at 3.5
  chars/token)
- Conservative estimate: ~50 tokens per message average → ~400 messages between
  summaries
- Tool-heavy worst case: ~2000 tokens per message → ~10 messages between
  summaries

### Absolute cost

A sequential scan of 400 integer rows in an index-filtered heap is **sub-millisecond**.
PostgreSQL returns this faster than Python can format a log line.

### Verdict

The SUM query is free in the context of a chat request that already makes one or
more LLM calls (each taking seconds). An incremental counter provides zero
measurable benefit. Do not optimize what is not a bottleneck.

---

## 4 Tool Message Policy

All message types should contribute their **full token count** toward the trigger.

### Why each type matters

| Role | Contribute? | Rationale |
|---|---|---|
| `user` | Yes | Core new information from the user |
| `assistant` | Yes | Model reasoning, replies, tool-call blocks |
| `tool` (results) | Yes | The extraction LLM sees tool outputs (truncated to 25K chars in `memory_extraction_service.py:55`) — they are part of the content being summarized |
| `tool` (name/input) | Yes | Included in what the extraction LLM processes |

### Why NOT to cap or exclude

- The extraction pipeline (`_build_conversation_text` at
  `memory_extraction_service.py:46-63`) includes ALL message types in the
  conversation transcript it sends to the LLM. If a message type contributes to
  the extraction input, it should contribute to the trigger.
- The 20,000 token threshold at ~7143 tokens per large tool output means ~3
  large tool messages could trigger a summary. This is **correct** — three
  large tool outputs represent substantial new information.
- The original problem was that tool messages inflate **message count** (each
  tool call adds +1 to `message_count`). A token-based trigger inherently fixes
  this: tool outputs are counted by their actual content size, not by quantity.

### Collapse handling (critical fix)

The collapse path in `save_message()` (`conversation_store.py:167-185`) mutates
`content` on an existing row without recalculating `token_count`. When
`token_count` is populated, the collapse path must also update it:

```python
last_msg.content = normalized_content
last_msg.token_count = estimate_message_tokens(  # ADD
    role=normalized_role, content=normalized_content
)
last_msg.context = context
last_msg.created_at = datetime.utcnow()
```

This only applies to `user` and `assistant` roles (the collapse guard at line
158), so no tool-specific handling is needed.

---

## 5 Configuration Review

`SUMMARY_TRIGGER_TOKEN_COUNT` already exists in `config.py:153`:

```python
SUMMARY_TRIGGER_TOKEN_COUNT: int = int(
    os.getenv("SUMMARY_TRIGGER_TOKEN_COUNT", "8000")
)
```

This setting was added in a previous task but is currently **dead code** — the
repo-wide grep confirms it has no readers. The previous proposal's
`TOKEN_THRESHOLD = 20000` constant duplicates this.

### Recommendation

1. Change the default from `8000` to `20000` in `config.py`.
2. Read `settings.SUMMARY_TRIGGER_TOKEN_COUNT` in `ConversationSummarizer` or
   `MemoryTriggerService`.
3. Remove the hard-coded class constant.
4. Keep `MESSAGE_THRESHOLD` on the class as a fallback for backward
   compatibility, or remove it entirely (no external code reads it).

This ensures the threshold is configurable without a code change, consistent
with the rest of the application's settings pattern.

---

## 6 Encapsulation Review

Token counting must live inside `ConversationStore.save_message()`.

### Why save_message is the right place

- `save_message()` already accepts `token_count` as an optional parameter (line
  149).
- All seven call sites pass `None` for `token_count` (verified by grep).
- `save_message()` already has access to all fields needed for estimation:
  `role`, `content`, `tool_name`, `tool_output`.
- The collapse path (lines 167-185) already mutates the row — adding
  `token_count` recalculation there is a one-line change in the same function.
- No caller needs to know about token counting. No duplicated logic across seven
  call sites.

### What save_message should do

```python
if token_count is None:
    token_count = estimate_message_tokens(
        role=normalized_role,
        content=normalized_content,
        tool_name=tool_name,
        tool_output=tool_output,
    )
```

And in the collapse branch (after line 181):

```python
if token_count is None:
    token_count = estimate_message_tokens(
        role=normalized_role,
        content=normalized_content,
    )
last_msg.token_count = token_count
```

### What save_message should NOT do

- Do NOT increment or reset `tokens_since_last_summary` (Option A eliminates
  this field entirely).
- Do NOT call the trigger — that remains in `MemoryTriggerService.maybe_trigger`
  at the end of the request.
- Do NOT update `last_extracted_at` — that remains in `extract_and_store`.

### Trigger location

`MemoryTriggerService.maybe_trigger` remains at its current call sites
(`agent_service.py:209, 480`). The check changes from:

```python
if conv.message_count < threshold or conv.message_count % threshold >= 2:
    return
```

to:

```python
tokens_stmt = select(func.coalesce(func.sum(AgentMessage.token_count), 0)).where(
    AgentMessage.conversation_id == conv.id,
    AgentMessage.created_at > conv.last_extracted_at,
)
token_sum = await self.db.scalar(tokens_stmt)
if token_sum < self.TOKEN_THRESHOLD:
    return
```

The advisory lock logic stays unchanged.

---

## 7 Updated Implementation Plan

### Files to change

| # | File | Change |
|---|---|---|
| 1 | `backend/app/config.py` | Change `SUMMARY_TRIGGER_TOKEN_COUNT` default from `8000` to `20000` |
| 2 | `backend/app/ai/agents/conversation_store.py` | Add `token_count` auto-calculation in `save_message()` (both insert path and collapse path) |
| 3 | `backend/app/ai/agents/memory_trigger_service.py` | Replace message-count modulo check with `SUM(token_count)` query using `last_extracted_at` pointer |
| 4 | `backend/app/ai/agents/conversation_summarizer.py` | Read `SUMMARY_TRIGGER_TOKEN_COUNT` from settings instead of hard-coded `MESSAGE_THRESHOLD` |

### Files NOT changed

- `backend/app/models.py` — no new column needed. `AgentMessage.token_count`
  already exists. `AgentConversation.last_extracted_at` already exists.
- `backend/app/ai/agents/agent_service.py` — no caller changes needed. Token
  counting is encapsulated in `save_message()`.
- `backend/app/services/memory_extraction_service.py` — extraction pipeline
  unchanged. `last_extracted_at` is already updated here.
- `backend/alembic/` — no migration needed. All columns already exist.

### No migration required

Both `AgentMessage.token_count` and `AgentConversation.last_extracted_at`
already exist in the schema. The only behavioural change is that
`token_count` is now populated instead of remaining `NULL`.
