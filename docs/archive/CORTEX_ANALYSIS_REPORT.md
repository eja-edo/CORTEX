# Cortex — Product & Architecture Analysis Report

> **Author**: AI Product Architect / Software Architect
> **Date**: 2026-07-28
> **Scope**: Full codebase audit against the Cortex product vision

---

## Executive Summary

### What Cortex Is Today

Cortex is a **FastAPI-based productivity backend** with a **React/TypeScript frontend** that provides:

- **AI Chat** with tool-calling (notes, schedules, search, web)
- **Note-taking** with hierarchical structure, versioning, and diff-based patching
- **Schedule management** with recurring events, reminders, and bidirectional Google Calendar sync
- **Workspaces** for multi-user collaboration with role-based permissions
- **Media processing** pipeline (screen recording → OCR/transcription → LLM extraction → knowledge units)
- **Workflow runtime** (separate service) backed by Temporal with a React Flow visual builder
- **SSE-based real-time** notifications and sync status
- **Basic undo system** (Redis snapshot for mutating tools)
- **Episodic + Semantic memory** (PostgreSQL summaries + Zep graph)

### What Cortex Is Becoming

The product vision describes a **proactive personal AI assistant / personal operating system** that:

- Understands user intent and context
- Remembers commitments, preferences, and goals
- Plans and schedules work
- Executes actions through tools and integrations
- Monitors progress and detects risks
- Proactively assists at the right time
- Learns from behavior and feedback

### The Biggest Gaps

| Gap | Severity | Impact |
|-----|----------|--------|
| **No Goals system** | Critical | Cannot answer "What am I trying to achieve?" |
| **No Event Bus** | Critical | No centralized event routing for proactive workflows |
| **No Proactive Engine** | Critical | Cannot decide when/how to interrupt users |
| **No Planning/Routing model** | High | Cannot answer "What should I do next?" |
| **No Commitments model** | High | Cannot track promises, follow-ups, deadlines from conversations |
| **No Task system (separate from schedules)** | High | Tasks are conflated with calendar events |
| **No Context Graph / Relations** | High | Cortex cannot connect entities across domains |
| **No structured Intents/Commands** | Medium | AI directly calls tools without an intent layer |
| **No AI cost optimization** | Medium | No model routing tiers, no caching, no small-model fallbacks |
| **No User preferences store** | Medium | Preferences live in localStorage, not queryable by AI |
| **No email/messaging integrations** | Medium | No external context except Google Calendar |

### The Biggest Architectural Risks

1. **Tool Registry is a global mutable singleton** — No capability-based access control, no schema enforcement, no versioning
2. **Event handling is ad-hoc** — Redis streams for transcription, Redis pub/sub for sync, SSE for frontend, but no unified event bus
3. **AgentService is monolithic** — ~1000 lines, handles conversation, tools, context, memory, and streaming in one class
4. **Sync SQLAlchemy used in async context** — `next(get_db())` in `reminder_worker.py` and other async workers
5. **workflow_service is a separate service** — Not connected to the core backend event system
6. **Memory depends on Zep (external cloud service)** — Single point of failure, no self-hosted fallback
7. **No integration testing for AI flows** — Tests exist but don't test end-to-end AI + tool flows

### The Highest-Value Opportunities

1. **Build Event Bus** — Foundation for all proactive capabilities
2. **Build Goals + Commitments** — Highest product value, enables planning and monitoring
3. **Build Proactive Engine** — Rules + policies + AI reasoning for timing-based assistance
4. **Build Intent/Command Layer** — Decouples NL from execution, enables structured undo, audit, and permissions
5. **Optimize AI costs** — Implement model routing tiers (deterministic → small model → fast LLM → reasoning)

---

## 1. Current System Inventory

### 1.1 Backend (`backend/`)

| Component | Path | Lines | Language | Status |
|-----------|------|-------|----------|--------|
| FastAPI App Init | `backend/app/__init__.py` | 226 | Python | Functional |
| Config | `backend/app/config.py` | 165 | Python | Functional |
| Database Sync | `backend/app/database.py` | 28 | Python | Functional |
| Database Async | `backend/app/database_async.py` | 28 | Python | Functional |
| Models | `backend/app/models.py` | 606 | Python | Functional |
| Schemas | `backend/app/schemas.py` | 574 | Python | Functional |
| Security/Auth | `backend/app/security.py` | - | Python | Functional |

#### API Routes (`backend/app/api/`)

| Endpoint | File | Methods | Purpose |
|----------|------|---------|---------|
| `/api/auth/...` | `auth.py` | POST | Login, register, refresh tokens |
| `/api/agent/chat` | `agent.py` | POST | Non-streaming AI chat |
| `/api/agent/stream/chat` | `agent.py` | POST | Streaming AI chat (SSE) |
| `/api/agent/conversations` | `agent.py` | GET, DELETE | List/get/delete conversations |
| `/api/agent/actions/{id}/revert` | `agent.py` | POST | Revert mutating action |
| `/api/agent/complete` | `agent.py` | POST | One-shot AI (internal) |
| `/api/schedules/...` | `schedules.py` | CRUD | Schedule management |
| `/api/notes/...` | `notes.py` | CRUD | Note management |
| `/api/workspaces/...` | `workspaces.py` | CRUD | Workspace management |
| `/api/notifications/...` | `notifications.py` | GET | List/mark-read notifications |
| `/api/google-calendar/...` | `google_calendar.py` | OAuth | Google Calendar auth + sync |
| `/api/knowledge/...` | `knowledge.py` | - | Knowledge extraction from assets |
| `/api/assets/...` | `assets.py` | CRUD | Media asset management |
| `/api/images/...` | `images.py` | - | Image uploads |
| `/api/upload/...` | `upload.py` | - | Multipart file uploads |
| `/api/proposals/...` | `proposals.py` | CRUD | AI note edit proposals |
| `/api/internal/...` | `internal.py` | - | Service-to-service endpoints |
| `/api/sse/sync/events` | `sse/` | GET | Calendar sync events (SSE) |
| `/api/sse/notifications/events` | `sse/` | GET | Real-time notifications (SSE) |

#### Services (`backend/app/services/`)

| Service | File | Purpose |
|---------|------|---------|
| ScheduleService | `schedule_service.py` | Business logic for schedules |
| NoteService | `notes.py` | Business logic for notes |
| ReminderService | `reminder_service.py` | Create/cancel reminders |
| ReminderWorker | `reminder_worker.py` | Background polling for due reminders |
| GoogleCalendarSync | `google_calendar_sync.py` | Bidirectional Google Calendar sync |
| GoogleSyncWorker | `google_sync_worker.py` | Background sync queue processor |
| NotificationService | `notifications.py` | CRUD for notifications |
| MemoryExtraction | `memory_extraction_service.py` | LLM-based memory extraction pipeline |
| ZepMemory | `zep_memory.py` | Zep cloud integration for semantic memory |
| MongoService | `mongo_service.py` | MongoDB for transcriptions/OCR data |
| LLMProcessing | `llm_processing.py` | LLM window processing for asset knowledge |
| LLMProcessorWorker | `llm_processor_worker.py` | Background Redis-stream consumer for LLM |
| TranscriptionConsumer | `transcription_results_consumer.py` | Redis stream → MongoDB consumer |
| ProposalService | `proposal_service.py` | Note edit proposal logic |
| MarkdownConfig | `markdown_config.py` | Markdown rendering configuration |
| RecurrenceService | `recurrence.py` | Recurring schedule logic |
| Documents | `documents.py` | Document processing |
| WorkspacePermission | `workspace_permission.py` | Workspace access control |

#### AI Layer (`backend/app/ai/`)

