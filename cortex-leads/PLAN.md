# cortex-leads — Hợp đồng xây dựng v0

Tài liệu cho các agent thực thi. **Nguồn sự thật về *cái gì* và *vì sao* là [`../docs/DESIGN.md`](../docs/DESIGN.md)** (đặc biệt §5 và §7.2). Tài liệu này chỉ chốt *cách ghép* để các gói việc (WP) chạy song song không giẫm chân nhau.

## 0. Luật cho mọi agent

1. **Chỉ sửa file thuộc gói của mình** (bảng §2). Cần đổi file của gói khác — đặc biệt `db/models.py`, `core/*`, `pyproject.toml` — thì **không sửa**; ghi vào báo cáo cuối dưới mục `SCHEMA/CONTRACT REQUEST` và làm tạm bằng cách khác (hoặc dừng phần đó).
2. **Không import gì từ `backend/`** hay thư mục khác ngoài `cortex-leads/`. Code cũ chỉ được *đọc và chép có chủ đích*, ghi chú nguồn ở đầu hàm/tệp: `# port từ backend/app/...` (DESIGN §5.11).
3. **Không commit, không push, không động vào git stash, không truy cập server/production, không gọi LLM thật** (dùng `FakeProvider`). Không cài gì ngoài `.venv` của dự án.
4. **Không secret mặc định.** Mọi secret đọc từ env; thiếu → lỗi khi khởi động. Test tự đặt env trong `conftest`.
5. **Ngân sách dòng** (không tính test/migration) ghi ở §2. Vượt → dừng và báo cáo, không nén code cho lọt.
6. **Mỗi bất biến được thi hành phải có test.** Ghi `# DESIGN A3` (hoặc §, N…) ở chỗ thi hành.
7. Code và tên định danh bằng tiếng Anh; chú thích ngắn, chỉ khi giải thích *vì sao*. Type hints đầy đủ. Python 3.12.
8. Hoàn thành = `make test` xanh (gồm test của gói khác đã có) + báo cáo cuối theo mẫu §6.

## 1. Stack & quy ước

- Python 3.12 · FastAPI · SQLAlchemy 2.x async + asyncpg · Alembic · Pydantic v2 + pydantic-settings · httpx · PyYAML · openai (client OpenAI-compatible) · cryptography (Fernet) · mcp (Python SDK) · pytest + pytest-asyncio.
- Postgres 16 qua `docker-compose.yml` của thư mục này: service `pg`, cổng host **5544**, db `cortex_leads`, user `cl_owner` (owner, chạy migration) và role ứng dụng `cl_app` (KHÔNG phải owner, chịu RLS). Mật khẩu dev chỉ nằm trong `docker-compose.yml`/`.env.test`, không trong code.
- Venv: `cortex-leads/.venv`. `make setup` (tạo venv + `pip install -e .[dev]`), `make db-up`, `make migrate`, `make test`, `make lint` (ruff nếu có, không bắt buộc).
- Thời gian: luôn `datetime` có timezone UTC trong DB; hiển thị theo `tenant.timezone` (mặc định `Asia/Ho_Chi_Minh`).
- ID: UUIDv7 (`core/ids.py: uuid7()`), riêng connector id dạng chuỗi `conn_<base32>`.

## 2. Gói việc & quyền sở hữu tệp

| WP | Sở hữu (chỉ được tạo/sửa) | Ngân sách dòng | Phụ thuộc |
|---|---|---|---|
| WP0 Khung | `pyproject.toml`, `Makefile`, `docker-compose.yml`, `.env.test`, `.gitignore`, `README.md`, `alembic.ini`, `cortex_leads/__init__.py`, `cortex_leads/config.py`, `cortex_leads/app.py` (FastAPI factory + router mount theo §5), `cortex_leads/core/**`, `cortex_leads/db/**`, `migrations/**`, `tests/conftest.py`, `tests/core/**`, `tests/db/**` | 650 | — |
| WP1 Giác quan | `cortex_leads/ingest/**`, `cortex_leads/channels/**`, `cortex_leads/clock/schedule.py`, `tests/ingest/**`, `tests/clock/test_schedule.py` | 500 | WP0 |
| WP2 Tay chân | `cortex_leads/tools/**`, `cortex_leads/privacy/**`, `cortex_leads/guard/**`, `tests/tools/**`, `tests/privacy/**`, `tests/guard/**` | 750 | WP0 |
| WP3 Skill/profile/sandbox | `cortex_leads/skills/**`, `cortex_leads/sandbox/**`, `sandboxes/**`, `tests/skills/**`, `tests/sandbox/**` | 450 | WP0 |
| WP4 Cổng LLM | `cortex_leads/llm/**`, `tests/llm/**` | 400 | WP0 |
| WP5 Não | `cortex_leads/clock/sweeper.py`, `cortex_leads/triggers/**`, `cortex_leads/runner/**`, `cortex_leads/review/**`, `cortex_leads/supervisor/**`, `cortex_leads/cli.py`, `tests/triggers/**`, `tests/runner/**`, `tests/review/**`, `tests/supervisor/**` | 800 | WP1–4 |
| WP6 Biên | `cortex_leads/mcp_server/**`, `bridges/**`, `tests/mcp_server/**`, `tests/bridges/**` | 450 | WP1, WP2 |
| WP7 Tích hợp | `tests/e2e/**`, cập nhật `README.md` (mục chạy thử) | 0 (chỉ test) | WP5, WP6 |

Tổng ≤ 4.000 (DESIGN L3).

## 3. Hợp đồng chung (WP0 hiện thực, mọi WP dùng)

### 3.1 `cortex_leads/config.py`
`Settings` (pydantic-settings, prefix `CL_`): `DATABASE_URL` (app role), `DATABASE_OWNER_URL` (migration), `CONNECTOR_SECRET_KEY` (Fernet key, bắt buộc), `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_LITE`, `INGEST_MAX_SKEW_S=300`, `INGEST_MAX_BATCH=100`. Hàm `get_settings()` có cache. Khởi động: thiếu biến bắt buộc → lỗi; nếu giá trị nằm trong `KNOWN_LEAKED = {"cortex-internal-key-2024", "change-this-in-production-super-secret-key"}` → lỗi (DESIGN §10).

### 3.2 `cortex_leads/core/`
- `ids.py`: `uuid7() -> UUID`, `new_connector_id() -> str`.
- `context.py`:
  ```python
  @dataclass(frozen=True) class CustomerPrincipal: contact_id: UUID
  @dataclass(frozen=True) class StaffPrincipal: staff_ref: str
  @dataclass(frozen=True) class SystemPrincipal: job: str
  Principal = CustomerPrincipal | StaffPrincipal | SystemPrincipal
  @dataclass(frozen=True) class Scope: conversation_id: UUID | None = None; job_id: UUID | None = None
  @dataclass(frozen=True) class RunContext:
      run_id: UUID; tenant_id: UUID; sandbox_id: UUID
      profile: str; profile_version: int
      principal: Principal; scope: Scope
      trigger_event_id: str | None = None
      @property actor -> str   # "ai:<profile>@<ver>" | "staff:<ref>" | "system:<job>"
  ```
- `envelope.py`:
  ```python
  Status = Literal["ok","proposed","blocked","not_found","ambiguous","error"]
  class BlockedCode(StrEnum): WINDOW_CLOSED, NO_CONSENT, TOUCH_LIMIT, UNVERIFIED_CLAIM, FORBIDDEN_PHRASE, OWNER_IS_HUMAN, OPTED_OUT, NO_NEW_INFO, EFFECT_CEILING, NOT_ALLOWED, BUDGET, PAUSED
  class ErrorCode(StrEnum): INVALID_ARGS, NOT_FOUND, AMBIGUOUS_REF, CONFLICT, UPSTREAM_UNAVAILABLE, PERMISSION_DENIED, INTERNAL
  class Violation(BaseModel): code: BlockedCode; span: str | None = None; detail: str | None = None
  class ErrorInfo(BaseModel): code: ErrorCode; retryable: bool = False; fields: list[str] = []
  class ToolResult(BaseModel):
      status: Status; data: Any = None; note: str | None = None
      violations: list[Violation] = []; error: ErrorInfo | None = None
      next_step: str | None = None; action_id: UUID | None = None; replayed: bool = False
  ```
- `vocabulary.py`: `EVENT_TYPES = {"customer.message","staff.reply","conversation.silent","conversation.promised_date_reached","draft.expired"}`; `INTENTS = {"hoi_gia","hoi_lich","khac"}`; `REASON_CODES = {"so_sanh","soc_gia","chua_san_sang","hoi_nguoi_nha","da_mua","khong_ro"}`; `OUTPUT_KINDS = {"draft_for_staff","staff_task","owner_digest","none"}` (**không có giá trị nào là gửi khách — DESIGN A9**).
- `errors.py`: `CortexError` gốc, `ConfigError`, `TenantScopeError`.

### 3.3 `cortex_leads/db/` — schema đầy đủ v0 (WP0 tạo hết; WP khác KHÔNG sửa)
Mọi bảng (trừ `tenant`, `connector`, `api_key`) có `tenant_id UUID NOT NULL` đứng đầu mọi index, **RLS bật + FORCE**, policy `USING/WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)`. `cl_app` có GRANT SELECT/INSERT/UPDATE (DELETE chỉ nơi cần).

