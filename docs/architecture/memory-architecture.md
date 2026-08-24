# Memory Architecture

> Revision date: 2026-07-30  
> Scope: Backend — conversation memory, semantic memory, embeddings, Zep integration, extraction triggers, token accounting

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Data Models](#2-data-models)
3. [Message Lifecycle](#3-message-lifecycle)
4. [Conversation Summary](#4-conversation-summary)
5. [Semantic Memory](#5-semantic-memory)
6. [Coupling Analysis](#6-coupling-analysis)
7. [Timestamps and Pointers](#7-timestamps-and-pointers)
8. [Token Accounting](#8-token-accounting)
9. [Trigger Mechanisms](#9-trigger-mechanisms)
10. [Retrieval Pathways](#10-retrieval-pathways)
11. [Architecture Diagram](#11-architecture-diagram)
12. [Component Inventory](#12-component-inventory)
13. [Architectural Assumptions](#13-architectural-assumptions)
14. [Technical Debt](#14-technical-debt)

---

## 1. System Overview

The memory system has two tiers:

| Tier | Name | Storage | Purpose | GC |
|---|---|---|---|---|
| 1 | **Episodic Summary** | `agent_conversations.summary` (PostgreSQL) | Rolling compressed history of each conversation; overwritten on each extraction | Overwritten, not appended |
| 2 | **Semantic Memory** | Zep Cloud OR `semantic_memories` table (pgvector) | Long-term facts extracted from conversations; cross-conversation retrieval | Dedup (in-process + similarity) |

The two tiers are produced by a single LLM extraction call. The LLM analyzes new messages (or the full conversation on first pass) and returns a JSON object with three keys: `episodic_summary`, `semantic_memories`, `title`.

### File map

| File | Role |
|---|---|
| `app/ai/agents/agent_service.py` | Main orchestrator — routes user message through conversation service, LLM, tool execution, then triggers memory |
| `app/ai/agents/conversation_service.py` | Lifecycle: get/create conv, load history, build system prompt with summary injection |
| `app/ai/agents/conversation_store.py` | Low-level DB access: save messages, increment counters, token-budgeted history loading |
| `app/ai/agents/conversation_summarizer.py` | Summarizer wrapper: delegates to `memory_extraction_service.extract_and_store()`, provides `get_conversation_context()` for prompt injection |
| `app/ai/agents/memory_trigger_service.py` | Trigger guard: checks message-count threshold, acquires advisory lock, calls summarizer |
| `app/services/memory_extraction_service.py` | Extraction pipeline: fetch new messages, call LLM with extraction prompt, parse JSON, store episodic summary + semantic memories |
| `app/services/memory_extraction_prompt.py` | Builds system+user prompt for the extraction LLM |
| `app/services/semantic_memory_provider.py` | Abstract interface + Fallback provider (Zep → PgVector) |
| `app/services/zep_memory.py` | Zep Cloud implementation — user management, graph add/search, dedup |
| `app/services/pgvector_memory_provider.py` | Local pgvector implementation — embedding via `EmbeddingService`, cosine similarity search, dedup |
| `app/ai/agents/embedding_service.py` | Text → vector via OpenAI-compatible `/v1/embeddings`, Redis cache |
| `app/ai/tools/extract_memory.py` | Agent tool: retrieves semantic memories from Zep/PgVector + optional episodic summary from PostgreSQL |
| `app/utils/tokens.py` | Token estimation via tiktoken (cl100k_base) with char-based fallback |

---

## 2. Data Models

### `AgentConversation` (`app/models.py`, table `agent_conversations`)

```python
class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id                          = Column(UUID, primary_key=True)
    user_id                     = Column(UUID, FK->users.id)
    workspace_id                = Column(UUID, FK->workspaces.id, nullable=True)
    title                       = Column(String(255), nullable=True)
    summary                     = Column(Text, nullable=True)              # Episodic summary (overwritten)
    message_count               = Column(Integer, default=0)               # Total messages ever sent
    total_token_count           = Column(Integer, default=0)               # Provider-reported total tokens
    last_extracted_at           = Column(DateTime, nullable=True)          # Last memory extraction timestamp
    last_summary_message_id     = Column(UUID, FK->agent_messages.id,
                                         nullable=True)                    # Cursor: last message included in summary
    tokens_since_last_summary   = Column(Integer, default=0)               # Estimated tokens since last summary
    messages_since_last_summary = Column(Integer, default=0)               # Messages since last summary
    created_at                  = Column(DateTime)
    updated_at                  = Column(DateTime)
```

**Memory-related fields:**

| Field | Type | Written by | Read by | Invariant |
|---|---|---|---|---|
| `summary` | Text | `extract_and_store()` at `memory_extraction_service.py:152` | `get_conversation_context()` at `conversation_summarizer.py:88`; `extract_memory_handler()` at `extract_memory.py:73` | Rolling compressed history; overwritten each extraction cycle. NULL if never extracted. |
| `message_count` | Integer | `ConversationStore.increment_message_count()` — atomic `UPDATE ... RETURNING` | `ConversationService.check_token_budget()` | Total messages ever created (user + assistant + tool). Incremented twice per request. |
| `total_token_count` | Integer | `ConversationStore.increment_token_count()` — atomic `UPDATE` with provider `usage.total_tokens`| `ConversationService.check_token_budget()` — daily limit guard | Cumulative provider-reported tokens. NOT reset on extraction. Used for budgetary gating only. |
| `last_extracted_at` | DateTime | `extract_and_store()` at `memory_extraction_service.py:155` | `MemoryExtractionService.extract_and_store()` (incremental fetch filter); legacy `get_conversation_context()` display | Timestamp of last successful extraction. Null means never extracted. Used as cursor for Semantic Memory. NOTE: Summary extraction now uses `last_summary_message_id` for its cursor — `last_extracted_at` is retained only for Semantic Memory. |
| `last_summary_message_id` | UUID (FK) | `ConversationStore.reset_summary_counters()` at `conversation_store.py` | `ConversationSummarizer.get_conversation_context()` (resolves to timestamp); `MemoryExtractionService.extract_and_store()` (incremental fetch cursor) | Points to the last `agent_messages.id` that was included in the latest summary. Resolved to `created_at` at fetch time for FIFO-stable cursor. Reset on successful extraction. |
| `tokens_since_last_summary`| Integer | `ConversationStore.save_message()` — auto-incremented on every message save | `MemoryTriggerService.maybe_trigger()` — hybrid threshold check | Estimated tokens accumulated since `last_summary_message_id`. Reset to 0 on successful extraction. |
| `messages_since_last_summary`| Integer | `ConversationStore.save_message()` — auto-incremented on every message save | `MemoryTriggerService.maybe_trigger()` — hybrid threshold check | Message count since `last_summary_message_id`. Reset to 0 on successful extraction. |

### `AgentMessage` (`app/models.py:591-611`, table `agent_messages`)

```python
class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id              = Column(UUID, primary_key=True)
    conversation_id = Column(UUID, FK->agent_conversations.id, ondelete=CASCADE)
    role            = Column(String(20))          # "user" | "assistant" | "tool"
    content         = Column(Text, nullable=True)
    context         = Column(JSONB, nullable=True)
    tool_name       = Column(String(100), nullable=True)
    tool_input      = Column(JSONB, nullable=True)
    tool_output     = Column(JSONB, nullable=True)
    tool_call_id    = Column(String(100), nullable=True)
    turn_id         = Column(UUID, nullable=True)
    token_count     = Column(Integer, nullable=True)   # ALWAYS NULL — never populated
    created_at      = Column(DateTime)
```

**Critical finding:** `AgentMessage.token_count` is defined in the schema, accepted as a parameter in `ConversationStore.save_message()`, and stored on the model — but **no caller ever passes a value**. It is `NULL` for every row. This is identified as dead code / unfulfilled design in `docs/PLAN_token_trigger_refactor.md`.

---

## 3. Message Lifecycle

### Non-streaming path (`/api/v1/agent/chat`)

```
HTTP POST /api/v1/agent/chat
    │
    ▼
agent.py:46 — chat() handler
    │
    ├─ AgentService(user, db)
    │       ├─ ConversationService(user, db, ConversationStore)
    │       ├─ ToolExecutionService(user, db, store, ToolRegistry)
    │       └─ MemoryTriggerService(db)
    │
    ├─ conversation_service.get_or_create(conv_id, workspace_id, message)
    │       ├─ get_conversation_by_id() or get_or_create_conversation()
    │       └─ _generate_conversation_title(message)  [LLM call for new convs]
    │
    ├─ conversation_service.check_token_budget(conv)
    │       └─ conv.total_token_count >= 2_000_000 → reject
    │
    ├─ conversation_service.get_summarizer()
    │       └─ ConversationSummarizer(db)
    │
    ├─ conversation_service.build_system_prompt(conv, message, context, summarizer, SYSTEM_PROMPT)
    │       ├─ summarizer.get_conversation_context(conv.id, include_summary=True)
    │       │     └─ returns formatted string with conv.summary + timestamp boundary
    │       └─ _build_skill_section(message, context)
    │
    ├─ conversation_service.load_history(conv.id, conv.last_summary_message_id)
    │       └─ store.get_messages_since()  [cursor-based — only messages after last summary]
    │           (falls back to get_recent_messages_by_token_budget when no cursor exists)
    │
    ├─ conversation_service.save_user_message(conv.id, message, context)
    │       └─ store.save_message(role="user", ...)
    │
    ├─ conversation_service.increment_message_count(conv.id)
    │
    └─ LLM TOOL LOOP (max 30 turns)
        │
        ├─ _model_client.generate(messages, config, tools=tools)
        │
        ├─ if tool_calls:
        │     └─ tool_service.execute_tools_pass(tool_calls, conv, ctx, ...)
        │           ├─ registry.execute(name, args, ctx) for each tool
        │           └─ store.save_message(role="tool", ...) per tool result
        │
        └─ if no tool_calls:
              └─ store.save_message(role="assistant", content=reply_text)

    ├─ conversation_service.update_timestamp(conv.id)
    ├─ conversation_service.increment_message_count(conv.id)          # second increment
    │
    ├─ memory_service.maybe_trigger(summarizer, conv)
    │     └─ See [Trigger Mechanisms] section
    │
    └─ db.commit()

    └─ return AgentChatResponse(conversation_id, reply)
```

**Key ordering facts:**

1. The user message is saved BEFORE the LLM call (`save_user_message` at `agent_service.py:93`, LLM call at `agent_service.py:135`).
2. The assistant reply is saved AFTER the LLM loop completes (`agent_service.py:205`).
3. `message_count` is incremented exactly twice per request: once after saving the user message (`agent_service.py:94`), once after saving the assistant reply (`agent_service.py:207`). Tool messages do NOT increment `message_count`.
4. `maybe_trigger()` runs AFTER all saves and AFTER the second `increment_message_count()`, ensuring the count reflects the complete request.
5. `db.commit()` is called AFTER `maybe_trigger()`, meaning the extraction LLM call happens inside the same transaction as the message saves. If the extraction fails, `db.commit()` still runs — the extraction failure is logged but does NOT roll back the conversation messages.

### Streaming path (`/api/v1/agent/stream/chat`)

The streaming path follows the same sequence but interleaves SSE events (`token`, `tool_start`, `tool_result`, `done`). Assistant messages are saved incrementally per-turn rather than once at the end.

### Message persistence details

`ConversationStore.save_message()` (`conversation_store.py:139-215`):

- Normalizes role to lowercase
- **Collapses consecutive same-role messages:** if the last message has the same role as the new one, it overwrites `last_msg.content` and `last_msg.created_at` instead of inserting a new row. This means if the LLM generates multiple assistant responses for the same turn, only the last one survives.
- For `user`/`assistant` roles: requires non-null content; clears tool fields
- For `tool` role: requires `tool_name`, `tool_input`, and `tool_output` all present
- Sets `created_at = datetime.utcnow()` on every insert or collapse

---

## 4. Conversation Summary

### What it is

The "Conversation Summary" is the **Episodic Summary** stored in `agent_conversations.summary`. It is a single text string produced by an LLM that compresses the conversation history up to the extraction point. It is NOT a separate table — it lives as a column on the conversation row.

### Trigger

See [Trigger Mechanisms section 9](#9-trigger-mechanisms).

### Pipeline

```
MemoryTriggerService.maybe_trigger()
    │
    ├─ Check: summarizer is not None
    ├─ Check: messages_since_last_summary >= 20 OR tokens_since_last_summary >= 20000
    ├─ Acquire: pg_try_advisory_xact_lock(hashtextextended(conv.id, 0))
    │
    ▼
ConversationSummarizer.summarize_conversation(conv.id)
    │
    ▼
extract_and_store(conversation_id, db)
    │
    ├─ 1. Fetch conv (AgentConversation)
    ├─ 2. Resolve last_summary_message_id → created_at cursor
    ├─ 3. Fetch messages since that cursor
    │      (or all messages if first time)
    ├─ 4. ABORT if fewer than 5 new messages
    ├─ 5. Build conversation text (_build_conversation_text)
    ├─ 6. Build extraction prompt (build_extraction_messages)
    │      └─ Includes existing summary for merge (if any)
    ├─ 7. Call LLM (ModelClient.generate, temp=0.2, max_output_tokens=4096)
    ├─ 8. Parse JSON response (_parse_extraction_response)
    │      └─ Normalizes semantic_memories, filters by confidence >= 0.7
    │
    ├─ 9. STORE EPISODIC SUMMARY
    │      └─ conv.summary = episodic_summary
    │         conv.title = title (if provided)
    │         conv.last_extracted_at = datetime.utcnow()
    │         conv.updated_at = datetime.utcnow()
    │         await db.flush()
    │
    ├─ 10. RESET SUMMARY COUNTERS (via ConversationStore.reset_summary_counters())
    │      └─ conv.last_summary_message_id = last_message.id
    │         conv.messages_since_last_summary = 0
    │         conv.tokens_since_last_summary = 0
    │         await db.flush()
    │
    ├─ 11. STORE SEMANTIC MEMORIES
    │      └─ If workspace_id present:
    │           provider = get_semantic_memory_provider(db)
    │           provider.ensure_user(workspace_id_str)
    │           provider.add_semantic_memories_batch(workspace_id_str, memories)
    │
    └─ 12. db.commit()
```

### What the summary is used for

The summary is injected into the system prompt on every subsequent request:

```
ConversationService.build_system_prompt()
    │
    ├─ if summarizer and conv.summary:
    │     summary_context = summarizer.get_conversation_context(conv.id)
    │     system_prompt += "\n\n" + summary_context
    │
    ▼
Injected text format:
    === PREVIOUS CONVERSATION HISTORY (events up to <last_summary_timestamp>) ===
    <conv.summary text>

    === RECENT CONVERSATION ===
```

This tells the LLM what happened before the sliding window (last N messages or token budget). The boundary timestamp tells the LLM how recent the summarized events are.

### Incremental design: message-id cursor

Instead of a timestamp-based cursor (`last_extracted_at`), the summary system uses a **stable message-id cursor** (`last_summary_message_id UUID → agent_messages.id`). The cursor is resolved to its `created_at` timestamp at fetch time. This is more robust than the old timestamp cursor because:

1. **FIFO-stable**: `created_at` is auto-set but the ordering authority is `id` (UUID v4 generates monotonically)
2. **Collapse-safe**: Same-role message collapse overwrites `created_at` but `id` is immutable
3. **Exact boundary**: Points to exactly one message, not a timestamp with microsecond granularity

### Incremental design

Only messages since the cursor (resolved from `last_summary_message_id` → `created_at`) are sent to the extraction LLM. The LLM receives both the existing summary and the new messages, and must merge new information into the existing summary. This keeps the extraction call O(new messages) rather than O(conversation length).

---

## 5. Semantic Memory

### Where it begins and ends

**Begins** at the LLM extraction response: `result_data.get("semantic_memories", [])` in `memory_extraction_service.py:165`. The LLM is prompted to produce an array of memory objects with `content`, `category`, `confidence`, and `expected_lifetime`.

**Ends** at storage via `FallbackSemanticMemoryProvider.add_semantic_memories_batch()` → either `ZepMemoryProvider.add_semantic_memory()` or `PgVectorMemoryProvider.add_semantic_memory()`.

Semantic memory is **separate from the conversation** — it crosses conversation boundaries and is retrieved via the `extract_memory` agent tool or the `search_semantic_memories` API.

### Extraction flow

See pipeline in section 4. The semantic memories are extracted in the SAME LLM call as the episodic summary. The LLM prompt (`app/ai/prompts/memory/semantic_extraction.md`) instructs:

- Extract user goals, preferences, constraints, decisions, and behavioral patterns
- Rate importance and expected lifetime
- Filter weak signals (confidence ≥ 0.7 in `_parse_extraction_response`)
- Temporary information belongs in episodic_summary, not semantic_memories

### Storage flow (Zep)

```
extract_and_store() → get_semantic_memory_provider(db)
    │
    ▼
FallbackSemanticMemoryProvider(db)
    │
    ├─ primary: ZepMemoryProvider()
    │     └─ Calls Zep Cloud API via zep_cloud SDK
    │         client.graph.add(user_id, type="json", data=memory_payload)
    │
    └─ fallback: PgVectorMemoryProvider(db)
          └─ If Zep raises SemanticMemoryUnavailable
```

### Storage flow (PgVector)

```
PgVectorMemoryProvider.add_semantic_memory()
    │
    ├─ 1. In-process LRU dedup check
    ├─ 2. Embed content via EmbeddingService.embed_text()
    ├─ 3. pgvector similarity dedup check (cosine >= 0.90)
    ├─ 4. INSERT INTO semantic_memories
    │      (user_id, category, content, embedding, confidence, expected_lifetime)
    └─ 5. Update in-process dedup cache
```

### Embedding flow

```
PgVectorMemoryProvider:
    add_semantic_memory() → EmbeddingService.embed_text(content)
    search_semantic_memories() → EmbeddingService.embed_query(query)

EmbeddingService._embed(text):
    ├─ SHA256 cache key → check Redis (30-day TTL)
    ├─ If miss: AsyncOpenAI(api_key, base_url).embeddings.create(
    │     model=settings.EMBEDDING_MODEL,
    │     dimensions=settings.EMBEDDING_DIMENSIONS
    │   )
    └─ Store in Redis → return embedding
```

### Zep flow

```
ZepMemoryProvider:
    ensure_user(user_id)    → client.user.add(user_id, ...)
    add_semantic_memory()   → 2-phase dedup, then client.graph.add(type="json", data=...)
    search_semantic_memories() → client.graph.search(query, user_id, scope="edges",
                                     reranker="cross_encoder")
```

**Zep client:** Module-level singleton, constructed on first access. Requires `ZEP_API_KEY` in settings. Uses `httpx` under the hood with configurable timeout (`ZEP_CLIENT_TIMEOUT`, default 10s).

**Zep deduplication (2-phase):**

1. **In-process LRU:** `_dedupe_cache` (OrderedDict, max 4096 entries) keyed on `(user_id, category, normalized_content)`. Thread-safe via `_dedupe_lock`.
2. **Zep similarity check:** Calls `search_semantic_memories(content, limit=5, min_score=0.95)`. If any result has score ≥ 0.95 OR exact content match (after normalization), skip insertion.

### Retrieval flow

Two retrieval paths:

**A) Agent tool `extract_memory`** (`app/ai/tools/extract_memory.py`):

```
LLM decides to call extract_memory(query, conversation_id?, limit=10)
    │
    ▼
extract_memory_handler(args, ctx)
    ├─ 1. WorkspacePermission.require_member(workspace_id, user_id)
    ├─ 2. provider.search_semantic_memories(workspace_id_str, query, limit)
    ├─ 3. If conversation_id: fetch conv.summary from PostgreSQL
    └─ 4. Format: "=== SEMANTIC MEMORIES ===\n..." + "=== EPISODIC SUMMARY ===\n..."
```

The `extract_memory` tool is registered in the tool registry and exposed to the LLM. The system prompt (`assistant_system.md`) instructs the LLM to call it when the user references prior conversations with temporal phrases ("last time", "as we discussed").

**B) `search_semantic_memories` function** (`zep_memory.py:416-447`, legacy shim):

Direct call from other components. Uses the same `FallbackSemanticMemoryProvider.search_semantic_memories()` under the hood.

### PgVector retrieval

```
PgVectorMemoryProvider.search_semantic_memories(user_id, query, limit, min_score)
    ├─ embed_query(query) → query_embedding
    ├─ Cosine similarity: (1 - (embedding <-> cast(:q AS vector)) / 2) AS score
    ├─ WHERE user_id = :user_id AND embedding IS NOT NULL
    │   AND score >= min_score (if provided)
    ├─ ORDER BY score DESC LIMIT limit
    └─ Return list[SemanticMemoryResult]
```

---

## 6. Coupling Analysis

### How Conversation Summary and Semantic Memory are coupled

**Architectural coupling: YES — they are tightly coupled at the extraction point.**

| Coupling point | File & line | Nature |
|---|---|---|
| **Single LLM call** produces both | `memory_extraction_service.py:116-139` | The LLM is asked to return a JSON with BOTH `episodic_summary` AND `semantic_memories`. They cannot be produced independently without changing the prompt. |
| **Single extraction function** stores both | `memory_extraction_service.py:147-179` | `extract_and_store()` first stores the episodic summary (lines 151-162) then stores semantic memories (lines 164-179) in the same function, same transaction. |
| **Same trigger** gates both | `memory_trigger_service.py:39-40` | When `maybe_trigger()` fires, it calls `summarize_conversation()` which calls `extract_and_store()` — producing both outputs together. There is no way to run one without the other. |
| **Same prompt template** instructs both | `memory_extraction_prompt.py:38` | The user message ends with "Respond with a JSON object containing episodic_summary, semantic_memories, and title." |
| **Same message fetch** feeds both | `memory_extraction_service.py:92-106` | The same `new_messages` list is used to build the conversation text that is fed to the LLM for both tasks. |
| **Same dedup patterns** in both providers | `zep_memory.py` & `pgvector_memory_provider.py` | Both providers implement the same 2-phase dedup strategy (in-process LRU + similarity check), with slightly different score thresholds. |

**Implementation coupling vs architectural coupling:**

This is primarily **implementation coupling**, not architectural. The coupling exists because:
1. A single LLM call is cheaper than two separate calls
2. The episodic summary provides context that helps extract better semantic memories
3. They share the same incremental fetch cursor (`last_extracted_at`)

The system COULD be redesigned to decouple them (separate triggers, separate extraction calls, separate prompts), but the current implementation deliberately couples them for simplicity and cost efficiency.

**Where they function independently:**

- **Retrieval**: The episodic summary is injected into the system prompt for the same conversation; semantic memories are retrieved via the `extract_memory` tool across conversations. These paths are completely independent.
- **Storage**: Episodic summary → PostgreSQL (overwritten); semantic memories → Zep/PgVector (appended). Different backends, different write patterns.
- **Lifecycle**: Semantic memories persist indefinitely (dedup prevents duplicates); episodic summaries are overwritten and only the latest version survives.

---

## 7. Timestamps and Pointers

### `agent_conversations.last_extracted_at`

| Property | Value |
|---|---|
| **Type** | `DateTime`, nullable |
| **Writers** | `extract_and_store()` at `memory_extraction_service.py:155` |
| **Readers** | `extract_and_store()` (incremental fetch filter for Semantic Memory) |
| **Invariant** | Set to `datetime.utcnow()` after every successful extraction. Retained for Semantic Memory cursor — the summary system now uses `last_summary_message_id` instead. |

### `agent_conversations.last_summary_message_id`

| Property | Value |
|---|---|
| **Type** | `UUID`, FK → `agent_messages.id`, nullable |
| **Writers** | `ConversationStore.reset_summary_counters()` at `conversation_store.py` (via `ConversationSummarizer.summarize_conversation()` on successful extraction) |
| **Readers** | `ConversationSummarizer.get_conversation_context()` (resolves to `created_at` for context display); `MemoryExtractionService.extract_and_store()` (incremental fetch cursor) |
| **Invariant** | Points to the last `agent_messages.id` included in the latest summary. Resolved to `created_at` at fetch time. Null means "no extraction has ever run; process all messages". |

### `agent_conversations.tokens_since_last_summary`

| Property | Value |
|---|---|
| **Type** | `Integer`, default 0 |
| **Writers** | `ConversationStore.save_message()` — auto-incremented using `estimate_weighted_message_tokens()` |
| **Readers** | `MemoryTriggerService.maybe_trigger()` — hybrid token threshold check |
| **Invariant** | Estimated token count accumulated since `last_summary_message_id`. Includes weighted tool message tokens (`min(estimated_tokens × 0.25, 800)`). Reset to 0 on successful extraction. |

### `agent_conversations.messages_since_last_summary`

| Property | Value |
|---|---|
| **Type** | `Integer`, default 0 |
| **Writers** | `ConversationStore.save_message()` — auto-incremented for every message save (any role) |
| **Readers** | `MemoryTriggerService.maybe_trigger()` — hybrid message threshold check |
| **Invariant** | Message count since `last_summary_message_id`. Incremented for ALL roles (user, assistant, tool). Reset to 0 on successful extraction. |

### `agent_conversations.created_at` / `updated_at`

| Field | Writers | Invariant |
|---|---|---|
| `created_at` | `ConversationStore.get_or_create_conversation()` | Immutable after creation |
| `updated_at` | `ConversationStore.update_conversation_timestamp()`, `update_conversation_title()`, `extract_and_store()` | Updated on every message save, title change, and extraction |

### `agent_messages.created_at`

| Property | Value |
|---|---|
| **Writers** | `ConversationStore.save_message()` at `conversation_store.py:211` |
| **Readers** | `extract_and_store()` (incremental fetch filter), `_build_history_contents()`, `get_recent_messages()`, `get_recent_messages_by_token_budget()` |
| **Invariant** | Set to `datetime.utcnow()` on every insert. Also overwritten when collapsing consecutive same-role messages. Used as the ordering key for history loading. NOTE: The summary extraction cursor uses `last_summary_message_id` (resolved to `created_at` at fetch time) rather than `created_at` directly, mitigating the collapse-overwrite issue. |

### `agent_conversations.message_count`

| Property | Value |
|---|---|
| **Writers** | `ConversationStore.increment_message_count()` — atomic `UPDATE ... RETURNING` |
| **Readers** | `ConversationService.check_token_budget()` |
| **Invariant** | Total count of messages ever sent (user + assistant + tool). Incremented twice per successful request (once for user, once for assistant). Never decremented. No longer used for extraction trigger (replaced by `messages_since_last_summary`). |

### `agent_conversations.total_token_count`

| Property | Value |
|---|---|
| **Writers** | `ConversationStore.increment_token_count()` — atomic `UPDATE` |
| **Readers** | `ConversationService.check_token_budget()` — daily limit of 2,000,000 |
| **Invariant** | Cumulative sum of provider-reported `usage.total_tokens` from LLM calls. Written ONLY in the streaming path (`agent_service.py:472`). NOT written in the non-streaming path (the `handle()` method calls `_estimate_token_breakdown` for logging but never calls `increment_token_count`). This is an **asymmetry**. |

---

## 8. Token Accounting

### Token estimation utilities (`app/utils/tokens.py`)

**`estimate_tokens(text: str) -> int`**:
- Uses `tiktoken` with `cl100k_base` encoding when available
- Falls back to `len(text) / 3.5` character-based estimate
- Used in: logging breakdowns, token-budgeted history loading, streaming path logging

**`estimate_message_tokens(role, content, tool_name, tool_output) -> int`**:
- Sums: content tokens + role tokens + tool_name tokens + tool_output JSON tokens + 4 overhead
- Uses `estimate_tokens()` internally for each component
- Used in: `get_recent_messages_by_token_budget()` history trimming, `_estimate_token_breakdown()` logging

### Where tokens are counted

| Location | What is counted | Authoritative? |
|---|---|---|
| `ModelClient.generate()` / `stream_with_fallback()` | Provider `usage.total_tokens` from API response | Authoritative (provider-reported) |
| `_estimate_token_breakdown()` | Estimated breakdown per-turn (system, history, input, tool results) | Estimated (tiktoken/cl100k_base) |
| `store.get_recent_messages_by_token_budget()` | Per-message tokens to fit within MAX_HISTORY_TOKENS (8000) | Estimated (tiktoken) |
| `agent_service.py:472` (streaming) | Provider `usage.total_tokens` accumulated per-request | Authoritative (stored to `total_token_count`) |
| `agent_service.py:129-131` (non-streaming) | `_estimate_token_breakdown` — **logged but NOT stored** | Estimated — NOT stored |

### The `AgentMessage.token_count` gap

`AgentMessage.token_count` is an `Integer` column, nullable, accepted by `save_message()` as a parameter — but **never populated**. All callers omit the `token_count` argument. This is documented as known debt in `docs/PLAN_token_trigger_refactor.md`.

### `total_token_count` asymmetry

- **Streaming path**: `total_tokens` from provider usage is accumulated across turns and stored via `increment_token_count()` at `agent_service.py:472`
- **Non-streaming path**: `total_tokens` is accumulated into `total_usage` dict but NEVER stored (the `handle()` method at line 212 logs the breakdown but never calls `increment_token_count()`)
- This means the `total_token_count` guard (`check_token_budget()`) only works for streaming requests

---

## 9. Trigger Mechanisms

### Single trigger: Memory extraction via `maybe_trigger()`

**File:** `app/ai/agents/memory_trigger_service.py`

**Started by:** `AgentService.handle()` (line 209) and `AgentService.handle_streaming_generator()` (line 480), after all messages are saved but before `db.commit()`.

**Threshold:** Hybrid (message-count OR token-count)

```python
msg_threshold = summarizer.MESSAGE_THRESHOLD  # 20 (conversation_summarizer.py:25)
token_threshold = summarizer.TOKEN_THRESHOLD  # 20000 (conversation_summarizer.py:26)

msg_ok = fresh_msg_count >= msg_threshold
token_ok = fresh_token_count >= token_threshold
```

Fires when **either** threshold is crossed. This replaces the old modulo-based gating (`message_count % threshold >= 2`) with a simple cumulative check against incremental counters (`messages_since_last_summary`, `tokens_since_last_summary`).

**Why hybrid:**
- **Message threshold** (20) ensures extraction fires regularly even for low-token conversations
- **Token threshold** (20000) catches tool-heavy conversations where messages are few but token usage is high (multiple tool calls per turn, large tool outputs)
- Either threshold alone is sufficient to trigger — the first one crossed wins

**Fresh-counter read:** The trigger reads fresh values from the DB (not the potentially stale `conv` Python object) to accurately reflect the latest `save_message` auto-increments:

```python
stmt = select(
    AgentConversation.messages_since_last_summary,
    AgentConversation.tokens_since_last_summary,
).where(AgentConversation.id == conv.id)
```

**Lock:** PostgreSQL transaction-scoped advisory lock

```python
lock_key = conv.id.hex
lock_stmt = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))")
```

- Lock scope: transaction-level (released on commit or rollback)
- Contention: if another request holds the lock, `pg_try_advisory_xact_lock()` returns False and extraction is skipped
- The lock is NOT tied to the extraction result — it only prevents concurrent extractions. A failed extraction does NOT hold the lock across requests.

**Retries:** Retry behavior is implicitly driven by the continuous counters. Since `messages_since_last_summary` and `tokens_since_last_summary` are NOT reset on failure, they continue to accumulate. On the next request, the trigger will check the (now larger) fresh counters — as long as either still exceeds the threshold, extraction will fire again. Unlike the old modulo-based system, there is no "dead zone" between multiples.

**Failure behaviour:**

| Failure mode | Effect |
|---|---|
| Advisory lock not acquired | Skip extraction, log, return |
| Advisory lock acquisition throws | Log warning, return (extraction skipped) |
| `summarize_conversation()` fails (returns `success=False`) | Log warning; counters NOT reset → retry on next request |
| `summarize_conversation()` throws exception | Log warning; counters NOT reset → retry on next request |
| LLM extraction call fails | Error logged, returns `success=False` |

**In all failure cases:** counters are NOT reset. Extraction will be retried on the next request.

---

## 10. Retrieval Pathways

### A) Episodic Summary → system prompt injection

```
ConversationService.build_system_prompt()
    └─ ConversationSummarizer.get_conversation_context(conv.id)
         └─ SELECT AgentConversation WHERE id = conv.id
              └─ conv.summary + conv.last_extracted_at → formatted string
```

This happens on EVERY request to the conversation. The summary is prepended before the system prompt's main body.

### B) Semantic Memory → agent tool `extract_memory`

```
LLM decides to call extract_memory(query, conversation_id?, limit=10)
    └─ extract_memory_handler()
         ├─ FallbackSemanticMemoryProvider.search_semantic_memories(workspace_id, query, limit)
         │    └─ ZepMemoryProvider.search_semantic_memories() OR PgVectorMemoryProvider.search_semantic_memories()
         └─ Optional: fetch conv.summary from PostgreSQL
```

This is the LLM-driven retrieval path. The system prompt instructs the LLM to call this tool when the user references past conversations or expectations.

### C) Direct API call (internal)

```
search_semantic_memories() function at zep_memory.py:416-447
    └─ FallbackSemanticMemoryProvider.search_semantic_memories()
```

Legacy module-level function that wraps the same provider call. Returns a flat list of dicts with keys `fact`, `name`, `score`, `category`, `content`.

### D) Note/Knowledge semantic search (separate system)

`semantic_search.py` provides `semantic_search_notes()` and `semantic_search_knowledge()` — these search `notes` table embeddings (pgvector) and MongoDB knowledge units respectively. These are NOT part of the conversation memory system but share the `EmbeddingService` and pgvector infrastructure.

---

## 11. Architecture Diagram

```
                          USER
                           │
                    ┌──────▼───────┐
                    │  /agent/chat  │
                    │  /agent/stream│
                    └──────┬───────┘
                           │ AgentChatRequest {message, conversation_id, workspace_id, context}
                           ▼
              ┌────────────────────────────┐
              │       AgentService         │
              │  (agent_service.py)        │
              │  orchestrator              │
              └──┬────┬────────┬───────────┘
                 │    │        │
        ┌────────┘    │        └──────────────┐
        ▼             ▼                      ▼
┌────────────────┐ ┌────────────────┐ ┌───────────────────┐
│ConversationSvc │ │ToolExecutionSvc│ │MemoryTriggerSvc   │
│(conversation_  │ │(tool_execution_│ │(memory_trigger_   │
│ service.py)    │ │ service.py)    │ │ service.py)       │
│                │ │                │ │                   │
│- get_or_create │ │- execute_tools │ │- maybe_trigger()  │
│- load_history  │ │  _pass()       │ │  (advisory lock)  │
│- build_system_ │ │- check_tool_   │ │                   │
│  prompt        │ │  limits()      │ │  calls ───────────┤
│- check_token_  │ │- proactive     │ │         ▼         │
│  budget        │ │  triggers      │ │  ┌────────────────┐
└───────┬────────┘ └──────┬─────────┘ │  │ConversationSum-│
        │                 │           │  │marizer         │
        │                 │           │  │(conversation_  │
        │                 │           │  │ summarizer.py) │
        ▼                 ▼           │  │                │
┌───────────────────────────────────┐ │  │- summarize_    │
│        ConversationStore          │ │  │  conversation()│
│   (conversation_store.py)         │ │  │- get_conversat-│
│                                   │ │  │  ion_context() │
│- save_message()                   │ │  └───────┬────────┘
│- increment_message_count()        │ │          │
│- increment_token_count()          │ │          ▼
│- get_recent_messages_by_token_    │ │  ┌───────────────────────┐
│  budget() / get_recent_messages() │ │  │extract_and_store()   │
│- get_or_create_conversation()     │ │  │(memory_extraction_   │
└──────────────┬────────────────────┘ │  │ service.py)           │
               │                      │  │                      │
               │                      │  │ 1. Fetch new msgs    │
               ▼                      │  │ 2. Build prompt      │
┌──────────────────────┐              │  │ 3. Call LLM           │
│   PostgreSQL         │              │  │ 4. Parse response     │
│   agent_conversations│              │  │ 5. Store episodic     │
│   agent_messages     │              │  │ 6. Store semantic     │
└──────────────────────┘              │  └───────┬───────────────┘
                                      │          │
                                      │  ┌───────┴────────────────┐
                                      │  │                        │
                                      ▼  ▼                        ▼
                        ┌──────────────────────────┐  ┌───────────────────┐
                        │ SemanticMemoryProvider   │  │  PostgreSQL      │
                        │ (semantic_memory_        │  │ conv.summary     │
                        │  provider.py)            │  │ conv.title       │
                        │                          │  │ conv.last_       │
                        │ FallbackSemanticMemory   │  │   extracted_at   │
                        │   Provider               │  └───────────────────┘
                        │   ├─ ZepMemoryProvider   │
                        │   │   (zep_memory.py)    │
                        │   └─ PgVectorMemory      │
                        │       Provider           │
                        │   (pgvector_memory_      │
                        │    provider.py)          │
                        └──────────┬───────────────┘
                                   │
                     ┌─────────────┴──────────────┐
                     ▼                            ▼
            ┌──────────────────┐    ┌──────────────────────┐
            │  Zep Cloud       │    │  PostgreSQL          │
            │  (Zep graph)     │    │  semantic_memories   │
            │  zep_cloud SDK   │    │  + pgvector index    │
            └──────────────────┘    │  + EmbeddingService  │
                                    │  (embedding_service  │
                                    │   .py)               │
                                    │  + Redis cache       │
                                    └──────────────────────┘

                    RETRIEVAL PATHWAYS

┌──────────────────────────────────────────────────────────┐
│ 1. Episodic Summary → injected into system prompt        │
│    (per-request, same conversation)                       │
│                                                          │
│ 2. Semantic Memory → extract_memory tool                 │
│    (LLM-driven, cross-conversation)                      │
│    └─ FallbackSemanticMemoryProvider                     │
│         .search_semantic_memories()                      │
│                                                          │
│ 3. Semantic Memory → search_semantic_memories() API      │
│    (programmatic access, legacy shim)                    │
└──────────────────────────────────────────────────────────┘

                    BACKGROUND WORKERS

┌──────────────────────────────────────────────────────────┐
│ LLMProcessorWorker (llm_processor_worker.py)             │
│   - Consumes LLM tasks from Redis Stream                 │
│   - Processes OCR frames + transcript segments            │
│   - Extracts knowledge units → MongoDB                   │
│   - SEPARATE from conversation memory system              │
│                                                          │
│ (No background workers exist for conversation memory.    │
│  Memory extraction is triggered synchronously in the     │
│  request path.)                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 12. Component Inventory

### 12.1 `AgentService` (`agent_service.py`)

| Property | Value |
|---|---|
| **Responsibility** | Main orchestrator: decides flow, coordinates sub-services |
| **Inputs** | `User`, `AsyncSession`, `message`, `conversation_id`, `workspace_id`, `context` |
| **Outputs** | `{"conversation_id", "reply"}` or SSE event stream |
| **Dependencies** | `ConversationService`, `ToolExecutionService`, `MemoryTriggerService`, `ModelClient`, `ConversationStore`, `ToolRegistry` |
| **Key method** | `handle()` — non-streaming; `handle_streaming_generator()` — streaming |

### 12.2 `ConversationService` (`conversation_service.py`)

| Property | Value |
|---|---|
| **Responsibility** | Conversation lifecycle, history loading, system prompt construction, summary injection |
| **Key methods** | `get_or_create()`, `load_history()`, `build_system_prompt()`, `check_token_budget()`, `get_summarizer()`, `save_user_message()`, `increment_message_count()`, `increment_token_count()` |
| **Dependencies** | `ConversationStore`, `ConversationSummarizer`, `ModelClient` |

### 12.3 `ConversationStore` (`conversation_store.py`)

| Property | Value |
|---|---|
| **Responsibility** | Low-level DB operations for conversations and messages |
| **Key methods** | `save_message()`, `increment_message_count()`, `increment_token_count()`, `get_recent_messages()`, `get_recent_messages_by_token_budget()`, `get_or_create_conversation()`, `get_conversation_by_id()`, `list_conversations()`, `delete_conversation()`, `update_conversation_title()`, `update_conversation_timestamp()` |
| **Dependencies** | `AsyncSession`, SQLAlchemy models `AgentConversation`, `AgentMessage` |

### 12.4 `ConversationSummarizer` (`conversation_summarizer.py`)

| Property | Value |
|---|---|
| **Responsibility** | Summarization wrapper: threshold constant, orchestrates extraction, provides summary context for prompt injection |
| **Key constants** | `MESSAGE_THRESHOLD = 20` |
| **Key methods** | `should_summarize()`, `summarize_conversation()`, `get_conversation_context()` |
| **Dependencies** | `AsyncSession`, `extract_and_store()`, `AgentConversation` |

### 12.5 `MemoryTriggerService` (`memory_trigger_service.py`)

| Property | Value |
|---|---|
| **Responsibility** | Decides whether to trigger memory extraction, acquires advisory lock |
| **Key method** | `maybe_trigger(summarizer, conv)` |
| **Dependencies** | `AsyncSession`, `ConversationSummarizer` |
| **Locking** | PostgreSQL `pg_try_advisory_xact_lock(hashtextextended(conv_id, 0))` |

### 12.6 `extract_and_store()` (`memory_extraction_service.py`)

| Property | Value |
|---|---|
| **Responsibility** | Full extraction pipeline: fetch messages, call LLM, parse response, store episodic + semantic |
| **Inputs** | `conversation_id`, `db` |
| **Outputs** | `{"success", "episodic_stored", "semantic_count", "model_used", "title", "new_messages"}` |
| **Dependencies** | `ModelClient`, `build_extraction_messages()`, `_parse_extraction_response()`, `get_semantic_memory_provider()` |
| **Guard** | Requires ≥5 new messages since `last_extracted_at` |

### 12.7 `build_extraction_messages()` (`memory_extraction_prompt.py`)

| Property | Value |
|---|---|
| **Responsibility** | Builds [system, user] message array for the extraction LLM |
| **Prompt file** | `app/ai/prompts/memory/semantic_extraction.md` |
| **Dependencies** | `prompt_loader.load()` |

### 12.8 `SemanticMemoryProvider` interface (`semantic_memory_provider.py`)

| Property | Value |
|---|---|
| **Responsibility** | Abstract interface for semantic memory backends |
| **Methods** | `ensure_user()`, `add_semantic_memory()`, `add_semantic_memories_batch()`, `search_semantic_memories()` |
| **Implementations** | `ZepMemoryProvider`, `PgVectorMemoryProvider` |

### 12.9 `FallbackSemanticMemoryProvider` (`semantic_memory_provider.py:72-148`)

| Property | Value |
|---|---|
| **Responsibility** | Wraps Zep as primary, PgVector as fallback |
| **Fallback trigger** | `SemanticMemoryUnavailable` exception from Zep |
| **Dependencies** | `ZepMemoryProvider`, `PgVectorMemoryProvider` |

### 12.10 `ZepMemoryProvider` (`zep_memory.py:88-299`)

| Property | Value |
|---|---|
| **Responsibility** | Zep Cloud integration for semantic memory |
| **Storage** | `client.graph.add(type="json")` |
| **Search** | `client.graph.search(scope="edges", reranker="cross_encoder")` |
| **Dedup** | 2-phase: in-process LRU + Zep similarity check (score ≥ 0.95) |
| **Dependencies** | `zep_cloud` SDK, `httpx`, `settings.ZEP_API_KEY` |

### 12.11 `PgVectorMemoryProvider` (`pgvector_memory_provider.py`)

| Property | Value |
|---|---|
| **Responsibility** | Local pgvector fallback for semantic memory |
| **Storage** | INSERT into `semantic_memories` table |
| **Search** | Cosine similarity via `<->` operator, HNSW index on `embedding` |
| **Embedding** | `EmbeddingService.embed_text()` / `.embed_query()` |
| **Dedup** | 2-phase: in-process LRU + pgvector cosine similarity (score ≥ 0.90) |
| **Dependencies** | `AsyncSession`, `EmbeddingService`, pgvector |

### 12.12 `EmbeddingService` (`embedding_service.py`)

| Property | Value |
|---|---|
| **Responsibility** | Text → vector embeddings via OpenAI-compatible API, Redis caching |
| **Cache** | SHA256 key, 30-day TTL |
| **Model** | `settings.EMBEDDING_MODEL` |
| **Dimensions** | `settings.EMBEDDING_DIMENSIONS` |
| **Dependencies** | `AsyncOpenAI`, `redis.asyncio` |

### 12.13 `ModelClient` (`model_client.py`)

| Property | Value |
|---|---|
| **Responsibility** | Unified LLM client: one request runs on one model (the requested one, or the default), plus retry on transient errors. Rotation, cross-model fallback and the local rate-limit budget were removed 2026-08-20 — failover is the LLM service's job |
| **Provider** | `OpenAIProvider` (OpenAI-compatible API) |
| **Key methods** | `generate()`, `stream()` |
| **Usage in memory** | Called by `extract_and_store()` for extraction, and by `_generate_conversation_title()` |

### 12.14 `extract_memory` tool (`extract_memory.py`)

| Property | Value |
|---|---|
| **Responsibility** | LLM-callable tool for retrieving semantic memories + episodic summary |
| **Inputs** | `query`, `conversation_id` (optional), `limit` |
| **Outputs** | Formatted text with semantic memories + episodic summary |
| **Dependencies** | `FallbackSemanticMemoryProvider`, `AgentConversation` |

### 12.15 Token utilities (`utils/tokens.py`)

| Property | Value |
|---|---|
| **Responsibility** | Token estimation for history management |
| **Functions** | `estimate_tokens(text)`, `estimate_message_tokens(role, content, tool_name, tool_output)` |
| **Encoding** | `tiktoken` cl100k_base → char-based fallback (`len/3.5`) |

---

## 13. Architectural Assumptions

### Ordering assumptions

1. **`message_count` is incremented twice per request.** The trigger threshold assumes exactly 2 increments (user + assistant). If the assistant reply fails to save (e.g., LLM error), `message_count` still reflects the user message alone, which may delay the next extraction by one request.

2. **Messages are saved before `maybe_trigger()` is called.** This ensures the extraction sees the new messages' `created_at` timestamps in the incremental fetch.

3. **`created_at` is monotonically increasing.** The incremental extraction filter (`AgentMessage.created_at > conv.last_extracted_at`) assumes strict monotonicity. Since `created_at` is set to `datetime.utcnow()`, clock skew between requests could theoretically cause a fetch to miss messages created at exactly the same microsecond as `last_extracted_at`.

### Timestamp assumptions

4. **`last_extracted_at` is from `datetime.utcnow()`, not server-side `NOW()`.** This means the timestamp is set by the application, not the database. If the application clock drifts, extraction boundaries become inaccurate.

5. **`last_extracted_at` is ONLY updated on SUCCESS.** If the extraction LLM fails or returns invalid JSON, `last_extracted_at` stays at its previous value and the same messages will be retried on the next trigger.

### Conversation lifecycle assumptions

6. **A conversation always belongs to exactly one user.** `ConversationStore.get_conversation_by_id()` filters by both `conversation_id` AND `user_id`.

7. **Workspace ID governs semantic memory scope, not user ID.** In `extract_and_store()`, semantic memories are stored under `workspace_id_str` as the Zep/PgVector `user_id`, not the user's own ID (`memory_extraction_service.py:169-178`). This means all users in the same workspace share semantic memory.

8. **Semantic memories are per-workspace, not per-conversation.** They are stored with `user_id = workspace_id_str` in both Zep and PgVector. This is explicitly noted in the migration comment at `alembic/versions/p0123456789l_create_semantic_memory_table.py:28-29`.

### Extraction timing assumptions

9. **Extraction is synchronous in the request path.** `maybe_trigger()` is called inside the HTTP request handler. The LLM extraction call blocks the response. For long conversations, this can significantly increase latency.

10. **New messages should NOT be empty.** The extraction guard requires ≥5 new messages since `last_extracted_at` (`memory_extraction_service.py:108-109`). If multiple extraction triggers fire before 5 new messages accumulate (e.g., rapid tool-heavy conversation), extraction is silently skipped.

11. **The modulo window `>= 2` prevents races.** This assumes that `message_count` can jump by at most 2 between checks (user + assistant). With parallel requests on the same conversation, the count could jump by more, making extraction skip entirely until the next multiple of 20.

### Token budget assumptions

12. **`total_token_count` is only accumulated in the streaming path.** The non-streaming `handle()` method never calls `increment_token_count()`. This means daily budget gating based on `total_token_count` is inconsistent across the two paths.

13. **Provider `usage.total_tokens` is the authoritative token count.** The streaming path stores this per-request and increments `total_token_count`. Tool messages do not contribute to `total_token_count` (they have no provider usage).

### Storage assumptions

14. **Episodic summary is a single overwritten text field.** There is no versioning or append log. Only the latest summary survives.

15. **Semantic memory dedup is best-effort.** The in-process LRU resets on process restart. The similarity check has a high threshold (0.95 for Zep, 0.90 for PgVector). Near-duplicates with slightly different phrasing may still be inserted.

---

## 14. Technical Debt

### D1. (PARTIALLY FIXED) `AgentMessage.token_count` is now populated

**Resolution:**
- `save_message()` now auto-calculates `token_count` via `estimate_weighted_message_tokens()` when the caller does not provide one
- Tool messages use the weighted policy: `min(estimated_tokens × 0.25, 800)`
- User and assistant messages use the standard `estimate_message_tokens()`
- The column is no longer perpetually NULL

### D2. `total_token_count` asymmetry between streaming and non-streaming

**Evidence:**
- Streaming: `agent_service.py:472` calls `increment_token_count(conv.id, total_usage["total_tokens"])`
- Non-streaming: `agent_service.py:212` logs the breakdown but NEVER stores tokens
- The budget guard `check_token_budget()` checks `conv.total_token_count` — only effective for streaming users

### D3. (FIXED) Failed extraction now retries on next request

**Resolution:**
- The hybrid trigger uses `messages_since_last_summary` and `tokens_since_last_summary` (cumulative counters that are NOT reset on failure)
- Counters continue to accumulate past the threshold
- On the next request, the trigger re-evaluates against the (now larger) fresh counters — extraction fires again as long as either still exceeds the threshold
- No "dead zone" between threshold multiples

### D4. Old memory tables are dropped but the migration history still contains references

**Evidence:**
- `005_create_memory_tables.py` created `conversation_summaries`, `semantic_memories` (old schema), `preference_memories`, `episodic_memories`, `knowledge_chunks`, `action_history`, `memory_links`, `memory_embeddings`
- `m9012345678i_drop_old_memory_tables.py` dropped them all
- `p0123456789l_create_semantic_memory_table.py` created a new `semantic_memories` with a completely different schema
- The old tables used UUID `user_id`, the new one uses String `user_id` (for workspace_id)
- The migration chain is correct but the history is misleading — code references to "memory tables" could refer to two different schemas

### D5. Mismatched dedup score thresholds

**Evidence:**
- Zep dedup threshold: `ZEP_DEDUPE_SCORE = 0.95` (cross-encoder reranker)
- PgVector dedup threshold: `PGVECTOR_DEDUPE_SCORE = 0.90` (cosine similarity)
- The code comment at `pgvector_memory_provider.py:45-48` explicitly notes they are NOT comparable
- This means the two backends behave differently for dedup, which could cause data drift during Zep outages

### D6. In-process dedup caches are process-local and unbounded across conversations

**Evidence:**
- `_dedupe_cache` is limited to 4096 entries in both `zep_memory.py` and `pgvector_memory_provider.py`
- Each entry is keyed on `(user_id, content)` — 4096 is shared across ALL conversations
- Under heavy usage with many users and conversations, the cache may thrash
- On process restart, the cache is empty — ALL previously deduped memories will be checked again against Zep/PgVector (phase 2 dedup still works)

### D7. Legacy shims in `zep_memory.py`

**Evidence:**
- `zep_memory.py:302-447` contains module-level functions (`ensure_user`, `add_semantic_memory`, `add_semantic_memories_batch`, `search_semantic_memories`, `_check_zep_duplicate`)
- These are called "legacy shims" in the code comments (line 347-350)
- They wrap `_get_provider()` which returns a singleton `ZepMemoryProvider`
- They catch `SemanticMemoryUnavailable` and return sentinel values (False, 0, [])
- The `FallbackSemanticMemoryProvider` already handles the same fallback logic — the shims duplicate this

### D8. `message_count` includes tool messages but `increment_message_count` is only called for user + assistant

**Evidence:**
- Tool messages are saved via `store.save_message(role="tool", ...)` at `tool_execution_service.py:301` and `395`
- Tool saves do NOT call `increment_message_count()`
- `message_count` reflects only user + assistant messages, NOT tool messages

**Note:** This is no longer relevant for the extraction trigger — the trigger now uses `messages_since_last_summary` which IS auto-incremented for ALL roles (including tool). The hybrid design intentionally counts tool messages toward the trigger to handle tool-heavy conversations.

### D9. No background worker for memory extraction

**Evidence:**
- `maybe_trigger()` runs synchronously in the request path
- The `extract_and_store()` function calls an LLM (could take 5-30 seconds)
- This blocks the HTTP response
- Contrast with the LLMProcessorWorker which processes OCR/transcript LLM tasks asynchronously via Redis Stream

### D10. `summary` field has no versioning

**Evidence:**
- `conv.summary = episodic_summary` at `memory_extraction_service.py:152` — direct overwrite
- No history of what was previously in the summary
- If the extraction LLM produces a degraded summary, the previous good summary is permanently lost

### D11. `created_at` is overwritten on same-role collapse

**Evidence:**
- `conversation_store.py:183`: `last_msg.created_at = datetime.utcnow()` when collapsing consecutive same-role messages
- This changes the message's timestamp, potentially affecting the precision of the incremental fetch cursor
- If the collapsed message was created before `last_extracted_at`, setting `created_at = now()` could cause it to be included in the next extraction even though it was already summarized

### D12. `tool_output` is stored with full content but truncated in extraction

**Evidence:**
- Tool outputs are stored in full in `agent_messages.tool_output` (JSONB)
- In extraction, they are truncated to `MEMORY_TOOL_OUTPUT_MAX_CHARS = 25000` (at `memory_extraction_service.py:55`)
- In conversation history, they are truncated to `TOOL_OUTPUT_MAX_CHARS = 4000` (in `openai_provider.py`)
- Two different truncation limits exist for the same data, used in different contexts

### D13. No retry mechanism for Zep API failures

**Evidence:**
- `ZepMemoryProvider.add_semantic_memory()` raises `SemanticMemoryUnavailable` on API error
- `FallbackSemanticMemoryProvider._try_fallback()` catches this and retries on PgVector
- But the Zep call itself has no retry — a transient Zep failure immediately falls back to PgVector
- The Zep client has no built-in retry logic (the `httpx` client default is no retries)

### D14. The `prompt_loader` hides prompt file paths

**Evidence:**
- `MEMORY_EXTRACTION_SYSTEM_PROMPT = load("memory/semantic_extraction.md")` at `memory_extraction_prompt.py:11`
- The prompt file lives at `app/ai/prompts/memory/semantic_extraction.md`
- The path prefix `app/ai/prompts/` is implicit in the loader — not visible at the call site
- This makes it harder to find prompt files when reading extraction code

---

## Appendix: Key Constants

| Constant | Value | Location | Purpose |
|---|---|---|---|
| `MESSAGE_THRESHOLD` | 20 | `conversation_summarizer.py:25` | Message-count trigger threshold (hybrid: OR with token threshold) |
| `TOKEN_THRESHOLD` | 20000 | `conversation_summarizer.py:26` | Token-count trigger threshold (hybrid: OR with message threshold) |
| `TOOL_TOKEN_WEIGHT` | 0.25 | `utils/tokens.py` | Weight for tool message tokens in `estimate_weighted_message_tokens()` |
| `TOOL_TOKEN_CAP` | 800 | `utils/tokens.py` | Cap for weighted tool message tokens (`estimated_tokens × 0.25, capped at 800`) |
| `MAX_CONVERSATION_HISTORY` | 10 | `agent_service.py:35` | Message-count history mode limit |
| `MAX_HISTORY_TOKENS` | 8000 | `agent_service.py:39` | Token-budget history mode limit |
| `MAX_TOKENS_PER_DAY_PER_USER` | 2,000,000 | `agent_service.py:38` | Daily token budget guard |
| `MAX_TOOL_TURNS` | 30 | `agent_service.py:36` | Max LLM tool-calling turns |
| `MAX_SAME_TOOL_CALLS` | 20 | `agent_service.py:37` | Per-tool call limit |
| `MAX_TURN_RETRIES` | 3 | `agent_service.py:40` | LLM retry count |
| `MEMORY_TOOL_OUTPUT_MAX_CHARS` | 25000 | `memory_extraction_service.py:43` | Tool output truncation for extraction |
| `ZEP_DEDUPE_SCORE` | 0.95 | `zep_memory.py:49` | Zep similarity dedup threshold |
| `PGVECTOR_DEDUPE_SCORE` | 0.90 | `pgvector_memory_provider.py:48` | PgVector cosine dedup threshold |
| `ZEP_CLIENT_TIMEOUT` | 10.0s | `zep_memory.py:52` | Zep HTTP timeout |
| `_DEDUPE_CACHE_LIMIT` | 4096 | `zep_memory.py:43`, `pgvector_memory_provider.py:40` | LRU dedup cache size |
| `EMBEDDING_CACHE_TTL` | 86400 × 30 | `embedding_service.py:48` | Embedding Redis cache TTL |
| `MIN_KNOWLEDGE_VALUE` | 0.3 | `llm_processor_worker.py:46` | Knowledge unit extraction threshold |

---

## Appendix: Database Tables Summary

| Table | Created by migration | Columns related to memory | Purpose |
|---|---|---|---|---|
| `agent_conversations` | `f1234567890b` | `summary`, `message_count`, `total_token_count`, `last_extracted_at`, `last_summary_message_id`, `tokens_since_last_summary`, `messages_since_last_summary` | Conversation-level data |
| `agent_messages` | `f1234567890b` | `token_count` (now populated via auto-count in `save_message`) | Individual messages |
| `semantic_memories` | `p0123456789l` | `user_id` (workspace ID), `category`, `content`, `embedding` (vector(768)), `confidence`, `expected_lifetime` | PgVector fallback for semantic memory |
| `notes` | `g2345678901c` | `embedding` (vector(768)) | Note embeddings for `semantic_search_notes` |

**Tables that existed in `005` but were dropped by `m9012345678i`:** `conversation_summaries`, `preference_memories`, `episodic_memories`, `knowledge_chunks`, `action_history`, `memory_links`, `memory_embeddings`.