| Component | Path | Purpose |
|-----------|------|---------|
| AgentService | `agents/agent_service.py` | Main agent loop (1000+ lines) |
| ModelClient | `agents/model_client.py` | One model per request + retry (rotation removed 2026-08-20) |
| OpenAIProvider | `agents/openai_provider.py` | OpenAI-compatible API client |
| BaseProvider | `agents/base_provider.py` | Abstract provider interface |
| ProviderTypes | `agents/provider_types.py` | Dataclasses for messages, tools, config |
| ToolRegistry | `agents/tool_registry.py` | Global tool registration + execution |
| ToolContext | `agents/tool_context.py` | Per-request tool execution context |
| ConversationStore | `agents/conversation_store.py` | DB persistence for conversations |
| ConversationSummarizer | `agents/conversation_summarizer.py` | Triggers memory extraction |
| ActionSnapshotStore | `agents/action_snapshot_store.py` | Redis+PG undo snapshots |
| EmbeddingService | `agents/embedding_service.py` | Text embedding for vector search |
| SemanticSearch | `agents/semantic_search.py` | Semantic search across entities |

#### AI Tools (`backend/app/ai/tools/`)

16 registered tools:

| Tool | Type | Revertable |
|------|------|------------|
| `search_notes` | Read | No |
| `create_note` | Write | Yes |
| `update_note` | Write | Yes |
| `get_schedules` | Read | No |
| `create_schedule` | Write | Yes |
| `update_schedule` | Write | Yes |
| `search_knowledge` | Read | No |
| `summarize_asset` | Read | No |
| `get_notifications` | Read | No |
| `extract_memory` | Read | No |
| `revert_action` | Write | N/A (undo tool) |
| `web_search` | Read | No |
| `web_fetch` | Read | No |
| `deep_research` | Read | No |
| `neural_search` | Read | No |

#### Skills (`backend/app/ai/skills/`)

5 registered skills with SKILL.md:

| Skill | Directory | Purpose |
|-------|-----------|---------|
| memory | `skills/memory/` | Memory retrieval strategies |
| planning | `skills/planning/` | Task/goal planning |
| research | `skills/research/` | Web research workflows |
| workflow | `skills/workflow/` | Workflow orchestration |
| reasoning | `skills/reasoning/` | Step-by-step reasoning |

#### Background Workers

| Worker | Type | Purpose |
|--------|------|---------|
| ReminderWorker | Polling (30s) | Check due reminders → create notifications |
| GoogleSyncWorker | Polling | Process sync queue → push/pull Google Calendar |
| LLMProcessorWorker | Redis Stream | Process asset knowledge extraction |
| TranscriptionConsumer | Redis Stream | Save transcription chunks to MongoDB |

### 1.2 Frontend (`frontend/`)

| Component | Path | Purpose |
|-----------|------|---------|
| App.tsx | `src/App.tsx` | Main app shell, routing, SSE connections |
| AskAI | `src/components/AskAI.tsx` | AI chat panel with streaming, tool visualization |
| GlobalHome | `src/components/GlobalHome.tsx` | Home dashboard |
| CalendarView | `src/components/CalendarView.tsx` | Schedule calendar with drag-create |
| WorkspaceNoteEditor | `src/components/WorkspaceNoteEditor.tsx` | Markdown note editor |
| WorkflowBuilder | `src/components/WorkflowBuilder.tsx` | React Flow visual workflow builder |
| SettingsPanel | `src/components/SettingsPanel.tsx` | Google Calendar, theme, settings |
| AuthPanel | `src/components/AuthPanel.tsx` | Login/register |
| NotificationBell | `src/components/NotificationBell.tsx` | Notification inbox |
| DiffReviewPanel | `src/components/DiffReviewPanel.tsx` | Review AI note proposals |
| ConversationHistory | `src/components/ConversationHistory.tsx` | AI conversation list |
| ConversationDetail | `src/components/ConversationDetail.tsx` | AI conversation messages |
| TokenBudgetIndicator | `src/components/TokenBudgetIndicator.tsx` | Token usage display |
| WorkspaceSwitcher | `src/components/WorkspaceSwitcher.tsx` | Workspace selector |

#### Frontend Stores

| Store | File | Purpose |
|-------|------|---------|
| conversationStore | `stores/conversationStore.ts` | AI conversation state |
| editorStore | `stores/editorStore.ts` | Note editor state |

#### Frontend Hooks

| Hook | File | Purpose |
|------|------|---------|
| useAuth | `hooks/useAuth.ts` | Auth state, login, register |
| useWorkspaces | `hooks/useWorkspaces.ts` | Workspace CRUD |
| useNotes | `hooks/useNotes.ts` | Notes CRUD with hierarchy |
| useSchedules | `hooks/useSchedules.ts` | Schedule CRUD + Google Calendar |
| useAssets | `hooks/useAssets.ts` | Media asset management |
| useNotifications | `hooks/useNotifications.ts` | Notification CRUD |
| useWorkflows | `hooks/useWorkflows.ts` | Workflow CRUD |
| useNoteProposals | `hooks/useNoteProposals.ts` | AI proposal review |

#### Frontend Services

| Service | File | Purpose |
|---------|------|---------|
| API | `services/api.ts` | HTTP client with auth + streaming |
| Routes | `services/routes.ts` | URL route helpers |

### 1.3 Workflow Service (`workflow_service/`)

| Component | Path | Purpose |
|-----------|------|---------|
| FastAPI App | `app/main.py` | Workflow service on port 8001 |
| Workflow API | `app/api/v1/workflows.py` | Workflow CRUD |
| Execution API | `app/api/v1/executions.py` | Execution history |
| Webhook API | `app/api/v1/webhooks.py` | External webhook triggers |
| Actions API | `app/api/v1/actions.py` | Action execution |
| Temporal Workflow | `app/temporal/workflows.py` | CortexWorkflow Temporal definition |
| Temporal Activities | `app/temporal/activities.py` | Action execution activities |
| Temporal Client | `app/temporal/client.py` | Temporal client connection |
| Temporal Worker | `app/temporal/worker.py` | Background Temporal worker |
| Action Registry | `app/actions/registry.py` | Plugin-based action system |
| Built-in Actions | `app/actions/builtin/` | Pre-built action implementations |
| Trigger Engine | `app/triggers/` | Internal event + webhook triggers |
| Models | `app/models/` | WorkflowDefinition, WorkflowInstance, WorkflowStepExecution |

### 1.4 Infrastructure (`infrastructure/`)

| Component | Docker Image | Purpose |
|-----------|-------------|---------|
| PostgreSQL | pgvector/pgvector:pg16 | Main database with vector support |
| MongoDB | mongo:7 | Transcription/OCR data |
| Redis | redis:7-alpine | Queues, pub/sub, snapshots, sessions |
| MinIO | minio/minio | S3-compatible media storage |
| SearXNG | searxng/searxng | Web search engine |
| Unsearch API | custom | Layer over SearXNG |
| Temporal | temporalio/auto-setup | Workflow orchestration engine |
| Temporal UI | temporalio/ui | Workflow visualization |
| Workflow Service | custom (Dockerfile) | Workflow API + Temporal worker |

---

## 2. Current Architecture

```
                    React Frontend (port 5173)
                          │
                     HTTP/SSE
                          │
                    ──────┴──────
                    FastAPI Backend (port 8000)
                          │
            ┌─────────────┼─────────────┐
            │             │             │
       AgentService   Schedule/Note  Background
       (AI Runtime)   CRUD APIs      Workers
            │             │             │
       ┌────┴────┐   ┌────┴────┐   ┌────┴────┐
       │Tools    │   │PostgreSQL│   │Redis    │
       │Registry │   │(pgvector)│   │Streams  │
       │ModelClient│  │MongoDB  │   │Pub/Sub  │
       │Zep Memory│   │MinIO S3 │   │         │
       │Skills   │   │         │   │         │
       └─────────┘   └─────────┘   └─────────┘
                          │
               ┌──────────┴──────────┐
               │                    │
          Google Calendar    Workflow Service
                              (port 8001)
                                  │
                              Temporal
                                  │
                              PostgreSQL
                              (workflow schema)
```

### Key Architectural Observations

