# CORTEX — COMPLETE ENGINEERING & PRODUCT ASSESSMENT REPORT

---

## 1. PROJECT OVERVIEW

**What it currently is**: Cortex is an AI-augmented scheduling + media-processing system that also has notes, workspaces, screen recording OCR/STT pipelines, and an agentic chat interface. It is targeting students (Vietnamese context — `plan.md` confirms it is a graduation project at HCMUS).

**What it already resembles**: A hybrid between a student productivity dashboard (schedules, notes, workspaces) and an AI research demo (agentic chat, semantic search, OCR/STT knowledge extraction). The identity is split — neither side is mature enough to stand alone.

### Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 19, TypeScript 6, Vite 8, Zustand, React Router v7, react-big-calendar, Lucide icons |
| **Backend** | Python 3.x, FastAPI, SQLAlchemy (sync + async), Alembic, Pydantic v2 |
| **Database** | PostgreSQL 16 + pgvector, MongoDB 7 |
| **Queue** | Redis 7 (Streams + Pub/Sub) |
| **Object Storage** | MinIO (S3-compatible, 7-day lifecycle policy) |
| **AI Providers** | Google Gemini (1.5 Flash, 1.5 Pro, 3.1 Flash Lite), Gemma 4 (31B, 26B), Google text-embedding-004 |
| **Messaging** | SSE (Server-Sent Events) — in-house manager with asyncio.Queue |
| **Auth** | JWT (access + refresh tokens), PKCE OAuth2, API key auth for internal endpoints |
| **External Integrations** | Google Calendar (bidirectional sync via webhook push + polling), SearXNG (privacy-first metasearch), Unsearch (embedded full web crawling/RAG platform) |
| **Microservices** | `ocr_service/` (layout reconstruction), `stt_service/` (Whisper transcription) — both consume Redis streams |
| **Infrastructure** | Docker Compose (10 services), Prometheus/Grafana monitoring (in unsearch), CI/CD (unsearch) |

### Major Existing Services

- **`backend/app/`**: Core API (auth, notes, schedules, assets, upload, workspaces, agent, knowledge, notifications, google_calendar)
- **`backend/app/services/agent/`**: AI agent system (model_client with multi-model fallback, tool_registry, conversation_store, embedding_service, semantic_search, 12 tools)
- **`backend/app/services/redis/`**: Redis stream producers (STT, OCR, LLM, Google sync, embeddings)
- **`backend/app/worker/`**: Background workers (embeddings, reminders, google sync, LLM processor)
- **`backend/app/api/sse/`**: SSE infrastructure (manager, base generator, sync_events, agent_events channels)
- **`frontend/`**: SPA with workspace-scoped routing, note tree, calendar, recording viewer, AI chat panel
- **`infrastructure/unsearch/`**: Full embedded web search/crawling/RAG platform with its own DB, AI, billing, monitoring

---

## 2. CURRENT FEATURE INVENTORY

### Productivity Core

| Feature | Status | Architectural Quality | Missing Pieces | Scalability Concern |
|---|---|---|---|---|
| **Notes** | Implemented | MEDIUM — proper repo/service pattern, async, patch-based editing with version control, soft delete, hierarchical tree, drag-and-drop reordering | No full-text search (only substring `contains`); no note templates; no rich collaborative editing; no offline support; patches are JSON diff (not OT/CRDT) | Version conflict resolution is fragile (basic `==` check); no merge capabilities |
| **Schedules** | Implemented | HIGH — well-factored ScheduleService, recurrence, reminders, Google Calendar sync with webhook push, instance management, versioning | No natural language parsing for event creation; no schedule sharing across workspaces; no availability view | Google sync worker runs in-process thread — blocks graceful shutdown; sync queue is a DB table (not Redis) |
| **Workspaces** | Implemented | MEDIUM — reasonable RBAC (owner/editor/viewer), personal + shared workspaces, member management | No workspace-level permissions for schedules/assets; no workspace templates; no group calendar view | Permission checks use mixed sync/async DB sessions (risk of inconsistency) |
| **Calendar** | Implemented | MEDIUM — react-big-calendar integration, slot selection, event CRUD, Google Calendar bidirectional sync | No week/day agenda view; no drag-to-resize; no calendar color coding; no task integration | Full schedule re-fetch on every sync event |
| **Editor** | Implemented | LOW — raw textarea/markdown editing, rendered via markdown-it + bleach, no prosemirror or slate | No rich text toolbar; no real-time collaboration; no images/media embedding; no checklists; no tables | None (too simple to scale poorly) |
| **Reminders** | Implemented | MEDIUM — ScheduleReminder model with polls, scheduled_at timing, retry support | No persistent notification delivery (in-memory only); no push notification infrastructure; no email delivery | In-process worker — no durability guarantee |
| **Screen Recording** | Implemented | MEDIUM — multipart upload to MinIO, asset tracking, live streaming mode | No recording management UI; no trimming; no re-encoding | Multipart upload is mature (tracks parts, presigned URLs) |

