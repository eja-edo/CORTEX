# Implementation Plan: Summary Cursor & Trigger Refactor

## Overview

Replace the timestamp-based `last_extracted_at` cursor for Conversation Summary with a message-ID-based cursor `last_summary_message_id`. Implement hybrid trigger (message-count OR token-count). Add weighted token policy for tool messages.

## Architecture Decisions (locked)

See `docs/architecture/memory-architecture.md` for full context. Key decisions:

1. `last_summary_message_id UUID NULL` replaces `last_extracted_at` as Summary cursor
2. Hybrid trigger: `messages_since_last_summary >= MESSAGE_THRESHOLD OR tokens_since_last_summary >= TOKEN_THRESHOLD`
3. Tool token policy: `min(estimated_tokens × 0.25, 800)`
4. `last_extracted_at` kept but only for Semantic Memory (unchanged behavior)

## Task List

### Phase 1: Schema + Model
- [ ] Task 1: Add fields to AgentConversation model + create migration

### Phase 2: Token utilities
- [ ] Task 2: Add weighted token estimation function

### Phase 3: ConversationStore
- [ ] Task 3: Auto-calculate token_count in save_message, add counter methods

### Phase 4: MemoryExtractionService
- [ ] Task 4: Fetch by message_id cursor, update cursor on success

### Phase 5: ConversationSummarizer
- [ ] Task 5: Add TOKEN_THRESHOLD, reset counters, update context

### Phase 6: MemoryTriggerService
- [ ] Task 6: Hybrid trigger

### Phase 7: AgentService + ConversationService
- [ ] Task 7: Wire token/message counting after saves

### Phase 8: Documentation
- [ ] Task 8: Update memory-architecture.md, create conversation-summary.md

### Checkpoint
- [ ] All tests pass, migration works, architecture doc updated

## Dependency Graph

```
Task 1 (model+schema)
    │
    ▼
Task 2 (token utils) ──► Task 3 (store)
    │                        │
    │                        ▼
    │                  Task 4 (extraction svc)
    │                        │
    │                        ▼
    └─────────────────► Task 5 (summarizer)
                               │
                               ▼
                         Task 6 (trigger svc)
                               │
                               ▼
                         Task 7 (agent svc wiring)
                               │
                               ▼
                         Task 8 (docs)
```

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| `last_extracted_at` readers missed | MED — semantic memory breaks | Exhaustive grep for all `last_extracted_at` reads |
| Message collapse changes created_at | LOW — cursor resolves to message timestamp | Documented assumption; cursor still stable because message ID is fixed |
| Existing conversations have NULL `last_summary_message_id` | MED — first fetch returns all messages | Acceptable: first summary after migration processes entire conversation |