1. **Monolithic backend**: Everything lives in `backend/app/` — no service boundaries
2. **workflow_service is separate**: Not connected to core event system, relies on REST calls to backend
3. **Two "workflow" concepts**: `workflow_service` (Temporal-based) and `workflow_feature/` (planning docs) are related but not fully integrated
4. **Event mechanism is fragmented**: Redis streams (transcription), Redis pub/sub (sync), SSE (frontend), no unified event bus
5. **AI ↔ Tool communication is direct**: LLM generates tool calls → ToolRegistry.execute → DB write. No intent layer, no validation layer beyond Pydantic schemas
6. **Async-sync mixing**: Sync SQLAlchemy sessions used inside async workers (`next(get_db())`)
7. **Two memory systems**: Zep (cloud) for semantic, PostgreSQL for episodic — no fallback if Zep is down

---

## 3. Real Execution Flows

### 3.1 Chat → AI → Tool → Response (Streaming)

```
User types message in AskAI panel
    │
    ▼
frontend/src/components/AskAI.tsx
  → streamAgentMessage() in services/api.ts
    │
    ▼  POST /api/agent/stream/chat  (SSE)
backend/app/api/agent.py:stream_chat()
  → AgentService.handle_streaming_generator()
    │
    ├─ 1. ConversationStore.get_or_create_conversation()
    │     → SELECT/INSERT agent_conversations
    │
    ├─ 2. Generate title via LLM (if new)
    │     → yield "title_generated" SSE event
    │
    ├─ 3. Check token budget
    │
    ├─ 4. Load recent messages (sliding window or token-budget-based)
    │     → ConversationStore.get_recent_messages()
    │     → SELECT * FROM agent_messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT N
    │
    ├─ 5. Load summary context (if exists)
    │     → ConversationSummarizer.get_conversation_context()
    │
    ├─ 6. Build system prompt (system + summary + skills)
    │
    ├─ 7. Save user message
    │     → INSERT agent_messages (role='user')
    │     → UPDATE agent_conversations SET message_count++
    │
    ├─ 8. Build contents array (history + current message)
    │
    ├─ 9. MAIN LOOP (max 30 turns):
    │   │
    │   ├─ a. ModelClient.stream_with_fallback(messages, tools)
    │   │     → POST to OpenAI-compatible API (9Router)
    │   │     → Iterates chunks, buffers tool_calls
    │   │     → yield "token" SSE events for text chunks
    │   │     → yield "reasoning_token" SSE events (for reasoning models)
    │   │
    │   ├─ b. If no tool_calls in response:
    │   │     → break (response is complete)
    │   │
    │   ├─ c. For each tool_call:
    │   │     → yield "tool_start" SSE event
    │   │     → ToolRegistry.execute(name, args, ctx)
    │   │       → ToolDefinition.validate_and_execute()
    │   │         → Pydantic validation (if input_model defined)
    │   │         → handler(args, ctx)  ← actual execution
    │   │         → ActionSnapshotStore.save()  ← snapshot for undo
    │   │     → yield "tool_result" SSE event
    │   │     → Check proactive triggers (currently stub)
    │   │     → Save tool message to DB
    │   │
    │   ├─ d. Append tool results to messages array
    │   │
    │   └─ e. If max turns reached:
    │         → Synthesis turn (LLM without tools)
    │
    ├─ 10. Save final assistant response to DB
    │
    ├─ 11. Update conversation timestamp + message count
    │
    ├─ 12. Trigger memory extraction if threshold reached
    │     → _maybe_trigger_memory_extraction()
    │       → pg_try_advisory_xact_lock (concurrency guard)
    │       → ConversationSummarizer.summarize_conversation()
    │         → extract_and_store()
    │           → LLM call with extraction prompt
    │           → Updates conv.summary (PostgreSQL)
    │           → Adds semantic memories to Zep
    │
    ├─ 13. yield "done" SSE event with usage stats
    │
    └─ 14. Client processes SSE events:
          → "token" → append to message display
          → "tool_start" → show tool execution indicator
          → "tool_result" → update tool execution UI
          → "done" → finalize message
```

### 3.2 AI → Undo Flow

```
User says "undo" or "hoàn tác" in chat
    │
    ▼
AgentService
  → LLM generates: revert_action(action_id="...")
    │
    ▼
ToolRegistry.execute("revert_action", args)
  → revert_action handler
    → ActionSnapshotStore.get(user_id, action_id)
      → Redis GET revert:snapshot:{user_id}:{action_id}
    → Check if already reverted
    → Dispatch to appropriate _revert_* function
      → _revert_create_note → DELETE note (soft)
      → _revert_update_note → restore snapshot content
      → _revert_create_schedule → DELETE schedule
      → _revert_update_schedule → restore snapshot fields
    → ActionSnapshotStore.mark_reverted()
    → Return result to LLM

Or directly via REST: POST /api/agent/actions/{action_id}/revert
```

### 3.3 Reminder Flow

```
ReminderWorker._run_loop() (every 30s)
    │
    ▼
_process_due_reminders()
  → SELECT FROM schedule_reminders WHERE status='pending' AND scheduled_at <= now+30s
    │
    ▼
For each due reminder:
  → Optimistic lock: UPDATE status='processing' WHERE id=? AND status='pending'
  → _send_notification()
    → Lookup Schedule
    → INSERT INTO notifications (user_id, type='reminder', ...)
    → TODO: Publish via SSE/FCM
  → UPDATE status='sent', sent_at=NOW()
```

### 3.4 Google Calendar Sync Flow

```
GoogleSyncWorker._run_loop() (every 5s)
    │
    ▼
_process_sync_queue()
  → SELECT FROM schedule_sync_queue WHERE status='pending' ORDER BY priority, created_at LIMIT 10
    │
    ▼
For each sync item (UPSERT or DELETE):
  → GoogleCalendarSyncService.sync_upsert_schedule() or sync_delete_schedule()
    → Get CalendarConnection, ensure access_token (refresh if expired)
    → If UPSERT:
      → Check if ScheduleExternalMap exists
      → If not: POST to Google Calendar API → store map
      → If yes: PATCH to Google Calendar API → update map
    → If DELETE:
      → DELETE from Google Calendar API → remove map
    → Update sync queue status
```

### 3.5 Workflow Execution Flow (Temporal)

```
Trigger (internal event / webhook / schedule / manual)
    │
    ▼
workflow_service/triggers/
  → Creates WorkflowInstance in DB
  → Starts Temporal workflow via Temporal client
    │
    ▼
Temporal CortexWorkflow:
  → Update instance status to RUNNING
  → Topological sort of action nodes
  → For each action node:
    → Update step status to RUNNING
    → Execute action activity (retry policy: 3 attempts)
      → ActionRegistry.execute(type, config, context)
        → Calls Cortex backend via REST (AI completion, notification, etc.)
    → Update step status to COMPLETED or FAILED
    → Handle condition branches
  → Update instance status to COMPLETED
  → Notify completion
```

---

## 4. Current Maturity Matrix