### AI Features

| Feature | Status | Architectural Quality | Missing Pieces | Scalability Concern |
|---|---|---|---|---|
| **Agent Chat** | Implemented | HIGH — well-designed tool registry, conversation store with summarization, token budgeting, streaming SSE events, multi-model fallback with rate-limiting | No per-user model preference; no custom tool creation; no system prompt customization; tool context has no access to embedding search | All conversations stored in single DB table; message_count is denormalized correctly |
| **Tool Calling** | Implemented | HIGH — 12 Gemini function tools, Pydantic input validation, async execution, proactive trigger hooks | No tool chaining orchestration (no DAG-based sequencing); no human-in-the-loop approval; no tool timeout | Tool execution is serial within a turn — could be parallelized |
| **Model Client** | Implemented | VERY HIGH — sophisticated RateLimitBudget with sliding windows, round-robin cursor, per-model retry, rotation fallback, structured JSON model filtering, proactive budget checks | No cost tracking per-conversation; no model A/B testing framework | Rate limiting is process-local (lost on restart) — needs Redis-based budget tracking |
| **Semantic Search (Notes)** | Implemented | MEDIUM — uses pgvector cosine similarity on 768-dim embeddings, fallback to keyword substring search | No combined vector + keyword (hybrid) search; no BM25 fallback; embedding column is JSONB (not `vector` type) — casts on every query | Full JSONB → vector cast per query eliminates index benefits; no `ivfflat` or `hnsw` index |
| **Semantic Search (Knowledge)** | Placeholder | LOW — explicitly marked "not implemented", returns empty results | Needs MongoDB Atlas Vector Search or Chroma/FAISS sidecar | Not yet a concern |
| **Embeddings** | Implemented | MEDIUM — EmbeddingService with Redis caching, proper task_type distinction (retrieval_document vs retrieval_query) | No batch embedding; no embedding refreshes on note update; no incremental embedding | Embedding generation is synchronous in the request path for notes |
| **OCR Pipeline** | Implemented | MEDIUM — separate microservice, Redis stream orchestration, MongoDB storage, timeline-based knowledge extraction with LLM analysis | No incremental/realtime OCR (only batch window processing); no support for non-video images | MongoDB queries for timeline lookups are unscoped to asset — missing index |
| **STT Pipeline** | Implemented | MEDIUM — separate microservice (Whisper), Redis stream producer/consumer, MongoDB transcription storage | No speaker diarization; no language detection; no real-time transcription | Same as OCR — timeline scope concern |
| **LLM Knowledge Processing** | Implemented | HIGH — schema-constrained Gemini calls with timeline event extraction, structured JSON output (response_schema), cost tracking | No continuous re-processing pipeline; no confidence-rating decay; no deduplication | Window-based LLM calls are expensive ($0 cost tracking but no real budget) |
| **Web Search** | Implemented | MEDIUM — agent tool delegates to Unsearch/SearXNG | No local search result caching; no search result ranking/reranking | Unsearch is a separate embedded project with its own scaling story |
| **Deep Research** | Implemented | LOW — agent tool that returns "too long, try non-streaming" — explicitly broken for streaming | Not usable in streaming mode; no progressive result delivery | Not usable |

### Infrastructure Features

