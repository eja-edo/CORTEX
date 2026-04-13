# Cortex Knowledge Backend Design (Asset -> Segment -> Note Mapping)

Date: 2026-04-13
Status: Proposed (ready for phased implementation)

## 1. Goals and Constraints

Primary objective:
- Convert video/screen recordings into reusable knowledge, not passive playback.

Core modeling principles:
- Segment is atomic unit for indexing and timeline mapping.
- Notes are reusable knowledge objects, independent from a single asset.
- Mapping layer (note <-> segment) is first-class and many-to-many.

Real-world constraints:
- Multi-tenant (user/workspace scoped).
- High ingest volume (large media, async processing).
- Low-latency timeline jump and cross-note search.
- Safe concurrent editing and future collaborative editing (Yjs/CRDT).

## 2. High-level Architecture

Ingest pipeline:
1. Client uploads media (already available: multipart upload endpoint).
2. Asset is created and queued for processing.
3. Workers extract frames/audio, run OCR/ASR/UI detection.
4. Segment records are written in batches.
5. AI creates initial notes and mapping links.
6. Search index + embedding index are updated asynchronously.

Serving/query pipeline:
1. UI loads note graph + timeline snippets.
2. Clicking a note resolves linked segments and returns jump targets.
3. Clicking segment resolves related notes by relevance/role.
4. Global search queries notes + segments + OCR chunks.

## 3. Data Model (PostgreSQL)

Use UUID primary keys, add created_at/updated_at for all mutable entities.
Use JSONB only for flexible metadata fields, not for core relational links.

### 3.1 Enums

- asset_type: uploaded_video, screen_recording, live_session
- asset_status: pending, processing, ready, failed, archived
- segment_source: ocr, asr, ui_detection, user_highlight, ai_detection
- note_type: ai_summary, user_note, mixed
- link_type: reference, highlight, derived
- job_type: ingest, ocr, asr, detect_ui, summarize, embed
- job_status: queued, running, success, failed, canceled

### 3.2 Core Tables

#### users (existing)
Reuse existing users table.

#### assets
- id UUID PK
- user_id UUID NOT NULL FK users(id)
- workspace_id UUID NULL (future team/workspace support)
- type asset_type NOT NULL
- status asset_status NOT NULL DEFAULT pending
- title VARCHAR(255) NULL
- description TEXT NULL
- source_upload_id UUID NULL FK uploads(id)
- source_object_key VARCHAR(1024) NOT NULL
- duration_ms BIGINT NULL
- frame_rate NUMERIC(8,3) NULL
- width INT NULL
- height INT NULL
- captured_at TIMESTAMP NULL
- processed_at TIMESTAMP NULL
- failed_reason TEXT NULL
- metadata JSONB NOT NULL DEFAULT '{}'
- created_at TIMESTAMP NOT NULL DEFAULT NOW()
- updated_at TIMESTAMP NOT NULL DEFAULT NOW()

Indexes:
- (user_id, created_at DESC)
- (user_id, status)
- (workspace_id, created_at DESC)

#### segments
- id UUID PK
- user_id UUID NOT NULL FK users(id)
- asset_id UUID NOT NULL FK assets(id) ON DELETE CASCADE
- start_ms BIGINT NOT NULL
- end_ms BIGINT NOT NULL
- confidence NUMERIC(5,4) NULL
- source segment_source NOT NULL
- ocr_text TEXT NULL
- transcript_text TEXT NULL
- ui_summary TEXT NULL
- keyframe_url TEXT NULL
- language VARCHAR(16) NULL
- metadata JSONB NOT NULL DEFAULT '{}'
- created_at TIMESTAMP NOT NULL DEFAULT NOW()
- updated_at TIMESTAMP NOT NULL DEFAULT NOW()

Constraints:
- CHECK (start_ms >= 0)
- CHECK (end_ms > start_ms)

Indexes:
- (asset_id, start_ms)
- (user_id, created_at DESC)
- GIN on to_tsvector('simple', coalesce(ocr_text,'') || ' ' || coalesce(transcript_text,'') || ' ' || coalesce(ui_summary,''))

#### notes (extend existing notes table)
Current table can be reused with additive fields:
- title VARCHAR(255) NULL
- note_type note_type NOT NULL DEFAULT user_note
- workspace_id UUID NULL
- source_note_id UUID NULL FK notes(id) (for derivation)
- latest_snapshot_id UUID NULL (for versioning migration)

Keep existing fields:
- content, content_type, version, is_deleted, style, position, size

Indexes (add):
- (user_id, note_type, updated_at DESC)
- (workspace_id, updated_at DESC)
- optional FTS GIN for content

#### note_segment_links (critical mapping layer)
- id UUID PK
- user_id UUID NOT NULL FK users(id)
- note_id UUID NOT NULL FK notes(id) ON DELETE CASCADE
- segment_id UUID NOT NULL FK segments(id) ON DELETE CASCADE
- link_type link_type NOT NULL DEFAULT reference
- weight NUMERIC(5,4) NOT NULL DEFAULT 1.0
- anchor_text TEXT NULL
- start_offset INT NULL
- end_offset INT NULL
- metadata JSONB NOT NULL DEFAULT '{}'
- created_by UUID NULL FK users(id)
- created_at TIMESTAMP NOT NULL DEFAULT NOW()
- updated_at TIMESTAMP NOT NULL DEFAULT NOW()