| Domain | Score | Evidence | Maturity | Risks |
|--------|-------|----------|----------|-------|
| **Memory** | 3 | Episodic summary (PG) + Semantic (Zep cloud). Incremental extraction. Dedup. Advisory lock. | Partially implemented | Zep dependency; no self-hosted fallback; no cross-conversation memory retrieval from AI automatically |
| **Conversation** | 4 | Full CRUD, sliding window, token-budget loading, title generation, streaming, summaries | Functional | Window is only 10 messages by default; no conversation branching |
| **AI Runtime** | 4 | Model selection, streaming, tool-calling, skill injection | Functional | Monolithic AgentService; no cost optimization; no intent layer |
| **Tool System** | 4 | Registry with validation, undo snapshots, parallel execution, SSE events for tool progress | Functional | Global mutable singleton; no capability-based permission; no tool versioning |
| **Command System** | 1 | No intent/command layer exists. AI calls tools directly. No command registry. | Concept only | High risk: direct AI-to-DB coupling |
| **Event Bus** | 1 | Redis streams for transcription, Redis pub/sub for sync, but no unified event schema or routing | Concept only | High risk: proactive features depend on events |
| **Workflow Runtime** | 3 | Separate service with Temporal + React Flow builder. Supports conditions, waits, retries. | Partially implemented | Not connected to core event system; no built-in triggers for core events (note created, schedule changed) |
| **Goals** | 0 | No goals table, no goal CRUD, no goal tracking in AI | Does not exist | Critical gap |
| **Tasks** | 1 | Tasks are conflated with DEADLINE schedule type. No separate tasks model. | Concept only | Confuses schedules and tasks |
| **Calendar** | 3 | Internal schedules with recurrence. Google Calendar bidirectional sync (OAuth). | Partially implemented | Google-only; no push-based sync (polling); webhooks partially implemented |
| **Commitments** | 0 | No commitment data model, no extraction, no tracking | Does not exist | Critical gap for proactive assistance |
| **Notifications** | 3 | DB-backed notifications, SSE push, browser notifications, mark-as-read | Partially implemented | No push notification service (FCM); no notification preferences; no grouping |
| **Proactive Engine** | 0 | Only `_check_proactive_triggers()` stub in AgentService (empty log statement) | Does not exist | Critical gap |
| **Integrations** | 2 | Google Calendar only (OAuth + sync). Unsearch (web search). | Prototype | No email, messaging, GitHub, or other integrations |
| **Context System** | 2 | Context pills + runtime context passed to AI. Workspace context. Note context. | Prototype | No structured context service; context is ad-hoc dict passing |
| **Relation Engine** | 0 | No entity resolution, no relationship tracking, no knowledge graph | Does not exist | Zep graph is external and not deeply integrated |
| **Search** | 3 | Neural search via pgvector embeddings, Google-like web search via SearXNG/Unsearch | Partially implemented | Embeddings stored as JSONB (not proper vector type); no hybrid search |
| **Permissions** | 2 | JWT auth, workspace roles (owner/editor/viewer), basic note ownership | Prototype | No permission for individual notes; no AI tool-level permissions |
| **Audit** | 2 | Action snapshots in Redis + PG (action_history table). Conversation messages logged. | Prototype | No structured audit service; no read-only audit trail |
| **Undo / Revert** | 3 | Snapshot-before-mutate for 4 tools. Redis 24h TTL. PG audit trail. REST + AI-triggered. | Partially implemented | Only 4 tools covered; no Google Calendar undo; no batch revert |
| **Frontend** | 3 | React + TypeScript, SSE streaming, calendar, workspace editor, AI panel, workflow builder | Partially implemented | AskAI is 1365 lines (too large); no proper mobile support |
| **Backend** | 3 | FastAPI, async, proper multi-worker startup, graceful shutdown | Partially implemented | Sync/async mixing; global singletons; monolithic AgentService |
| **Testing** | 2 | ~20 test files in backend/tests, some integration tests, some memory tests | Prototype | Tests are ad-hoc; no CI pipeline visible; no AI E2E tests; no workflow tests |

**Overall Maturity: 2.3 / 5.0** — Prototype-to-Functional, with critical gaps in Goals, Events, Proactive Engine, and Commitments.

---

## 5. Product Gap Analysis

### A. Understand — Can Cortex understand the user?

| Capability | Current State | Gap |
|------------|--------------|-----|
| User intent | LLM infers from natural language | No structured intent detection |
| Current context | Context pills + runtime dicts passed to AI | No unified context service |
| Current project | Via workspace scoping | No project entity |
| Current task | Not tracked; no "current task" concept | **Major gap** |
| Current goal | Not tracked | **Major gap** |
| Application state | Runtime context from frontend | Minimal |

### B. Remember — Can Cortex remember?

| Capability | Current State | Gap |
|------------|--------------|-----|
| Conversations | Sliding window + summaries | Good |
| User preferences | Only theme (localStorage) | **Major gap** — not queryable by AI |
| Commitments | Not modeled | **Major gap** |
| Goals | Not modeled | **Major gap** |
| Project context | Via workspace name only | No structured project model |
| Relationships | Zep graph (external) | No internal relation engine |
| Important facts | Episodic summary + semantic memory | Good but Zep-dependent |

### C. Plan — Can Cortex plan?

| Capability | Current State | Gap |
|------------|--------------|-----|
| Create goals | Not possible | **Major gap** |
| Break goals into milestones | Not possible | **Major gap** |
| Create tasks | Via DEADLINE schedules only | **Major gap** — no task entity |
| Schedule work | Via schedule CRUD | Adequate for events |
| Re-plan dynamically | Not possible | **Major gap** |
| Daily planning | Not supported | **Major gap** |

### D. Act — Can Cortex execute?

| Capability | Current State | Gap |
|------------|--------------|-----|
| Execute commands | Via tool calls | Good |
| Call tools | 16 registered tools | Good coverage for MVP |
| Run workflows | Temporal-based workflow service | Partially implemented |
| Interact with external systems | Google Calendar only | Very limited |

### E. Monitor — Can Cortex track progress?

| Capability | Current State | Gap |
|------------|--------------|-----|
| Track progress | No goal progress tracking | **Major gap** |
| Detect overdue work | No overdue detection beyond reminders | **Major gap** |
| Detect blockers | Not possible | **Major gap** |
| Detect goal risk | Not possible | **Major gap** |

### F. Proactively Assist — Can Cortex initiate?

| Capability | Current State | Gap |
|------------|--------------|-----|
| Remind | Schedule-based reminders (30s polling) | Basic; no smart reminders |
| Recommend | LLM can in chat, but no push | No proactive recommendations |
| Prepare | Not possible | **Major gap** |
| Follow up | Not possible | **Major gap** |
| Notify | SSE + browser notifications | Adequate for now |
| Take autonomous action | Not possible outside chat | **Major gap** |

---

## 6. Architecture Gap Analysis

### 6.1 Critical Gaps

| Component | Missing | Impact | Workaround |
|-----------|---------|--------|------------|
| **Event Bus** | No unified event schema, no event router, no subscriber registry | Cannot trigger workflows from core events; no proactive engine foundation | Ad-hoc: some events via Redis, some via polling, some not emitted at all |
| **Intent/Command Layer** | No structured intent → command pipeline | AI calls tools directly; no permission layer; no validation before execution | Relies on Pydantic per-tool validation |
| **Context Service** | No centralized context provider | Each component builds context differently; no shared context graph | Ad-hoc dict passing |
| **Planning Engine** | No plan data model, no planner service | Cannot create or track plans | None |
| **Goals Engine** | No goal data model, no goal service | Cannot track goals | None |

### 6.2 Significant Gaps

| Component | Missing | Impact |
|-----------|---------|--------|
| **Task System** | No task entity separate from schedules | Cannot track todos, action items, follow-ups |
| **Commitment Tracker** | No commitment model | Cannot detect forgotten promises |
| **Relation Engine** | No entity resolution | Cannot connect notes↔schedules↔goals |
| **Model Router** | No AI cost tiers | All AI calls use same expensive model |
| **Integration SDK** | No normalized integration framework | Each integration is custom-built |

### 6.3 Technical Debt

| Issue | Location | Risk |
|-------|----------|------|
| Global mutable ToolRegistry singleton | `tool_registry.py:191` | Thread-safety, test isolation |
| Sync DB in async context | `reminder_worker.py:64`, `schedule_service.py:144` | Blocking in async loop |
| AgentService 1000+ lines | `agent_service.py` | Difficult to test, maintain, extend |
| JSONB for embeddings | `models.py:390` | Cannot use pgvector index properly |
| AskAI 1365 lines | `frontend/src/components/AskAI.tsx` | Extremely difficult to maintain |
| Two "workflow" concepts | `workflow_service/` + `workflow_feature/` docs | Confusion about what is implemented vs planned |
| Zep external dependency | `services/zep_memory.py` | No fallback if Zep is unavailable |
| SSE token refresh in frontend | `App.tsx:579-603` | Complex inline logic, hard to reason about |

---

## 7. Integration Analysis

### 7.1 Current Integrations