| Feature | Status | Architectural Quality | Missing Pieces | Scalability Concern |
|---|---|---|---|---|
| **Auth (JWT + PKCE)** | Implemented | HIGH — access/refresh token rotation, PKCE OAuth2 flow, authorization codes with code challenge | No OAuth2 social login; no MFA; no API key management for integrations | Token revocation requires DB lookup (no blacklist cache) |
| **SSE Realtime** | Implemented | HIGH — well-designed SSEManager with channel/context/connection hierarchy, duplicate prevention, heartbeat, graceful shutdown | No WebSocket fallback; no message persistence (lost on reconnect); no reconnection backoff tuning | In-memory queues are lost on restart; asyncio.Queue maxsize=100 limits per-connection buffer |
| **Redis Streams** | Implemented | HIGH — proper stream/consumer group pattern, task encapsulation with producer/consumer separation | No dead-letter queue; no stream monitoring dashboard; no stream replay for debugging | Streams have no retention limit configured — unbounded growth |
| **Background Workers** | Implemented | LOW — WorkerThread runs asyncio loop in a thread (not proper process isolation) | No process supervision; no health checks for workers; no worker metrics | In-process workers crash with the main process; thread safety concerns with shared DB sessions |
| **File Upload** | Implemented | HIGH — proper multipart upload with presigned URLs, part tracking, upload sessions, S3-compatible storage | No file preview; no file type validation; no file search; no versioned file storage | MinIO bucket lifecycle set to 7 days (auto-deletion of old recordings) |
| **CORS** | Implemented | OK — whitelist-based, allows all methods/headers | No per-origin method control; no preflight caching tuning | Acceptable for current scale |
| **Internal API** | Implemented | OK — shared secret key authentication for service-to-service | No mTLS; no request signing; no audit logging | Simple shared key is brittle |
| **Rate Limiting** | Per-function decorator | LOW — `rate_limit.py` exists for upload (RPM), no global rate limiting | No distributed rate limiting; no per-endpoint granularity | Global API has no protection against DoS |

---

## 3. DOMAIN MODEL ANALYSIS

### Current Entities

```
User (1) ──── Owner ──→ Workspace (N)
User (1) ──── Member ─→ WorkspaceMember (N)
User (1) ──── Has ────→ Schedule (N)
User (1) ──── Has ────→ Note (N) ←── Parent (self-ref)
User (1) ──── Has ────→ Asset (N) → Workspace (N)
User (1) ──── Has ────→ AgentConversation (N) → AgentMessage (N)
User (1) ──── Has ────→ CalendarConnection (N)
User (1) ──── Has ────→ Upload (N) → UploadPart (N)
User (1) ──── Has ────→ Notification (N)

Schedule (1) ──── Has ───→ ScheduleReminder (N)
Schedule (1) ──── Recurrence → Schedule (self-ref)
Schedule (1) ──── ExternalMap ──→ ScheduleExternalMap (N) ──→ CalendarProvider

Workspace (1) ──── Has ────→ Note (N)
Workspace (1) ──── Has ────→ Asset (N)
Workspace (1)─── Has ────→ AgentConversation (N)

Note (1) ──── Has ────→ NoteRevision (N) [patch-based history]

Asset (1) ──── Has ────→ OCRJobDocument (Mongo)
Asset (1) ──── Has ────→ KnowledgeUnitDocument (Mongo)
Asset (1) ──── Has ────→ OCRProcessedDocument (Mongo)
```

### Identified Domain Issues

1. **No Task entity**: Schedules have `is_completed` for DEADLINE type, but there is no first-class Task entity with priority, status, assignee, due date, labels, or project association. Tasks are conflated into schedules.

2. **No Project entity**: Workspaces are the only organizational unit. There is no Project entity that groups notes + tasks + schedules + files under a common goal. A workspace is essentially a folder, not a project.

3. **No File entity**: Assets are tied to recording/media processing pipeline. There is no general File entity for document storage, attachments, or arbitrary file management.

4. **Weak Note ↔ Schedule relationship**: Notes can mention schedules but there is no explicit linking table. The agent can create notes from schedules and vice versa, but there's no persistent relationship.

5. **No ActivityEvent entity**: There is no audit trail — no entity tracking who created/modified/deleted what and when. The `NoteRevision` is the closest thing but only covers note content changes.

6. **No Tag/Label entity**: Notes have `style.color` as an analog for categorization, but there is no general-purpose tagging system that spans notes, schedules, tasks, files.

7. **No SearchResult entity**: Semantic search returns ad-hoc dicts. There is no persistent search index or cached search results.

8. **Conversation ↔ Note/Schedule/Task linking is absent**: When the AI creates a note or schedule from a conversation, there is no `source_conversation_id` on those entities to trace provenance.