Constraints:
- UNIQUE(note_id, segment_id, link_type)
- CHECK(weight >= 0 AND weight <= 1)

Indexes:
- (note_id, link_type)
- (segment_id, link_type)
- (user_id, created_at DESC)

#### bookmarks
- id UUID PK
- user_id UUID NOT NULL FK users(id)
- asset_id UUID NOT NULL FK assets(id) ON DELETE CASCADE
- segment_id UUID NULL FK segments(id) ON DELETE SET NULL
- label VARCHAR(255) NULL
- color VARCHAR(32) NULL
- metadata JSONB NOT NULL DEFAULT '{}'
- created_at TIMESTAMP NOT NULL DEFAULT NOW()

Indexes:
- (user_id, asset_id, created_at DESC)

### 3.3 Versioning and Collaboration Tables

#### note_snapshots
- id UUID PK
- note_id UUID NOT NULL FK notes(id) ON DELETE CASCADE
- version INT NOT NULL
- content TEXT NOT NULL
- patch JSONB NULL (optional structured diff)
- actor_user_id UUID NULL FK users(id)
- message VARCHAR(255) NULL
- created_at TIMESTAMP NOT NULL DEFAULT NOW()

Constraints:
- UNIQUE(note_id, version)

Indexes:
- (note_id, version DESC)

#### collab_documents (future CRDT)
- id UUID PK
- note_id UUID NOT NULL UNIQUE FK notes(id) ON DELETE CASCADE
- ydoc_state BYTEA NOT NULL
- vector_clock JSONB NULL
- updated_at TIMESTAMP NOT NULL DEFAULT NOW()

### 3.4 Processing and Search Tables

#### ingest_jobs
- id UUID PK
- user_id UUID NOT NULL FK users(id)
- asset_id UUID NOT NULL FK assets(id) ON DELETE CASCADE
- job_type job_type NOT NULL
- status job_status NOT NULL
- attempt INT NOT NULL DEFAULT 0
- progress NUMERIC(5,2) NOT NULL DEFAULT 0
- error_message TEXT NULL
- payload JSONB NOT NULL DEFAULT '{}'
- started_at TIMESTAMP NULL
- finished_at TIMESTAMP NULL
- created_at TIMESTAMP NOT NULL DEFAULT NOW()
- updated_at TIMESTAMP NOT NULL DEFAULT NOW()

Indexes:
- (asset_id, job_type)
- (status, created_at)

#### embeddings (for semantic search)
Option A (recommended): pgvector extension in same Postgres.
- id UUID PK
- owner_type VARCHAR(16) NOT NULL  -- note or segment
- owner_id UUID NOT NULL
- model VARCHAR(64) NOT NULL
- embedding VECTOR(1024) NOT NULL  -- size depends on model
- created_at TIMESTAMP NOT NULL DEFAULT NOW()

Constraints:
- UNIQUE(owner_type, owner_id, model)

Indexes:
- ivfflat/hnsw index on embedding
- btree on (owner_type, model)

## 4. API Design (v1)

Base path: /api
Auth: Bearer JWT, user_id from token.

### 4.1 Assets

POST /assets
- Create asset metadata after upload init/complete.

Request:
{
  "type": "uploaded_video",
  "title": "React Hooks Lecture",
  "source_upload_id": "uuid",
  "source_object_key": "videos/u1/2026/04/13/abc.webm"
}

Response 201:
{
  "id": "uuid",
  "status": "pending",
  "type": "uploaded_video",
  "created_at": "..."
}

GET /assets
- Filters: status, type, q, limit, cursor.

GET /assets/{asset_id}
PATCH /assets/{asset_id}
DELETE /assets/{asset_id}  -- soft delete recommended

POST /assets/{asset_id}/process
- Enqueue ingest pipeline.

Response 202:
{
  "asset_id": "uuid",
  "job_id": "uuid",
  "status": "queued"
}

GET /assets/{asset_id}/jobs
- Track pipeline status/progress.

### 4.2 Segments

GET /assets/{asset_id}/segments
- Query by time range, source, keyword.
- Params: from_ms, to_ms, source, q, limit, cursor.

POST /assets/{asset_id}/segments
- Create manual/user-highlight segment.

PATCH /segments/{segment_id}
DELETE /segments/{segment_id}

POST /segments/batch
- Bulk upsert from processing worker.

Request:
{
  "asset_id": "uuid",
  "segments": [
    {
      "start_ms": 12000,
      "end_ms": 18500,
      "source": "ocr",
      "ocr_text": "useEffect runs after render",
      "confidence": 0.93,
      "metadata": {"frame": 320}
    }
  ]
}

### 4.3 Notes