| Integration | Type | Read | Write | Events | Auth | Maturity |
|-------------|------|------|-------|--------|------|----------|
| Google Calendar | OAuth 2.0 | ✅ | ✅ | Polling + webhook (partial) | OAuth tokens encrypted | 3 - Functional |
| SearXNG / Unsearch | HTTP API | ✅ | ❌ | ❌ | None (internal) | 3 - Functional |
| Jina AI Reader | HTTP API | ✅ | ❌ | ❌ | API key | 2 - Prototype |
| OpenAI / 9Router | HTTP API | ✅ | ❌ | ❌ | API key | 4 - Functional |
| Zep Cloud | Cloud SDK | ✅ | ✅ | ❌ | API key | 3 - Functional |
| MinIO (S3) | S3 API | ✅ | ✅ | ❌ | Access keys | 3 - Functional |

### 7.2 Highest-Value Future Integrations

| Integration | Value | Why |
|-------------|-------|-----|
| **Email (Gmail/Outlook)** | Critical | Email contains commitments, follow-ups, deadlines, context |
| **Calendar (beyond Google)** | High | Context for planning |
| **Messaging (Slack/Telegram)** | High | Commitments, follow-ups, context |
| **GitHub** | Medium-High | Developer workflows, PR tracking |
| **Notion/Linear/Jira** | Medium | Task context for knowledge workers |

---

## 8. AI Architecture Analysis

### 8.1 Current AI Call Flow

```
Every AI call:
  → ModelClient.generate() or stream()
    → Runs on the requested model, or the default when none was requested
    → If fatal error (401/403/404) → return error
    → If 429/rate-limited → return error (the LLM service's to manage)
    → If transient error (500/503) → retry the same model
```

> Updated 2026-08-20. As audited, this rotated across the catalogue and
> fell back model-to-model on failure, gated by a local rate-limit
> budget. That was removed: it made the answer's author unpredictable
> turn to turn, and duplicated routing the provider proxy already does.

### 8.2 AI Cost Analysis

| Usage | Current Model | Estimated Token Cost | Optimization Potential |
|-------|---------------|---------------------|----------------------|
| Chat conversation | `oc/qwen3.6-plus-free` (reasoning) | ~2K-50K tokens/turn | High — most queries don't need reasoning |
| Title generation | Same model | ~200 tokens | L1: small model or template |
| Memory extraction | Same model | ~10K-50K tokens/run | L1: structured extraction with smaller model |
| Tool argument generation | Same model | ~1K-5K tokens/turn | L0: deterministic for known patterns |
| Knowledge extraction (assets) | `oc/qwen3.6-plus-free` | ~30K-200K/asset | L2: fast LLM sufficient |
| Workflow AI completion | `oc/qwen3.6-plus-free` | ~1K tokens | L0: deterministic for most cases |

### 8.3 Current Token Controls

| Control | Value | Notes |
|---------|-------|-------|
| Daily limit per user | 2,000,000 tokens | Hard limit, no tiered enforcement |
| History window | 10 messages or 8000 tokens | Switches based on feature flag |
| Max tool turns | 30 | Prevents infinite loops |
| Max same tool calls | 20 per turn | Prevents tool-specific abuse |
| Tool output truncation | 4000 chars (conversation LLM) | Independent from memory extraction (25000 chars) |

### 8.4 Model Tier Gap

| Tier | Description | Current | Should Use |
|------|-------------|---------|------------|
| L0 | Deterministic code | ❌ Not used | Date calc, conflict detection, overdue checks |
| L1 | Small model / Parser | ❌ Not used | Intent classification, simple extraction |
| L2 | Fast LLM | ❌ Not used | Knowledge extraction, summarization |
| L3 | Reasoning model | ✅ Always | Complex planning, multi-step reasoning |

**Impact**: Every AI query uses a reasoning-class model, even for simple operations. This is expensive and slow.

---

## 9. Proactive Assistant Analysis

### 9.1 What Currently Happens

| Event | Current Behavior |
|-------|-----------------|
| Schedule start approaching | 30s-polling ReminderWorker creates notification |
| Google Calendar sync | SSE event to frontend showing sync stats |
| Knowledge extraction complete | Notification created (basic) |
| AI detects useful action | LLM can mention it in chat, but no notification |

### 9.2 What Is Required for True Proactivity

```
Event occurs (schedule approaching, deadline missed, note created, etc.)
    │
    ▼
Event Bus emits typed event
    │
    ├─ 1. Context Retrieval: What is user doing now? What is important?
    ├─ 2. Rule Evaluation: Are there hard rules? (always remind for deadlines)
    ├─ 3. Policy Evaluation: User preferences (silent hours, notification channels)
    ├─ 4. AI Reasoning (if needed): Is this worth interrupting?
    ├─ 5. Decision:
    │     ├─ Silent (log only)
    │     ├─ Inform (low-priority notification)
    │     ├─ Recommend (suggestion with options)
    │     ├─ Ask Approval (confirm before acting)
    │     └─ Act autonomously (high-confidence, low-risk)
    │
    ▼
Action (notification, suggestion UI, autonomous execution)
```

### 9.3 What Is Missing

| Component | Status | Required For |
|-----------|--------|-------------|
| Event Bus | ❌ Missing | All proactive flows |
| Policy/Preference Store | ❌ Missing | Deciding when to interrupt |
| Context Retrieval Engine | ❌ Missing | Understanding current user state |
| Decision Engine | ❌ Missing | Choosing action level |
| Proactive trigger definitions | ❌ Missing | What events trigger proactivity |
| User feedback loop | ❌ Missing | Learning what interruptions are valuable |

---

## 10. Research Findings

### 10.1 AI Agent Architectures

| Approach | Pros | Cons | Suitable for Cortex? |
|----------|------|------|---------------------|
| ReAct (current) | Simple, well-understood | No planning, no state | Phase 0 (current) |
| Plan-and-Execute | Better for multi-step tasks | More complex | Phase 2+ |
| Tree-of-Thought | Better reasoning | Expensive | Phase 3+ for complex planning |
| LLM + Structured Commands | Separates NL from execution | Requires command registry | **Yes, for Phase 1** |

### 10.2 Memory Systems

| System | Pros | Cons | Suitable for Cortex? |
|--------|------|------|---------------------|
| Zep Cloud (current) | Managed, good semantic search | Cost, vendor lock-in | Short-term only |
| **Self-hosted pgvector** | No external dependency, no cost | Requires embedding pipeline | **Yes, for Phase 1** |
| Mem0 / MemGPT | Purpose-built for AI memory | Still maturing | Monitor for Phase 3+ |
| LangMem (LangChain) | Flexible | Heavy dependency | Not recommended |

### 10.3 Event-Driven Architectures

| System | Pros | Cons | Suitable for Cortex? |
|--------|------|------|---------------------|
| **Redis Streams** (partial use) | Already in stack | No schema, no routing | **Yes, extend existing** |
| Kafka / Redpanda | Production-grade | Overkill for single-user | No |
| RabbitMQ | Mature | Extra dependency | Possible but not preferred |
| Postgres LISTEN/NOTIFY | Simple, no extra infra | No persistence, no replay | No for core bus |

### 10.4 Workflow Orchestration

| System | Pros | Cons | Suitable for Cortex? |
|--------|------|------|---------------------|
| Temporal (current) | Durable, retries, visibility | Complex, separate infra | **Yes, keep** |
| In-process workflow engine | Simple | No durability | Not for production |
| Prefect / Dagster | Good for data pipelines | Overkill | No |

### 10.5 Command Architecture (New)

| Pattern | Pros | Cons | Suitable for Cortex? |
|---------|------|------|---------------------|
| **Intent → Command → Execution** | Clean separation, audit, undo | More code | **Yes, recommended** |
| Function calling (current) | Simple | No governance | Phase 0 only |
| Semantic Kernel (Microsoft) | Structured | Heavy dependency | Not recommended |

### 10.6 Proactive Notification Intelligence

| Approach | Pros | Cons |
|----------|------|------|
| **Rule-based + Policy** | Predictable, no AI cost | Cannot handle novel situations |
| **AI-routed** | Flexible, adaptive | Expensive, latency |
| **Hybrid (rules + AI fallback)** | Best balance | More complex |

**Recommendation**: Start with rules + policies. Add AI routing for ambiguous cases.

