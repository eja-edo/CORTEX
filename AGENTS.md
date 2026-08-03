# AGENTS.md

Cortex is a monorepo with multiple services. Always identify which service a task touches before running commands.

## Codebase discovery

Project đã được index trong `codebase-memory-mcp` dưới tên **`home-duyanh-project-Cortex`** — luôn truyền `project="home-duyanh-project-Cortex"` khi gọi MCP. Ưu tiên graph tools (`search_graph` → `trace_path` → `get_code_snippet` → `query_graph`) hơn grep/glob. Chi tiết cách dùng từng tool (mode, paging, Cypher queries hay dùng, khi nào fallback) xem `.opencode/MCP_USAGE.md`.

## Repository layout (services)

| Dir | Stack | Purpose | Default port |
|---|---|---|---|
| `backend/` | FastAPI + SQLAlchemy + Alembic | Main API: auth, notes, schedules, workspaces, agent/chat, media, SSE | 8000 |
| `frontend/` | Vite + React 19 + TS | Web UI; proxies `/api/v1/{workflows,executions,webhooks,actions}` → workflow_service | 5173 |
| `workflow_service/` | FastAPI + Temporal | Workflow runtime (CRUD, triggers, actions); talks to backend via internal API key | 8001 |
| `ocr_service/` | FastAPI + EasyOCR | Video/image OCR pipeline; Redis queue consumer | — |
| `stt_service/` | FastAPI + WhisperX | Speech-to-text worker; Redis queue consumer | — |
| `sync-server/` | Node/Yjs (sources empty here; see `sync-server/tests/`) | Yjs CRDT sync endpoint | 1235 |
| `infrastructure/` | docker-compose | Postgres+pgvector (5434), Mongo (27016), Redis (6377), MinIO (9002/9003), Temporal (7233, UI 8088), workflow_service | — |
| `lab/` | Python | Throwaway OCR pipeline experiments — do not import from here in any service | — |
| `docs/`, `workflow_feature/` | Markdown | Product spec + workflow runtime design docs (read before implementing workflow features) | — |

## Run order (local dev)

1. `cd infrastructure && docker compose up -d db mongo redis minio-cortex minio-cortex-init temporal temporal-ui` — bring up infra. `pgvector/pgvector:pg16` is required (not plain postgres).
2. Backend migrations: from `backend/`, `python -m alembic upgrade head` (or `python run_migration.py`). Re-run after every schema change.
3. Backend: `python main.py` (preferred) or `uvicorn app:app --reload --host 0.0.0.0 --port 8000`. `main.py` configures the root logger before SQLAlchemy imports — use it, not bare `uvicorn`, when log noise matters.
4. Workflow service: `uvicorn app.main:app --port 8001` from `workflow_service/` (uses `app/config.py` Settings; reads `workflow_service/.env` if present, else falls back to localhost defaults).
5. Frontend: `npm run dev` from `frontend/`. Vite proxy already routes workflow endpoints to `:8001`.
6. OCR/STT workers only needed if touching the media pipeline.

Health checks: `http://localhost:8000/health`, `http://localhost:8001/health`, `http://localhost:8088` (Temporal UI), `http://localhost:9002` (MinIO console `:9003`).

## Environment / secrets

- `backend/.env` is committed with non-prod keys (Google OAuth, Gemini, OpenAI-compatible local endpoint, Zep, MinIO, internal API key `cortex-internal-key-2024`). Treat as dev only — never reuse these in prod.
- `backend/.env` points to non-default ports (`5434` Postgres, `27016` Mongo, `6377` Redis, `9002` MinIO) to match `infrastructure/docker-compose.yml`. Don't change to defaults without updating compose.
- The same `INTERNAL_API_KEY` value (`cortex-internal-key-2024`) is used by `workflow_service/config.py` default and by the Yjs sync-server tests (`X-Internal-Token: cortex-internal-secret` in `sync-server/tests/test-headless-apply.mjs` — note the value differs; sync-server uses `cortex-internal-secret`).
- JWT secret default is the literal string `change-this-in-production-super-secret-key` (see `backend/.env`, `workflow_service/app/config.py:resolved_jwt_secret`). Required for both backend and workflow_service to validate the same tokens.

## Backend (FastAPI)

- Entry: `backend/app/__init__.py` (constructs `app`), started by `backend/main.py`. Workers (transcription consumer, LLM processor, reminder, Google sync) are started in background threads via `WorkerThread` in the app lifespan.
- DB: async SQLAlchemy (`database_async.py`) + sync (`database.py`) for scripts. Schema migrations live in `backend/alembic/versions/`. Migrations named like `00X_*.py` — use sequential numbering for new ones.
- Settings: `backend/app/config.py` (`pydantic-settings`), reads `backend/.env`.
- API routers in `backend/app/api/`: `auth`, `agent` (chat/SSE), `notes`, `schedules`, `workspaces`, `proposals`, `assets`, `images`, `upload`, `knowledge`, `notifications`, `google_calendar`, `internal` (for workflow_service callbacks), `sse/*`.
- Adding a new API route: register the router in `backend/app/__init__.py`.
- One-off scripts live in `backend/scripts/` and add the parent to `sys.path` themselves — run as `python -m scripts.<name>` from `backend/`.

### Backend tests

