# Cortex Knowledge Backend — System Design v2

**Date:** 2026-04-13
**Status:** Proposed — Production-ready, phased implementation
**Scope:** Full-stack backend design for video-to-knowledge extraction platform

---

## Table of Contents

1. [Goals & Non-Goals](#1-goals--non-goals)
2. [Architecture Overview](#2-architecture-overview)
3. [Data Model](#3-data-model)
4. [API Design](#4-api-design)
5. [Ingest Pipeline & Workers](#5-ingest-pipeline--workers)
6. [Search & AI Layer](#6-search--ai-layer)
7. [Permissions & Multi-tenancy](#7-permissions--multi-tenancy)
8. [Versioning & Collaboration](#8-versioning--collaboration)
9. [Observability & Cost Tracking](#9-observability--cost-tracking)
10. [Scalability & Infrastructure](#10-scalability--infrastructure)
11. [Migration Plan](#11-migration-plan)
12. [Error Contract](#12-error-contract)
13. [KPIs](#13-kpis)

---

## 1. Goals & Non-Goals

### Primary Goals

- Convert video/screen recordings into reusable, searchable knowledge objects.
- Atomic segment-level indexing with bi-directional note↔segment mapping.
- Low-latency timeline jump, cross-note semantic search, and AI-assisted note generation.
- Production-grade: multi-tenant, concurrent-safe, observable, cost-aware.

### Non-Goals (v1)

- Real-time collaborative video editing.
- Public-facing content distribution (CDN management is out of scope).
- Native mobile client; API-first only.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLIENT (Web/Desktop)                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTPS / SSE / WebSocket
┌────────────────────────────▼────────────────────────────────────────┐
│                         API GATEWAY                                 │
│          (Rate limiting · Auth JWT · Request validation)            │
└──────┬──────────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────┐
│              APPLICATION LAYER              │
│  FastAPI / NestJS — stateless, horizontally │
│  scalable pods                              │
│                                             │
│  Routers: assets · segments · notes ·       │
│           search · note_links · jobs ·      │
│           admin                             │
└──────┬──────────┬──────────────┬────────────┘
       │          │              │
┌──────▼──┐  ┌────▼──────┐  ┌───▼──────────────────────┐
│PostgreSQL│  │  Redis    │  │   Message Queue          │
│+ pgvector│  │  (cache · │  │   (Celery/ARQ/BullMQ)    │
│          │  │   locks · │  │                          │
│          │  │   SSE pub) │  │  Workers:                │
└──────────┘  └───────────┘  │  - ingest_worker         │
                              │  - ocr_worker            │
                              │  - asr_worker            │
                              │  - embed_worker          │
                              │  - ai_note_worker        │
                              │  - cache_worker          │
                              └──────────────────────────┘
```

**Storage layers:**

| Layer | Technology | Purpose |
|---|---|---|
| Primary DB | PostgreSQL 15+ | All relational data, FTS, pgvector |
| Cache / Pub-Sub | Redis 7 | Session cache, SSE pub/sub, job locks |
| Object Storage | S3-compatible | Raw media, derivatives, exports |
| Search (future) | OpenSearch | When FTS + pgvector reaches limits |
| Queue | Redis (ARQ) or RabbitMQ | Async job dispatch |

---

## 3. Data Model

### 3.1 Design Principles

- UUID primary keys everywhere.
- `created_at / updated_at` on all mutable tables.
- `deleted_at TIMESTAMP NULL` for soft delete on all user-owned entities.
- No polymorphic UUID FK — use nullable typed FK columns instead.
- JSONB only for flexible metadata, never for core relational links.
- Idempotent upsert keys defined explicitly on worker-written tables.

---

### 3.2 Enums

```sql
CREATE TYPE asset_type      AS ENUM ('uploaded_video','screen_recording','live_session');
CREATE TYPE asset_status    AS ENUM ('pending','processing','ready','failed','archived');
CREATE TYPE segment_source  AS ENUM ('ocr','asr','ui_detection','user_highlight','ai_detection');
CREATE TYPE note_type       AS ENUM ('ai_summary','user_note','mixed');
CREATE TYPE link_type       AS ENUM ('reference','highlight','derived');
CREATE TYPE job_type        AS ENUM ('ingest','ocr','asr','detect_ui','summarize','embed','cache');
CREATE TYPE job_status      AS ENUM ('queued','running','success','failed','canceled','dead');
CREATE TYPE relation_type   AS ENUM ('references','explains','derived_from','contradicts','supports');
CREATE TYPE derivative_type AS ENUM ('thumbnail','waveform','transcript','keyframes','summary_clip');
```

---

### 3.3 Core Tables

#### `workspaces`
```sql
CREATE TABLE workspaces (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            VARCHAR(255) NOT NULL,
  owner_user_id   UUID NOT NULL REFERENCES users(id),
  plan            VARCHAR(32) NOT NULL DEFAULT 'free',
  metadata        JSONB NOT NULL DEFAULT '{}',
  deleted_at      TIMESTAMP NULL,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### `workspace_members`
```sql
CREATE TABLE workspace_members (
  workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role          VARCHAR(32) NOT NULL DEFAULT 'member', -- owner | admin | member | viewer
  joined_at     TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, user_id)
);
```

#### `workspace_quotas`
```sql
CREATE TABLE workspace_quotas (
  workspace_id            UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
  max_storage_bytes       BIGINT NOT NULL DEFAULT 10737418240, -- 10 GB
  used_storage_bytes      BIGINT NOT NULL DEFAULT 0,
  max_concurrent_jobs     INT NOT NULL DEFAULT 3,
  max_assets              INT NOT NULL DEFAULT 100,
  ai_tokens_monthly_limit BIGINT NOT NULL DEFAULT 1000000,
  ai_tokens_used_month    BIGINT NOT NULL DEFAULT 0,
  quota_reset_at          TIMESTAMP NOT NULL DEFAULT DATE_TRUNC('month', NOW()) + INTERVAL '1 month',
  updated_at              TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

#### `assets`
```sql
CREATE TABLE assets (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES users(id),
  workspace_id      UUID NULL REFERENCES workspaces(id),
  type              asset_type NOT NULL,
  status            asset_status NOT NULL DEFAULT 'pending',
  title             VARCHAR(255) NULL,
  description       TEXT NULL,
  source_upload_id  UUID NULL REFERENCES uploads(id),
  source_object_key VARCHAR(1024) NOT NULL,
  duration_ms       BIGINT NULL,
  frame_rate        NUMERIC(8,3) NULL,
  width             INT NULL,
  height            INT NULL,
  size_bytes        BIGINT NULL,
  checksum_sha256   VARCHAR(64) NULL,  -- dedup detection
  captured_at       TIMESTAMP NULL,
  processed_at      TIMESTAMP NULL,
  failed_reason     TEXT NULL,
  metadata          JSONB NOT NULL DEFAULT '{}',
  deleted_at        TIMESTAMP NULL,
  created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ON assets (user_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ON assets (user_id, status) WHERE deleted_at IS NULL;
CREATE INDEX ON assets (workspace_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ON assets (checksum_sha256) WHERE checksum_sha256 IS NOT NULL;
```

> **Note:** `checksum_sha256` cho phép detect duplicate upload trong cùng workspace mà không cần re-process.

---

#### `asset_derivatives`
```sql
CREATE TABLE asset_derivatives (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id        UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  derivative_type derivative_type NOT NULL,
  storage_key     VARCHAR(1024) NOT NULL,
  format          VARCHAR(32) NULL,   -- webp, mp3, vtt, json
  size_bytes      BIGINT NULL,
  duration_ms     BIGINT NULL,
  metadata        JSONB NOT NULL DEFAULT '{}',
  created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE (asset_id, derivative_type)
);

CREATE INDEX ON asset_derivatives (asset_id, derivative_type);
```

---

#### `segments`
```sql
CREATE TABLE segments (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id),
  asset_id      UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  start_ms      BIGINT NOT NULL,
  end_ms        BIGINT NOT NULL,
  source        segment_source NOT NULL,
  confidence    NUMERIC(5,4) NULL,
  keyframe_url  TEXT NULL,
  language      VARCHAR(16) NULL,
  external_id   VARCHAR(255) NULL, -- worker-assigned idempotency key
  metadata      JSONB NOT NULL DEFAULT '{}',
  deleted_at    TIMESTAMP NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMP NOT NULL DEFAULT NOW(),

  CONSTRAINT chk_segment_time CHECK (start_ms >= 0 AND end_ms > start_ms)
);

-- Idempotent upsert key cho worker
CREATE UNIQUE INDEX ON segments (asset_id, external_id)
  WHERE external_id IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX ON segments (asset_id, start_ms) WHERE deleted_at IS NULL;
CREATE INDEX ON segments (user_id, created_at DESC) WHERE deleted_at IS NULL;
```

---

#### `segment_contents`
```sql
CREATE TABLE segment_contents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  segment_id    UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  content_type  VARCHAR(16) NOT NULL, -- ocr | asr | ui | translation | code
  content       TEXT NOT NULL,
  language      VARCHAR(16) NULL,
  confidence    NUMERIC(5,4) NULL,
  metadata      JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (segment_id, content_type, language)
);

CREATE INDEX ON segment_contents (segment_id, content_type);
-- Full-text search index
CREATE INDEX ON segment_contents USING GIN (to_tsvector('simple', content));
```

---

#### `notes` (additive extension of existing table)
```sql
-- Add columns to existing notes table:
ALTER TABLE notes ADD COLUMN title          VARCHAR(255) NULL;
ALTER TABLE notes ADD COLUMN note_type      note_type NOT NULL DEFAULT 'user_note';
ALTER TABLE notes ADD COLUMN workspace_id   UUID NULL REFERENCES workspaces(id);
ALTER TABLE notes ADD COLUMN source_note_id UUID NULL REFERENCES notes(id);
ALTER TABLE notes ADD COLUMN deleted_at     TIMESTAMP NULL;

-- New indexes
CREATE INDEX ON notes (user_id, note_type, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ON notes (workspace_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ON notes USING GIN (to_tsvector('simple', content)) WHERE deleted_at IS NULL;
```

---

#### `note_segment_links`
```sql
CREATE TABLE note_segment_links (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES users(id),
  note_id          UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  segment_id       UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  linked_asset_id  UUID NOT NULL REFERENCES assets(id),
  linked_start_ms  BIGINT NOT NULL,
  linked_end_ms    BIGINT NOT NULL,
  link_type        link_type NOT NULL DEFAULT 'reference',
  weight           NUMERIC(5,4) NOT NULL DEFAULT 1.0,
  anchor_text      TEXT NULL,
  start_offset     INT NULL,
  end_offset       INT NULL,
  created_by       UUID NULL REFERENCES users(id),
  metadata         JSONB NOT NULL DEFAULT '{}',
  deleted_at       TIMESTAMP NULL,
  created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (note_id, segment_id, link_type),
  CONSTRAINT chk_link_weight CHECK (weight >= 0 AND weight <= 1),
  CONSTRAINT chk_link_time CHECK (linked_start_ms >= 0 AND linked_end_ms > linked_start_ms)
);

CREATE INDEX ON note_segment_links (note_id, link_type) WHERE deleted_at IS NULL;
CREATE INDEX ON note_segment_links (segment_id, link_type) WHERE deleted_at IS NULL;
CREATE INDEX ON note_segment_links (linked_asset_id, linked_start_ms) WHERE deleted_at IS NULL;
CREATE INDEX ON note_segment_links (user_id, created_at DESC) WHERE deleted_at IS NULL;
```

---

#### `bookmarks`
```sql
CREATE TABLE bookmarks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  asset_id    UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  segment_id  UUID NULL REFERENCES segments(id) ON DELETE SET NULL,
  label       VARCHAR(255) NULL,
  color       VARCHAR(32) NULL,
  metadata    JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (user_id, asset_id, segment_id)
);

CREATE INDEX ON bookmarks (user_id, asset_id, created_at DESC);
```

---

### 3.4 Tags

```sql
CREATE TABLE tags (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  UUID NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id       UUID NOT NULL REFERENCES users(id),
  name          VARCHAR(100) NOT NULL,
  color         VARCHAR(32) NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (workspace_id, name),
  UNIQUE (user_id, name) -- personal tags when workspace_id IS NULL
);

CREATE TABLE entity_tags (
  tag_id       UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  -- Typed FK columns, no polymorphic UUID
  note_id      UUID NULL REFERENCES notes(id) ON DELETE CASCADE,
  asset_id     UUID NULL REFERENCES assets(id) ON DELETE CASCADE,
  segment_id   UUID NULL REFERENCES segments(id) ON DELETE CASCADE,
  concept_id   UUID NULL REFERENCES concepts(id) ON DELETE CASCADE,
  created_at   TIMESTAMP NOT NULL DEFAULT NOW(),

  CONSTRAINT chk_entity_tags_one_target CHECK (
    (note_id IS NOT NULL)::INT +
    (asset_id IS NOT NULL)::INT +
    (segment_id IS NOT NULL)::INT +
    (concept_id IS NOT NULL)::INT = 1
  )
);

CREATE INDEX ON entity_tags (note_id)    WHERE note_id IS NOT NULL;
CREATE INDEX ON entity_tags (asset_id)   WHERE asset_id IS NOT NULL;
CREATE INDEX ON entity_tags (segment_id) WHERE segment_id IS NOT NULL;
```

---

### 3.5 Versioning & Collaboration Tables

#### `note_snapshots`
```sql
CREATE TABLE note_snapshots (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  note_id       UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  version       INT NOT NULL,
  base_version  INT NULL,
  content       TEXT NOT NULL,
  patch         TEXT NULL,          -- diff-match-patch or CRDT op-log
  patch_format  VARCHAR(32) NULL,   -- 'dmp' | 'yjs-update' | 'full'
  actor_user_id UUID NULL REFERENCES users(id),
  message       VARCHAR(255) NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (note_id, version)
);

CREATE INDEX ON note_snapshots (note_id, version DESC);
```

#### `collab_documents` (Yjs CRDT)
```sql
CREATE TABLE collab_documents (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  note_id      UUID NOT NULL UNIQUE REFERENCES notes(id) ON DELETE CASCADE,
  ydoc_state   BYTEA NOT NULL,
  vector_clock JSONB NULL,
  updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

### 3.6 Processing Tables

#### `ingest_jobs`
```sql
CREATE TABLE ingest_jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id),
  asset_id        UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  job_type        job_type NOT NULL,
  stage           VARCHAR(32) NULL,
  parent_job_id   UUID NULL REFERENCES ingest_jobs(id),
  status          job_status NOT NULL DEFAULT 'queued',
  attempt         INT NOT NULL DEFAULT 0,
  max_attempts    INT NOT NULL DEFAULT 3,
  progress        NUMERIC(5,2) NOT NULL DEFAULT 0,
  error_message   TEXT NULL,
  -- Cost tracking
  provider        VARCHAR(32) NULL,    -- openai | google | whisper | local
  tokens_used     INT NULL,
  cost_usd        NUMERIC(10,6) NULL,
  -- Idempotency
  idempotency_key VARCHAR(255) NULL,
  payload         JSONB NOT NULL DEFAULT '{}',
  started_at      TIMESTAMP NULL,
  finished_at     TIMESTAMP NULL,
  created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (idempotency_key) -- prevent duplicate job dispatch
);

CREATE INDEX ON ingest_jobs (asset_id, job_type, stage);
CREATE INDEX ON ingest_jobs (parent_job_id);
CREATE INDEX ON ingest_jobs (status, created_at) WHERE status IN ('queued', 'running');
CREATE INDEX ON ingest_jobs (user_id, created_at DESC);
```

> **idempotency_key** = `{asset_id}:{job_type}:{stage}` — worker upserts on conflict do nothing.

---

### 3.7 Search & Embedding Tables

#### `note_embeddings`
```sql
CREATE TABLE note_embeddings (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  note_id     UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  model       VARCHAR(64) NOT NULL,
  embedding   VECTOR(1024) NOT NULL,
  is_current  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (note_id, model)
);

CREATE INDEX ON note_embeddings (note_id, is_current);
CREATE INDEX ON note_embeddings USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

#### `segment_embeddings`
```sql
CREATE TABLE segment_embeddings (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  segment_id  UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  model       VARCHAR(64) NOT NULL,
  embedding   VECTOR(1024) NOT NULL,
  is_current  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMP NOT NULL DEFAULT NOW(),

  UNIQUE (segment_id, model)
);

CREATE INDEX ON segment_embeddings (segment_id, is_current);
CREATE INDEX ON segment_embeddings USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

> Khi upgrade model: set `is_current = FALSE` cho toàn bộ records cũ, chạy re-embed job, rồi flip `is_current` atomically. Query layer chỉ JOIN với `is_current = TRUE`.

---

### 3.8 Knowledge Graph Tables

#### `concepts`
```sql
CREATE TABLE concepts (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id),
  workspace_id  UUID NULL REFERENCES workspaces(id),
  title         VARCHAR(255) NOT NULL,
  description   TEXT NULL,
  embedding     VECTOR(1024) NULL,
  metadata      JSONB NOT NULL DEFAULT '{}',
  deleted_at    TIMESTAMP NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
```

#### `entity_links` (typed FK, không polymorphic)
```sql
CREATE TABLE entity_links (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id),
  -- Source entity: exactly one non-null
  from_note_id      UUID NULL REFERENCES notes(id) ON DELETE CASCADE,
  from_segment_id   UUID NULL REFERENCES segments(id) ON DELETE CASCADE,
  from_concept_id   UUID NULL REFERENCES concepts(id) ON DELETE CASCADE,
  -- Target entity: exactly one non-null
  to_note_id        UUID NULL REFERENCES notes(id) ON DELETE CASCADE,
  to_segment_id     UUID NULL REFERENCES segments(id) ON DELETE CASCADE,
  to_concept_id     UUID NULL REFERENCES concepts(id) ON DELETE CASCADE,
  -- Edge metadata
  relation_type relation_type NOT NULL,
  weight        NUMERIC(5,4) NOT NULL DEFAULT 1.0,
  metadata      JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMP NOT NULL DEFAULT NOW(),

  CONSTRAINT chk_entity_links_from CHECK (
    (from_note_id IS NOT NULL)::INT +
    (from_segment_id IS NOT NULL)::INT +
    (from_concept_id IS NOT NULL)::INT = 1
  ),
  CONSTRAINT chk_entity_links_to CHECK (
    (to_note_id IS NOT NULL)::INT +
    (to_segment_id IS NOT NULL)::INT +
    (to_concept_id IS NOT NULL)::INT = 1
  )
);

CREATE INDEX ON entity_links (user_id, from_note_id)    WHERE from_note_id IS NOT NULL;
CREATE INDEX ON entity_links (user_id, from_segment_id) WHERE from_segment_id IS NOT NULL;
CREATE INDEX ON entity_links (user_id, to_note_id)      WHERE to_note_id IS NOT NULL;
CREATE INDEX ON entity_links (user_id, to_concept_id)   WHERE to_concept_id IS NOT NULL;
```

---

### 3.9 Cache & Scoring Tables

#### `asset_timeline_cache`
```sql
CREATE TABLE asset_timeline_cache (
  asset_id      UUID PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  version       INT NOT NULL DEFAULT 1,
  is_dirty      BOOLEAN NOT NULL DEFAULT FALSE, -- flag for lazy regeneration
  timeline      JSONB NOT NULL,
  generated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

> Thay vì DB trigger regenerate synchronously, worker subscribe vào event `segment.created`, `link.updated` và set `is_dirty = TRUE`. Cache layer regenerate lazily khi API đọc và `is_dirty = TRUE`.

#### `note_scores`
```sql
CREATE TABLE note_scores (
  note_id             UUID PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
  importance_score    NUMERIC(6,4) NOT NULL DEFAULT 0,
  recency_score       NUMERIC(6,4) NOT NULL DEFAULT 0,
  interaction_score   NUMERIC(6,4) NOT NULL DEFAULT 0,
  link_density_score  NUMERIC(6,4) NOT NULL DEFAULT 0,
  updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

### 3.10 Audit & Notification Tables

#### `audit_events`
```sql
CREATE TABLE audit_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id),
  workspace_id  UUID NULL REFERENCES workspaces(id),
  entity_type   VARCHAR(32) NOT NULL,  -- asset | segment | note | link | concept
  entity_id     UUID NOT NULL,
  action        VARCHAR(32) NOT NULL,  -- create | update | delete | link | revert
  old_value     JSONB NULL,
  new_value     JSONB NULL,
  ip_address    INET NULL,
  user_agent    TEXT NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Monthly partitions
CREATE TABLE audit_events_2026_04 PARTITION OF audit_events
  FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE INDEX ON audit_events (user_id, created_at DESC);
CREATE INDEX ON audit_events (entity_type, entity_id);
```

#### `notifications`
```sql
CREATE TABLE notifications (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  type        VARCHAR(64) NOT NULL, -- ingest.completed | ai_note.ready | mention | quota.warning
  title       VARCHAR(255) NOT NULL,
  body        TEXT NULL,
  payload     JSONB NOT NULL DEFAULT '{}',
  read_at     TIMESTAMP NULL,
  created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX ON notifications (user_id, read_at, created_at DESC);
```

---

## 4. API Design

**Base path:** `/api/v1`
**Auth:** Bearer JWT — `user_id` extracted from token.
**Pagination:** Cursor-based (`cursor` + `limit`), không dùng OFFSET.
**Soft-deleted resources** trả về 404.

---

### 4.1 Assets

```
POST   /assets                          Create asset after upload
GET    /assets                          List assets (filters: status, type, q, tag, workspace_id)
GET    /assets/:id                      Get single asset
PATCH  /assets/:id                      Update title/description/metadata
DELETE /assets/:id                      Soft delete

POST   /assets/:id/process              Enqueue ingest pipeline
GET    /assets/:id/jobs                 List ingest jobs and progress
GET    /assets/:id/segments             List segments (from_ms, to_ms, source, q)
GET    /assets/:id/notes                Notes referencing any segment of this asset
GET    /assets/:id/timeline             Precomputed merged timeline (segments + links)
GET    /assets/:id/derivatives          List derivatives (thumbnail, waveform, etc.)
```

**POST /assets response (201):**
```json
{
  "id": "uuid",
  "status": "pending",
  "type": "uploaded_video",
  "created_at": "2026-04-13T10:00:00Z"
}
```

**POST /assets/:id/process response (202):**
```json
{
  "asset_id": "uuid",
  "root_job_id": "uuid",
  "child_jobs": ["uuid", "uuid", "uuid"],
  "estimated_duration_s": 45
}
```

---

### 4.2 Segments

```
GET    /assets/:id/segments             List segments with content
POST   /assets/:id/segments             Create manual/highlight segment
PATCH  /segments/:id                    Update label/metadata
DELETE /segments/:id                    Soft delete

POST   /segments/batch                  Bulk upsert from workers (idempotent)
GET    /segments/:id/notes              Notes linked to this segment
```

**POST /segments/batch request:**
```json
{
  "asset_id": "uuid",
  "segments": [
    {
      "external_id": "ocr-frame-320",
      "start_ms": 12000,
      "end_ms": 18500,
      "source": "ocr",
      "confidence": 0.93,
      "contents": [
        {
          "content_type": "ocr",
          "content": "useEffect runs after every render by default",
          "language": "en",
          "confidence": 0.93
        }
      ],
      "metadata": { "frame_index": 320 }
    }
  ]
}
```

Response: `{ "created": 12, "updated": 3, "skipped": 0 }`

---

### 4.3 Notes

Giữ nguyên API hiện tại, bổ sung:

```
GET    /notes                           Thêm filter: linked_asset_id, linked_segment_id, workspace_id
POST   /notes
GET    /notes/:id
PATCH  /notes/:id
DELETE /notes/:id                       Soft delete

GET    /notes/:id/links                 All linked segments grouped by asset
PUT    /notes/:id/links                 Replace full link set (atomic)
PATCH  /notes/:id/links                 Add/remove selected links
GET    /notes/:id/timeline              Jump targets sorted by asset/time
GET    /notes/:id/history               Version history
GET    /notes/:id/history/:version      Snapshot at version
POST   /notes/:id/revert               Revert to version
GET    /notes/:id/diff?from=3&to=7     Patch diff between versions
```

**PATCH /notes/:id/links request:**
```json
{
  "add": [
    {
      "segment_id": "uuid",
      "linked_asset_id": "uuid",
      "linked_start_ms": 12000,
      "linked_end_ms": 18500,
      "link_type": "reference",
      "weight": 0.9,
      "anchor_text": "useEffect definition",
      "metadata": { "reason": "definition" }
    }
  ],
  "remove": [
    { "segment_id": "uuid", "link_type": "highlight" }
  ]
}
```

---

### 4.4 Search

```
GET /search
```

**Query params:**

| Param | Type | Description |
|---|---|---|
| `q` | string (required) | Keyword or natural language query |
| `types` | notes,segments | Resource types to include |
| `semantic` | boolean | Enable pgvector similarity |
| `asset_id` | uuid | Scope to single asset |
| `workspace_id` | uuid | Scope to workspace |
| `from_ms` / `to_ms` | int | Time range filter for segments |
| `link_type` | enum | Filter notes by link relationship |
| `tag_ids` | uuid[] | Filter by tags |
| `limit` / `cursor` | pagination | |

**Response:**
```json
{
  "query": "oauth state validation",
  "semantic": true,
  "items": [
    {
      "type": "segment",
      "id": "uuid",
      "score": 0.91,
      "asset_id": "uuid",
      "asset_title": "Auth Flow Deep Dive",
      "start_ms": 812000,
      "end_ms": 818000,
      "snippet": "state hash expires after 10 minutes and is single-use",
      "source": "asr"
    },
    {
      "type": "note",
      "id": "uuid",
      "score": 0.87,
      "title": "OAuth callback checklist",
      "snippet": "Validate state parameter and ensure one-time usage...",
      "linked_segments": 4,
      "tags": ["security", "oauth"]
    }
  ],
  "next_cursor": "eyJpZCI6InV1aWQiLCJzY29yZSI6MC44N30="
}
```

---

### 4.5 Jobs & Progress

```
GET  /jobs/:id             Job status + progress + cost info
GET  /assets/:id/jobs      All jobs for asset (grouped by stage)
POST /jobs/:id/cancel      Cancel queued/running job
```

**GET /jobs/:id response:**
```json
{
  "id": "uuid",
  "asset_id": "uuid",
  "job_type": "ocr",
  "stage": "extract",
  "status": "running",
  "progress": 42.5,
  "attempt": 1,
  "provider": "google",
  "tokens_used": null,
  "cost_usd": null,
  "started_at": "2026-04-13T10:01:00Z",
  "finished_at": null
}
```

---

### 4.6 Realtime (SSE)

**Channel:** `GET /realtime/events` (Bearer token required)

```
Event types:
  ingest.job.progress       { job_id, asset_id, stage, progress }
  ingest.job.completed      { job_id, asset_id, stage }
  ingest.job.failed         { job_id, asset_id, error }
  asset.ready               { asset_id }
  note.links.updated        { note_id, added, removed }
  note.version.created      { note_id, version }
  timeline.cache.dirty      { asset_id }
  quota.warning             { workspace_id, usage_pct }
  notification.created      { notification_id, type, title }
```

---

### 4.7 Admin / Internal

```
GET  /admin/jobs             Queue health overview
POST /admin/jobs/retry-dead  Retry dead-letter jobs
GET  /admin/quotas           Usage stats per workspace
POST /admin/embeddings/reindex  Trigger re-embed for model upgrade
```

---

## 5. Ingest Pipeline & Workers

### 5.1 Job DAG

```
POST /assets/:id/process
        │
        ▼
  [root: ingest]
        │
   ┌────┴─────────────┐
   ▼                  ▼
[extract_frames]  [extract_audio]
   │                  │
   ▼                  ▼
[ocr_worker]     [asr_worker]
   │                  │
   └────────┬─────────┘
            ▼
     [detect_ui_worker]
            │
            ▼
     [chunk_worker]       ← merge OCR+ASR into semantic chunks
            │
            ▼
     [embed_worker]       ← embed segments + update segment_embeddings
            │
            ▼
     [ai_note_worker]     ← generate initial notes + links
            │
            ▼
     [cache_worker]       ← regenerate timeline cache
```

### 5.2 Worker Design

**Idempotency:** Mọi worker đều upsert dựa trên `idempotency_key = {asset_id}:{job_type}:{stage}`. Retry an toàn.

**Progress reporting:** Worker update `ingest_jobs.progress` mỗi batch và publish SSE event `ingest.job.progress`.

**Dead letter:** Sau `max_attempts` thất bại, job chuyển sang `status = 'dead'`. Admin có thể retry thủ công.

**Cost tracking:**
```python
# Sau mỗi AI call trong worker:
await db.execute("""
  UPDATE ingest_jobs
  SET tokens_used = :tokens, cost_usd = :cost, provider = :provider
  WHERE id = :job_id
""", {...})

# Cộng dồn vào workspace quota:
await db.execute("""
  UPDATE workspace_quotas
  SET ai_tokens_used_month = ai_tokens_used_month + :tokens
  WHERE workspace_id = :workspace_id
""", {...})
```

### 5.3 Quota Check Before Dispatch

```python
async def dispatch_ingest(asset_id, workspace_id):
    quota = await get_quota(workspace_id)
    active_jobs = await count_active_jobs(workspace_id)

    if active_jobs >= quota.max_concurrent_jobs:
        raise QuotaExceededError("CONCURRENT_JOB_LIMIT")

    if quota.used_storage_bytes >= quota.max_storage_bytes:
        raise QuotaExceededError("STORAGE_LIMIT")

    # proceed to enqueue
```

---

## 6. Search & AI Layer

### 6.1 Search Strategy (Hybrid)

```
Query
  │
  ├── Keyword path:  PostgreSQL FTS (to_tsvector)
  │     segment_contents.content + notes.content
  │
  └── Semantic path: pgvector cosine similarity
        note_embeddings + segment_embeddings
        WHERE is_current = TRUE
  │
  └── Merge & re-rank by RRF (Reciprocal Rank Fusion):
        final_score = Σ 1 / (k + rank_i)  where k=60
```

**Khi nào chuyển sang OpenSearch:**
- Corpus > 10M segments, hoặc
- Cần faceted search phức tạp, hoặc
- FTS ranking không đủ chính xác với nhiều ngôn ngữ.

### 6.2 Embedding Model Upgrade Flow

```
1. Admin gọi POST /admin/embeddings/reindex?model=new-model
2. Worker set is_current = FALSE cho all records model cũ
3. Worker re-embed từng batch, insert record mới với is_current = TRUE
4. Xác nhận: count(is_current=TRUE, model=new) == total notes/segments
5. Xóa records cũ (hoặc giữ lại để rollback)
```

### 6.3 AI Note Generation

Worker `ai_note_worker` sau khi embed xong:

```
1. Lấy tất cả segments của asset
2. Group segments theo semantic cluster (cosine similarity > threshold)
3. Với mỗi cluster, gọi LLM:
   - Input: segment contents + timestamps
   - Output: { title, content, key_concepts[], link_suggestions[] }
4. Insert note với note_type = 'ai_summary'
5. Insert note_segment_links với link_type = 'derived'
6. Insert concepts nếu chưa tồn tại
7. Insert entity_links concept→note
```

---

## 7. Permissions & Multi-tenancy

### 7.1 Ownership Rules

| Resource | Ownership check |
|---|---|
| asset | `user_id = current_user` OR `workspace_id IN user_workspaces` |
| segment | Via `asset_id` ownership |
| note | `user_id = current_user` OR `workspace_id IN user_workspaces` |
| note_segment_link | Both `note` and `segment` must be accessible |

### 7.2 Workspace Roles

| Action | viewer | member | admin | owner |
|---|---|---|---|---|
| Read assets/notes | ✅ | ✅ | ✅ | ✅ |
| Upload / create | ❌ | ✅ | ✅ | ✅ |
| Delete (soft) | ❌ | own only | ✅ | ✅ |
| Manage members | ❌ | ❌ | ✅ | ✅ |
| Manage quotas | ❌ | ❌ | ❌ | ✅ |

### 7.3 Row-level Security (optional, PostgreSQL RLS)

```sql
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;

CREATE POLICY assets_user_isolation ON assets
  USING (
    user_id = current_setting('app.current_user_id')::UUID
    OR workspace_id IN (
      SELECT workspace_id FROM workspace_members
      WHERE user_id = current_setting('app.current_user_id')::UUID
    )
  );
```

---

## 8. Versioning & Collaboration

### 8.1 Optimistic Concurrency

```
PATCH /notes/:id
  Header: If-Match: "version-5"

  Server:
  1. SELECT version FROM notes WHERE id = :id FOR UPDATE
  2. IF version != 5 → 409 VERSION_CONFLICT
  3. INSERT INTO note_snapshots (note_id, version=6, content, patch, patch_format, actor)
  4. UPDATE notes SET version=6, content=..., updated_at=NOW()
  5. COMMIT
```

### 8.2 CRDT Collaboration (Phase 3)

- Client gửi Yjs update binary qua WebSocket.
- Server apply update vào `collab_documents.ydoc_state`.
- Broadcast update tới tất cả clients trong cùng `note_id` room.
- Định kỳ snapshot `ydoc_state` → `note_snapshots` với `patch_format = 'yjs-snapshot'`.

---

## 9. Observability & Cost Tracking

### 9.1 Metrics (Prometheus / OpenTelemetry)

```
cortex_ingest_job_duration_seconds{job_type, stage, status}
cortex_ingest_job_cost_usd_total{provider, job_type}
cortex_api_request_duration_seconds{method, endpoint, status_code}
cortex_search_latency_seconds{type}           # keyword vs semantic
cortex_embedding_queue_depth
cortex_timeline_cache_hit_ratio
cortex_workspace_quota_usage_ratio{workspace_id, quota_type}
```

### 9.2 Structured Logging

Mọi log đều có `trace_id`, `user_id`, `workspace_id`, `asset_id` (khi applicable).

```json
{
  "level": "info",
  "event": "ingest_job.completed",
  "trace_id": "abc-123",
  "user_id": "uuid",
  "asset_id": "uuid",
  "job_type": "ocr",
  "stage": "extract",
  "duration_ms": 3200,
  "segments_created": 47,
  "tokens_used": null,
  "cost_usd": null
}
```

### 9.3 Cost Dashboard Query

```sql
SELECT
  w.name AS workspace,
  ij.job_type,
  ij.provider,
  DATE_TRUNC('day', ij.finished_at) AS day,
  SUM(ij.tokens_used) AS total_tokens,
  SUM(ij.cost_usd)    AS total_cost_usd,
  COUNT(*)            AS job_count
FROM ingest_jobs ij
JOIN assets a ON a.id = ij.asset_id
JOIN workspaces w ON w.id = a.workspace_id
WHERE ij.status = 'success'
  AND ij.finished_at >= NOW() - INTERVAL '30 days'
GROUP BY 1, 2, 3, 4
ORDER BY day DESC, total_cost_usd DESC;
```

---

## 10. Scalability & Infrastructure

### 10.1 Database

| Concern | Solution |
|---|---|
| Segment table growth | Partition by `(asset_id hash % 8)` khi > 100M rows |
| Audit log growth | Partition `audit_events` by month (đã thiết kế) |
| Embedding index | HNSW index với `m=16, ef_construction=64` — balance recall vs memory |
| Wide row | Text payload ở `segment_contents`, không trong `segments` |
| Hot index | `(asset_id, start_ms)`, `(note_id)`, `(segment_id)` — focused và narrow |

### 10.2 Queue & Workers

```
Queue topology:
  ingest.high     → extract_frames, extract_audio  (priority, timeout 5min)
  ingest.medium   → ocr, asr                       (standard, timeout 10min)
  ingest.low      → embed, ai_note, cache           (background, timeout 30min)
  ingest.dead     → failed jobs after max_attempts  (manual retry)

Worker scaling:
  Auto-scale based on queue depth metric
  Min: 1 worker per queue
  Max: configurable per plan (free=2, pro=10, enterprise=50)
```

### 10.3 Caching Strategy

```
L1: In-process LRU cache (hot note metadata, workspace quotas)
    TTL: 30s, Max: 1000 entries

L2: Redis (timeline cache, search result cache, session)
    TTL: 5min for timeline, 60s for search results

L3: PostgreSQL (source of truth)
    asset_timeline_cache.is_dirty flag for lazy regeneration
```

### 10.4 Object Storage Layout

```
s3://cortex-media/
  raw/{workspace_id}/{asset_id}/original.{ext}
  derivatives/{workspace_id}/{asset_id}/thumbnail.webp
  derivatives/{workspace_id}/{asset_id}/waveform.json
  derivatives/{workspace_id}/{asset_id}/transcript.vtt
  exports/{workspace_id}/{export_id}/notes-export.zip
```

---

## 11. Migration Plan

### Phase 1 — Minimal Viable Mapping (Week 1–2)

- [ ] Migrations: `workspaces`, `workspace_members`, `workspace_quotas`
- [ ] Migrations: `assets`, `asset_derivatives`, `segments`, `segment_contents`
- [ ] Migrations: `note_segment_links`, `bookmarks`
- [ ] Migrations: `asset_timeline_cache` với `is_dirty` flag
- [ ] Migrations: add soft delete + new indexes to `notes`
- [ ] Routers: `/assets`, `/segments`, `/notes/:id/links`, `/segments/:id/notes`
- [ ] Timeline cache invalidation via `is_dirty` flag (no sync trigger)
- [ ] Existing note editing API: unchanged

### Phase 2 — Ingest Pipeline & Search (Week 3–5)

- [ ] Migrations: `ingest_jobs` (với cost tracking columns), `notifications`
- [ ] Migrations: `note_embeddings`, `segment_embeddings` (với `is_current`)
- [ ] Migrations: `tags`, `entity_tags`
- [ ] Async workers: extract → OCR → ASR → embed
- [ ] Router: `/search` (hybrid FTS + pgvector)
- [ ] AI note generation worker
- [ ] SSE channel cho job progress
- [ ] Quota enforcement middleware

### Phase 3 — Versioning, Graph & Collaboration (Week 6–8)

- [ ] Migrations: `note_snapshots`, `collab_documents`
- [ ] Migrations: `concepts`, `entity_links` (typed FK)
- [ ] Migrations: `audit_events` (partitioned), `note_scores`
- [ ] Note history API + diff endpoint
- [ ] Yjs WebSocket integration
- [ ] Knowledge graph API
- [ ] Admin endpoints + cost dashboard
- [ ] Embedding model upgrade flow

---

## 12. Error Contract

**Standard error shape:**
```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "Expected note version 5, got 4. Please reload and retry.",
    "details": {
      "note_id": "uuid",
      "expected_version": 5,
      "actual_version": 4
    },
    "trace_id": "abc-123-def"
  }
}
```

**Error codes:**

| Code | HTTP | Description |
|---|---|---|
| `ASSET_NOT_FOUND` | 404 | |
| `SEGMENT_NOT_FOUND` | 404 | |
| `NOTE_NOT_FOUND` | 404 | |
| `VERSION_CONFLICT` | 409 | Optimistic lock mismatch |
| `LINK_ALREADY_EXISTS` | 409 | Duplicate link_type for same (note, segment) |
| `INVALID_TIME_RANGE` | 422 | start_ms >= end_ms |
| `INGEST_JOB_FAILED` | 422 | Pipeline error, see job details |
| `DUPLICATE_UPLOAD` | 409 | checksum_sha256 already exists in workspace |
| `QUOTA_EXCEEDED` | 429 | Storage / job / token limit reached |
| `CONCURRENT_JOB_LIMIT` | 429 | Too many active ingest jobs |
| `RATE_LIMITED` | 429 | API rate limit hit |
| `PERMISSION_DENIED` | 403 | Role insufficient |
| `WORKSPACE_NOT_FOUND` | 404 | |

---

## 13. KPIs

### Product KPIs

| Metric | Target | How to measure |
|---|---|---|
| Time to first note after upload | < 60s (P50) | `note.created_at - asset.created_at` |
| Search click-through rate | > 40% | Events: search → jump/open |
| Timeline jump latency | < 200ms (P95) | API `/timeline` response time |
| Note reuse ratio | > 20% | Notes linked to 2+ assets / total notes |
| AI note acceptance rate | > 60% | User edits AI note vs deletes |

### System KPIs

| Metric | Target | Alert threshold |
|---|---|---|
| Ingest job success rate | > 98% | < 95% |
| P95 `/search` latency | < 300ms | > 500ms |
| P95 `/assets/:id/segments` | < 100ms | > 200ms |
| Embedding index lag | < 2min | > 5min |
| Timeline cache hit rate | > 85% | < 70% |
| Dead letter queue depth | < 10 | > 50 |

---

*Design này được xây dựng để preserve toàn bộ backend hiện tại trong khi bổ sung note-segment mapping layer và ingest pipeline như first-class capabilities. Mỗi phase có thể ship độc lập mà không breaking existing clients.*