---

## 11. Target Architecture

```
                    ┌──────────────────────────┐
                    │      Cortex Interface     │
                    │  (React + AskAI + Home)   │
                    └────────────┬─────────────┘
                                 │ HTTP / SSE
                    ┌────────────▼─────────────┐
                    │    Intent / Command API   │
                    │  (new: structured NLU)    │
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼────────┐ ┌──────▼───────┐ ┌────────▼────────┐
     │   AI Runtime    │ │  Command     │ │  Event Bus      │
     │  (ModelClient)  │ │  Registry    │ │  (Redis Streams │
     │  Skills Engine  │ │  Validator   │ │   + Router)     │
     │  Context Builder│ │  Executor    │ │                 │
     └────────┬────────┘ │  Permission  │ └────────┬────────┘
              │          └──────┬───────┘          │
              │                 │                  │
              └─────────────────┼──────────────────┘
                                │
              ┌─────────────────▼──────────────────┐
              │         Context / Memory            │
              │  (Context Graph + Relations +        │
              │   Goals + Commitments + Preferences) │
              └─────────────────┬──────────────────┘
                                │
     ┌──────────────────────────┼──────────────────────────┐
     │                          │                          │
┌────▼─────┐            ┌──────▼──────┐           ┌───────▼──────┐
│ Internal │            │  External   │           │   Workflow   │
│ Domain   │            │  Domain     │           │   Runtime    │
│          │            │             │           │   (Temporal) │
│ Notes    │            │ Calendar    │           │              │
│ Tasks    │            │ Email       │           │  Triggers    │
│ Goals    │            │ Messaging   │           │  Actions     │
│ Schedules│            │ GitHub      │           │  Conditions  │
│ Workspace│            │ MCP Servers │           │  Wait/Retry  │
└──────────┘            └─────────────┘           └──────┬───────┘
                                                         │
              ┌──────────────────────────────────────────┘
              │
     ┌────────▼────────┐
     │ Proactive Engine│
     │  (Rules +       │
     │   Policy + AI)  │
     └────────┬────────┘
              │
              ▼
        User Action / Notification
```

### 11.1 Component Responsibilities

| Component | Responsibility | Inputs | Outputs |
|-----------|---------------|--------|---------|
| Intent API | Parse NL → structured Intent | User message | Intent object |
| Command Registry | Register, validate, execute Commands | Intent | Execution result |
| AI Runtime | LLM orchestration, tool calling | Messages + tools | Response |
| Event Bus | Typed event publishing + routing | Any event | Subscriber notifications |
| Context Service | Build user context graph | All entities | Context for AI |
| Goals Engine | CRUD + progress tracking for goals | User input | Goal state |
| Task Engine | CRUD + state machine for tasks | User input | Task state |
| Commitment Tracker | Extract + monitor commitments | Conversations + events | Alert state |
| Proactive Engine | Decision engine for proactivity | Events + context + policy | Action level |
| Integration Layer | Normalized external connections | External API calls | Normalized data |
| Workflow Runtime | Multi-step orchestration | Trigger events | Execution state |

---

## 12. Phase Roadmap

### Phase 0 — Foundation & Stabilization

**Goal**: Make the current architecture stable, testable, and extensible.

**Duration**: 4-6 weeks

**Work**:
1. Extract AgentService into smaller services (ConversationService, ToolExecutionService, MemoryService)
2. Extract AskAI into smaller components
3. Add integration tests for AI + tool flows
4. Fix sync-in-async anti-pattern
5. Replace JSONB embeddings with proper pgvector column
6. Add embed-on-write for notes
7. Add Zep fallback (local pgvector-based semantic search)
8. Improve error handling in tool execution
9. Add structured logging for all tool calls
10. Add token usage tracking per request

### Phase 1 — Intent & Event Bus

**Goal**: Establish the architectural foundation that all future features depend on.

**Duration**: 4-6 weeks

**Work**:
1. Design Event Schema (typed events with standard envelope)
2. Implement Event Bus (extend Redis streams with router)
3. Define core events: `note.created`, `note.updated`, `schedule.created`, `schedule.approaching`, `conversation.message`, etc.
4. Design Command Schema (Intent → Command → Execution pattern)
5. Implement Command Registry with validation + permission + audit
6. Migrate tools to commands where appropriate
7. Implement Context Service (unified context builder)
8. Add Intent detection (L1: classifier, L2: LLM fallback)

### Phase 2 — Goals & Commitments

**Goal**: Cortex can understand what the user wants to achieve.

**Duration**: 6-8 weeks

**Work**:
1. Goal data model + CRUD API
2. Goal → Milestone breakdown
3. Goal progress tracking (auto-update from related entities)
4. Commitment data model + extraction from conversations
5. Commitment → Task conversion
6. Task data model + state machine (TODO → IN_PROGRESS → DONE)
7. Task ↔ Schedule integration (task with deadline → creates schedule)
8. Note ↔ Goal linking
9. AI skills for goal/commitment management
10. Frontend: Goal dashboard, task lists

### Phase 3 — Planning & Scheduling

**Goal**: Cortex helps users decide what to do next.

**Duration**: 4-6 weeks

**Work**:
1. Daily planning engine (what's due, what's important, what fits)
2. AI planner (break goals into weekly/daily plans)
3. Calendar-aware scheduling (suggest best time slots)
4. Dynamic re-planning (when things change)
5. "What should I do next?" query endpoint
6. Frontend: Daily view, planning suggestions

### Phase 4 — Workflow Integration

**Goal**: Connect the workflow runtime to the core event system.

**Duration**: 4-6 weeks

**Work**:
1. Connect Event Bus → Workflow Trigger bridge
2. Add built-in triggers for core events
3. Add built-in actions: create_note, create_task, send_notification, call_ai
4. Workflow → Goal linking (workflow can advance a goal)
5. Add Temporal to core docker-compose (already done)
6. Frontend: Better workflow templates, simpler creation flow

### Phase 5 — External Context

**Goal**: Cortex understands what is happening outside.

**Duration**: 8-12 weeks

**Work**:
1. Email integration (Gmail API: read commitments, detect follow-ups)
2. Multi-calendar support (Outlook, iCloud)
3. Messaging integration (Telegram bot for proactive notifications)
4. GitHub integration (PR tracking, issue commitments)
5. Integration SDK for third-party connectors
6. Normalized external entity model

### Phase 6 — Proactive Assistant

**Goal**: Cortex proactively assists at the right time.

**Duration**: 8-10 weeks

**Work**:
1. Proactive Engine design + implementation
2. Policy/Preference store (user configures interruption preferences)
3. Rule engine for deterministic proactive actions
4. AI reasoning for ambiguous proactive decisions
5. Proactive action levels: Silent → Inform → Recommend → Ask → Act
6. Smart reminders (context-aware, not just time-based)
7. Meeting preparation (auto-gather context before meetings)
8. Follow-up detection + reminder
9. Risk detection (forgotten commitments, overdue goals, schedule conflicts)
10. User feedback loop (was this interruption useful?)

### Phase 7 — AI Cost Optimization

**Goal**: Reduce AI costs by 60-80% through intelligent routing.

**Duration**: 4-6 weeks (parallel with other phases)

**Work**:
1. Model routing tiers (L0-L3)
2. Small model for intent classification
3. Deterministic execution for known command patterns
4. Context caching for repeated queries
5. Token budget enforcement per tier
6. Usage analytics dashboard

---

## 13. Detailed Estimates

### Phase 0 — Foundation & Stabilization

| Component | Effort | Dependencies |
|-----------|--------|--------------|
| Refactor AgentService | L (2-3 weeks) | None |
| Refactor AskAI | M (1-2 weeks) | None |
| Integration tests | M (1-2 weeks) | None |
| Fix sync-in-async | S (3-5 days) | None |
| pgvector migration | S (3-5 days) | None |
| Zep fallback | M (1 week) | Embedding service exists |
| Structured logging | S (3-5 days) | None |
| Token tracking per request | S (3-5 days) | ConversationStore |

