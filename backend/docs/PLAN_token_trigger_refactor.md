# Token-Based Trigger Refactor — Implementation Plan

## 1. Current Trigger

**File:** `backend/app/ai/agents/memory_trigger_service.py:39-41`

```python
threshold = summarizer.MESSAGE_THRESHOLD  # 20
if conv.message_count < threshold or conv.message_count % threshold >= 2:
    return
```

**How it works:**
- `MESSAGE_THRESHOLD = 20` is defined on `ConversationSummarizer` (`conversation_summarizer.py:25`)
- `message_count` is incremented atomically via `UPDATE ... RETURNING` in `ConversationStore.increment_message_count()` (`conversation_store.py:228-247`)
- Each user request increments `message_count` **twice**: once for the user message, once for the assistant reply (see `agent_service.py:94,207,255,468`)
- The modulo condition `conv.message_count % threshold >= 2` skips counts immediately after a multiple (21-39, 41-59, etc.), providing a one-message "catch window" to avoid races
- Summaries fire when `message_count` is 20, 40, 60, etc.
- PostgreSQL advisory lock (`pg_try_advisory_xact_lock`) prevents concurrent extractions on the same conversation

**Why it's problematic:**
- Tool-heavy conversations generate many messages but few user+assistant token pairs, triggering premature summaries
- Sparse but long-form conversations delay summaries despite significant new information
- Message count does not correlate with the volume of new content

**Call sites:**
- `agent_service.py:209` — `handle()` (non-streaming)
- `agent_service.py:480` — `handle_streaming_generator()` (streaming)

Both call `memory_service.maybe_trigger(summarizer, conv)` after the final `increment_message_count()`.

---

## 2. Current Token Support

### Existing tokenizer utility
**File:** `backend/app/utils/tokens.py`

| Function | Purpose | Implementation |
|---|---|---|
| `estimate_tokens(text)` | Tokenize any text string | Uses **tiktoken** (cl100k_base) when available; falls back to `len(text) / 3.5` |
| `estimate_message_tokens(role, content, tool_name, tool_output)` | Tokenize a DB message record | Sum of: content tokens + role tokens + tool_name tokens + tool_output JSON tokens + 4 overhead tokens |

This is production code already used by `get_recent_messages_by_token_budget()` in `conversation_store.py:78-137` for token-budgeted history trimming.

### Existing schema fields

| Model | Field | Type | Nullable | Currently Populated? |
|---|---|---|---|---|
| `AgentMessage` | `token_count` | `Integer` | **Yes** (nullable) | **No** — always `NULL` |
| `AgentConversation` | `total_token_count` | `Integer` | No | **Yes** — from provider `usage.total_tokens` via `increment_token_count()` |

### Key finding
`AgentMessage.token_count` already exists in the schema but is **never populated**. `ConversationStore.save_message()` already accepts `token_count: int | None = None` as a parameter (`conversation_store.py:149`), and stores it via `token_count=token_count` on the model (`conversation_store.py:210`).

No caller passes this parameter:
- `conversation_service.py:268` — `save_user_message()` (no token_count)
- `agent_service.py:205,344,463` — saving assistant replies (no token_count)
- `tool_execution_service.py:301,395` — saving tool messages (no token_count)

**Conclusion:** `estimate_message_tokens()` from `app/utils/tokens.py` is the correct, existing token-counting mechanism. It should be called at each save_message call site to populate `token_count` on the message record.

---

## 3. Required Changes

### Files to modify

| # | File | What to change | Impact |
|---|---|---|---|
| 1 | `backend/app/models.py` | Add `tokens_since_last_summary` column to `AgentConversation` | Adds a non-null Integer default 0 |
| 2 | `backend/alembic/versions/` | New migration: `ADD tokens_since_last_summary` | Adds column to `agent_conversations` table |
| 3 | `backend/app/ai/agents/conversation_store.py` | Modify `save_message()` to auto-calculate token_count when not provided | Call `estimate_message_tokens()` internally |
| 4 | `backend/app/ai/agents/conversation_store.py` | New method: `increment_tokens_since_last_summary(conv_id, token_count)` | Atomic UPDATE |
| 5 | `backend/app/ai/agents/conversation_store.py` | New method: `reset_tokens_since_last_summary(conv_id)` | Set to 0 |
| 6 | `backend/app/ai/agents/conversation_summarizer.py` | Add `TOKEN_THRESHOLD = 20000` constant; remove `MESSAGE_THRESHOLD` | New threshold constant |
| 7 | `backend/app/ai/agents/conversation_summarizer.py` | Modify `summarize_conversation()` to reset counter on success | Reset after successful summary |
| 8 | `backend/app/ai/agents/memory_trigger_service.py` | Replace message-count modulo check with `tokens_since_last_summary >= TOKEN_THRESHOLD` | Core trigger change |
| 9 | `backend/app/ai/agents/conversation_service.py` | Add wrapper for `increment_tokens_since_last_summary()` | Thin delegation |
| 10 | `backend/app/ai/agents/agent_service.py` | After save_message, increment `tokens_since_last_summary` by message.token_count | O(1) accumulation |

