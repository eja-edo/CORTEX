# Conversation Summary System

> Revision date: 2026-07-30  
> Scope: Incremental summary extraction, hybrid trigger, weighted token accounting

---

## Overview

The Conversation Summary is the **Episodic Summary** stored in `agent_conversations.summary` — a single text field, overwritten each extraction cycle, providing the LLM with a compressed history of past conversation turns. It is produced by the same LLM extraction call that produces semantic memories.

### Why a separate document?

The summary system was refactored from a timestamp-based cursor (`last_extracted_at`) to a **stable message-id cursor** (`last_summary_message_id UUID → agent_messages.id`) and from a modulo-based trigger to a **hybrid message/token threshold**. This document covers the summary-specific architecture; the broader memory system is documented in `memory-architecture.md`.

---

## Architecture

### Files

| File | Role |
|---|---|
| `app/ai/agents/memory_trigger_service.py` | Trigger guard: reads fresh counters, checks hybrid threshold, acquires advisory lock, calls summarizer |
| `app/ai/agents/conversation_summarizer.py` | Summarizer wrapper: threshold constants, calls `extract_and_store()`, provides `get_conversation_context()` for prompt injection |
| `app/services/memory_extraction_service.py` | Extraction pipeline: fetch new messages via cursor, call extraction LLM, store episodic + semantic, reset summary counters |
| `app/ai/agents/conversation_store.py` | DB operations: `save_message()` auto-increments counters, `reset_summary_counters()`, `get_messages_since()`, `increment_message_count()` |
| `app/ai/agents/agent_service.py` | Orchestrator: calls `maybe_trigger()` after final message save, before `db.commit()` |

---

## Cursor Design: `last_summary_message_id`

The extraction cursor is a **stable UUID** pointing to the last `agent_messages.id` that was included in the latest summary.

### Rationale

The old `last_extracted_at` timestamp cursor had two issues:

1. **Collapse-overwrite**: `save_message()` overwrites `created_at` when collapsing consecutive same-role messages (`conversation_store.py:183`), potentially shifting a summarized message's timestamp forward and causing it to be re-processed
2. **Microsecond ambiguity**: Two messages can share the same `created_at` microsecond, causing the `>` filter to miss one

The message-id cursor resolves both:
- The UUID is immutable (set at INSERT, never overwritten)
- It is resolved to `created_at` at fetch time, providing a stable boundary

### Resolution at fetch time

```python
# In extract_and_store():
cursor_ts = None
if conv.last_summary_message_id:
    last_msg = await db.get(AgentMessage, conv.last_summary_message_id)
    if last_msg:
        cursor_ts = last_msg.created_at

# Fetch messages after the cursor
stmt = select(AgentMessage).where(
    AgentMessage.conversation_id == conv.id,
    AgentMessage.created_at > cursor_ts,
).order_by(AgentMessage.created_at)
```

### Reset on success

After a successful extraction, `ConversationStore.reset_summary_counters()` is called:

```python
async def reset_summary_counters(self, conv_id: UUID, last_message_id: UUID) -> None:
    stmt = (
        update(AgentConversation)
        .where(AgentConversation.id == conv_id)
        .values(
            last_summary_message_id=last_message_id,
            messages_since_last_summary=0,
            tokens_since_last_summary=0,
        )
    )
    await self.db.execute(stmt)
```

---

## Weighted Token Accounting

### Problem

Tool messages carry tokens in `tool_input` and `tool_output` that dominate the per-message count (large JSON blobs). Using raw `estimate_message_tokens()` would make the token threshold trigger prematurely on single large tool results.

### Solution: Weighted tool token policy

**`estimate_weighted_message_tokens()`** in `app/utils/tokens.py`:

```python
TOOL_TOKEN_WEIGHT = 0.25
TOOL_TOKEN_CAP = 800

def estimate_weighted_message_tokens(
    role: str, content: str | None = None,
    tool_name: str | None = None,
    tool_output: dict | None = None,
) -> int:
    raw = estimate_message_tokens(role, content, tool_name, tool_output)
    if role == "tool":
        return min(raw, int(raw * TOOL_TOKEN_WEIGHT), TOOL_TOKEN_CAP)
    return raw
```

| Message role | Calculation | Typical range |
|---|---|---|
| `user` | Full `estimate_message_tokens(content, context)` | 50–500 |
| `assistant` | Full `estimate_message_tokens(content)` | 50–1000 |
| `tool` | `min(estimated_tokens × 0.25, 800)` | 200–800 (capped) |

### Auto-count in `save_message()`

`ConversationStore.save_message()` now auto-calculates `token_count` when the caller omits it:

```python
if token_count is None:
    token_count = estimate_weighted_message_tokens(
        role=role,
        content=content,
        tool_name=tool_name,
        tool_output=tool_output,
    )
```

The same weighted value is added to `tokens_since_last_summary` during the auto-increment step in `save_message()`.

---

## Hybrid Trigger

### Thresholds

| Threshold | Value | Constant | Located in |
|---|---|---|---|
| Message count | 20 | `MESSAGE_THRESHOLD` | `conversation_summarizer.py:25` |
| Token count | 20000 | `TOKEN_THRESHOLD` | `conversation_summarizer.py:26` |

### Logic

```python
fresh_msg_count >= 20 OR fresh_token_count >= 20000
```

Fires when **either** threshold is crossed. This is a simple cumulative check — no modulo, no window.

### Fresh-counter read

The trigger reads counters directly from the DB (not the Python `conv` object) because `save_message()` increments them atomically but does not update the in-memory object:

```python
stmt = select(
    AgentConversation.messages_since_last_summary,
    AgentConversation.tokens_since_last_summary,
).where(AgentConversation.id == conv.id)
```

### Counter lifecycle