**Total**: M-L (5-7 weeks)
**Confidence**: High (80%) — well-understood tasks
**Risks**: AgentService refactor may reveal hidden coupling

### Phase 1 — Intent & Event Bus

| Component | Effort | Dependencies |
|-----------|--------|--------------|
| Event schema design | S (3-5 days) | None |
| Event Bus implementation | M (1-2 weeks) | Redis already in stack |
| Core event definitions | S (3-5 days) | Event Bus |
| Command schema design | S (3-5 days) | None |
| Command Registry | M (1-2 weeks) | None |
| Migrate tools to commands | L (2-3 weeks) | Command Registry |
| Context Service | M (1-2 weeks) | None |
| Intent detection | M (1-2 weeks) | None |

**Total**: L (6-8 weeks)
**Confidence**: Medium (70%) — design decisions may evolve
**Risks**: Tool→Command migration may break existing AI behavior

### Phase 2 — Goals & Commitments

| Component | Effort | Dependencies |
|-----------|--------|--------------|
| Goal data model + API | M (1-2 weeks) | Event Bus (for goal events) |
| Goal progress tracking | M (1-2 weeks) | Goal model + Event Bus |
| Commitment extraction | M (1-2 weeks) | Memory system |
| Commitment data model | S (3-5 days) | None |
| Task data model + API | M (1-2 weeks) | None |
| Task ↔ Schedule integration | M (1 week) | Task + Schedule models |
| Frontend goal dashboard | L (2-3 weeks) | Goal API |
| AI skills for goals | S (3-5 days) | Goal API |

**Total**: L (8-10 weeks)
**Confidence**: Medium (65%) — commitment extraction quality depends on LLM
**Risks**: Goal progress tracking requires well-defined metrics

### Phase 3 — Planning & Scheduling

| Component | Effort | Dependencies |
|-----------|--------|--------------|
| Daily planning engine | M (1-2 weeks) | Task + Goal + Schedule |
| AI planner | M (1-2 weeks) | Goals + Tasks + Schedule |
| Calendar-aware scheduling | M (1 week) | Schedule model |
| Dynamic re-planning | M (1-2 weeks) | Event Bus + Goals |
| "What should I do next?" endpoint | S (3-5 days) | Planning engine |

**Total**: M (5-7 weeks)
**Confidence**: Medium (60%) — AI planner quality is uncertain
**Risks**: Users may reject AI-suggested plans if quality is poor

### Phase 4 — Workflow Integration

| Component | Effort | Dependencies |
|-----------|--------|--------------|
| Event Bus → Workflow bridge | M (1 week) | Event Bus + workflow_service |
| Built-in triggers | M (1-2 weeks) | Event Bus |
| Built-in actions | M (1-2 weeks) | Command Registry |
| Workflow → Goal linking | S (3-5 days) | Goals + Workflow |
| Frontend workflow templates | M (1 week) | Workflow Builder exists |

**Total**: M (4-6 weeks)
**Confidence**: High (75%) — workflow_service already exists
**Risks**: Temporal worker may need scaling

### Phase 5 — External Context

| Component | Effort | Dependencies |
|-----------|--------|--------------|
| Email integration (Gmail) | L (2-4 weeks) | Integration SDK pattern |
| Multi-calendar support | M (1-2 weeks) | Calendar connection model |
| Telegram bot | M (1-2 weeks) | Proactive Engine (Phase 6) |
| GitHub integration | M (1-2 weeks) | Integration SDK |
| Integration SDK | M (1-2 weeks) | Command Registry + Event Bus |

**Total**: XL (6-10 weeks)
**Confidence**: Low (50%) — each integration has unique API complexity
**Risks**: OAuth maintenance, rate limits, API changes

### Phase 6 — Proactive Assistant

| Component | Effort | Dependencies |
|-----------|--------|--------------|
| Proactive Engine design | M (1 week) | Event Bus + Goals + Tasks |
| Policy/Preference store | S (3-5 days) | User preferences model |
| Rule engine | M (1-2 weeks) | Event Bus |
| AI proactive reasoning | M (1-2 weeks) | AI Runtime |
| Smart reminders | M (1-2 weeks) | Schedule + Commitments |
| Meeting preparation | M (1 week) | Calendar + Notes |
| Follow-up detection | L (2-3 weeks) | Commitments + Email |
| Risk detection | M (1-2 weeks) | Goals + Tasks + Schedules |
| Feedback loop | M (1 week) | Notification system |

**Total**: XL (8-12 weeks)
**Confidence**: Low (45%) — proactive assistant UX is hard to get right
**Risks**: Notification fatigue if quality is poor

### Phase 7 — AI Cost Optimization

| Component | Effort | Dependencies |
|-----------|--------|--------------|
| Model routing tiers | M (1 week) | ModelClient |
| Small model integration | M (1-2 weeks) | Model routing |
| Deterministic command execution | S (3-5 days) | Command Registry |
| Context caching | M (1 week) | Redis |
| Usage analytics | S (3-5 days) | Token tracking |

**Total**: M (4-6 weeks)
**Confidence**: High (80%) — well-understood optimization

---

## 14. Dependencies Map

```
Phase 0 (Foundation)
  └── Everything else depends on this

Phase 1 (Intent & Event Bus)
  ├── Phase 2 (Goals & Commitments)
  ├── Phase 4 (Workflow Integration)
  └── Phase 5 (External Context)

Phase 2 (Goals & Commitments)
  ├── Phase 3 (Planning & Scheduling)
  └── Phase 6 (Proactive Assistant)

Phase 3 (Planning & Scheduling)
  └── Phase 6 (Proactive Assistant)

Phase 4 (Workflow Integration)
  └── Phase 6 (Proactive Assistant)

Phase 5 (External Context)
  └── Phase 6 (Proactive Assistant)

Phase 6 (Proactive Assistant)
  └── Everything before

Phase 7 (AI Cost Optimization)
  └── Parallel with all phases
```

**Critical Path**: Phase 0 → Phase 1 → Phase 2 → Phase 6
**Parallel Paths**: Phase 7 can run alongside any phase

---

## 15. Risks

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Zep becomes unavailable | Medium | High — memory system breaks | Build pgvector fallback (Phase 0) |
| AI model API changes | Low | High — all AI stops | Multi-model fallback already exists |
| Temporal adds complexity | Medium | Medium — operational burden | Already running in docker-compose |
| pgvector performance issues | Low | Medium — search degrades | Start with small dataset |
| SSE connection limits | Medium | Medium — many tabs | Tab-based SSE app ID already used |

### Product Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Users don't trust AI planning | High | High — Phase 3 fails | Start with suggestions, not auto-plans |
| Notification fatigue | High | High — users disable all | Phase 6 prioritizes quality over quantity |
| Commitment extraction quality | Medium | High — false positives/negatives | Start with explicit commitments only |
| Goal tracking feels like overhead | Medium | High — users abandon goals | Auto-track goals from conversations |
| Integration complexity | High | Medium — slows progress | Prioritize by user value (email first) |

### Cost Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AI costs grow faster than value | Medium | High | Phase 7 (cost optimization) early |
| Zep cloud costs at scale | Medium | Medium | Self-hosted fallback |
| Temporal infrastructure costs | Low | Low | Already minimal |

---

## 16. What NOT to Build

### Out of Scope (for now)

1. **Mobile app** — Web-first; PWA sufficient for MVP. Native apps distract from core product.
2. **Social features** — Multi-user collaboration is already minimal (workspaces). Real-time collaboration adds 10x complexity.
3. **Custom LLM fine-tuning** — Too expensive, too hard to maintain. Prompt engineering + model selection is sufficient.
4. **Vector database migration** — pgvector is fine for current scale. Don't add Pinecone/Weaviate/Chroma.
5. **Visual AI capabilities** — Image generation, vision-based agents. Not aligned with current product.
6. **Voice UI** — STT service exists but voice adds UX complexity. Text-first.
7. **Browser extension** — Too early. Only useful after external context (Phase 5).
8. **Plugin ecosystem** — API is not stable enough. Wait until Phase 5+.
9. **Self-hosted AI models** — Too expensive, requires GPU infra. Use managed APIs.
10. **Real-time collaborative editing** — Too complex for current stage.