### Files NOT changed (explicitly)
- `backend/app/services/memory_extraction_service.py` — extraction pipeline stays identical
- `backend/app/ai/agents/conversation_summarizer.py` — `get_conversation_context()` stays identical
- `backend/app/ai/agents/conversation_store.py` — `increment_message_count()`, `get_recent_messages_by_token_budget()`, `increment_token_count()` stay identical
- `backend/app/ai/agents/model_client.py`, `openai_provider.py` — provider usage tracking stays identical
- All API serializers and endpoints — no API contract changes

---

## 4. Token Counting Strategy

### Where token_count is calculated
In `ConversationStore.save_message()` (`conversation_store.py:139-215`).

### When it is calculated
At the **exact moment** the message is persisted. If the caller does not pass `token_count`, the method calculates it internally using `estimate_message_tokens()` before creating the `AgentMessage` record.

### Where it is stored
In `AgentMessage.token_count` (already exists, column `agent_messages.token_count`).

### Why this approach
- **Reuses existing infrastructure:** `estimate_message_tokens()` is already used by `get_recent_messages_by_token_budget()`. No new tokenizer library needed.
- **Exactly once tokenization:** The message is tokenized once when created and stored. Never re-tokenized.
- **O(1) per message:** No scanning, no recalculation.
- **Zero schema change for AgentMessage:** The column already exists.

### Why provider usage statistics are NOT used
- Provider `total_tokens` is a batch aggregate across all messages in a multi-turn request — it cannot be attributed to individual messages.
- Provider `prompt_tokens` / `completion_tokens` counts the full LLM call, not the message content. For tool messages, provider usage is zero.
- Provider usage depends on the model and provider; it's not available for local/offline models.
- Per-message `estimate_message_tokens()` is deterministic, model-independent, and always available.

### Implementation detail in `save_message()`:
```python
# At top of save_message(), before constructing AgentMessage:
if token_count is None:
    token_count = estimate_message_tokens(
        role=normalized_role,
        content=normalized_content,
        tool_name=tool_name,
        tool_output=tool_output,
    )
```

This populates the field for **every** message — user, assistant, and tool — with zero changes to callers.

---

## 5. Counter Design

### Where `tokens_since_last_summary` lives
As a new column on `AgentConversation`:
```python
tokens_since_last_summary = Column(Integer, nullable=False, default=0, server_default=text("0"))
```

### How it is updated
A new atomic method on `ConversationStore`:

```python
async def increment_tokens_since_last_summary(
    self, conversation_id: UUID, token_count: int
) -> None:
    stmt = (
        update(AgentConversation)
        .where(AgentConversation.id == conversation_id)
        .values(
            tokens_since_last_summary=AgentConversation.tokens_since_last_summary + token_count
        )
    )
    await self.db.execute(stmt)
```

Called from `ConversationService.increment_tokens_since_last_summary()` wrapper.

### Where the increment call is placed
After every `save_message()` call in `agent_service.py`. The pattern:

```python
saved_msg = await self.store.save_message(...)
if saved_msg and saved_msg.token_count:
    await self.increment_tokens_since_last_summary(conv.id, saved_msg.token_count)
```

Four call sites:
- `agent_service.py:205` (assistant reply, non-streaming)
- `agent_service.py:268` → `conversation_service.py:268` (user message)
- `agent_service.py:344` (assistant reply, streaming)
- `agent_service.py:463` (assistant reply, streaming — synthesis)

Plus `tool_execution_service.py:301` and `395` (tool messages). However, since these are within the same request, the counter increment for tool messages is safe — they contribute tokens but don't trigger summarization until the final `maybe_trigger()` call at the end.

### When it resets
Inside `ConversationSummarizer.summarize_conversation()`, immediately after a successful `extract_and_store()`:

```python
if result.get("success"):
    await self.store.reset_tokens_since_last_summary(conversation_id)
```

Where `reset_tokens_since_last_summary` is:
```python
async def reset_tokens_since_last_summary(self, conversation_id: UUID) -> None:
    stmt = (
        update(AgentConversation)
        .where(AgentConversation.id == conversation_id)
        .values(tokens_since_last_summary=0)
    )
    await self.db.execute(stmt)
```

### Why it avoids full conversation scans
- No SELECT on historical messages
- No re-tokenization
- No aggregation queries
- Purely incremental: each new message adds its token count via atomic UPDATE
- O(1) per message, O(1) per reset

---

## 6. Trigger Flow