| Bảng | Cột chính |
|---|---|
| `tenant` (không RLS) | id, name, timezone, status(active\|paused), created_at |
| `sandbox` | id, tenant_id, name, purpose(customer_care\|owner_digest), profile_ref (vd `customer_drafter@1`), status(active\|paused), isolation(logical), budget JSONB `{runs_per_day, drafts_per_staff_per_day, tokens_per_day}`, created_at |
| `connector` (không RLS; tra theo id trước khi biết tenant) | id TEXT PK, tenant_id, sandbox_id, channel_kind, trust(official\|partner\|custom), status(active\|disabled), secret_enc BYTEA (Fernet), contract_test_passed_at, created_at |
| `api_key` (không RLS) | id, tenant_id, key_hash (sha256), role(staff\|owner\|supervisor), staff_ref NULL, created_at, revoked_at |
| `contact` | id, tenant_id, connector_id, external_id, display_name, phone, opted_out BOOL, decision_maker TEXT NULL, created_at · UNIQUE(tenant_id, connector_id, external_id) |
| `conversation` | id, tenant_id, sandbox_id, connector_id, external_id, contact_id, channel_kind, intent NULL, owner_staff_ref NULL, last_customer_at, last_customer_msg_id NULL, last_staff_at, next_check_at NULL, promised_date DATE NULL, offchannel_contact BOOL, touches INT=0, state(open\|won\|lost\|opted_out), created_at, updated_at · UNIQUE(tenant_id, connector_id, external_id) · INDEX(tenant_id, next_check_at) WHERE next_check_at IS NOT NULL |
| `message` | id, tenant_id, conversation_id, connector_id, external_id, sender_role(customer\|staff\|bot), staff_ref NULL, text, occurred_at, created_at · UNIQUE(tenant_id, connector_id, external_id) |
| `ingest_event` | id, tenant_id, connector_id, external_id, type, payload JSONB, status(accepted\|duplicate\|rejected\|processed), error NULL, received_at · UNIQUE(tenant_id, connector_id, external_id) |
| `catalog_item` | id, tenant_id, code, name, category, price NUMERIC NULL, unit NULL, attrs JSONB, version INT, valid_until NULL, active BOOL · UNIQUE(tenant_id, code, version) |
| `skill_version` | id, tenant_id, sandbox_id, name, version INT, status(draft\|shadow\|live\|retired), manifest JSONB, body TEXT, checksum, created_at · UNIQUE(tenant_id, sandbox_id, name, version) · partial UNIQUE(tenant_id, sandbox_id, name) WHERE status='live' |
| `followup_job` | id, tenant_id, sandbox_id, conversation_id, skill_name, skill_version, event_type, dedupe_key, status(pending\|running\|done\|skipped\|failed), not_before, attempts INT, created_at, updated_at · UNIQUE(tenant_id, sandbox_id, skill_name, dedupe_key) · INDEX(tenant_id, status, not_before) |
| `trigger_run` (**không có cột văn bản tự do**) | id, tenant_id, sandbox_id, job_id, skill_name, skill_version, profile, profile_version, event_type, status(ok\|none\|blocked\|error\|budget_denied\|paused), act(none\|draft\|NULL), reason_code NULL, blocked_codes TEXT[], tokens_in, tokens_out, model NULL, started_at, finished_at NULL, staff_outcome(sent\|edited\|self\|skipped\|NULL) |
| `draft` | id, tenant_id, sandbox_id, conversation_id, run_id, status(proposed\|sent\|edited\|self\|skipped\|expired\|blocked), text, claims JSONB, reason_code, created_at, decided_at NULL, staff_ref NULL |
| `staff_action` | id, tenant_id, draft_id, action(sent\|edited\|self\|skipped), edited_text NULL, staff_ref, at |
| `decision_log` | id, tenant_id, run_id NULL, conversation_id NULL, decision TEXT (enum-like: job_created\|job_skipped_budget\|run_none\|draft_proposed\|draft_blocked\|draft_expired\|…), reason_code NULL, detail JSONB (**không chứa văn bản khách**), at |
| `action_log` | id, tenant_id, action_id, actor, tool, args_masked JSONB, evidence JSONB, status, at |

View `supervisor_run_view` (chỉ cột của `trigger_run` + `sandbox.name`), GRANT cho role `cl_supervisor` (tạo role trong migration). DESIGN §5.6.

`db/session.py`:
```python
async def tenant_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]   # mở transaction + SET LOCAL app.tenant_id
async def system_session() -> AsyncIterator[AsyncSession]                    # chỉ dùng cho tenant/connector/api_key
def list_active_tenants(session) -> list[UUID]                               # system
```
Test bắt buộc (WP0): dữ liệu tenant A không đọc được trong session của tenant B; thiếu `app.tenant_id` → không đọc được gì.

### 3.4 Fixture test dùng chung (`tests/conftest.py`, WP0)
`db_ready` (session-scope: compose up phải sẵn, chạy alembic upgrade head trên DB test, truncate giữa test), `tenant_factory`, `sandbox_factory`, `connector_factory(secret=...)`, `conversation_factory`, `message_factory`, `catalog_factory`, `api_key_factory(role, staff_ref)`, `app_client` (httpx AsyncClient với `create_app()`), `freeze_time` (đơn giản, tiêm `now` qua tham số — **mọi hàm phụ thuộc thời gian nhận `now: datetime` làm tham số**, không gọi `datetime.now()` bên trong logic).

## 4. Giao diện giữa các gói

### WP1 → (mọi người)
- `ingest/format.py`: Pydantic models của **Cortex Event Format v1** đúng DESIGN §5.2 (`EventBatch`, `Event`, …). `format` phải = `"cortex.event/1"`.
- `ingest/signing.py`: `sign(secret: bytes, timestamp: int, body: bytes) -> str`, `verify(...) -> bool` (so sánh hằng thời gian, lệch giờ > `INGEST_MAX_SKEW_S` → False). **Bridge (WP6) dùng chính hàm `sign` này.**
- `ingest/api.py`: router `POST /ingest/v1/events` → 202 + kết quả từng event. Tenant suy ra từ connector (A3). Connector `disabled` → 403. Batch > max → 413.
- `ingest/normalize.py`: `async def apply_event(session, connector, event, now) -> Literal["accepted","duplicate","rejected"]` — upsert contact/conversation, insert message (idempotent), cập nhật `last_customer_at/last_staff_at/last_customer_msg_id`, đặt `intent` đơn giản bằng luật từ khoá (`hoi_gia` nếu chứa "giá|bao nhiêu|học phí|chi phí|price"), rồi gọi `clock.schedule.compute_next_check_at(conversation, now)`; tin `staff`/`customer` mới **huỷ các `followup_job` pending và chuyển draft `proposed` → `expired`** của hội thoại đó (event trigger "huỷ/dời", DESIGN §5.7) và ghi `decision_log`.
- `clock/schedule.py`: hàm thuần `compute_next_check_at(last_customer_at, last_staff_at, promised_date, state, tz, now, silent_after=24h) -> datetime | None`. Quy tắc: state≠open → None; promised_date trong tương lai → 08:00 giờ địa phương ngày đó; khách nhắn sau cùng → last_customer_at + silent_after; nhân viên nhắn sau cùng → last_staff_at + silent_after (khách im sau khi được trả lời).
- `channels/policy.py`: `CHANNEL_POLICIES: dict[str, ChannelPolicy]` (messenger: free 24h, human_agent 7d; zalo_oa: 48h — ghi `verified=False`; web: 0) và `window_state(channel_kind, last_customer_at, now) -> {"open": bool, "basis": str|None, "expires_at": datetime|None}`.

### WP2 → WP5, WP6
- `tools/registry.py`:
  ```python
  @dataclass(frozen=True) class ToolSpec:
      name: str; description: str          # ≤ 2 câu
      input_model: type[BaseModel]; effect: Literal["read","internal","customer"]
      tier: str; handler: Callable[[RunContext, AsyncSession, BaseModel], Awaitable[ToolResult]]
  class ToolRegistry:
      def register(spec) ; def specs_for(allowlist) -> list[ToolSpec]
      def openai_schemas(allowlist) -> list[dict]
      async def execute(ctx, session, name, raw_args: dict, *, allowlist, effect_ceiling, idempotency_key: str|None=None) -> ToolResult
  default_registry() -> ToolRegistry      # đã đăng ký các tool v0
  ```
  `execute` thi hành: tên ∉ allowlist → `blocked NOT_ALLOWED`; effect > trần → `blocked EFFECT_CEILING`; validate args → `error INVALID_ARGS` (+fields, retryable); scope lấy từ `ctx` (A3) — tool **không nhận** tenant/conversation từ args; kết quả rỗng không có `note` → registry tự thêm note mặc định; mọi tool `internal` ghi `action_log` (args đã che). Đăng ký tool `customer` → raise (A9).
- Tool v0 (đúng tên): `read_messages(last_n≤30)` · `read_contact()` · `lookup_catalog(query, category?)` (khớp chính xác/chứa trên code/name, không embedding) · `list_dropped_leads(silent_hours=24, limit≤20)` (headless/MCP; dùng `ctx.tenant_id`, sandbox) · `draft_followup(text, reason_code, claims[{value, source_id}], max_touches, never_say)` (effect internal; gọi `guard.validate_draft`; hợp lệ → insert `draft(proposed)` + `conversation.touches += 1`; không hợp lệ → insert `draft(blocked)` + trả `blocked` kèm violations).
- `tools/refs.py`: `resolve(candidates, query) -> match|ambiguous|not_found` (port `project_ref.py`).
- `privacy/redact.py`: `redact(text, known_names: list[str]) -> RedactResult(text, mapping)`; số ĐT VN (`0\d{9}`, `+84\d{9}`, có dấu cách/chấm), email, tên đã biết → `[PHONE_1]`, `[EMAIL_1]`, `[NAME_1]`.
- `guard/validator.py`: `validate_draft(text, claims, catalog_rows, *, never_say, touches, max_touches, opted_out, has_new_info: bool) -> list[Violation]`. Trích số kiểu VN: `2.500.000đ`, `2,5 triệu`, `2tr5`, `30%`, `3 tháng` → mọi số tiền/% phải khớp một claim; mỗi claim `source_id` phải là `catalog_item` active, còn hạn, và giá trị khớp `price`/`attrs`. `has_new_info=False` → `NO_NEW_INFO`.

### WP3 → WP5
- `skills/manifest.py`: Pydantic `SkillManifest` đúng DESIGN §5.8 (trigger `{kind: relative|event, on, match: dict[str, str|int|bool], after: duration?}`, `requires_tools`, `output_kind`, `limits`, `must_handoff`, `never_say`, `approval`, `eval`).
- `skills/loader.py`: `parse_skill_md(path) -> (SkillManifest, body)`; `lint(manifest, profile) -> list[str]` (luật DESIGN §5.8: tools ⊆ profile.allowlist & ≤8, `on` ∈ EVENT_TYPES, `match` chỉ equality — từ chối key bắt đầu `$`, `output_kind` ∈ OUTPUT_KINDS, ≤ ~15 trường frontmatter); `async sync_dir(session, tenant_id, sandbox_id, dir) -> list[skill_version]` (nạp thư mục skill vào DB, checksum, version bất biến).
- `skills/registry.py`: `async live_skills_for(session, sandbox_id, event_type) -> list[LoadedSkill]`; `match(skill, conversation) -> bool` (equality trên các trường hội thoại được phép: `intent`, `channel_kind`, `state`); `promote(name, version, to)` (draft→shadow→live, rollback = chuyển live sang version cũ).
- `skills/profile.py`: `AgentProfile` (DESIGN §5.5) + `load_profile(ref) -> AgentProfile` từ `sandboxes/*/profiles/*.yaml`.
- `sandbox/policy.py`: `requires_sandbox(cfg) -> bool` (DESIGN §5.6), `async check_budget(session, sandbox, kind, now) -> Violation|None`, `is_paused(sandbox) -> bool`.
- Nội dung mẫu: `sandboxes/customer_care/profiles/customer_drafter.yaml`, `sandboxes/customer_care/skills/hoi-lai-khach-im/SKILL.md` (relative, `conversation.silent`, `match: {intent: hoi_gia}`), `sandboxes/customer_care/skills/hoi-lai-dung-hen/SKILL.md` (relative, `conversation.promised_date_reached`, `match: {}`) — skill thứ hai là **phép thử A6**.