### Should Be Simplified or Removed

1. **Asset/Recording pipeline** — Complex OCR+transcription+LLM pipeline. Is this core to the product vision? If not, consider deprioritizing or simplifying. Currently consumes significant engineering effort (LLM processing, MongoDB, MinIO, OCR service).
2. **School schedule types** — CLASS, EXAM, DEADLINE are domain-specific. Generalize or remove if Cortex targets a broader audience.
3. **Unsearch/SearXNG infrastructure** — Adds 2 containers. Consider whether web search is core or can be handled simpler.

---

## 17. Recommended Next 3 Actions

### Action 1: Refactor AgentService into bounded services

**Why**: The current monolithic AgentService (~1000 lines) is the highest-leverage refactoring target. Every new feature (goals, commitments, planning) would add more code to this class. Breaking it into ConversationService, ToolExecutionService, and MemoryService makes the system extensible.

**What**:
1. Extract conversation management → `ConversationService`
2. Extract tool loop → `ToolExecutionService`
3. Extract memory extraction orchestration → `MemoryExtractionService`
4. Keep AgentService as a thin orchestrator
5. Add integration tests for each service

**Effort**: L (2-3 weeks)
**Blocks**: Phases 1-6

### Action 2: Design and implement the Event Bus

**Why**: Without an Event Bus, the system cannot react to events. Proactivity, workflow triggers, goal progress tracking, and commitment detection all depend on events. This is the single biggest architectural gap.

**What**:
1. Define event schema: `{type, source, timestamp, correlation_id, user_id, payload}`
2. Define core event types
3. Implement event publishing from key operations (notes, schedules, conversations, tools)
4. Implement event subscriptions (in-process + workflow bridge)
5. Add event logging for audit

**Effort**: L (3-4 weeks)
**Blocks**: Phases 2-6

### Action 3: Build Goals + Commitments

**Why**: The product vision centers on "What am I trying to achieve?" and "What might I be forgetting?" Without goals and commitments, Cortex cannot answer these questions. This is the highest user-value feature.

**What**:
1. Goal data model: `{id, user_id, title, description, status, target_date, milestones, progress}`
2. Commitment data model: `{id, user_id, source (conversation_id), description, due_date, status}`
3. CRUD APIs for both
4. AI extraction of commitments from conversations
5. Basic goal progress tracking (count related tasks)
6. Frontend: Goal overview + task list
7. AI skill for goal/commitment management

**Effort**: L (6-8 weeks — can be parallelized)
**Blocks**: Phases 3, 6

---

## 18. Final Decision Framework

### 1. What is Cortex's strongest existing capability?

**AI Chat with Tool Calling**. The streaming chat, tool execution with undo, skill injection, conversation memory, and SSE events form a solid AI interaction layer. This is the most mature part of the system and the foundation for all future capabilities.

### 2. What is Cortex's biggest architectural weakness?

**Lack of an Event Bus**. There is no centralized mechanism for routing events between components. This prevents:
- Workflow triggers reacting to core events
- Goal progress auto-updating
- Proactive engine evaluating situations
- Commitment detection from conversations
- Integration events flowing into the system

### 3. What is Cortex's biggest product gap?

**No Goals or Commitments**. The core product questions are "What am I trying to achieve?" and "What might I be forgetting?" Without data models for goals and commitments, Cortex cannot answer these questions. It can chat and manage notes/schedules, but it cannot help users pursue outcomes or remember promises.

### 4. What is the single most important capability to build next?

**Event Bus**. It unlocks everything. Without events, the system remains reactive (user asks → AI responds). With events, the system becomes proactive (system detects → AI decides → system acts). Every Phase 2+ feature depends on events.

### 5. What should be postponed?

- **Asset/Recording pipeline** improvements — Unless screen recording analysis is core to the product, this complex pipeline is consuming disproportionate engineering effort.
- **External integrations beyond Google Calendar** — Wait until Phase 5.
- **Proactive Engine** — Critical but depends on goals, commitments, and events being built first.
- **Mobile support** — Web-first for now.
- **AI cost optimization** — Important but can be done incrementally.

### 6. What should be removed or simplified?

- **School-specific schedule types** — Generalize or remove CLASS/EXAM/DEADLINE types
- **Unsearch/SearXNG** — 2 containers for web search; evaluate if built-in web_fetch tool is sufficient
- **OCR service** — If not core to product direction, consider deprecating

### 7. What integrations provide the highest user value?

1. **Email (Gmail/Outlook)** — Contains commitments, follow-ups, deadlines, meeting context
2. **Messaging (Telegram)** — Best channel for proactive notifications
3. **GitHub** — Developer workflow commitments

### 8. What is the minimum architecture required for a truly proactive assistant?

1. Event Bus (typed events + routing)
2. Goals + Commitments + Tasks (structured data)
3. Context Service (unified context for AI)
4. Proactive Engine (rules + policy + AI decision)
5. Notification System (SSE exists, add push)
6. User Preferences (notification policies, quiet hours)

### 9. What can be achieved without additional LLM calls?

- **Conflict detection** — Deterministic schedule overlap check (already partially done)
- **Overdue detection** — Compare dates, deterministic
- **Reminder scheduling** — Already exists
- **Simple goal progress** — Count completed related tasks
- **Commitment deadline alerts** — Compare dates
- **Workflow triggers** — Event-based, no LLM needed
- **Notification grouping** — Deterministic dedup

These should be implemented deterministically, not routed through LLMs.

### 10. What should be the next 30 days of development?

| Week | Focus | Output |
|------|-------|--------|
| **Week 1** | AgentService refactor | ConversationService, ToolExecutionService extracted |
| **Week 2** | AgentService refactor + Event schema | Tests passing, event schema defined |
| **Week 3** | Event Bus implementation | Core events emitting from key operations |
| **Week 4** | Event Bus + Goals start | Events flowing, goal data model designed |

**Total next-30-days effort**: 4 focused weeks → Event Bus operational + AgentService refactored + Goals model ready for implementation.

---

## Priority Scoring Summary

| Feature | Value | Frequency | Strategy | Leverage | Cost | Risk | Priority |
|---------|-------|-----------|----------|----------|------|------|----------|
| Event Bus | 5 | 5 | 5 | 5 | 3 | 2 | **15** |
| Goals System | 5 | 4 | 5 | 4 | 4 | 3 | **11** |
| Commitments | 5 | 4 | 5 | 3 | 3 | 3 | **11** |
| Intent/Command Layer | 4 | 5 | 5 | 4 | 3 | 2 | **13** |
| AI Cost Optimization | 4 | 5 | 4 | 3 | 2 | 1 | **13** |
| Proactive Engine | 5 | 4 | 5 | 3 | 4 | 4 | **9** |
| Workflow→Core Bridge | 4 | 3 | 4 | 4 | 2 | 2 | **11** |
| External Integrations | 4 | 4 | 4 | 2 | 4 | 3 | **7** |
| Planning Engine | 4 | 3 | 4 | 2 | 3 | 3 | **7** |

> **Formula**: Priority = Value + Frequency + StrategyAlignment + TechnicalLeverage - Cost - Risk
> (Scale: 1-5 each, higher is better)

---

## Conclusion

Cortex has a **solid AI chat foundation** with tool calling, memory, and a functional note/schedule workspace. However, it is **not yet a proactive personal assistant**.

The system is currently **reactive** — it responds when the user asks. To become **proactive**, Cortex needs:

1. **An Event Bus** to know what is happening
2. **Structured Goals and Commitments** to know what matters
3. **A Proactive Engine** to decide when to act
4. **Integration with external context** to understand the user's full world

The recommended approach is to **stabilize the foundation (Phase 0)**, **build the event infrastructure (Phase 1)**, then **invest in goals and commitments (Phase 2)** before tackling proactivity directly.

**The ultimate goal remains**: Build a system where users feel "Cortex understands what I am trying to do, remembers what matters, helps me decide what to do next, and tells me when I might be missing something."