```
User sends message
    │
    ▼
agent_service.py (handle / handle_streaming_generator)
    │
    ├─ 1. save_user_message(conv.id, message, context)
    │       │
    │       ▼
    │   conversation_service.py: save_user_message()
    │       → store.save_message(role="user", content=..., ...)
    │           │
    │           ▼
    │       conversation_store.py: save_message()
    │           token_count = estimate_message_tokens(role, content)  ◄─ NEW
    │           AgentMessage(token_count=token_count)
    │           return message
    │       │
    │       ▼
    │   increment_tokens_since_last_summary(conv.id, saved_msg.token_count)  ◄─ NEW
    │
    ├─ 2. increment_message_count(conv.id)  ← unchanged
    │
    ├─ ...LLM turns with tool execution...
    │   Each tool save_message also calculates token_count and increments counter
    │
    ├─ 3. save_message(role="assistant", content=reply_text)
    │       │
    │       ▼
    │   token_count = estimate_message_tokens(role, content)  ◄─ NEW
    │   increment_tokens_since_last_summary(conv.id, saved_msg.token_count)  ◄─ NEW
    │
    ├─ 4. increment_message_count(conv.id)  ← unchanged
    │
    ├─ 5. memory_service.maybe_trigger(summarizer, conv)
    │       │
    │       ▼
    │   memory_trigger_service.py: maybe_trigger()
    │       if summarizer is None: return
    │       threshold = summarizer.TOKEN_THRESHOLD          ◄─ CHANGED
    │       if conv.tokens_since_last_summary < threshold:  ◄─ CHANGED
    │           return
    │       (advisory lock — unchanged)
    │       result = await summarizer.summarize_conversation(conv.id)
    │           │
    │           ▼
    │       conversation_summarizer.py: summarize_conversation()
    │           result = await extract_and_store(conversation_id, db)  ← unchanged
    │           if result.get("success"):
    │               await store.reset_tokens_since_last_summary(conv.id)  ◄─ NEW
    │
    └─ 6. db.commit()
```

### Threshold check detail

```python
# memory_trigger_service.py (new logic)
threshold = summarizer.TOKEN_THRESHOLD  # 20000
if conv.tokens_since_last_summary < threshold:
    return
```

The advisory lock race prevention is preserved exactly as today. The modulo window (`>= 2`) is no longer needed because the token counter is incremented incrementally with each message — there is no batch increment that could race. The advisory lock itself remains for safety.

---

## 7. Failure Cases

### Summary generation fails
- `extract_and_store()` returns `{"success": False, ...}`
- `summarize_conversation()` logs the failure and returns the error dict
- `tokens_since_last_summary` is **NOT reset**
- The accumulated value stays, so subsequent messages will push it further above threshold
- `maybe_trigger()` will fire again on the next increment that makes it pass the advisory lock

### Retry occurs
- The next request increments the counter further
- `maybe_trigger()` checks threshold again — it's still above 20,000
- Advisory lock ensures only one extraction runs at a time
- If the first extraction eventually succeeds (e.g., a transient error), counter resets normally

### New messages arrive before retry
- If new messages arrive while the counter is above threshold and the conversation is locked
- `maybe_trigger()` skips because the advisory lock is held
- The counter continues to grow
- After the lock is released (the running extraction completes or fails)
- On the **next request**, the threshold check passes again, and a new extraction runs
- The extra tokens accumulated during the lock are included in the next extraction's input

### Conversations become extremely large
- The counter is a single Integer column — no growth beyond 4 bytes per conversation
- At 20,000 tokens per summary, a conversation needs ~2,000 user+assistant pairs to overflow an Integer (2.1 billion tokens) — far beyond plausible conversation lengths
- No full-conversation scan ever occurs
- Token counting is O(1) per message regardless of conversation size
- `extract_and_store()` already handles incremental extraction (only processes messages since `last_extracted_at`)

---

## 8. Migration

### Strategy: Two-phase rollout

#### Phase 1 — Schema change (backward compatible)
1. Add `tokens_since_last_summary` column via Alembic migration
2. No code changes yet — the column exists but is unused
3. Safe to deploy — no runtime impact

Migration SQL:
```sql
ALTER TABLE agent_conversations
ADD COLUMN tokens_since_last_summary INTEGER NOT NULL DEFAULT 0;
```

#### Phase 2 — Code change
1. Deploy the code changes described in Section 3
2. Existing conversations start with `tokens_since_last_summary = 0`
3. The first 20,000 tokens of new messages in each conversation will trigger the first summary
4. No re-tokenization of existing messages occurs
5. The `message_count` field and all existing APIs remain untouched — full backward compatibility

#### Rollback
- Revert the code changes; the new column becomes unused (no-downward-migration needed for a simple column addition)
- If needed, the migration can be reversed: `ALTER TABLE agent_conversations DROP COLUMN tokens_since_last_summary;`

#### No data migration required
- Existing `AgentMessage.token_count` values are all `NULL` — the first save after deploy will populate them
- Existing conversations' `tokens_since_last_summary` starts at 0 — they'll naturally accumulate to threshold

### Testing the migration
1. Verify `estimate_message_tokens()` produces consistent results between the existing tiktoken implementation and the new usage in `save_message()`
2. Verify that an existing conversation with `tokens_since_last_summary = 0` starts accumulating correctly
3. Verify that `message_count` continues to work (in case any external code depends on it)