### WP4 → WP5
- `llm/gateway.py`:
  ```python
  @dataclass class LLMResult: content: str | None; tool_calls: list[ToolCall]; tokens_in: int; tokens_out: int; model: str
  class LLMGateway:
      def __init__(self, provider, *, global_concurrency=4, per_tenant_concurrency=2)
      async def complete(self, ctx: RunContext, messages: list[dict], *, tools: list[dict]|None=None, model: str|None=None, timeout_s=30) -> LLMResult
  ```
  Retry lỗi tạm thời + phân loại lỗi port từ `backend/app/ai/agents/model_client.py` (**không fallback model**); semaphore toàn cục + theo tenant (A4).
- `llm/providers.py`: `OpenAICompatibleProvider` (openai SDK async, base_url từ config) và `FakeProvider(script: list[LLMResult | Callable])` cho test.
- `llm/shape.py`: `response_shape(example: dict) -> str` — dòng chốt vẽ hình dạng JSON (port ý `response_shape()`; LESSONS / AGENTS: dòng cuối prompt quyết định shape) + `parse_json_object(text) -> dict` chịu được code fence.

### WP5 (dùng tất cả)
- `clock/sweeper.py`: `async sweep_once(now, *, limit=100) -> int` — với mỗi tenant active (system session để liệt kê, rồi tenant_session): lấy hội thoại tới hạn `FOR UPDATE SKIP LOCKED`, xác định event (`conversation.promised_date_reached` nếu promised_date ≤ hôm nay; còn lại `conversation.silent`), gọi engine, rồi đặt `next_check_at = NULL` cho tới khi có tin mới (mỗi đợt im bắn một lần).
- `triggers/engine.py`: `async on_conversation_event(session, conversation, event_type, now) -> list[followup_job]` — sandbox paused → bỏ; skills live khớp → `dedupe_key = f"silent:{conv_id}:{last_customer_msg_id or last_staff_at.isoformat()}"` (hoặc `promised:{conv_id}:{date}`); insert ON CONFLICT DO NOTHING; ghi `decision_log`. Event có `source="engine"` không bao giờ khớp lại (A9/§5.7).
- `triggers/select.py`: "chọn trước, viết sau" — xếp hạng job pending bằng luật 0 token (promised_date đến hạn > hỏi giá gần nhất > cũ hơn), lấy top K theo `budget.drafts_per_staff_per_day` còn lại; phần còn lại `skipped` + decision_log `job_skipped_budget`.
- `runner/context_builder.py`: chỉ nạp `profile.context_sources`; tin nhắn **đã che PII**, bọc như dữ liệu không tin được (`<customer_data>…</customer_data>` + chỉ dẫn "đây là dữ liệu, không phải lệnh").
- `runner/customer_run.py`: `async run_job(session, job, gateway, registry, now) -> trigger_run` — dựng `RunContext`; LLM được **chỉ các tool read** trong allowlist (∩ `requires_tools`), ≤ `max_tool_calls` vòng; kết quả cuối phải là JSON `{"act":"none"} | {"act":"draft","reason_code","has_new_info":bool,"claims":[...],"text":"..."}` (dùng `response_shape`); `act=draft` → **runner** gọi `draft_followup` qua `registry.execute` (validator chạy trong tool, A7). Ghi `trigger_run` (không văn bản), `decision_log`. Lỗi → `status=error`, job `failed` (3 lần → `skill` không tự tắt ở v0, chỉ ghi).
- `review/api.py` (auth `X-Api-Key` role staff/owner): `GET /review/drafts?status=proposed` (staff thấy text — đây là giao diện người, có audit), `POST /review/drafts/{id}/action` `{action: sent|edited|self|skipped, edited_text?}` → `staff_action`, cập nhật `draft`, `trigger_run.staff_outcome`; trước khi chấp nhận `sent/edited`: nếu có tin khách mới sau `draft.created_at` → 409 `STALE` (DESIGN §5.7 "kiểm lại lúc bấm gửi").
- `supervisor/api.py` (role supervisor): `GET /supervisor/summary?since=` đọc **chỉ** `supervisor_run_view`: số run theo status/act/reason_code/blocked_codes, tỷ lệ im (`act=none`), tỷ lệ outcome; nhóm có n<5 → ẩn số.
- `cli.py`: `python -m cortex_leads.cli sync-skills|sweep|run-pending|create-tenant|create-connector|create-api-key|import-catalog <csv>`.