9. **Weak AgentConversation → Workspace relationship**: `workspace_id` is nullable — meaning conversations can be orphaned from workspace context.

10. **Workspace ↔ Schedule is absent**: Schedules are user-scoped, not workspace-scoped. They appear in a global schedule view, not per-workspace.

---

## 4. PRODUCT MATURITY ASSESSMENT

**Current Identity**: Cortex is primarily an **AI demo** disguised as a scheduling app.

Evidence:
- The most sophisticated code is in `model_client.py` (770 lines) — the multi-model rate-limited fallback is production-grade AI infrastructure
- The agent system has 12 tools, streaming SSE, conversation summarization, token budgeting, and proactive suggestion triggers
- The OCR/STT pipeline with LLM knowledge extraction is the most complex subsystem
- Notes are basic — markdown textarea with no rich editing
- No projects, no tasks, no proper file management
- The "productivity" features (notes, schedules) are functional but primitive compared to the AI layer

**Why it is NOT yet a productivity platform**:
- No task management (the #1 productivity primitive)
- No project/initiative organization
- No global search (Cmd-K search only searches notes locally)
- No file management (only screen recording assets)
- No activity stream or feed
- No notification system beyond status bar messages
- No offline support
- No keyboard shortcuts beyond Cmd-K
- Notes have no rich formatting, no images, no linking
- The scheduling UI is read-only (no drag-to-create/edit)
- No todos, no checklists, no habit tracking

**What is impressive**:
- The AI infrastructure (model_client, tool_registry, SSE streaming) is genuinely well-architected
- The OCR/STT pipeline with LLM knowledge extraction is novel and research-worthy
- The Google Calendar sync with webhooks is properly implemented
- The upload system with multipart presigned URLs is robust

**In short**: Cortex has strong AI foundations but weak product foundations. It is over-engineered on the AI side and under-engineered on the core productivity side.

---

## 5. ARCHITECTURE ANALYSIS

### Strengths

**Service Layer**: `ScheduleService`, `NoteService`, `AgentService` follow a clean service pattern. Business logic is extracted from routers. The `NoteService` with a `NoteRepository` is a proper repository pattern.

**Async Architecture**: Async database sessions, async Redis clients, async SSE generators — the stack is consistently async.

**Queue Abstraction**: Redis stream producers/consumers with task-specific classes (`OCRProcessorTask`, `GoogleSyncTask`, `LLMProcessorTask`) provide good encapsulation.

**SSE Design**: The `SSEManager` with channel/context/connection hierarchy, asyncio.Queue per connection, duplicate prevention, and graceful shutdown is well-architected.

**Model Client**: `ModelClient` + `RateLimitBudget` is exceptional. The proactive budget checks, round-robin cursor, model fallback chain, and structured JSON model filtering are production-quality.

### Weaknesses & Anti-Patterns

1. **CRITICAL: In-process background workers**: `WorkerThread` runs asyncio loops in threads (`backend/app/__init__.py:35-97`). This means:
   - A crash in any worker crashes the entire API process
   - No horizontal scaling — can't run workers separately
   - Thread safety with SQLAlchemy sessions is unverified
   - Graceful shutdown is fragile (5-second timeout for stop)

2. **HIGH: Mixed sync/async database sessions**: Several endpoints use `SessionLocal()` (sync) inside async routes (e.g., `notes.py:52-53`, `notes.py:56`). This blocks the async event loop and risks deadlocks.

3. **HIGH: Embedding stored as JSONB, not vector**: `Note.embedding` is `JSONB` with a cast `::vector` on every query (`semantic_search.py:73-74`). This eliminates all performance benefits of pgvector — no index can be used. Full table scan + cast on every search.

4. **MEDIUM: Monolithic backend**: There is no modular separation. The backend is a single FastAPI app with everything under `app/`. No packages for auth, notes, schedules, etc. No dependency injection framework.

5. **MEDIUM: Unsearch embedded as a subproject**: `infrastructure/unsearch/` has its own git history, its own DB migrations, its own docker-compose, and its own AI integrations. This is a separate product merged as a directory. Code duplication with the main backend's AI features.

6. **MEDIUM: No service discovery/registry**: Services reference each other by hardcoded host:port. No Kubernetes, no Consul, no Docker Compose service naming discipline (but Docker Compose does provide internal DNS for some services).

7. **LOW: SSE queue maxsize=100**: Each SSE connection has an asyncio.Queue with `maxsize=100`. Under high event load, slow consumers will be silently dropped (logged as warning). No mechanism to replay missed messages.

8. **LOW: No OpenAPI/Swagger customization**: Pydantic schemas are used, but some endpoints return raw dicts instead of response models (e.g., agent endpoints return dict, not `AgentChatResponse` consistently).

9. **LOW: Frontend bundles too much in App.tsx**: `App.tsx` is 1227 lines of inline state, routing logic, sidebar rendering, and SSE connection management. No proper routing library separation (logic is in render).

---

## 6. AI ARCHITECTURE ANALYSIS

### Assessment: AI is the most sophisticated part of Cortex, but dangerously centralized

**What works well**:
- **ModelClient** is genuinely excellent — proactive rate-limiting, multi-model fallback, proper retry logic, streaming with buffered recovery
- **Tool Registry** is clean — Pydantic validation, async execution, Gemini-format schema generation
- **Conversation Store** handles message ordering, consecutive role collapse, history trimming, and summarization triggers
- **SSE streaming** with tool_start/tool_result/token events provides good UX feedback
- **Token budgeting** per user/day prevents runaway costs

**What is problematic**:

1. **HIGH: AI is too tightly coupled to product logic**. The `AgentService` directly manipulates `conversation_store` and `tool_registry`. Tools directly query the database. There is no abstraction layer between AI decisions and product data. If the AI layer needs to be replaced or A/B tested, significant refactoring is required.

2. **MEDIUM: Tools are synchronous in an async loop**. Each tool call blocks the entire agent loop. There's no parallel tool execution, no tool timeout, no tool queuing.

3. **MEDIUM: Prompt management is hardcoded**. The `SYSTEM_PROMPT` in `agent_service.py` is a string constant. No versioning, no per-user customization, no environment-specific prompts, no prompt templates.

4. **LOW: No function calling response caching**. If the same tool is called with the same arguments (e.g., "check my schedule"), the result is re-fetched every time.

5. **LOW: No AI observability**. No logging of which model was used per turn, no latency tracking per tool, no token usage per tool, no cost attribution.

6. **LOW: Deep research tool is broken in streaming mode**. It returns an error message asking users to use non-streaming mode. This is a product-level gap — users will hit this naturally.

### AI vs Product Boundaries

**What SHOULD remain AI-powered**:
- Natural language → structured data parsing
- Semantic search and knowledge retrieval
- Proactive suggestions (schedule conflicts, missing information)
- Conversation summarization
- Timeline-based knowledge extraction from media

**What SHOULD become normal product logic**:
- Note/schedule CRUD (tool calls are just API wrappers — should use the existing service layer)
- Search (should have a native product search, AI augmenting it)
- Notification delivery (AI should trigger, not deliver)
- File processing orchestration (OCR/STT should be product pipelines, not AI features)

---

## 7. OFFLINE-FIRST & SYNC READINESS

**Current state**: Zero offline support.

### Analysis

**Frontend**:
- All data is fetched from API on mount. No local persistence.
- Notes have a delayed-save pattern (280ms debounce via `scheduleNotePersist`), but it still requires network.
- Tokens are cached in localStorage, but there is no offline-capable API client.
- No service workers, no IndexedDB, no local-first data store.

**Backend**:
- No sync endpoint design — all endpoints are CRUD, not sync-optimized.
- No conflict resolution beyond basic version checks.
- No change log/feed mechanism for incremental sync.
- No cursor-based or timestamp-based pagination for sync.

### Required Changes for Offline-First

1. **CRITICAL**: Adopt a local-first data layer (e.g., SQLite via `absurd-sql` or `sql.js` on the frontend, or PouchDB/CouchDB)
2. **HIGH**: Implement CRDT or OT-based note editing (currently patch-based but not merge-friendly)
3. **HIGH**: Design a sync API with cursor-based pagination, change feeds, and batch operations
4. **HIGH**: Implement a sync queue with retry logic, conflict resolution, and status reporting
5. **MEDIUM**: Add Service Worker for API caching and offline fallback
6. **MEDIUM**: Redesign frontend stores for optimistic updates with rollback on conflict
7. **LOW**: Design conflict resolution UI (3-way merge for notes, last-write-wins for schedules)

**Verdict**: The current architecture is fundamentally online-only. Offline-first would require a ground-up rewrite of the data layer on both frontend and backend. The SSE mechanism is a step in the right direction (event-driven sync), but it's one-directional (server→client only).

---

## 8. TECHNICAL DEBT REPORT

| Issue | Rank | Impact | Recommended Fix |
|---|---|---|---|
| **In-process background workers** | CRITICAL | A crash in any worker kills the API; can't scale workers separately; thread safety | Extract workers into separate processes (subprocess or container); use Redis streams as durable queue; implement supervisor pattern |
| **JSONB embedding with pgvector cast** | HIGH | Full table scan + cast on every semantic search query; no index benefit | Migrate `embedding` column to `vector(768)` type; create `ivfflat` or `hnsw` index; write a one-off migration script |
| **Mixed sync/async DB sessions** | HIGH | Blocks async event loop; risk of deadlock | Convert all permission checks to async; remove all `SessionLocal()` usage from async routes |
| **No frontend routing abstraction** | MEDIUM | 1227-line App.tsx; routing logic mixed with rendering; no lazy loading | Extract routing into `react-router` route tree; lazy-load workspace views/chunks |
| **No task entity** | MEDIUM | Deadlines conflated into schedules; no first-class task primitive | Add `tasks` table with status, priority, assignee, due date, labels, project_id |
| **Unsearch double-embedded** | MEDIUM | Duplicated AI code; separate git history; own docker-compose; own DB migrations | Extract as external dependency or merge into monorepo properly with shared packages |
| **No full-text search on notes** | MEDIUM | Keyword fallback uses substring `contains` (no index, no ranking) | Add PostgreSQL `tsvector` column with GIN index; implement `ts_rank` for keyword search |
| **No test coverage for frontend** | MEDIUM | Backend has tests (`tests/`), frontend has zero test files | Add Vitest + React Testing Library for critical hooks and components |
| **Prompt management hardcoded** | MEDIUM | System prompt is a constant string; no versioning or customization | Extract prompts to configurable templates (JSON or DB-backed) with versioning |
| **No distributed rate limiting** | MEDIUM | RateLimitBudget is process-local; reset on restart | Migrate budget tracking to Redis with sorted sets or fixed-window counters |
| **Schedules not workspace-scoped** | LOW | Schedule events are user-level, not workspace-level; workspace switcher doesn't affect calendar | Add `workspace_id` FK to schedules; filter by workspace in queries |
| **Agent conversation messages not pruned** | LOW | Soft-deleted conversations still have orphaned messages (hard delete only) | Add TTL-based message archiving or periodic cleanup job |
| **No request ID / tracing** | LOW | No correlation IDs across API → worker → SSE flows | Add `structlog` or `python-json-logger` with request-id middleware |
| **No API versioning** | LOW | All endpoints on `/api` with no version prefix | Add `/api/v1/` prefix; maintain backward compatibility |

---

## 9. PRODUCT GAP ANALYSIS

### Foundational Platform Gaps (must-fix before AI enhancement)

1. **No Task Management**: The single biggest gap. Tasks are the atomic unit of productivity. Without them, Cortex cannot claim to be a productivity platform.

2. **No Project Structure**: Workspaces are flat containers. Projects with milestones, deliverables, status tracking, and goal alignment are missing.

3. **No Global Search**: Cmd-K opens a modal that searches only notes. No cross-entity search across notes, schedules, tasks, files, and conversations.

4. **No File Management**: Only screen recording assets are handled. No document upload, image gallery, file versioning, or file search.

5. **No Activity Feed**: No timeline of what happened — who created what, what was updated, what deadlines approach.

6. **No Notification System**: Notifications are ad-hoc (status bar messages). No notification center, no delivery channels (push, email), no notification preferences.

7. **No Real-Time Collaboration**: No shared editing, no presence, no live cursors, no comments/annotations on notes.

8. **No Keyboard-First Navigation**: Only Cmd-K for search. No keyboard shortcuts for note creation, schedule navigation, workspace switching, or AI chat.

9. **No Data Export/Import**: No way to export notes as markdown/PDF, no calendar import (ICS), no workspace migration.

10. **No Settings Persistence for AI**: No user-facing model selection, no custom system prompts, no AI feature toggles.

### Advanced AI Enhancements (nice-to-have, not blocking)

- Proactive schedule conflict detection across workspaces
- AI-generated meeting summaries from recordings
- Automatic task extraction from notes
- Natural language querying for any data
- Personalized daily/weekly digests
- Integration with third-party tools (Slack, Notion, GitHub, Linear)

---

## 10. RECOMMENDED PRODUCT DIRECTION

**Primary Direction**: **Personal Knowledge Operating System**

### Justification

Cortex already has:
- Notes with hierarchical tree (atomic knowledge units)
- Semantic search across notes (knowledge retrieval)
- Media processing pipeline that extracts knowledge from recordings
- Conversation-based AI assistant that can manipulate and retrieve data
- Workspace organization

The **strongest thesis** is: *A system that captures, organizes, retrieves, and augments personal knowledge across notes, recordings, schedules, and conversations, powered by AI that works for you rather than replacing you.*

### What SHOULD be Prioritized
1. **Tasks** — the fundamental productivity primitive
2. **Projects** — the organizational structure above notes and tasks
3. **Global search** — the gateway to all knowledge
4. **Activity feed** — the awareness layer
5. **Cross-entity relationships** — linking notes → tasks → schedules → files → conversations

### What SHOULD NOT be Prioritized
- **More AI tools**: 12 tools are already too many for the current product surface
- **More model providers**: Gemini is fine; adding more providers adds complexity, not value
- **Advanced RAG pipelines**: The search pipeline needs to work at product level before adding RAG complexity
- **Real-time collaboration**: Premature — single-user productivity must come first
- **Mobile apps**: Web-only until the product identity is solidified
- **Unsearch integration**: The embedded web crawling platform is a distraction from the core product

### What Features Create Strong Differentiation
- **Timeline-based knowledge extraction** from screen recordings (unique — no other productivity tool does this)
- **AI that proactively suggests** (schedule conflicts, task creation from notes, context from past conversations)
- **Conversation-aware context** (the AI remembers across sessions with summarization)

---

## 11. RECOMMENDED ROADMAP

### Immediate (2-4 weeks) — Product Foundation

| Area | Action |
|---|---|
| **Product** | Implement first-class Task entity (CRUD, status, priority, due dates, project_id) |
| **Product** | Implement Project entity (name, description, status, timeline, notes + tasks + schedules association) |
| **Infrastructure** | Extract background workers to separate processes (fix CRITICAL thread-safety issue) |
| **Infrastructure** | Migrate embedding column from JSONB to pgvector `vector(768)` with proper index |
| **Infrastructure** | Convert all mixed sync/async DB sessions to fully async |
| **AI** | Fix deep research tool for streaming mode |
| **AI** | Add AI observability (model usage, latency, cost per conversation) |

### Mid-Term (1-2 months) — Knowledge Layer

| Area | Action |
|---|---|
| **Product** | Implement global cross-entity search (notes + tasks + schedules + files) with Cmd-K |
| **Product** | Implement activity feed (who did what, when) |
| **Product** | Implement notification center with delivery channels (push via SSE, email via SMTP) |
| **Infrastructure** | Add PostgreSQL full-text search (tsvector + GIN) for keyword search fallback |
| **Infrastructure** | Add note ↔ task ↔ schedule ↔ conversation relationship linking |
| **Infrastructure** | Implement file management (upload, preview, search, versioning) |
| **AI** | Add task extraction from notes (AI suggests tasks from note content) |
| **AI** | Add calendar conflict detection using schedule AI |
| **Refactor** | Extract routing from App.tsx into proper route tree with lazy loading |
| **Refactor** | Extract prompts to versioned templates |

### Long-Term (3+ months) — Architecture & Research

| Area | Action |
|---|---|
| **Architecture** | Design and implement offline-first data layer (local-first sync) |
| **Architecture** | Implement event sourcing for audit trail and cross-device sync |
| **Architecture** | Move to proper microservices (auth-service, notes-service, schedule-service, knowledge-service) |
| **Research** | Publish paper on timeline-based knowledge extraction from screen recordings |
| **Research** | Evaluate CRDT-based collaborative editing (Yjs/Automerge) |
| **AI** | Implement AI agent with tool DAG orchestration (parallel tool execution, conditional branching) |
| **AI** | Implement multi-user AI context (workspace-aware AI) |

---

## 12. CODEBASE HEALTH SCORE

| Dimension | Score | Explanation |
|---|---|---|
| **Architecture** | 6/10 | Good service layer and AI architecture, but ruined by in-process workers, mixed sync/async, and lack of modularity |
| **Maintainability** | 5/10 | Well-organized directory structure, but 1227-line App.tsx, embedded Unsearch subproject, and hardcoded prompts reduce maintainability |
| **Scalability** | 4/10 | Cannot scale horizontally due to in-process workers, JSONB embedding, no distributed rate limiting, no caching layer |
| **Product Readiness** | 3/10 | Core productivity features are too primitive. Cannot compete with even basic tools. AI is impressive but not enough to build a product around |
| **AI Engineering** | 9/10 | ModelClient, RateLimitBudget, ToolRegistry, SSE streaming, conversation summarization — all genuinely well-engineered. Best part of the codebase |
| **Research Value** | 8/10 | Timeline-based knowledge extraction from recordings + multi-model LLM orchestration + proactive agent are strong research contributions |
| **Extensibility** | 5/10 | Tool registry is extensible, but tight AI-product coupling and lack of plugin system limit extension. No webhook/events system for external integration |
| **Production Readiness** | 3/10 | Broken deep research tool, no monitoring, no structured logging, in-process worker crashes kill API, SSE queues are in-memory and lost on restart, no backup strategy |

### Overall Score: **4.5/10**

This is generous — it reflects the genuinely excellent AI infrastructure pulling up very weak product and operational foundations.

---

## 13. FINAL VERDICT

### 1. What is Cortex CURRENTLY?
An **AI research demo with a scheduling app attached**. The engineering effort is heavily skewed toward the AI layer (model fallback, streaming, OCR/STT knowledge pipelines) while the core productivity features (notes, schedules) remain basic. The Unsearch subproject adds further confusion — it's a separate web crawling/RAG platform embedded as a directory.

### 2. What SHOULD Cortex become?
A **Personal Knowledge Operating System** — a platform that captures, organizes, retrieves, and augments personal knowledge across notes, tasks, schedules, files, and conversations. AI should be the assistant that enhances every interaction, not the primary interface. The screen recording → knowledge extraction pipeline is a unique differentiator no other productivity tool offers.

### 3. What architectural shift is most important right now?
**Extract workers from the main process.** The in-process `WorkerThread` pattern is the single most dangerous architectural decision. It prevents horizontal scaling, couples infrastructure to API, and makes the entire system fragile. Fixing this unlocks the ability to scale background processing independently and adds operational reliability.

### 4. What should stop being over-engineered?
**The AI model client.** It's already production-quality with rate limiting, multi-model fallback, and streaming recovery. Adding more models, more fallback logic, or more budget tracking complexity before the product has tasks, projects, and search is premature optimization. The AI is ready — the product needs to catch up.

### 5. What foundational systems are missing?
- **Task management** (the #1 productivity primitive)
- **Project organization** (hierarchy above notes/tasks)
- **Global search** (cross-entity, full-text + semantic)
- **Activity/audit trail** (awareness of what happened)
- **Notification delivery** (push/email with user preferences)
- **File management** (arbitrary file storage, preview, search)
- **Offline resilience** (local-first sync)

### 6. What creates the strongest thesis/research value?
**Timeline-based knowledge extraction from screen recordings.** This is Cortex's unique innovation. The combination of OCR + STT + LLM analysis to produce searchable, timestamp-anchored knowledge units from a screen recording session is genuinely novel. This could be published as a research paper and is the strongest differentiation from any existing productivity tool.

### 7. What would make this project feel like a real product?
1. **Implement tasks and projects** — this immediately changes the identity from "schedule app" to "productivity platform"
2. **Fix global search** — Cmd-K should search everything, not just notes
3. **Make the calendar interactive** — drag-to-create, drag-to-resize, color-coded by schedule type
4. **Add keyboard shortcuts** — productivity tools must be keyboard-first
5. **Enable the "Ask AI" panel by default** in a way that's contextual (show relevant suggestions based on current note/schedule)
6. **Polish the note editor** — at minimum a rich-text toolbar, ideally ProseMirror or TipTap
7. **Show a daily/weekly dashboard** on home screen with upcoming tasks, schedule, recent notes, and AI suggestions