Keep existing /notes API, add capabilities:
- title, note_type, workspace_id
- filter by linked assets/segments
- optional include_links=true

New endpoints:

GET /notes/{note_id}/links
- Return all linked segments grouped by asset/timestamp.

PUT /notes/{note_id}/links
- Replace full mapping set atomically.

PATCH /notes/{note_id}/links
- Add/remove selected links.

Request:
{
  "add": [
    {
      "segment_id": "uuid",
      "link_type": "reference",
      "weight": 0.9,
      "metadata": {"reason": "definition"}
    }
  ],
  "remove": [
    {
      "segment_id": "uuid",
      "link_type": "highlight"
    }
  ]
}

GET /notes/{note_id}/timeline
- Resolve jump targets sorted by asset/time.

### 4.4 Reverse Navigation

GET /segments/{segment_id}/notes
- Return notes referencing this segment with link metadata.

GET /assets/{asset_id}/notes
- Return notes that reference any segment in this asset.

### 4.5 Search

GET /search
Params:
- q (required)
- types=notes,segments
- semantic=true|false
- limit, cursor

Response:
{
  "query": "oauth state",
  "items": [
    {
      "type": "segment",
      "id": "uuid",
      "score": 0.87,
      "asset_id": "uuid",
      "start_ms": 812000,
      "end_ms": 818000,
      "snippet": "state hash expires in 10 minutes"
    },
    {
      "type": "note",
      "id": "uuid",
      "score": 0.84,
      "title": "OAuth callback checklist",
      "snippet": "Validate state and one-time usage...",
      "linked_segments": 4
    }
  ],
  "next_cursor": "..."
}

### 4.6 Versioning

GET /notes/{note_id}/history
GET /notes/{note_id}/history/{version}
POST /notes/{note_id}/revert

Optional diff endpoint:
GET /notes/{note_id}/diff?from=3&to=7

### 4.7 Realtime (SSE/WebSocket)

Reuse existing SSE approach and add channels:
- ingest.job.updated
- asset.ready
- note.links.updated
- note.version.created

## 5. Permissions and Multi-tenant Rules

- Every read/write checks user_id ownership.
- Future workspace/team mode:
  - add workspace_members table and role checks.
  - user-scoped unique indexes become workspace-scoped where needed.

## 6. Scalability Guidelines

Database:
- Partition segments by month or by asset_id hash when table grows large.
- Keep hot query indexes focused: (asset_id, start_ms), (note_id), (segment_id).
- Move heavy metadata to JSONB only when query is rare.

Processing:
- Queue-based workers (Celery/RQ/Arq/Kafka consumers).
- Idempotent job handlers by unique key (asset_id + job_type + stage).
- Dead-letter queue for repeated failures.

Search:
- Start with PostgreSQL FTS + pgvector.
- Move to OpenSearch/Elastic when corpus and ranking complexity increase.

API:
- Cursor pagination for large lists (avoid offset for high cardinality).
- Batch endpoints for segment/link upsert.
- Strict payload size limits for safety.

## 7. Migration Plan From Current Backend

Current reusable components:
- /api/upload endpoints are ready for asset ingestion entrypoint.
- /api/notes has optimistic concurrency and batch update logic.

Phased migration:

Phase 1 (minimal viable mapping):
1. Add assets, segments, note_segment_links tables.
2. Add /assets, /segments, /notes/{id}/links, /segments/{id}/notes.
3. Keep existing note editing API unchanged.

Phase 2 (search and AI generation):
1. Add ingest_jobs and async worker.
2. Add OCR/ASR pipeline writing segments.
3. Add /search and initial AI note generation endpoint.

Phase 3 (versioning and collaboration):
1. Add note_snapshots and history APIs.
2. Integrate Yjs persistence (collab_documents).

## 8. Suggested SQLAlchemy Model Additions

New model files:
- app/models_assets.py
- app/models_segments.py
- app/models_note_links.py
- app/models_jobs.py

Router modules:
- app/api/assets.py
- app/api/segments.py
- app/api/search.py
- app/api/note_links.py

Service modules:
- app/services/ingest_pipeline.py
- app/services/search_service.py
- app/services/note_link_service.py

## 9. API Error Contract

Standard error shape:
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "Expected note version 5, got 4",
    "details": {
      "note_id": "uuid",
      "expected_version": 5,
      "actual_version": 4
    }
  }
}

Suggested error codes:
- ASSET_NOT_FOUND
- SEGMENT_NOT_FOUND
- NOTE_NOT_FOUND
- VERSION_CONFLICT
- LINK_ALREADY_EXISTS
- INVALID_TIME_RANGE
- INGEST_JOB_FAILED
- RATE_LIMITED

## 10. Minimal KPIs to Track

Product KPIs:
- time_to_first_note after upload
- search_success_rate (click-through)
- average jump-to-timestamp latency
- note reuse ratio across assets

System KPIs:
- ingest job success rate
- P95 API latency for /search and /assets/{id}/segments
- index/update lag for embeddings

---

This design preserves your current backend foundations while introducing the critical note-segment mapping layer as a scalable, first-class capability.