### WP6
- `bridges/pancake/`: `client.py` (chỉ GET; token bucket 5 req/s/page; token đọc từ env/file trong `data/`), `mapper.py` (Pancake conversation/message → Event Format; **xác định `sender.role`**: tin từ page/admin → `staff` (có `admin_id`) hoặc `bot`; còn lại `customer`), `run.py` (poll theo cursor lưu ở `data/pancake_cursor.json`, ký bằng `ingest.signing.sign`, POST batch). **Contract test** với fixture JSON trong `tests/bridges/fixtures/` (dựng theo field của Pancake OpenAPI https://developer.pancake.biz/openapi/openapi.yaml — đọc spec để lấy đúng tên trường; nếu không tải được, ghi rõ giả định). Không gọi Pancake thật trong test.
- `mcp_server/server.py`: MCP stdio chỉ đọc cho người xây làm tay (DESIGN §5.9): tools `list_dropped_leads`, `read_conversation` (đã che PII), `lookup_catalog`, `list_drafts`. Tenant/sandbox lấy từ env `CL_MCP_TENANT_ID`/`CL_MCP_SANDBOX_ID`. Gọi qua `ToolRegistry` với allowlist chỉ-read. Test bằng cách gọi handler trực tiếp (không cần client MCP).

### WP7
`tests/e2e/test_walking_skeleton.py`: chuỗi đầy đủ DESIGN §7.2 trên Postgres thật với FakeProvider; **phép thử A6**: bật skill `hoi-lai-dung-hen` chỉ bằng `sync_dir` + `promote`, chạy được mà không sửa code engine; kiểm bất biến: không có đường gửi khách, supervisor view không có văn bản, RLS chặn chéo tenant, ingest trùng → `duplicate`, tin khách mới → nháp `expired` và review trả 409.

## 5. `app.py` (WP0) — mount router
`create_app()` mount nếu import được: `cortex_leads.ingest.api:router` (prefix `/ingest`), `cortex_leads.review.api:router` (`/review`), `cortex_leads.supervisor.api:router` (`/supervisor`). Dùng import có điều kiện để WP0 xanh khi các WP sau chưa có. `/health`.

## 6. Mẫu báo cáo cuối của mỗi agent
```
WP: <id>   Trạng thái: done | partial | blocked
Tệp đã tạo/sửa: <danh sách>
Số dòng (không tính test): <n> / ngân sách <m>
Test: <lệnh> → <kết quả, số pass/fail>
Bất biến đã thi hành + test tương ứng: <A?/N?/§ → test>
Port từ code cũ: <file nguồn → file mới>
SCHEMA/CONTRACT REQUEST: <nếu có>
Giả định chưa xác minh: <nếu có>
Việc còn lại / rủi ro: <…>
```

## 7. WP8 — Chiều ra (đã thiết kế, CHƯA mở)

Nguồn: DESIGN A9, N1, N3, N4, §5.2 "Chiều ra", §5.4 (`send_message`), §5.7 (`send_to_customer`, `fallback`), §5.8 (`send_policy`, `outbound`, lint). Chỉ bắt đầu khi chủ dự án mở bằng một dòng sửa đổi trong DESIGN (L2). Ngân sách ≤ 500 dòng.

| Phần | Việc |
|---|---|
| Schema (revision 0002) | bảng `outbox(id, tenant_id, action_id UNIQUE, conversation_id, connector_id, actor, text, disclosure, window JSONB, source JSONB, status queued\|sent\|refused\|error\|cancelled, reason, attempts, external_message_id, created_at, sent_at)` + RLS; cột `connector.outbound JSONB` |
| `core/vocabulary.py` | thêm `send_to_customer` vào `OUTPUT_KINDS` |
| `tools/` | tool `send_message` (effect `customer`): validate_draft + **sàn A9** (kill switch tenant/sandbox/skill/connector, opt-out, disclosure khi actor `ai:*`, idempotency) → ghi `outbox(queued)`. Registry: cho phép **đúng một** tool effect `customer` là `send_message`; actor `ai:*` chỉ commit khi skill `send_policy.mode=auto`, ngược lại trả `proposed` + tạo draft |
| `skills/` | manifest `send_policy` + lint (`auto` ⇒ có `send_message` và `output_kind: send_to_customer`) |
| `outbound/` (mới) | worker đọc `outbox` (`SKIP LOCKED`), ký HMAC, POST Cortex Action Format v1 tới `connector.outbound.url`; `refused` → `blocked` + decision_log, không retry; `error retryable` → backoff, tối đa 3; chỉ connector `official`/`partner` |
| `runner/` | `act: send` khi skill auto → gọi `send_message` thay `draft_followup`; bridge từ chối + `fallback: draft` → tạo nháp |
| `bridges/pancake/` | endpoint nhận action (chạy kèm bridge), thi hành `outbound.policy` (ai_send, quiet_hours, rate, `ai:*` trong `human_agent` → `refused PLATFORM_POLICY`), gọi Pancake send API; contract test chiều ra |
| `review/` | nhân viên bấm "Gửi" có thể đi qua chính `send_message` (actor `staff:*`) khi connector bật outbound |
| Test thay đổi | e2e A9 đổi từ "không có đường gửi" thành "**chỉ một đường**": quét import mạng chỉ ở `llm/` và `outbound/`; mọi gửi đều qua `outbox`; skill `draft` không bao giờ sinh outbox; bridge `refused` → không gửi |

## 8. Đợt 2 — "sẵn sàng chạy thật" (DESIGN §7.2, ngân sách tổng ≤ 5.000 dòng)

Luật §0 vẫn áp dụng. Thứ tự sóng do **tệp dùng chung** quyết định: WP12 → (WP9 ∥ WP10 ∥ WP11 ∥ WP13) → WP8 → WP14. Mỗi agent dùng DB test riêng `cortex_leads_<wp>`.

### 8.1 WP12 Nền (sóng 0, một mình) — ≤ 200 dòng

**Migration `0002_wave2.py`** (revision mới; không sửa 0001). Mọi bảng mới có `tenant_id` + RLS ENABLE/FORCE + policy như 0001 + GRANT cho `cl_app`:
- `contact_fact(id, tenant_id, contact_id FK, conversation_id FK NULL, kind TEXT, value JSONB, evidence_msg_ids UUID[] NOT NULL DEFAULT '{}', source TEXT, status TEXT CHECK IN (candidate, active, superseded, fulfilled, cancelled, done, rejected), superseded_by UUID NULL, created_at, updated_at)` · INDEX(tenant_id, contact_id, kind, status).
- `deal(id, tenant_id, connector_id FK, external_id, contact_id NULL, conversation_id NULL, status CHECK IN (booked, won, lost, cancelled), value NUMERIC NULL, currency TEXT DEFAULT 'VND', occurred_at, linked BOOL DEFAULT false, created_at)` · UNIQUE(tenant_id, connector_id, external_id).
- `outbox(id, tenant_id, action_id UUID UNIQUE, conversation_id FK, connector_id FK, draft_id NULL, actor TEXT, text, disclosure NULL, window JSONB, source JSONB, status CHECK IN (queued, sending, sent, refused, error, cancelled), reason NULL, attempts INT DEFAULT 0, not_before TIMESTAMPTZ NULL, external_message_id NULL, created_at, sent_at NULL)` · INDEX(tenant_id, status, not_before).
- `sandbox`: thêm `send_mode TEXT NOT NULL DEFAULT 'manual' CHECK IN (auto, manual)`, `domain_pack JSONB NOT NULL DEFAULT '{}'`, `business_hours JSONB NOT NULL DEFAULT '{"start":"08:00","end":"21:00"}'`; **bỏ** CHECK của `purpose` (domain-agnostic; kiểm trong code).
- `connector`: thêm `outbound JSONB NULL`.
- `conversation.state`: CHECK thêm `booked`.
- `draft.status`: CHECK thêm `approved`, `failed`. `staff_action.action`: CHECK thêm `approved`.
- View cho supervisor (không cột văn bản, `security_invoker`): `supervisor_fact_view(tenant_id, kind, source, status, created_at)`, `supervisor_deal_view(tenant_id, status, value, currency, occurred_at, linked)`, `supervisor_outbox_view(tenant_id, status, reason, actor_kind, created_at, sent_at)`; GRANT cho `cl_supervisor`.
- Cập nhật `db/models.py` tương ứng.

**Domain pack** — từ vựng nghiệp vụ ra khỏi lõi (DESIGN A6):
- `core/vocabulary.py` chỉ giữ cái **cấu trúc**: `EVENT_TYPES = {customer.message, staff.reply, conversation.silent, conversation.promised_date_reached, conversation.outcome, deal.updated, draft.expired}` (đổi tên `lead.*` → `conversation.*`; cập nhật mọi chỗ dùng + 2 skill mẫu + test), `OUTPUT_KINDS` (giữ, WP8 thêm `send_to_customer`), `CORE_FACT_KINDS = {promised_date, outcome, offchannel}`.
- `domain/pack.py` (mới): `DomainPack` (pydantic): `intents: dict[str, {label, keywords: list[str]}]`, `reason_codes: list[str]`, `fact_kinds: list[str]` (thêm vào core), `decision_maker_roles: list[str]`, `outcome_keywords: dict[status, list[str]]`. `load_pack(sandbox) -> DomainPack` từ `sandbox.domain_pack`; `sandboxes/<sandbox>/domain.yaml` + CLI `sync-domain` ghi vào DB.
- `sandboxes/customer_care/domain.yaml`: từ vựng bán hàng hiện tại (`hoi_gia` + keywords, `hoi_lich`, 6 reason_codes, `decision_maker_roles: [ban_than, vo_chong, bo_me, con, sep, khac]`, `fact_kinds: [decision_maker, need, budget, objection, preference]`, `outcome_keywords` cho booked/won/lost).
- `ingest/normalize.py`: gán `intent` theo `domain_pack.intents[*].keywords` của sandbox (khớp nguyên từ, không dấu, không phân biệt hoa thường) — bỏ regex cứng.
- `tools/v0.py` `draft_followup.reason_code` và `skills/loader.lint` (giá trị `match.intent`) kiểm theo domain pack, không theo hằng.
- Test: đổi pack → intent/reason_code thay đổi mà không sửa code; pack thiếu → lỗi rõ; toàn bộ test cũ vẫn xanh sau đổi tên sự kiện.

### 8.2 Sóng 1 (song song, sau WP12)

Leader đã nối sẵn router trong `app.py` (`cortex_leads.review.facts_api` → `/review`, `cortex_leads.staff_ui.routes` → `/staff`) và thêm `jinja2`, `python-multipart` vào `pyproject.toml`. **Không gói nào sửa `app.py`, `pyproject.toml`, `db/models.py`, migration** — thiếu thì ghi CONTRACT REQUEST. Quy ước migration (REVIEW R20): nếu buộc phải thêm, leader làm.

#### WP9 — Trí nhớ, vòng đời lời hẹn, kết quả (≤ 450 dòng)
Sở hữu: `cortex_leads/memory/**` (mới), `cortex_leads/tools/memory.py` (mới), `cortex_leads/guard/facts.py` (mới), `cortex_leads/ingest/deal.py` (mới), `cortex_leads/review/facts_api.py` (mới); **được sửa**: `ingest/format.py`, `ingest/normalize.py` (móc), `tools/registry.py` (`default_registry` đăng ký tool mới), `runner/customer_run.py`, `runner/context_builder.py`, `triggers/select.py`, `triggers/engine.py`, `domain/pack.py` (thêm `priority_intents`), `sandboxes/customer_care/{domain.yaml,skills/**}`; test `tests/memory/**`.

**Giao diện dịch vụ — WP13 gọi trực tiếp, phải đúng chữ ký này** (`cortex_leads/memory/service.py`):
```python
async def record_fact(session, *, conversation_id: UUID, kind: str, value: dict, evidence_msg_ids: list[UUID],
                      source: str, now: datetime) -> ContactFact          # validate → supersede cũ cùng kind → chiếu sang cột
async def reject_fact(session, fact_id: UUID, *, staff_ref: str, now: datetime) -> ContactFact
async def record_outcome(session, *, conversation_id: UUID, status: Literal["booked","won","lost","cancelled","reopen"],
                         source: str, evidence_msg_ids: list[UUID], now: datetime) -> Conversation
async def mark_offchannel(session, *, conversation_id: UUID, channel: Literal["phone","zalo_personal","in_person"],
                          staff_ref: str, now: datetime) -> ContactFact
async def list_facts(session, *, contact_id: UUID, include_inactive: bool = False) -> list[ContactFact]
async def pending_confirmations(session, *, sandbox_id: UUID) -> list[ContactFact]   # candidate cần người xác nhận
async def confirm_fact(session, fact_id: UUID, *, staff_ref: str, now: datetime) -> ContactFact
class MemoryError(CortexError)  # lỗi validate, có .code ∈ {NO_EVIDENCE, EVIDENCE_NOT_CUSTOMER, EVIDENCE_OTHER_CONVERSATION, DATE_NOT_IN_EVIDENCE, DATE_OUT_OF_RANGE, UNKNOWN_KIND, TOO_MANY_FACTS}
```
Luật:
- `kind ∈ pack.all_fact_kinds`. `source="staff:<ref>"` không cần bằng chứng; `ai:*` và `rule` **bắt buộc** `evidence_msg_ids` thuộc đúng hội thoại và là tin `customer`.
- `promised_date`: `value={"date": "YYYY-MM-DD"}`, tương lai, ≤ 180 ngày; với `ai:*` phải có cụm ngày trong tin bằng chứng khớp (`guard/facts.extract_date_candidates(text, now, tz)`: `dd/mm[/yyyy]`, `ngày dd`, `mai`, `ngày kia`, `thứ X [tuần này|tuần sau]`, `cuối tuần`, `tuần sau`, `tháng sau` → tập ngày hợp lệ). Cụm mơ hồ không kiểm được (vd "sau Tết") → lưu `status=candidate`, chờ người xác nhận.
- Ghi `promised_date` active → `conversation.promised_date` = ngày đó, tính lại `next_check_at` (`clock.schedule`). `decision_maker` → `contact.decision_maker` (giá trị ∈ `pack.decision_maker_roles`). `offchannel` → `conversation.offchannel_contact=true`, `next_check_at=None`, huỷ job pending.
- `record_outcome`: `won|booked` → lời hẹn active thành `fulfilled`; `lost|cancelled` → `cancelled`; `conversation.state` = `won|booked|lost` (cancelled → lost); huỷ job pending, nháp proposed → expired, ghi `decision_log` `promise_closed_by_outcome`. `reopen` → state `open`, giữ fact, tính lại đồng hồ. Outcome từ `ai:*` → chỉ tạo fact `outcome` **candidate** và **dừng theo sát** (job huỷ, `next_check_at=None`) cho tới khi người xác nhận/bác.
- Tối đa 5 fact `ai:*` mỗi run (`TOO_MANY_FACTS`).
- **Ingest:** event mới `deal.updated` trong `ingest/format.py` — `{"type":"deal.updated","external_id","occurred_at","contact":{"phone"?, "ref"?: {"connector_id","external_id"}},"deal":{"status","value"?,"currency"?}}`. `ingest/deal.py`: lưu bảng `deal` (idempotent), khớp khách **chính xác** (ref, hoặc SĐT chuẩn hoá trùng duy nhất trong tenant; không đoán), khớp được → `linked=true` + `record_outcome(source="connector:<id>")`. Tin khách: luật 0 token tạo fact `candidate` (`source="rule"`) cho cụm ngày và `pack.outcome_keywords` — **không** đổi lịch, không đổi state.
- **Runner:** kết quả JSON có thêm `facts: [{"kind","value","evidence":["m3",…]}]` — context builder đánh số tin `m1..mN` (map server-side sang UUID; LLM không thấy UUID); runner ghi fact qua tool `record_facts` (effect internal, gọi `record_fact`) **trước** khi xử lý `act`; nếu vừa ghi promised_date tương lai cho event `conversation.silent` → bỏ nháp (`decision_log run_none reason=promised_future`). **Chặn kép trước LLM:** `state != open`, có outcome candidate chưa xác nhận, hoặc (silent mà có promised_date tương lai) → không gọi LLM. Context builder nạp fact active (đã redact) của khách.
- `triggers/select.py`: ưu tiên theo `pack.priority_intents` (thêm trường vào `DomainPack`, mặc định `[]`) — gỡ `hoi_gia` cứng (R21).
- **API nhân viên** `review/facts_api.py` (`router`, prefix `/review` có sẵn; auth như `review/api.py`): `GET /conversations/{id}/facts`, `POST /conversations/{id}/facts` (staff), `POST /conversations/{id}/outcome`, `POST /conversations/{id}/offchannel`, `POST /facts/{id}/confirm`, `POST /facts/{id}/reject`, `GET /confirmations`.
- Test: kịch bản "để sau Tết bàn với chồng" (decision_maker + candidate promise; staff confirm → đồng hồ tới ngày) · "tuần sau" kiểm được → active · AI bịa ngày → `DATE_NOT_IN_EVIDENCE` · bằng chứng là tin staff / hội thoại khác → bị từ chối · > 5 fact → chặn · hẹn tuần sau nhưng hôm sau `deal.updated won` → hẹn `fulfilled`, không còn job, nháp expired · AI outcome candidate → dừng theo sát, staff reject → mở lại · offchannel → khỏi danh sách rơi · RLS · supervisor fact view không có `value`.

#### WP10 — Bridge Messenger (≤ 280 dòng)
Sở hữu: `bridges/messenger/**`, `tests/bridges/messenger/**`. Không sửa lõi.
- Một app FastAPI riêng (`python -m bridges.messenger.app`) đọc env: `MESSENGER_APP_SECRET`, `MESSENGER_VERIFY_TOKEN`, `MESSENGER_PAGE_TOKEN`, `MESSENGER_PAGE_ID`, `MESSENGER_OWN_APP_ID`, `CL_INGEST_URL`, `CL_CONNECTOR_ID`, `CL_CONNECTOR_SECRET` (token đọc từ env hoặc tệp trong `data/`, không bao giờ log).
- **Chiều vào:** `GET /webhook` (hub.mode/verify_token/challenge) · `POST /webhook` kiểm `X-Hub-Signature-256` (HMAC-SHA256 bằng app secret, so sánh hằng thời gian) → với mỗi `messaging` event: tin từ khách → `customer`; `message.is_echo=true` và `app_id == MESSENGER_OWN_APP_ID` → `bot` (tin do Cortex gửi); `is_echo=true` không có `app_id` hoặc `app_id` khác (Page inbox/Pancake…) → `staff` nếu không có `app_id`, `bot` nếu là app khác → **ghi rõ quy tắc + test** (đây là lời giải R13). `external_id = "messenger:<page_id>:<mid>"`, `conversation.external_id` = PSID khách, `occurred_at` từ `timestamp` (ms, UTC). Gom batch, ký bằng `cortex_leads.ingest.signing.sign`, POST tới ingest; trả 200 cho Meta **nhanh** (xử lý sau, hàng đợi trong bộ nhớ + thử lại có backoff).
- **Chiều ra** (Cortex Action Format v1, DESIGN §5.2): `POST /actions` kiểm `X-Cortex-Timestamp`/`X-Cortex-Signature` bằng **cùng** `ingest.signing.verify` với connector secret; idempotent theo `action_id` (lưu `data/messenger_actions.json` hoặc sqlite trong `data/`); thi hành policy từ env/JSON (`ai_send`, `quiet_hours`, `max_per_minute`): actor `ai:*` khi `ai_send=false` → `refused AI_SEND_DISABLED`; `window.basis=="human_agent"` + actor `ai:*` → `refused PLATFORM_POLICY`; `basis=="human_agent"` + actor `staff:*` → gửi với `messaging_type=MESSAGE_TAG, tag=HUMAN_AGENT`; `window.open=false` → `refused WINDOW_CLOSED`; trong cửa sổ tự do → `messaging_type=RESPONSE`; text gửi = `text` + (`"\n— " + disclosure` nếu có). Gọi Graph Send API (`POST /v{ver}/me/messages`, page token) qua httpx; lỗi 5xx/mạng → `error retryable=true`; 4xx → `error retryable=false`.
- Contract test bằng fixture dựng theo tài liệu webhook Meta (đọc https://developers.facebook.com/docs/messenger-platform/webhooks qua WebFetch để lấy đúng trường; không tải được thì ghi giả định): chữ ký đúng/sai, verify challenge, customer/staff/bot, echo của chính app, batch nhiều entry; chiều ra: từng nhánh policy, idempotency, HUMAN_AGENT cho staff, mock httpx (không gọi Meta thật); e2e qua `create_app()` ASGI như test bridge Pancake.

#### WP11 — Bộ chạy thử (≤ 150 dòng sản phẩm; `dev/` không tính)
Sở hữu: `bridges/twenty/**`, `bridges/gsheet/**`, `dev/**`, `tests/bridges/{twenty,gsheet}/**`.
- `bridges/twenty/`: app FastAPI nhận webhook Twenty (đọc tài liệu webhook Twenty qua WebFetch: https://www.mintlify.com/twentyhq/twenty/developers/extending/webhooks — kiểm chữ ký theo đúng cách Twenty mô tả; ghi giả định nếu không rõ) cho `opportunity.updated|created`; map stage → `deal.status` qua cấu hình `TWENTY_STAGE_MAP` (vd `{"WON":"won","LOST":"lost","MEETING":"booked"}`); khách lấy từ person liên kết: SĐT, hoặc custom field `cortexRef` dạng `<connector_id>:<external_id>` → `contact.ref`. Gửi `deal.updated` đã ký vào ingest.
- `bridges/gsheet/`: đọc CSV export của Google Sheet chia sẻ bằng link (`https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>`): (1) **catalog** → tái dùng logic `import-catalog` (gọi hàm trong `cli.py` nếu tách được, không chép); (2) **đơn hàng** (cột: `ma_don, sdt_hoac_ref, trang_thai, gia_tri, ngay`) → `deal.updated`, idempotent theo `ma_don`, poll theo chu kỳ. Ghi rõ: link-shared là cho dev; khách thật dùng service account (T1).
- `dev/`: `dev/twenty/docker-compose.yml` (image chính thức, nguyên bản, cổng không trùng 5544/8000), `dev/README.md` hướng dẫn: tạo Page + Meta app dev mode, tester, cloudflared, Twenty, Sheet mẫu (`dev/samples/catalog.csv`, `orders.csv`), env cho từng bridge; `dev/scenario.py` chạy **kịch bản chuẩn ở chế độ giả lập** (bơm payload Messenger/Twenty fixture qua các bridge vào `create_app()`, FakeProvider, tua thời gian bằng tham số `now`) và in từng bước + kết quả; `dev/scenario_live.md` checklist chạy với Page thật.
- Test: map stage, khớp `cortexRef`, chữ ký Twenty, CSV catalog/orders, idempotent `ma_don`; `dev/scenario.py` chạy được trong CI (đánh dấu test `tests/bridges/test_scenario_sim.py`).

#### WP13 — Trang duyệt cho nhân viên (≤ 300 dòng, không tính template HTML)
Sở hữu: `cortex_leads/staff_ui/**` (routes.py + templates/ + static tối thiểu), `tests/staff_ui/**`.
- Router `staff_ui.routes:router` (prefix `/staff` đã nối). Server-rendered (Jinja2), **không JS framework**, dùng được trên điện thoại (CSS tối giản inline, chữ ≥ 16px, nút to).
- Đăng nhập: form nhập API key nhân viên (role staff/owner) → cookie `HttpOnly; Secure (khi https); SameSite=Strict` chứa key đã ký (itsdangerous không có → tự ký HMAC bằng `CL_CONNECTOR_SECRET_KEY` derived, hoặc lưu sha256 + session id trong bộ nhớ — chọn cách đơn giản, an toàn, ghi rõ). Đăng xuất. CSRF: token trong form, kiểm khi POST.
- Trang: **Hàng chờ** (`GET /staff`): nháp `proposed` + fact `candidate` cần xác nhận (`memory.service.pending_confirmations`), xếp theo `created_at`; mỗi thẻ: tên khách (nhân viên được thấy — đây là giao diện người, có audit), lý do đoán (nhãn từ domain pack), nháp, cửa sổ (`window_state` + `basis`; `human_agent` ghi rõ "chỉ người gõ tay"), nút **Đã gửi / Sửa rồi gửi / Tôi tự làm / Bỏ** (gọi logic của `review/api.py` — tách hàm dùng chung nếu cần **trong tệp của bạn**, không sửa `review/api.py`; nếu không gọi được mà không sửa → CONTRACT REQUEST). **Chi tiết hội thoại** (`GET /staff/c/{id}`): 10 tin gần nhất, trí nhớ (facts active), nút nhanh: *Khách hẹn ngày…* (date picker) · *Đã gọi* · *Đã chuyển Zalo* · *Đã chốt / Đã đặt lịch / Mua chỗ khác / Mở lại* · Xác nhận / Bác fact candidate — gọi **đúng chữ ký `memory.service` ở WP9** (WP9 đang làm song song: viết code theo chữ ký đã chốt; test của bạn có thể `pytest.importorskip("cortex_leads.memory.service")` cho phần đó, leader chạy lại sau khi WP9 xong).
- Nhãn hiển thị tiếng Việt. Chưa có nút "Duyệt & gửi" (WP8 sẽ thêm).
- Test: chưa đăng nhập → chuyển trang đăng nhập; key sai; RLS (key tenant B không thấy nháp tenant A); CSRF thiếu → 403; hành động "Đã gửi" ghi `staff_action`; HTML không lộ nháp của tenant khác; trang render được (status 200, có tiêu đề).

### 8.3 Sóng 2 — WP8 Gửi tin: auto / manual (≤ 550 dòng; tổng v0 phải ≤ 5.000)

Nguồn: DESIGN A9, N1, N3, N4, §5.2 (Cortex Action Format v1), §5.4, §5.7, §5.8 (`send_policy`, hai chế độ, thang bật auto), §7.2 A6. Đọc REVIEW R6, R9, R15, R18, R22, R26, R27.

**Sở hữu mới:** `cortex_leads/outbound/**` (`action_format.py`, `worker.py`), `cortex_leads/tools/send.py`, `tests/outbound/**`.
**Được sửa:** `tools/registry.py` (cho phép **đúng một** tool effect `customer` là `send_message`, vẫn từ chối mọi tool `customer` khác), `core/vocabulary.py` (`OUTPUT_KINDS` thêm `send_to_customer`), `skills/manifest.py` + `skills/loader.py` (`send_policy{mode: auto|manual, auto_when, fallback: manual}`; lint: `auto` ⇒ `requires_tools` có `send_message` và `output_kind: send_to_customer`), `runner/customer_run.py`, `review/api.py` (`act_on_draft`), `staff_ui/routes.py` + templates, `supervisor/api.py`, `cli.py`, `dev/scenario.py`, `sandboxes/customer_care/**`, `tests/e2e/test_walking_skeleton.py` (sửa test A9).

**Luồng:**
- **Chế độ hiệu lực** = `skill.send_policy.mode` nếu khai, ngược lại `sandbox.send_mode` (mặc định `manual`).
- **auto:** runner có kết quả `act: draft` → gọi `send_message` (actor `ai:<profile>@<ver>`). **Lõi tự kiểm trước** (sàn A9 + luật cửa sổ): sandbox/connector bị tắt (kill switch), `connector.outbound` không bật hoặc trust không phải official/partner, khách opted_out, validator (N2, never_say, touches), `window.basis != "free"` với actor `ai:*`, `must_handoff`. Bất kỳ điều nào → **không** ghi outbox, tạo `draft(proposed)` cho nhân viên (rơi về manual) + `decision_log fallback_manual` kèm mã. Qua hết → `outbox(queued)`, `disclosure` = "Trợ lý AI của <tenant.name>"; ngoài `sandbox.business_hours` → `not_before` = giờ mở cửa kế tiếp.
- **manual:** như hiện tại tạo `draft(proposed)`. Nhân viên bấm **"Duyệt & gửi"** (trang duyệt + `POST /review/drafts/{id}/action {action: approved, edited_text?}`) → `send_message` với actor `staff:<ref>` → outbox → `draft.status = approved`, `staff_action approved`, `trigger_run.staff_outcome = sent|edited`. Connector không bật outbound → giữ hành vi cũ ("Đã gửi" = nhân viên tự gửi).
- **Worker** `outbound/worker.py: deliver_once(now, *, client=httpx.AsyncClient) -> int`: mỗi tenant (xoay vòng), lấy `outbox` `queued` có `not_before <= now` `FOR UPDATE SKIP LOCKED`, đánh `sending`, POST Cortex Action Format v1 tới `connector.outbound.url` với `X-Cortex-Timestamp` / `X-Cortex-Signature` (**cùng** `ingest.signing.sign` và secret connector — khớp `bridges/messenger` `/actions`). Kết quả: `sent` → lưu `external_message_id`, `sent_at`; `refused` → `status=refused` + `reason`, **không retry**, nếu skill/sandbox `fallback: manual` → tạo `draft(proposed)` cho nhân viên; `error retryable` → `queued`, `attempts+1`, `not_before` backoff, quá 3 lần → `error` + decision_log. Lệnh CLI `deliver-outbox`.
- **Idempotency:** `action_id = uuid5(run_id hoặc draft_id, "send")` — chạy lại runner/duyệt hai lần không gửi hai tin.
- **Tin đã gửi quay về qua chiều vào** (echo) — không tự ghi `message` từ outbox (tránh trùng); nhưng ghi `conversation.touches += 1` một lần khi `sent`.
- **Supervisor:** `GET /supervisor/summary` thêm đếm từ `supervisor_outbox_view` (status, reason, actor_kind), n<5 ẩn.
- **CLI:** thêm `promote-skill --sandbox S --name N --version V --to shadow|live` (dùng `skills.registry.promote`) và `set-send-mode --sandbox S auto|manual`.
- **Skill mẫu:** thêm `send_policy: {mode: manual, fallback: manual}` vào 2 skill; thêm skill thử `sandboxes/customer_care/skills/thu-nhanh/` (`after: 5m`, chỉ dùng cho kịch bản thử, status draft).
- **dev/scenario.py:** hoàn thiện bước 5 (Duyệt & gửi qua bridge Messenger ASGI, Graph API mock), bước 6 (chạy lại runner với FakeProvider trả `facts` → ghi `promised_date` + `decision_maker`, đợt im kế tiếp không gọi LLM), bước 10 (chạy lại ở `auto`: gửi thẳng; một ca ngoài cửa sổ tự do → rơi về manual).

**Test bắt buộc:** auto gửi qua bridge mock đúng chữ ký; manual duyệt → gửi; `basis=human_agent` + ai → fallback manual (cả lõi chặn trước lẫn bridge từ chối); window đóng; opted_out; validator chặn → manual; disclosure chỉ khi ai; ngoài giờ → `not_before`; idempotent; refused → không retry + fallback; error retry ≤ 3; kill switch (sandbox paused, connector disabled, outbound tắt); connector `custom` không gửi; supervisor đếm outbox không có văn bản; **A9 mới:** chỉ một đường gửi — quét AST: import thư viện mạng chỉ ở `llm/` và `outbound/`; mọi tin ra khách đều có dòng `outbox`; skill `manual` không bao giờ sinh outbox khi chưa có người duyệt.

### 8.4 Sóng 3 — WP14 Nghiệm thu (sau WP8): kịch bản chuẩn trên Page thật, đo nhóm B với LLM thật, checklist thiết lập doanh nghiệp. Cần chủ dự án cung cấp Page/app/API key.

## 9. WP16 — Lượt khách (DESIGN §5.7 `turn`, 2026-10-13) — +145 dòng sản phẩm (trần 240)

Sở hữu: `migrations/versions/0004_reply_check.py` (conversation.reply_check_at, reply_waits; draft.needs_human), `ingest/normalize.py` (đặt/xoá mốc), `clock/sweeper.py` (bắn `conversation.awaiting_reply`), `triggers/engine.py` (luật 0 token `STAFF_ACTIVE`, `TURN_MAX_AGE`; `dedupe_key` = `turn:<conv>:<tin khách cuối>:<reply_waits>`), `triggers/select.py` (lượt khách đi đầu, không bị trần nháp/nhân viên), `runner/customer_run.py` + `runner/context_builder.py` (act `reply|wait|handoff|none`, shape riêng), `tools/send.py` (không chờ giờ làm việc; chặn `ai:*` gửi nháp `needs_human`; `outbox.source.turn`), `outbound/worker.py` (lượt không cộng `touches`; staff nhắn cũng làm tin ai:* `STALE`), `review/api.py`, `staff_ui` (nhãn, nháp lượt lên đầu), `cli.py` (`worker --interval N`, hàm lõi `worker_once`), `skills/registry.py` (`TURN_EVENT`, `reply_after_for`), `skills/manifest.py` (đơn vị `s`), skill `sandboxes/customer_care/skills/tra-loi-khach`.

Giao diện mới: `registry.TURN_EVENT`; `registry.reply_after_for(session, sandbox_id) -> timedelta | None`; `cli.worker_once(gateway) -> (fired, runs, sent)`; `build_messages(..., turn=True)`. Test: `tests/outbound/test_turn.py`.


## 9. Đợt 2–6 (từ 2026-10-17, DESIGN §7.3) — phiếu gói việc

L3 đã bỏ; quyền sở hữu tệp vẫn theo §2 cho code cũ. Gói mới sở hữu thư mục riêng, được sửa `db/models.py`, `core/envelope.py`, `config.py`, `cli.py` khi cần (ghi ở đây). Mọi gói: test xanh trên Postgres thật, không gọi LLM thật trong test, bất biến A1–A9 giữ.

| WP | Nội dung | Tệp mới / sửa | Bất biến liên quan |
|---|---|---|---|
| **WP17 Thông báo đẩy** (R58) | Hàng đợi `notification` + `notify_target` (Telegram). Sinh khi có thẻ cần người (`draft.needs_human`) hoặc lịch học thử mới. Tin gửi nhân viên **không chứa tên, SĐT, nội dung khách**, chỉ đếm + link `/staff`. Gom nhiều thông báo cùng loại thành một tin | `notify/`, models, migration 0005, `config.py` (`TELEGRAM_BOT_TOKEN`, `PUBLIC_BASE_URL`), `cli.py`, hook trong `runner/customer_run.py` | A1 (RLS), privacy (không PII ra ngoài) |
| **WP18 Đặt lịch học thử** | Slot = dòng catalog `category=lich_hoc_thu` (`valid_until` = giờ bắt đầu, `attrs.suc_chua`, `attrs.ngay`, `attrs.gio`). Bảng `booking`. Tool `list_open_slots` (read, cho model), `book_slot` (internal, **chỉ runner gọi**, khoá dòng catalog để không vượt sức chứa, đặt lại lịch = huỷ lịch cũ). Đặt xong ghi hẹn (`promised_date` active) để skill "đúng hẹn" chạy. Validator: **giờ** (hh:mm) và **URL** trong tin gửi khách phải khớp dòng catalog được trích. Nhân viên huỷ lịch ở trang hội thoại | `tools/booking.py`, `tools/v0.py`(claims giờ), `guard/validator.py`, `memory/service.py`, `runner/customer_run.py`, `staff_ui/`, skill `tra-loi-khach` v16 | A3 (scope từ ctx), A7 (validator trong tool), A9 (AI không gửi phiếu, chỉ trích link từ catalog qua `send_message`) |
| **WP19 Cron (mẫu) + sandbox `owner_digest`** | Hai việc theo giờ, **0 token, chỉ là mẫu**: `morning_list` 07:45 giờ địa phương (khách chưa được trả lời + lịch học thử hôm nay → `staff_task`), `weekly_digest` thứ Hai 08:00 (số liệu tuần so với tuần trước → `digest`). Idempotent theo slot (UNIQUE trên bảng đầu ra). Sandbox thứ hai `owner_digest` (CLI `create-sandbox`); sandbox tạm dừng thì cron im. Đẩy Telegram chỉ có số. Trang `/staff` hiện việc sáng nay, `/staff/digest` chỉ cho role `owner` | `cron/`, `sandboxes/owner_digest/`, models (`StaffTask`, `Digest`), migration 0006, `staff_ui/`, `notify/` | A1, privacy (chỉ số và id; tên đọc lúc xem dưới RLS) |
| **WP20 Connector `http_readonly`** (T1) | Một GET tới host doanh nghiệp liệt kê. https, `allow_hosts`, không theo redirect, từ chối DNS trỏ về địa chỉ riêng (SSRF), query bị che PII trước khi đi, trả về JSON bị giới hạn kích thước/độ sâu và che PII, đánh dấu `untrusted`. Cấu hình ghim bằng `pin_sha256`, sửa sau khi duyệt thì bị từ chối. Tool `external_lookup` (read) **không bao giờ chạy trong customer run** | `connectors/`, `tools/external.py`, models (`ToolConnector`), migration 0007, `cli.py` | A1, A3, Dual-LLM (§5.5), DESIGN §5.8 |
| **WP21 AI tổng** | Chỉ đọc metadata: `read_findings` chạy bằng `supervisor_session` (role `cl_supervisor`, quyền theo cột; cột chữ ném lỗi chứ không bị lọc). 4 tín hiệu 0 token có tên: `blocked_spike`, `error_streak`, `skipped_high`, `outbox_failing` (n ≥ 5, ngưỡng là hằng số). Tín hiệu bắn → `proposal` (rollback / tạm dừng / xem lại), **chỉ người role `owner` bấm mới thi hành** (`supervisor/proposals.decide`, ghi `action_log`); điều kiện hết thì đề xuất thành `stale`. Báo cáo tuần có thêm đoạn tóm tắt do LLM viết **từ các con số**, mọi số trong đoạn phải nằm trong dữ liệu đưa vào, sai thì bỏ đoạn (digest vẫn còn) | `supervisor/{signals,proposals,narrative}.py`, models (`Proposal`), migration 0008, `cron/`, `staff_ui/` | A7, Dual-LLM (§5.5), DESIGN §5.6 |
| **WP22 Form skill + shadow** | Chủ tạo skill bằng form ở `/staff/skills`: mẫu cố định (`khach_im`, `dung_hen`), tool/`output_kind`/`send_policy` do mẫu quyết (form **không bao giờ** tạo skill tự gửi), `never_say`/`must_handoff` chỉ thêm không bớt, tên luôn `tuy-chinh-<slug>`, mỗi lần lưu là version mới bất biến qua `lint` như file. Vòng đời draft → **shadow** (engine tạo job riêng khóa `shadow:`; runner viết nháp có qua validator nhưng ở trạng thái `shadow`, không outbox, không thông báo, không ghi trí nhớ, không vào hàng duyệt, không tính trần nháp của nhân viên) → live (cần ≥ 10 lượt thử, chủ đọc nháp thử) | `skills/forms.py`, `skills/registry.py`, `triggers/`, `runner/customer_run.py`, `staff_ui/`, migration 0009 | A9, DESIGN §5.8 vòng đời |
| **WP23 MCP ngoài chỉ đọc** (T2) | Connector `mcp` qua HTTPS (không bao giờ stdio): `initialize` → `tools/list` → `tools/call`. Người duyệt ghim **định nghĩa** của đúng một tool (`tool_pin` = hash tên + mô tả + schema); mỗi lần gọi liệt kê lại và từ chối nếu khác (`TOOL_CHANGED`: rug-pull, tool poisoning). Tool tự khai ghi/phá huỷ thì bị từ chối. Cùng bức tường với `http_readonly` (https, `allow_hosts`, không redirect, DNS công khai, giới hạn kích thước, che PII hai chiều, `untrusted`). **Sau khi một lượt đọc dữ liệu ngoài, registry chặn mọi tool ghi của chính lượt đó** (`ToolSpec.taints`) | `connectors/mcp_remote.py`, `tools/registry.py`, `tools/external.py`, `cli.py`, migration 0010 | DESIGN §5.8 "MCP bên ngoài", Dual-LLM |
| **WP24 Chiều ngược về kênh** (T2) | `add_tag` / `add_note` trên nền tảng nơi nhân viên làm việc, khi có `booking`, `handoff`, `won`, `lost`. Không phải tin cho khách: không cửa sổ, không dòng xưng AI, không tính lần chạm. Vẫn là **một hàng `outbox`** (cột `kind`), cùng worker, cùng bridge ký; chỉ khi doanh nghiệp bật (`outbound.capabilities` + `outbound.tags/notes` là chuỗi cố định của họ, không có chữ của khách hay model). Bridge không hỗ trợ thì trả `NOT_SUPPORTED` và đó là kết quả cuối | `outbound/annotate.py`, `outbound/worker.py`, `outbound/action_format.py`, migration 0010 | A9 (không đường mới tới khách), A1 |
| **WP25 Thẻ chiến lược** (T2) | AI tổng đổi tín hiệu `skipped_high` thành **thẻ**: `proposal.kind=tune_skill`, `target.change = {field, from, to}`, chỉ hai trường được đổi (`limits.max_touches` 1–3, `trigger.after` 4–72h), tối đa 3 thẻ mở, mặc định 0. Chủ duyệt thì sinh **version mới của đúng skill đó chạy shadow** (một trường khác bản cũ); bản đang chạy giữ nguyên tới khi chủ đọc nháp thử và bật | `supervisor/{signals,proposals}.py`, `staff_ui/` | DESIGN §5.7 |
| **WP26 Multi-cell** (T2) | Một cell là một bản đầy đủ (DB, worker, tenant riêng). `connector id` mang tên cell (`conn_<cell>-<random>`, id cũ = cell mặc định `c1`); `cells/router.py` đọc **chỉ** header `X-Connector-Id` rồi chuyển nguyên byte tới đúng cell (chữ ký vẫn xác minh được), không có DB/secret/dữ liệu; cell từ chối connector của cell khác bằng 421 | `cells/`, `core/ids.py`, `config.py` (`CL_CELL`), `ingest/api.py` | DESIGN §5.10 |
| **WP27 Console (giao diện chính)** | SPA `cortex-leads/web/` (React 19 + TS + Vite + Tailwind v4 + TanStack Query + React Router), thiết kế ở `pencil/`. API JSON mới `cortex_leads/console/` dưới `/api/v1`: đăng nhập, hộp thư, kỹ năng, sandbox, AI tổng (trò chuyện chỉ trên số liệu), dừng khẩn cấp. FastAPI phục vụ bản build ở `/app`. Không tái sử dụng HTML của `/staff`; logic nghiệp vụ gọi lại đúng các hàm đã có (`act_on_draft`, `forms.*`, `proposals.decide`, `cancel_booking`) để không có đường thi hành thứ hai | `web/`, `cortex_leads/console/`, `app.py` | A1, A3 (tenant/actor từ phiên), A9 (duyệt gửi vẫn qua `act_on_draft`), §5.6 |
| **WP28 Nhật ký hoạt động** | Bảng `audit_event` (migration 0012, chỉ thêm, chuỗi băm), `cortex_leads/audit/` (ghi, kiểm), `console/audit.py` (danh sách phân trang, chi tiết, CSV, kiểm toàn vẹn), trang `Audit` ở SPA, mọi hành động console và đăng nhập/đăng xuất/từ chối đều ghi qua `audit.record` thay cho `action_log` | `audit/`, `console/{audit,trail}.py`, `web/src/pages/Audit.tsx` | A1, A3, DESIGN §5.14 |
| **WP29 Kỹ năng sửa tại chỗ, công cụ, nguồn dữ liệu** | Migration 0013–0014. Kỹ năng từ form lưu `form_spec` nguyên bản, sửa tại chỗ (`PUT /skills/{id}`, không tạo bản mới, số lượt thử tính lại từ `edited_at`), lịch sử sửa nằm ở `audit_event.metadata.before_spec` và khôi phục được (`POST /skills/{id}/revert`), xoá mềm `deleted_at` (ẩn, tắt, khôi phục được). `sandbox.tools_off`: chủ tắt công cụ theo sandbox, runner lấy giao của hồ sơ ∩ sandbox ∩ kỹ năng. `console/tools.py` (danh mục công cụ, ma trận quyền, bật/tắt), `console/sources.py` (nguồn HTTP/MCP: thêm + ghim, khoá mềm, duyệt lại khi định nghĩa đổi, chỉ gắn sandbox không nói chuyện với khách). SPA: chi tiết + sửa kỹ năng, tab Đã xoá, Công cụ & kết nối, thêm nguồn, chi tiết sandbox (sơ đồ liên kết + ma trận) | `console/{skills,tools,sources}.py`, `skills/forms.py`, `web/src/pages/{SkillDetail,SkillForm,Tools,SourceNew,SandboxDetail}.tsx` | A1, A3, A9 (không thêm đường gửi), §5.8, §5.14 |
| **WP30 Đăng nhập, phiên, phân quyền** | Migration 0015 (`app_user`, `auth_session`, `login_throttle`). `cortex_leads/auth/` (mật khẩu scrypt + luật, chống đoán, phiên phía server, tài khoản, bảng quyền), `console/{auth,session,team}.py` viết lại: đăng nhập email + mật khẩu, khoá khi đoán sai, đổi mật khẩu, thiết bị đang đăng nhập, quản lý nhân viên, mật khẩu tạm hiện một lần. CLI `create-user`, `reset-password`. SPA: Đăng nhập, đặt mật khẩu mới bắt buộc, Tài khoản, Nhân viên & quyền | `auth/`, `console/{auth,session,team}.py`, `web/src/pages/{Login,Account,Team}.tsx` | A1 (RLS trên mọi bảng mới), A3 (người từ phiên), §5.14, §5.15 |
| **WP31 Sandbox `lesson_recap`** | Bản ghi buổi học → tổng kết (nội dung, bài tập về nhà, nhận xét chung lớp) → kênh Mezon của đội. Migration 0017 (`lesson_source`, `lesson`; `notification.kind` thêm `lesson`, `notify_target.kind` thêm `mezon`). `cortex_leads/connectors/{lesson_sources,speech}.py` (mọi gọi mạng nằm ở đây để giữ nguyên chốt A9: Drive qua service account chỉ-đọc hoặc thư mục máy; Whisper API hoặc faster-whisper tại chỗ), `cortex_leads/lessons/`: `audio` (ffmpeg cắt 10 phút), `recap` (che PII, JSON cố định, buổi dài đọc theo đoạn rồi gộp), `job` (3 lượt DB ngắn quanh phần chậm, tối đa 3 lần thử, tính vào ngân sách). Đẩy qua `notify`, **chỉ tới đích `mezon`**, không qua `outbox` nên A9 không bị chạm. CLI `add-lesson-source`, `add-notify-target --kind mezon`, `lessons`. Chưa có: nhận xét riêng từng học sinh (Whisper không biết ai nói), màn console | `lessons/`, `connectors/{lesson_sources,speech}.py`, `notify/`, `cli.py`, `config.py`, `db/models.py`, `sandboxes/lesson_recap/` | A1 (RLS), A3 (tenant từ phiên cron), §5.6 (nội dung buổi học không đi lên AI tổng), §6 (dữ liệu trẻ em, chuyển ra nước ngoài) |
| **WP32 Khối dùng lại cho sandbox** | (1) `sandbox/kinds.py`: registry `SandboxKind` (nhãn, mô tả, hồ sơ, thư mục skill, việc cron, cách dựng ban đầu) thay `JOBS`, `PROFILES`, `TEMPLATES`, `PURPOSE_LABELS`, `TEMPLATE_DIRS` và nhánh `lesson_recap` trong CLI. (2) `llm/ask.py` (`ask_json`) và `llm/pieces.py` (`read_in_pieces`): hỏi lại khi JSON hoặc schema sai, đoạn hỏng thì chia đôi, ghi chú từng đoạn lưu ở `lesson.notes` (migration 0018) để thử lại không làm lại. (3) `lessons/job.py`: chốt `claimed_at` khi ghi kết quả. (4) `connectors/egress.py`: kiểm địa chỉ webhook (https, host trong `CL_WEBHOOK_ALLOW_HOSTS`, IP công cộng) khi lưu và khi gửi. **Không làm trong gói này:** `work_item`, `effect_ceiling`, `Sink` registry, mã hoá địa chỉ webhook, đích theo sandbox, trình dựng, `classroom_grader` | `sandbox/kinds.py`, `llm/`, `lessons/`, `connectors/egress.py`, `cron/runner.py`, `cli.py`, `console/sandboxes.py`, `skills/profile.py` | A1, A3, A9 (không đổi), §5.6 |
| **WP33 Sandbox `classroom_grader`** | Migration 0019: `classroom_source` (khoá mã hoá), `grading_guide` (thang điểm theo tiêu chí + đáp án do giáo viên đưa), `grade_item` (hàng việc theo bài nộp + đề xuất điểm), `assignment_draft` (đề chờ duyệt). `connectors/google_auth.py` (JWT dịch vụ có `sub`, hoặc refresh token), `connectors/classroom.py` (khoá học, bài tập, bài nộp, tạo bài, ghi điểm, trả bài; Docs đính kèm xuất ra chữ). `work/queue.py`: nhận việc, chốt `claimed_at`, thất bại theo mã (rút từ `lessons/job.py`, hai sandbox dùng chung). `grader/`: `guide`, `validator` (A7: điểm trong thang, tổng khớp, trích dẫn có thật), `grade` (che PII, `ask_json`, kiểm), `job`, `writeback` (duy nhất ghi điểm, chỉ khi giáo viên duyệt và bài `associatedWithDeveloper`). Skill `cham-bai`, `soan-bai-tap`. Console: màn **Chấm bài** và **Bài tập** (quyền `grading.use`). Thông báo chỉ có số lượng (`notification.kind=grading`). CLI `add-classroom-source`, `import-grading-guide`, `classroom`. Máy chủ Classroom giả cho thử | `connectors/`, `grader/`, `work/`, `console/grading.py`, `web/src/pages/{Grading,Assignments}.tsx`, `sandboxes/classroom_grader/` | A1 (RLS), A3 (người duyệt từ phiên), A7 (validator điểm), A9 (không đường gửi khách mới), §6 (dữ liệu trẻ em) |
| **WP34 Bài nộp nhiều định dạng** | `grader/extract.py` đọc bài nộp theo loại: Google Docs và văn bản, PDF có lớp chữ (`pypdf`), Word (đọc đoạn văn bằng regex, không dùng bộ phân tích XML), âm thanh và video (chỉ lấy tiếng, `media/audio.py` cắt 5 phút, tối đa 3 đoạn, chép lời bằng `connectors/speech.py`). Mã từ chối có lý do: `NO_TEXT_LAYER`, `TOO_LONG`, `TOO_LARGE`, `NO_SPEECH`, `FILE_UNREADABLE`, `UNSUPPORTED_ATTACHMENT`. `ClassroomClient` chỉ còn tải tệp và xuất Docs; việc đọc nằm ở `grader/`. Migration 0020 `grade_item.content_kind`. Màn Chấm bài hiện nguồn đọc và lưu ý nghe lại | `grader/extract.py`, `media/`, `connectors/{classroom,speech}.py`, `grader/{job,grade}.py`, `console/grading.py`, `web/src/pages/Grading.tsx` | A3, A7, §6 (giọng nói học sinh, chuyển ra nước ngoài nếu Whisper API) |
| **WP35 Tải bản ghi lên trang Buổi học** | Migration 0024 (`lesson_source.kind` thêm `upload`, `lesson.language`). `PUT /lessons/upload?name&language` (quyền `lessons.upload`; thân là tệp, ghi thẳng xuống đĩa, từ chối theo `Content-Length`, `ffprobe` kiểm có âm thanh, mỗi tệp một tên do máy chủ đặt), `GET /lessons/{id}/media` (Range, riêng tư theo phiên và tenant), `DELETE /lessons/{id}/media` (giữ chữ). `connectors/lesson_sources.UploadStore`, `lessons/uploads.py`, `media/audio.probe`. Hàng việc dùng nguồn `upload` (xếp hàng ngay khi tải lên, không quét); ngôn ngữ bản chữ theo lựa chọn. Trang Buổi học: khung tải lên có tiến độ, danh sách có nguồn và biểu tượng xem lại được, bảng chi tiết có trình phát và nội dung cạnh nhau, xoá tệp gốc, link mở thẳng `/app/lessons/<id>` (tin Mezon của buổi tải lên trỏ về đây). Cấu hình `CL_UPLOAD_DIR`, `CL_UPLOAD_MAX_MB` | `console/lessons.py`, `lessons/{job,uploads}.py`, `connectors/lesson_sources.py`, `web/src/pages/Lessons.tsx` | A1, A3 (người tải từ phiên), §6 (giọng nói học sinh) |
| **WP36 Bản ghi lưu ở Drive của giáo viên** | Migration 0025: `drive_target` (đăng nhập OAuth mã hoá, id thư mục) và `lesson.drive_{target_id,file_id,url}`. `connectors/drive_store.py`: `DriveUploader` (tạo thư mục, tải lên theo đoạn 8 MB, phân loại lỗi `UNAUTHENTICATED`/`PERMISSION_DENIED`/`STORAGE_FULL`). Vòng `lessons`: lên Drive trước, chuyển chữ, tổng kết, rồi xoá bản tạm khi xong (chỉ khi đã có bản ở Drive). `PUT /lessons/upload?target=<drive_target>`; trang Buổi học có ô "Lưu bản ghi ở", chi tiết hiện nút mở trong Drive thay trình phát. CLI `add-drive-target` (kiểm quyền bằng cách tạo thư mục), `add-classroom-source` nay thay mã khi nối lại; `classroom-login` xin thêm quyền `drive.file` | `connectors/drive_store.py`, `lessons/job.py`, `console/lessons.py`, `cli.py`, `web/src/pages/Lessons.tsx` | A1, A3, §6 (giọng nói học sinh ở lại tài khoản của trung tâm) |
| **WP37 Một đường xử lý, tải thẳng từ trình duyệt, xem lại từ Drive** | Migration 0026: `drive_target.folder_adopted`. `POST /lessons/upload/session` (hạn mức, `Origin` từ cấu hình) mở phiên upload resumable ở Drive của giáo viên; `web` gửi từng đoạn thẳng lên Google (`uploadToDrive`). `discover` là đường xử lý duy nhất, đọc ngôn ngữ từ thuộc tính Drive; `to_text` kiểm `probe`. Gỡ: `PUT /lessons/upload`, kho tải lên, `send_to_drive`, `UploadStore`, xoá tệp gốc, `CL_UPLOAD_DIR`. `GET /lessons/{id}/media` phát từ Drive (Range, tenant); `classroom-login --for drive`; `add-drive-target` mặc định thư mục đang theo dõi (`--own-folder`, `--folder-id`) | `connectors/drive_store.py`, `lessons/job.py`, `console/lessons.py`, `console/spa.py`, `cli.py`, `web/src/api/client.ts`, `web/src/pages/Lessons.tsx` | A1, A3 |
| **WP38 Lớp học** | Phiếu [`docs/PHIEU-lop-hoc.md`](../docs/PHIEU-lop-hoc.md). Migration 0037 (bảng `class`, `assignment`; `lesson.class_id`, `lesson.released_at`; `grade_item.assignment_id`, `grade_item.write_mode`, trạng thái `pending`; chuyển dữ liệu từ `lesson_source`, `classroom_source`, `grading_guide`, `assignment_draft`), 0038 gỡ bảng cũ và đổi `grade_item` thành `submission`. Chính sách theo lớp `recap_mode`, `grading_mode`. Cổng duyệt tổng kết bài giảng; chấm bài ba chế độ (`manual`, `review`, `auto_write`). SPA: mục "Lớp học" gộp Bài giảng, Chấm bài, Bài tập; hộp thoại Sửa lớp | `db/models.py`, `migrations/`, `console/{classes,flow,google,grading,lessons}.py`, `grader/`, `lessons/`, `notify/worker.py`, `cli.py`, `web/src/{App,components/Shell,api/hooks}.ts*`, `web/src/pages/{Lessons,Grading,Assignments,ClassPage,Classes}.tsx` | A1 (RLS bảng mới), A3 (chế độ từ cột, không từ body), A7 (validator chạy trước tự ghi điểm), A9 (không đường gửi mới), §6 (dữ liệu trẻ em) |
| **WP47 Trang quản trị nền tảng (P0)** | Người vận hành máy chủ làm qua giao diện những việc trước đây phải SSH chạy `cli`: xem danh sách doanh nghiệp, tạo doanh nghiệp (đủ sandbox) + mời chủ đầu tiên, bổ sung sandbox thiếu, tạm dừng / chạy lại AI của một doanh nghiệp hoặc **toàn hệ thống**, cứu chủ bị khoá (gửi lại liên kết mời/đặt lại mật khẩu, tắt xác thực 2 lớp, đăng xuất mọi thiết bị), mời thêm chủ. **Không phải một vai trò trong doanh nghiệp:** bảng riêng `platform_admin` (migration 0050, không `tenant_id`, như `tenant`/`login_throttle`), JWT khoá riêng (`admin-jwt|`, `aud=admin`), cookie `cl_admin` chỉ gửi tới `/api/admin`, CSRF riêng. **Bắt buộc xác thực 2 lớp:** lần đăng nhập đầu tiên phải cài TOTP xong mới có phiên. Phiên 30 phút không hoạt động / 8 giờ tối đa, mỗi request đọc lại `platform_admin` (ít người dùng, không cần Redis); đăng xuất = tăng `token_version`. Tắt 2 lớp của người khác và dừng toàn hệ thống cần mã TOTP hiện tại của admin. Admin **không** đặt, không thấy mật khẩu của ai (chỉ gửi liên kết qua email, DESIGN §5.15); không đọc hội thoại, SĐT, nội dung khách: chỉ số đếm và tài khoản của doanh nghiệp. Mọi thao tác ghi vào nhật ký **của doanh nghiệp bị tác động** (`actor=admin:<email>`, `role=platform`); đăng nhập admin ghi dòng phạm vi nền tảng (`tenant_id` NULL). Tài khoản admin tạo bằng `cli create-admin` (hỏi mật khẩu ở terminal); mất điện thoại: `cli reset-admin-mfa`. `cli create-tenant` dùng chung hàm `admin/service.py`. L1: phục vụ G1/G2, mở doanh nghiệp cho khách đầu tiên mà không cần quyền SSH; chưa có bằng chứng từ khách (công cụ của người vận hành) | `admin/{auth,service,api}.py`, `db/models.py` (`PlatformAdmin`), migration 0050, `cli.py`, `app.py` (mount `/api/admin`), `config.py` (`ADMIN_*`), `web/src/admin/`, `App.tsx`, `tests/console/test_platform_admin.py` | A1 (thao tác trong tenant vẫn qua `tenant_session`), A3 (tenant lấy từ đường dẫn chỉ sau khi phiên admin hợp lệ), §5.15 (không mật khẩu tạm) |
| *(WP27 — trạng thái 2026-10-21)* | Đã xây: API `console/` (session + CSRF, hộp thư, kỹ năng, sandbox, AI tổng, dừng khẩn cấp, phục vụ SPA, `template_dir` theo purpose, cột `sandbox.title`, migration 0011), SPA 5 màn, 41 test pytest + 58 test vitest. Chưa có: Việc hôm nay, Dữ liệu (catalog, lịch học thử), Báo cáo, Cài đặt (R85–R90) | | |