- Config: `backend/pytest.ini` → `testpaths = tests`, asyncio scope = function. Run from `backend/`: `python -m pytest` or `python -m pytest tests/test_foo.py -v`.
- Many numbered ad-hoc tests sit at the top of `backend/` (`test_issue1_extract_memory_triggers.py` … `test_issue8_dead_code.py`, `test_e2e_*.py`, `test_function_unit.py`, `test_token_budget_history.py`, etc.). They follow a "Part N" convention — see the file's module docstring for `Run: python -m pytest <file> -v`.
- Integration tests for the agent require the agent infrastructure; check fixture docstrings before running.
- `backend/check_env.py` and `backend/check_migration.py` are diagnostic one-liners, not tests.

## Workflow service

- Entry: `workflow_service/app/main.py` — lifespan starts the internal-event Redis listener and a Temporal worker in the background.
- Depends on: Temporal at `temporal:7233` (compose service name), backend at `http://localhost:8000` (or `host.docker.internal:8000` from inside compose), Redis at `redis:6377`.
- Talks to backend over `X-Internal-Token: $CORTEX_INTERNAL_API_KEY` (default `cortex-internal-key-2024`); see `backend/app/api/internal.py` for the receiving side.
- Triggering: backend publishes events on Redis channel `cortex:workflow:events` (see `workflow_feature/10_INTEGRATION_GUIDE.md`). Webhooks use `trigger_type=webhook` and a per-workflow `webhook_url` + `webhook_secret`; secret is required only if set.
- Tests: `workflow_service/pytest.ini` (asyncio_mode=auto, session scope). Pytest suite: `python -m pytest` from `workflow_service/`. End-to-end integration script: `bash workflow_service/tests/run_integration_tests.sh` (requires a running service at `$HOST`, default `http://localhost:8001`).
- Design docs in `workflow_feature/01_…` through `11_…` are authoritative for API contracts, schemas, and architecture decisions — read before changing the service.

## Frontend

- Vite config: `frontend/vite.config.ts` — proxy targets are for workflow_service paths only. Backend calls go directly to `:8000`.
- Scripts: `npm run dev`, `npm run build` (runs `tsc -b` then Vite build — type errors fail the build), `npm run lint` (ESLint flat config), `npm run test` (Vitest, jsdom, files matched by `src/**/*.{test,spec}.{ts,tsx}`).
- Order matters when validating: `lint → build (typecheck via tsc) → test`.
- Main app shell: `frontend/src/App.tsx`; workflow UI lives in `frontend/src/components/workflow/` plus `WorkflowBuilder.tsx`.
- Don't forget to also run `npm run build` after TypeScript changes — `tsc -b` is the project's typecheck.

## OCR / STT / Sync notes

- `ocr_service/main.py` and `stt_service/main.py` each load a local `.env` from their own directory and start a Redis queue consumer at startup. They depend on MinIO + Redis from compose.
- `ocr_service/worker/` contains the RQ-style task processors; `stt_service/service/` the WhisperX pipeline.
- `sync-server/` source tree is empty in this checkout (only `tests/` and `dist/`, `node_modules/`); the Yjs protocol contract is in `docs/feat_notes/03-prompt-migrate-realtime-collab-yjs.md` and `04-prompt-crdt-agent-proposals.md`. When asked to modify sync-server behavior, verify the running source elsewhere first.

## Conventions / gotchas worth knowing

- Logging must be configured before SQLAlchemy is imported (`_configure_root_logger()` in `backend/app/__init__.py` and `backend/main.py`) — don't reorder imports or the SQLAlchemy banner floods stdout.
- Internal service-to-service auth uses `INTERNAL_API_KEY` header (`backend/app/api/internal.py`); do not add JWT to internal calls.
- Worker threads in `backend/app/__init__.py` run async loops in their own threads — be careful sharing async resources (DB sessions, Redis pools) across them; each worker manages its own.
- `backend/migrations/` is an old folder, not used; the live migration tree is `backend/alembic/`.
- `lab/` and `logs/` are gitignored; safe to ignore unless the task explicitly references them.
- Several `.bak` files exist under `backend/tests/` (`test_search.py.bak`) — leave them alone unless asked.
- The codebase mixes English and Vietnamese comments/docs; preserve existing language in surrounding context when editing comments.

## When the task touches more than one service

- Schema change: alembic migration in `backend/` → run `alembic upgrade head` → if workflow_service reads the new columns, update its models in `workflow_service/app/models/` and re-run its migrations.
- New workflow trigger/action: implement handler in `workflow_service/app/triggers/` or `workflow_service/app/actions/`, then add backend publisher in `backend/app/services/redis/event_publisher.py` per `workflow_feature/10_INTEGRATION_GUIDE.md`.
- New frontend route under `/workflows`: add the React Flow component under `frontend/src/components/workflow/` and wire the route in `frontend/src/App.tsx`.

## Agent Protocol

Before executing ANY task:

1. Read `.opencode/protocol.md` in full.
2. Read `.opencode/state/TASK.md`. That file, not the chat message, is the task.
3. Read `.opencode/state/FACTS.md` for established facts. Do not re-verify them.
4. Follow the mode contract in protocol.md section 1.
5. Write `.opencode/state/REPORT.md` using the template, and append to LOG.md.

`.opencode/protocol.md` takes priority over your default execution habits.
You are an executor, not a planner: never invent the next task, never widen scope.