```
save_message(role="user", ...)
    ├─ auto-calculate token_count via estimate_weighted_message_tokens()
    ├─ messages_since_last_summary += 1          # atomic UPDATE
    └─ tokens_since_last_summary += token_count  # atomic UPDATE

save_message(role="assistant", ...)
    ├─ (same as above)

save_message(role="tool", ...)
    ├─ token_count = min(raw × 0.25, 800)        # weighted
    ├─ messages_since_last_summary += 1
    └─ tokens_since_last_summary += token_count

maybe_trigger():
    ├─ read fresh counters from DB
    ├─ if msg >= 20 OR tokens >= 20000:
    │     ├─ acquire advisory lock
    │     ├─ call summarize_conversation()
    │     │    ├─ on success: reset_summary_counters() → counters = 0
    │     │    └─ on failure: counters NOT reset → retry next request
    │     └─ release lock (transaction commit)
    └─ else: return
```

---

## Conversation Context Loading

### Cursor-based history (replaces end-based budget window)

Originally, `ConversationService.load_history()` loaded the last 8000 tokens from the end of the conversation. This had a critical gap problem:

```
last_summary_message_id → msg50
                           │
     msg51 ─── msg70 ─── msg80 ─── msg100
     │                     │
     ├─ không trong context ├─ 8000 tokens cuối → OK
     │  (bị budget cắt)     │
     └─ chưa được summary    └─ thấy trong context
        (tokens_since~12000)
```

Messages msg51–msg70 were **lost entirely** — not in the summary (not yet extracted) and not in the context window (cut by 8000 budget).

**Fix:** `load_history()` now loads messages **since** `last_summary_message_id` via `get_messages_since()`, not from the end of the conversation. The summary (injected via `get_conversation_context()`) already covers everything before the cursor. The two together provide a gapless view:

```
[SYSTEM PROMPT]:
  === PREVIOUS CONVERSATION HISTORY (events up to <cutoff>) ===
  <conv.summary text>                       ← covers everything before cursor
  === RECENT CONVERSATION ===

[MESSAGES]:
  [all messages since last_summary_message_id]  ← covers everything after cursor
  [current user message]
```

**No token budget applied** to the cursor-based path — the trigger threshold (20000 tokens) already bounds the un-summarized region. The `MAX_HISTORY_TOKENS` constant is only used as a fallback for conversations that have never been extracted (no cursor).

### Comparison: old vs new trigger

| Aspect | Old (modulo-based) | New (hybrid) |
|---|---|---|
| Cursor | `last_extracted_at` (timestamp) | `last_summary_message_id` (UUID FK) |
| Counter | `message_count` (total, modulo 20) | `messages_since_last_summary` (reset on success) |
| Token awareness | None | `tokens_since_last_summary` with weighted tool policy |
| Failure recovery | Stalls until next modulo boundary | Retries on next request (counters continue to grow) |
| Race resilience | Modulo guard `% >= 2` window | Advisory lock (unchanged) |

---

## Token Accounting for Summary

### Where tokens are estimated

| Location | What is estimated | Policy |
|---|---|---|
| `save_message()` | `token_count` per message | Weighted (tools: min(raw × 0.25, 800)) |
| `tokens_since_last_summary` | Cumulative since last extraction | Sum of per-message weighted tokens |
| `get_messages_since()` | Count + token sum for extraction | Uses fresh DB counters |
| `estimate_tokens()` | Raw text tokens (cl100k_base) | Unweighted, used for history loading |

### What is NOT stored

The per-message `token_count` column is now populated (see D1 fix), but it is **not authoritative** for trigger decisions — the authoritative counters are `tokens_since_last_summary` and `messages_since_last_summary` on `AgentConversation`.

---

## Trigger Safety

### Advisory lock

PostgreSQL `pg_try_advisory_xact_lock(hashtextextended(conv.id, 0))` prevents concurrent extractions on the same conversation. The lock is:
- **Non-blocking**: returns false if held by another session
- **Transaction-scoped**: released on `COMMIT` or `ROLLBACK`
- **Not tied to extraction result**: failed extractions do not hold the lock

### Call order

```
save all messages → increment_message_count (total) → maybe_trigger → db.commit
```

`maybe_trigger()` runs inside the same transaction as the message saves. If the extraction LLM call fails, `db.commit()` still runs — the extraction failure is logged but the messages are not rolled back.

### Failure modes

| Failure | Counter state | Next trigger |
|---|---|---|
| Advisory lock busy | Unchanged | Will re-check thresholds |
| Extraction LLM error | Unchanged (not reset) | Counters still above threshold → fires again |
| Extraction returns `success=False` | Unchanged (not reset) | Counters still above threshold → fires again |
| Exception during extraction | Unchanged (not reset) | Counters still above threshold → fires again |

---

## Key Assumptions

1. **`save_message` caller does not need to provide `token_count`.** The auto-count in `save_message` covers all callers. Explicit `token_count` is still accepted but unused in practice.

2. **Tool messages count toward the trigger.** The hybrid design intentionally includes tool messages in both counters. A tool-heavy conversation reaches the token threshold faster, which is desirable (more tokens = more context to summarize).

3. **`last_summary_message_id` is resolved to `created_at` at fetch time, not stored directly.** This preserves FIFO ordering while using the stable UUID as the pointer.

4. **Counters are NOT decremented on rollback.** If the transaction rolls back after counters are incremented (by `save_message`) but before the extraction runs, the counters will be "ahead" of the actual messages. This is acceptable — the extraction will fire one request earlier than strictly needed.

5. **The advisory lock is the sole guard against duplicate extractions.** The hybrid threshold is NOT a guard — both thresholds are "at least" checks, not "exactly" checks. Concurrent requests may both read fresh counters above threshold; the lock prevents both from running extraction.
