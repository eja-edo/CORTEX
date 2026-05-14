# Cortex AI System Architecture Analysis

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [System Architecture Overview](#system-architecture-overview)
3. [AI Components and Modules](#ai-components-and-modules)
4. [AI Integration Architecture](#ai-integration-architecture)
5. [Data Flow Analysis](#data-flow-analysis)
6. [API and Service Integration](#api-and-service-integration)
7. [Memory and Context Management](#memory-and-context-management)
8. [Tool Calling and Orchestration](#tool-calling-and-orchestration)
9. [Real-time Streaming Support](#real-time-streaming-support)
10. [Technology Stack](#technology-stack)
11. [AI Capabilities Matrix](#ai-capabilities-matrix)
12. [Distinction: Chatbot AI vs AI System](#distinction-chatbot-ai-vs-ai-system)
13. [Extensibility Analysis](#extensibility-analysis)
14. [Recommendations for Project Description](#recommendations-for-project-description)

---

## Executive Summary

Cortex là một **integrated AI system** được xây dựng trên nền tảng FastAPI (Python), tích hợp AI vào một hệ thống quản lý công việc (notes, schedules, notifications, knowledge). Hệ thống sử dụng kiến trúc **multi-service microservices** với 3 thành phần AI chính:

1. **Agent Service** - AI Agent với function calling
2. **OCR Service** - Xử lý video/image thành text
3. **STT Service** - Speech-to-text transcription

Điểm khác biệt quan trọng: Cortex không chỉ là một "chatbot AI" đơn thuần mà là một **AI-integrated productivity platform** với khả năng:
- Tương tác ngôn ngữ tự nhiên với dữ liệu người dùng
- Xử lý batch các file media (video/audio)
- Semantic search với vector embeddings
- Real-time streaming responses

---

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CORTEX SYSTEM ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                              FRONTEND (TypeScript/React)                │   │
│  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │   │
│  │   │   Chat UI   │  │  Notes UI   │  │ Calendar UI │  │Knowledge UI │   │   │
│  │   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘   │   │
│  └──────────┼────────────────┼────────────────┼────────────────┼──────────┘   │
│             │                │                │                │               │
│             └────────────────┴────────────────┴────────────────┘               │
│                                      │                                         │
│                                      ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                         BACKEND API (FastAPI)                             │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │   │
│  │  │                      API Endpoints                                  │ │   │
│  │  │  /agent/chat  /notes  /schedules  /upload  /assets  /knowledge   │ │   │
│  │  └─────────────────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                      │                                         │
│     ┌───────────────────────────────┼───────────────────────────────┐        │
│     │                               │                               │        │
│     ▼                               ▼                               ▼        │
│  ┌─────────────┐            ┌─────────────┐              ┌─────────────┐        │
│  │  Database   │            │    Redis   │              │  MinIO      │        │
│  │  PostgreSQL │            │  (Cache/   │              │  (Storage)  │        │
│  │  + pgvector │            │   Queue)   │              │             │        │
│  └─────────────┘            └─────────────┘              └─────────────┘        │
│                                                                                 │
│  ┌────────────────────────┬────────────────┬────────────────────────────┐   │
│  │     AI SERVICES        │                │                            │   │
│  ├────────────────────────┼────────────────┼────────────────────────────┤   │
│  │  ┌──────────────────┐  │                │                            │   │
│  │  │   AGENT SERVICE  │◄────────┐    ┌────▼────────────────────┐    │   │
│  │  │   (Gemini API)   │         │    │   OCR SERVICE (8007)     │    │   │
│  │  │                  │         │    │   - Layout Processor     │    │   │
│  │  │ - ModelClient    │         │    │   - Video Pipeline       │    │   │
│  │  │ - ToolRegistry   │         │    │   - MinIO/MongoDB        │    │   │
│  │  │ - Embedding      │         │    └─────────────────────────┘    │   │
│  │  │ - Semantic Search│         │                                      │   │
│  │  └──────────────────┘         │    ┌─────────────────────────┐     │   │
│  │                                │    │   STT SERVICE (8008)     │     │   │
│  │                                │    │   - Whisper              │     │   │
│  │                                │    │   - VOSK                 │     │   │
│  │                                │    │   - Redis Queue          │     │   │
│  │                                │    └─────────────────────────┘     │   │
│  └────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Architecture Layers

| Layer | Components | Description |
|-------|------------|-------------|
| **Presentation** | React Frontend | UI cho chat, notes, schedules, knowledge |
| **API Gateway** | FastAPI Backend | REST APIs, SSE endpoints |
| **Data Layer** | PostgreSQL, Redis, MinIO, MongoDB | Storage, caching, queue |
| **AI Services** | Agent, OCR, STT | Core AI processing |
| **External AI** | Gemini API, Whisper, VOSK | Third-party AI providers |

---

## AI Components and Modules

### 1. AGENT SERVICE (Backend AI Core)

**Location**: `backend/app/services/agent/`

**Main Components**:

| Component | File | Role |
|-----------|------|------|
| `AgentService` | `agent_service.py` | Main orchestration - xử lý conversation, tool calling loop |
| `ModelClient` | `model_client.py` | Gemini API client với round-robin, retry, rate-limit handling |
| `ToolRegistry` | `tool_registry.py` | Đăng ký và quản lý các AI tools |
| `ToolContext` | `tool_context.py` | Context provider cho tool execution |
| `EmbeddingService` | `embedding_service.py` | Text embedding generation (Gemini text-embedding-004) |
| `SemanticSearch` | `semantic_search.py` | Vector search trong PostgreSQL (pgvector) |
| `ConversationStore` | `conversation_store.py` | Lưu trữ và truy xuất conversation history |
| `ConversationSummarizer` | `conversation_summarizer.py` | Tóm tắt conversation dài |

### 2. Available AI Tools

**Location**: `backend/app/services/agent/tools/`

| Tool Name | Function | Description |
|-----------|----------|-------------|
| `search_notes` | Semantic search | Tìm kiếm notes bằng semantic similarity |
| `create_note` | Write | Tạo note mới trong workspace |
| `get_schedules` | Read | Lấy danh sách lịch trong khoảng thời gian |
| `create_schedule` | Write | Tạo event/schedule mới |
| `update_schedule` | Write | Cập nhật schedule existing |
| `search_knowledge` | Search | Tìm kiếm knowledge units |
| `summarize_asset` | AI Processing | Tóm tắt video/audio content |
| `get_notifications` | Read | Lấy notifications của user |
| `web_search` | Search | Tìm kiếm web |
| `neural_search` | Advanced Search | Neural search với embeddings |
| `deep_research` | Research | Deep research capability |

### 3. OCR SERVICE

**Location**: `ocr_service/`

```
OCR Service Architecture:
┌─────────────────────────────────────────────────────┐
│                   FastAPI (8007)                    │
├─────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │  Consumer   │  │   Pipeline   │  │  Storage  │  │
│  │  (Redis)    │  │  (Layout,    │  │  MinIO,   │  │
│  │             │  │   Video)     │  │  MongoDB  │  │
│  └─────────────┘  └─────────────┘  └───────────┘  │
└─────────────────────────────────────────────────────┘
```

### 4. STT SERVICE

**Location**: `stt_service/`

```
STT Service Architecture:
┌─────────────────────────────────────────────────────┐
│                   FastAPI (8008)                    │
├─────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │  Whisper    │  │    VOSK     │  │  Redis    │  │
│  │  (Large)    │  │  (Realtime) │  │  Queue    │  │
│  └─────────────┘  └─────────────┘  └───────────┘  │
│  ┌─────────────┐  ┌─────────────┐                   │
│  │   Summary   │  │   Result    │                   │
│  │  Processor  │  │  Dispatcher│                   │
│  └─────────────┘  └─────────────┘                   │
└─────────────────────────────────────────────────────┘
```

---

## AI Integration Architecture

### 1. Agent Service Integration Flow

```
User Request Flow:
┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Frontend│────►│  /agent/chat│────►│AgentService │────►│ ModelClient │
│  (UI)   │     │ (API)       │     │ (Handler)   │     │ (Gemini)    │
└─────────┘     └─────────────┘     └──────┬──────┘     └──────┬──────┘
                                           │                   │
                                           ▼                   ▼
                                    ┌─────────────┐     ┌─────────────┐
                                    │ ToolRegistry│     │  Response   │
                                    │ (Execute)   │────►│  + Tools    │
                                    └──────┬──────┘     └─────────────┘
                                           │
                   ┌───────────────────────┼───────────────────────┐
                   │                       │                       │
                   ▼                       ▼                       ▼
            ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
            │ Note Tools │         │Schedule Tools│         │Other Tools │
            │ (CRUD)     │         │  (CRUD)     │         │            │
            └──────┬──────┘         └──────┬──────┘         └──────┬──────┘
                   │                       │                       │
                   └───────────────────────┼───────────────────────┘
                                           │
                                           ▼
                                    ┌─────────────┐
                                    │Conversation │
                                    │   Store     │
                                    └─────────────┘
```

### 2. Sequence Flow: User Chat Request

```
Sequence: User sends chat message -> AI processes -> Tools execute -> Response
┌──────────┐    ┌─────────┐    ┌────────────┐    ┌─────────────┐    ┌─────────┐
│  Client  │    │API Layer│    │AgentService│    │ModelClient  │    │  LLM    │
└────┬─────┘    └────┬────┘       └─────┬────┘       └──────┬─────┘    └────┬────┘
     │               │                   │                   │              │
     │ POST /chat   │                   │                   │              │
     │────────────► │                   │                   │              │
     │               │ AgentService()   │                   │              │
     │               │─────────────────►│                   │              │
     │               │                   │ Get conversation │              │
     │               │                   │─────────────────►│              │
     │               │                   │◄─────────────────│              │
     │               │                   │                  │              │
     │               │                   │ Build contents   │              │
     │               │                   │─────────────────►│              │
     │               │                   │                  │ Generate()   │
     │               │                   │                  │────────────►│
     │               │                   │                  │◄────────────│
     │               │                   │                  │              │
     │               │                   │ Check function   │              │
     │               │                   │ calls            │              │
     │               │                   │◄─────────────────│              │
     │               │                   │                  │              │
     │               │                   │ Execute tools   │              │
     │               │                   │─────────────────►│              │
     │               │                   │◄─────────────────│              │
     │               │                   │                  │              │
     │               │                   │ Loop (max 6)    │              │
     │               │                   │◄────────────────│              │
     │               │                   │                  │              │
     │               │                   │ Save messages   │              │
     │               │                   │─────────────────►│              │
     │               │                   │◄─────────────────│              │
     │               │                   │                  │              │
     │ Response      │                   │                  │              │
     │◄─────────────│                   │                  │              │
     │               │                   │                  │              │
```

---

## Data Flow Analysis

### 1. Input/Output Data

| Component | Input | Output |
|-----------|-------|--------|
| **Agent Service** | User message (text), conversation_id, workspace_id | Reply text, conversation_id, tool results |
| **OCR Service** | Video file (MinIO), job metadata | Extracted text, layout data (MongoDB) |
| **STT Service** | Audio file (MinIO) | Transcription text, timestamps |
| **Embedding Service** | Text string | 768-dim vector (JSON) |
| **Semantic Search** | Query text | Ranked list of notes with similarity scores |

### 2. Data Flow Between Components

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                              COMPLETE DATA FLOW                                 │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  USER MESSAGE                                                                   │
│       │                                                                         │
│       ▼                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                      FastAPI /agent/chat                                  │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│       │                                                                         │
│       ▼                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                    AgentService.handle()                                  │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │   │
│  │  │ 1. Get/Create Conversation (DB)                                    │ │   │
│  │  │ 2. Check token budget                                               │ │   │
│  │  │ 3. Load recent messages (ConversationStore)                         │ │   │
│  │  │ 4. Build system prompt + context                                    │ │   │
│  │  └─────────────────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│       │                                                                         │
│       ▼                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                    ModelClient.generate()                                 │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │   │
│  │  │ - Round-robin: gemini-3.1-flash-lite -> gemma-4-31b-it -> gemma... │ │   │
│  │  │ - Rate limit budget tracking (RPM, TPM, RPD)                        │ │   │
│  │  │ - Retry with fallback on errors                                     │ │   │
│  │  └─────────────────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│       │                                                                         │
│       ▼                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                    LLM Response + Function Calls                          │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│       │                                                                         │
│       ▼                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                    Tool Execution Loop (MAX_TOOL_TURNS = 6)              │   │
│  │  ┌─────────────────────────────────────────────────────────────────────┐ │   │
│  │  │ For each function call:                                            │ │   │
│  │  │   - ToolRegistry.execute(tool_name, args, ctx)                    │ │   │
│  │  │   - Execute via ToolDefinition.handler                             │ │   │
│  │  │   - Return result to model                                         │ │   │
│  │  └─────────────────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│       │                                                                         │
│       ▼                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                    ConversationStore.save_message()                     │   │
│  │  - Save user message                                                    │   │
│  │  - Save assistant message (with function calls)                        │   │
│  │  - Save tool results                                                    │   │
│  │  - Update conversation timestamp & message count                       │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│       │                                                                         │
│       ▼                                                                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                    Response + Conversation ID                            │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## API and Service Integration

### 1. Main API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agent/chat` | POST | Non-streaming chat with AI agent |
| `/agent/stream/chat` | POST | Streaming chat with SSE |
| `/agent/conversations` | GET | List all conversations |
| `/agent/conversations/{id}` | GET | Get conversation with messages |
| `/agent/conversations/{id}` | DELETE | Delete conversation |
| `/notes` | GET/POST | Notes CRUD |
| `/schedules` | GET/POST/PUT | Schedule CRUD |
| `/upload` | POST | File upload to MinIO |
| `/assets` | GET/POST | Asset management |

### 2. SSE Events (Streaming)

| Event | Payload | Description |
|-------|---------|-------------|
| `token` | `{text: string}` | Text chunk from LLM |
| `tool_start` | `{tool_name, tool_args}` | Tool execution started |
| `tool_result` | `{tool_name, result}` | Tool execution completed |
| `done` | `{conversation_id}` | Stream completed |
| `error` | `{message}` | Error occurred |

---

## Memory and Context Management

### 1. Conversation Memory Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        CONVERSATION MEMORY LAYERS                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  Layer 1: Current Turn (in-memory)                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ contents = [                                                              │    │
│  │   Content(role="user", parts=[Part(text=current_message)]),             │    │
│  │   Content(role="model", parts=[Part(function_call=...)]),              │    │
│  │   Content(role="user", parts=[Part(function_response=...)])            │    │
│  │ ]                                                                         │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                      │                                          │
│  Layer 2: Recent Messages (sliding window)                                     │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ MAX_CONVERSATION_HISTORY = 10 messages                                  │    │
│  │ - Loaded from DB: AgentMessage records                                  │    │
│  │ - Converted to Gemini Content format                                    │    │
│  │ - Oldest first (chronological order)                                    │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                      │                                          │
│  Layer 3: Conversation Summary (long conversations)                            │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │ MESSAGE_THRESHOLD = 20 messages                                         │    │
│  │ - Summarizer compresses older messages to ~300 words                   │    │
│  │ - Stored in AgentConversation.summary                                   │    │
│  │ - Prepended to system prompt as "=== PREVIOUS CONVERSATION CONTEXT ==="│    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2. Embedding and Semantic Search

```
Semantic Search Flow:
┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────┐
│  User Query │───►│ EmbeddingService │───►│ SemanticSearch  │───►│ pgvector │
│             │    │ .embed_query()   │    │ .semantic_search│    │   DB     │
│             │    │ (768-dim vector) │    │   (cosine sim)  │    │          │
└─────────────┘    └──────────────────┘    └─────────────────┘    └──────────┘
                                               │
                                               ▼
                                        ┌─────────────────┐
                                        │  Results with   │
                                        │  similarity %   │
                                        └─────────────────┘
```

### 3. Redis Caching

| Cache Key | Data | TTL |
|-----------|------|-----|
| `embedding:v1:{sha256(text)}` | Embedding vector JSON | 30 days |
| Redis Stream: `stt_tasks` | STT job queue | N/A |
| Redis Stream: `ocr_tasks` | OCR job queue | N/A |

---

## Tool Calling and Orchestration

### 1. Tool Registry Architecture

```
Tool Registration Flow:
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Application Startup                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  import app.services.agent.tools                                            │
│       │                                                                      │
│       ▼                                                                      │
│  register_all_tools()                                                        │
│       │                                                                      │
│       ├── search_notes ──► ToolDefinition                                    │
│       ├── create_note  ──► ToolDefinition                                    │
│       ├── get_schedules ─► ToolDefinition                                    │
│       ├── create_schedule ─► ToolDefinition                                  │
│       └── ...                                                               │
│                                                                              │
│       Each ToolDefinition contains:                                          │
│       ┌────────────────────────────────────────────────────────────────┐    │
│       │ name: str          - Tool identifier                           │    │
│       │ description: str   - For LLM to understand capabilities        │    │
│       │ schema: dict      - JSON Schema for parameters                 │    │
│       │ handler: Callable - Async function(args, ctx) -> dict         │    │
│       │ input_model: Pydantic - Optional validation model             │    │
│       └────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Tool Execution Flow

```
Tool Execution Sequence:
┌─────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────────────┐
│  Model  │    │ToolRegistry │    │ToolDefinition│    │    Handler       │
│ Response│───►│ .execute()  │───►│ .validate() │───►│ (tool_*.py)      │
└─────────┘    └─────────────┘    └──────────────┘    └──────────────────┘
     │               │                   │                      │
     │         Find tool by          Validate with           Execute
     │         name in dict          Pydantic model          business logic
     │                                                        │
     │                                                        ▼
     │                                                 ┌─────────────┐
     │                                                 │   Context   │
     │                                                 │  (DB, user) │
     │                                                 └─────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Tool Result returned to model for next iteration                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 3. Tool Security

- **User Isolation**: All tools filtered by `ctx.user_id` from authenticated session
- **Permission Check**: Workspace permission verified before write operations
- **Input Validation**: Pydantic models validate all tool arguments

---

## Real-time Streaming Support

### 1. SSE Architecture

```
Streaming Chat Flow:
┌─────────┐    ┌─────────────────┐    ┌────────────────┐    ┌─────────────┐
│ Frontend│    │/agent/stream/   │    │AgentService    │    │ ModelClient │
│ EventSource│  │    chat        │    │.handle_streaming│  │ .stream_with│
└────┬────┘    └────────┬────────┘    └───────┬────────┘    └──────┬──────┘
     │                  │                      │                   │
     │ POST message    │                      │                   │
     │────────────────►│                      │                   │
     │                  │                      │                   │
     │                  │ Yield token events   │                   │
     │                  │◄─────────────────────│                   │
     │                  │                      │                   │
     │                  │                      │ Tool execution    │
     │                  │                      │◄─────────────────│
     │                  │                      │                   │
     │                  │ Yield tool events    │                   │
     │                  │◄─────────────────────│                   │
     │                  │                      │                   │
     │                  │                      │ Done event        │
     │                  │◄─────────────────────│                   │
     │                  │                      │                   │
     │ event: token    │                      │                   │
     │◄────────────────│                      │                   │
     │                 │                      │                   │
```

### 2. Streaming Events Structure

```json
// Token event
{"event": "token", "text": "Hello! I can help you with..."}

// Tool start event
{"event": "tool_start", "tool_name": "search_notes", "tool_args": {"query": "meeting"}}

// Tool result event
{"event": "tool_result", "tool_name": "search_notes", "result": {"count": 5, "notes": [...]}}

// Done event
{"event": "done", "conversation_id": "uuid-string", "latency_ms": 1234}

// Error event
{"event": "error", "message": "An error occurred"}
```

---

## Technology Stack

### 1. Backend Technologies

| Category | Technology | Version/Notes |
|----------|------------|---------------|
| **Framework** | FastAPI | Python async |
| **Database** | PostgreSQL | + pgvector for embeddings |
| **Cache/Queue** | Redis | Async support |
| **Object Storage** | MinIO | S3-compatible |
| **Document DB** | MongoDB | For knowledge/assets |
| **ORM** | SQLAlchemy | Async support |
| **AI Model** | Gemini API | gemini-3.1-flash-lite, gemma-4 |
| **Embedding** | Gemini text-embedding-004 | 768-dim |

### 2. AI Service Technologies

| Service | Technology | Purpose |
|---------|------------|---------|
| **Agent LLM** | Gemini API | Conversation AI |
| **Embedding** | Gemini embedding-001/004 | Text vectorization |
| **OCR** | Tesseract + Custom | Video frame text extraction |
| **STT** | Whisper + VOSK | Audio transcription |
| **Summary** | Gemini API | Conversation/document summarization |

### 3. Frontend Technologies

| Category | Technology |
|----------|------------|
| **Framework** | React |
| **Language** | TypeScript |
| **State** | Zustand |
| **HTTP** | Axios |
| **Real-time** | SSE (EventSource) |

---

## AI Capabilities Matrix

| Capability | Implementation | Status |
|------------|----------------|--------|
| **Chat/Conversation** | AgentService + Gemini | ✅ Active |
| **Create Note** | create_note tool | ✅ Active |
| **Get Schedules** | get_schedules tool | ✅ Active |
| **Create Schedule** | create_schedule tool | ✅ Active |
| **Update Schedule** | update_schedule tool | ✅ Active |
| **Search Notes (Semantic)** | search_notes + SemanticSearch | ✅ Active |
| **Search Knowledge** | search_knowledge tool | ✅ Active |
| **Summarize Asset** | summarize_asset tool | ✅ Active |
| **Get Notifications** | get_notifications tool | ✅ Active |
| **Web Search** | web_search tool | ✅ Active |
| **Neural Search** | neural_search tool | ✅ Active |
| **Deep Research** | deep_research tool | ✅ Active |
| **OCR Processing** | OCR Service | ✅ Active |
| **Speech-to-Text** | STT Service (Whisper/VOSK) | ✅ Active |
| **Vector Search** | pgvector + EmbeddingService | ✅ Active |
| **Conversation Summary** | ConversationSummarizer | ✅ Active |
| **Real-time Streaming** | SSE in /agent/stream/chat | ✅ Active |
| **Multi-model Fallback** | ModelClient round-robin | ✅ Active |
| **Rate Limit Management** | RateLimitBudget tracking | ✅ Active |
| **Tool Result Caching** | Redis | ⚙️ Not fully utilized |

---

## Distinction: Chatbot AI vs AI System

### 1. What Cortex IS NOT (Not just a chatbot)

| Aspect | Simple Chatbot | Cortex AI System |
|--------|----------------|------------------|
| **Scope** | Conversational UI only | Full productivity platform |
| **Data Access** | None or limited | Full access to user data (notes, schedules, notifications) |
| **Actions** | Text responses only | Can CREATE, UPDATE, DELETE data |
| **Integration** | Standalone | Deep integration with backend services |
| **Processing** | Single request/response | Multi-step workflows with tool orchestration |
| **Context** | Current message only | Conversation history + summaries |

### 2. What Cortex IS (AI-integrated system)

| Characteristic | Implementation |
|----------------|----------------|
| **AI as Orchestrator** | AgentService coordinates multiple tools in a loop |
| **AI as Data Processor** | OCR, STT process media files into structured data |
| **AI as Search Engine** | Semantic search with vector embeddings |
| **AI as Context Manager** | Conversation summarization for long-running dialogues |
| **AI as Action Executor** | Tools can modify user data (create note, schedule) |
| **AI as Real-time Processor** | Streaming responses with SSE |
| **Multi-service Architecture** | Agent, OCR, STT as separate microservices |

### 3. System Integration Points

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     CORTEX AI SYSTEM INTEGRATION POINTS                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   Frontend <──────┐                                                                │
│       │           │                                                                │
│       ▼           │                                                                │
│   FastAPI Backend│                                                                │
│       │           │                                                                │
│       ├───────────┼────────────────────────────────────────────────────────────┐  │
│       │           │                              │                            │  │
│       ▼           ▼                              ▼                            ▼  │
│  ┌─────────┐ ┌─────────┐              ┌──────────────┐   ┌──────────────┐    │
│  │ Agent   │ │  Notes  │              │  Schedule    │   │ Notification │    │
│  │ Service │ │ Service │              │   Service    │   │   Service    │    │
│  └────┬────┘ └────┬────┘              └───────┬──────┘   └───────┬──────┘    │
│       │           │                              │                 │            │
│       │           │                              │                 │            │
│       ▼           ▼                              ▼                 ▼            │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                         TOOL LAYER (AI-CONTROLLED)                       │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │ search   │ │ create   │ │  get     │ │ create   │ │   get    │    │   │
│  │  │ _notes   │ │ _note    │ │_schedules│ │_schedule │ │_notifs   │    │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘    │   │
│  └───────┼────────────┼────────────┼────────────┼────────────┼──────────┘   │
│          │            │            │            │            │                 │
│          └────────────┴────────────┴────────────┴────────────┘                 │
│                                       │                                        │
│                                       ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA LAYER                                        │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │   │
│  │  │ PostgreSQL  │  │    Redis    │  │   MinIO     │  │  MongoDB    │     │   │
│  │  │ (Notes,     │  │ (Cache,     │  │ (Media      │  │ (Knowledge,│     │   │
│  │  │  Schedules) │  │  Queue)     │  │  Files)     │  │  Assets)   │     │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘     │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Extensibility Analysis

### 1. Adding New Tools

```python
# Step 1: Create handler in tools/
async def my_new_tool_handler(args: dict, ctx: ToolContext) -> dict:
    # Implementation
    return {"result": "success"}

# Step 2: Define schema
MY_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "param1": {"type": "string", "description": "..."}
    },
    "required": ["param1"]
}

# Step 3: Add to __init__.py
MY_TOOL_DEFINITION = {
    "name": "my_new_tool",
    "handler": my_new_tool_handler,
    "input_model": MyToolInput,
    "schema": MY_TOOL_SCHEMA,
    "description": "Description for LLM"
}
```

### 2. Adding New AI Models

```python
# In model_client.py - extend AVAILABLE_MODELS
AVAILABLE_MODELS = [
    "models/gemini-3.1-flash-lite",
    "models/gemma-4-31b-it",
    # Add new model
    "models/gemini-2.0-flash-exp",
]

# Extend MODEL_LIMITS
MODEL_LIMITS = {
    "models/gemini-2.0-flash-exp": ModelLimits(rpm=15, tpm=1_000_000, rpd=500),
}
```

### 3. Multi-service Integration

Current services can be extended:
- **OCR**: Add new layout processors, support new formats
- **STT**: Add new language models, improve accuracy
- **Agent**: Add more sophisticated reasoning, agentic workflows

---

## Recommendations for Project Description

### Recommended Project Title

**"Cortex: AI-Integrated Productivity Platform with Multi-Service Architecture"**

### Recommended Description (for thesis/report)

> "Cortex là một hệ thống tích hợp AI (AI-integrated system) được xây dựng trên kiến trúc microservices, tích hợp các khả năng của AI vào nền tảng quản lý công việc (productivity platform). Hệ thống bao gồm ba thành phần AI chính: (1) Agent Service - AI agent với function calling để xử lý yêu cầu người dùng và điều phối các công cụ (tools) như tạo note, quản lý lịch, tìm kiếm knowledge; (2) OCR Service - dịch vụ xử lý video/image thành text; (3) STT Service - dịch vụ chuyển đổi audio thành văn bản. Hệ thống sử dụng PostgreSQL với pgvector cho semantic search, Redis cho caching và message queue, và Gemini API của Google làm LLM chính. Điểm nổi bật là khả năng tích hợp AI vào workflow của người dùng - AI không chỉ trả lời câu hỏi mà còn có thể thực hiện các thao tác trên dữ liệu (create, update, delete) thông qua tool calling mechanism."

### Key Terminology to Emphasize

| Term | Usage |
|------|-------|
| **AI-integrated system** | Hệ thống tích hợp AI, không chỉ là chatbot |
| **Function calling** | Cơ chế gọi hàm/tác vụ |
| **Tool orchestration** | Điều phối công cụ |
| **Multi-service architecture** | Kiến trúc đa dịch vụ |
| **Semantic search** | Tìm kiếm ngữ nghĩa với vector |
| **Real-time streaming** | Xử lý streaming với SSE |
| **Context management** | Quản lý ngữ cảnh (memory, summarization) |

---

## Appendix: Database Models Related to AI

### Agent Models

```python
class AgentConversation(Base):
    """Multi-turn conversation thread with an AI agent."""
    id: UUID
    user_id: UUID
    workspace_id: UUID
    title: str
    summary: Text  # Compressed summary of older messages
    message_count: int
    total_token_count: int

class AgentMessage(Base):
    """Message in an agent conversation."""
    id: UUID
    conversation_id: UUID
    role: str  # "user" | "assistant" | "tool"
    content: Text
    tool_name: str
    tool_input: JSONB
    tool_output: JSONB
    token_count: int
```

### Note Model with Embedding

```python
class Note(Base):
    """Note with vector embedding for semantic search."""
    id: UUID
    content: Text
    embedding: JSONB  # 768-dim vector (Gemini text-embedding-004)
    embedding_generated_at: DateTime
```

---

## Conclusion

Cortex represents a **comprehensive AI-integrated productivity system** where AI is deeply embedded into the application's core functionality. Unlike simple chatbot implementations, Cortex provides:

1. **Full Data Integration**: AI has access to and can manipulate user's notes, schedules, notifications
2. **Multi-Service Architecture**: Separate OCR and STT services handle media processing
3. **Advanced AI Features**: Semantic search, conversation summarization, multi-model fallback
4. **Real-time Capabilities**: Streaming responses via Server-Sent Events
5. **Extensibility**: Easy to add new tools and models

This architecture positions Cortex as a **modern AI-first productivity platform** rather than just a "chatbot with AI" wrapper.