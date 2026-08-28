# ARCHITECTURE DECISIONS
## Các quyết định kiến trúc + Lý do + Trade-offs

> **Mục đích**: Giải thích TẠI SAO chọn từng giải pháp, không chỉ là CÁCH làm.  
> Đọc file này trước khi bắt đầu bất kỳ phase nào để hiểu bức tranh tổng thể.

---

## AD-001: Tại sao dùng Temporal thay vì tự xây execution engine?

### Quyết định
Dùng Temporal làm workflow execution engine, không tự xây từ đầu.

### Bối cảnh
Cortex là graduation project với timeline 2-3 tháng và solo developer. Nếu tự xây execution engine, phải giải quyết:
- Queue + retry logic
- State persistence khi server restart
- Pause/resume workflow
- Long-running workflow (chờ user approval)
- Concurrency control
- Execution history

### Lý do chọn Temporal

**Durability**: Workflow state được lưu ở Temporal server. Nếu workflow_service crash giữa chừng, khi restart lên, Temporal tự replay lại history và tiếp tục từ điểm đúng. Không mất execution.

**Built-in retry**: Mỗi Activity có retry policy. Không cần tự code try/catch/sleep/retry.

**Execution history**: Temporal UI cho thấy toàn bộ lịch sử execution của từng workflow — từng step, từng retry, từng input/output. Cực kỳ hữu ích cho demo và debugging.

**Production-grade**: Stripe, Netflix, Coinbase dùng Temporal. Đây không phải thư viện thí nghiệm.

### Trade-offs

**Phức tạp hơn**: Temporal có learning curve. Developer cần hiểu phân biệt Workflow Definition vs Activity, Temporal Worker, Task Queue, Determinism constraints.

**Thêm infrastructure**: Cần 2 containers thêm (temporal server + temporal-postgresql). Docker Compose phức tạp hơn.

**Determinism constraint**: Code trong `@workflow.defn` KHÔNG được có side effects (không gọi DB, không random, không time.now()). Mọi side effect phải đặt trong `@activity.defn`. Đây là rule quan trọng nhất cần nhớ.

### Giải pháp cho trade-off
Dùng `temporalio/auto-setup` image — self-contained, tự khởi tạo DB schema, không cần config phức tạp. Phù hợp cho development và demo.

---

## AD-002: Tại sao dùng schema riêng `workflow` trong PostgreSQL thay vì DB riêng?

### Quyết định
workflow_service dùng schema `workflow` trong cùng PostgreSQL database của Cortex (không phải DB riêng).

### Lý do

**Đơn giản**: Solo developer không cần quản lý 2 PostgreSQL connections khác nhau. Một connection string, một backup, một monitoring.

**Foreign keys**: Nếu sau này cần JOIN với `users` table của Cortex (ví dụ: filter workflows theo user email), không cần cross-database query.

**Resource**: Chạy 2 PostgreSQL instances tốn RAM và CPU — không cần thiết ở scale hiện tại.

### Trade-offs

**Coupling**: workflow_service phụ thuộc vào Cortex PostgreSQL. Nếu Cortex DB down, workflow_service cũng không làm được gì.

**Migration conflict**: Alembic của workflow_service và Cortex backend phải chạy độc lập. Giải pháp: workflow_service chỉ tạo table trong schema `workflow`, không đụng vào schema `public` của Cortex.

### Khi nào nên tách ra DB riêng
Khi workflow_service trở thành independent service thực sự — tức là khi có team riêng, SLA riêng, deploy cycle riêng. Không phải bây giờ.

---

## AD-003: Tại sao workflow_service là service riêng (port 8001) thay vì thêm vào Cortex backend?

### Quyết định
Tạo `workflow_service` mới với FastAPI riêng (port 8001), không merge vào `backend/app/`.

### Lý do

**Temporal Worker không thể chạy trong Cortex backend dễ dàng**: Cortex backend dùng WorkerThread pattern (in-process thread). Temporal Worker cần asyncio event loop riêng. Merge vào backend sẽ gây conflict với existing worker pattern.

**Tách concern rõ ràng**: Workflow logic (graph traversal, state machine, trigger matching) là một domain khác với note/schedule/agent. Tách ra giúp code không bị lẫn lộn.

**Dễ scale độc lập**: Nếu workflow execution tốn nhiều tài nguyên, có thể scale workflow_service riêng mà không ảnh hưởng Cortex backend.

**Không break existing code**: Thêm module mới vào Cortex backend (1227-line App.tsx, mixed sync/async) có rủi ro cao. Tách ra service mới an toàn hơn.

### Trade-offs

**Thêm network hop**: Cortex frontend cần gọi 2 endpoints (`:8000` và `:8001`). Giải pháp: dùng nginx reverse proxy hoặc API gateway sau này, hoặc frontend tự biết gọi đúng service.

**JWT secret phải đồng bộ**: workflow_service dùng cùng JWT_SECRET_KEY với Cortex để verify token. Hai service phải đọc cùng env var. Cần đảm bảo cùng giá trị trong `.env`.

**Thêm service trong Docker Compose**: Từ 10 services lên 14 services.

---

## AD-004: Tại sao dùng Redis Pub/Sub cho internal events thay vì HTTP callback?

### Quyết định
Cortex backend publish events lên Redis Pub/Sub channel `cortex:workflow:events`. workflow_service subscribe và process.

### Alternatives đã xem xét

**Option 1: HTTP Callback** — Cortex backend gọi `POST http://workflow_service:8001/internal/events` sau mỗi operation.

**Option 2: Redis Pub/Sub** ← Chọn cái này

**Option 3: Dùng Redis Streams** (như pattern hiện tại của Cortex)

### Lý do chọn Redis Pub/Sub

Cortex đã có Redis. Thêm Pub/Sub không cần thêm infrastructure mới.

Pub/Sub là fire-and-forget — Cortex backend publish xong không cần chờ response. Không block request lifecycle.

Đơn giản hơn Redis Streams ở phase này — không cần consumer group, không cần ACK.

### Trade-offs so với HTTP Callback

HTTP Callback dễ debug hơn (có HTTP status code, response body). Nhưng tạo circular dependency: Cortex backend phụ thuộc vào workflow_service URL.

### Trade-offs so với Redis Streams

Redis Streams có durability (message không mất khi consumer offline). Pub/Sub thì mất message nếu workflow_service đang down khi event được publish.

**Quyết định**: Chấp nhận trade-off này. Nếu workflow_service down, triggers bị miss. Có thể nâng cấp lên Redis Streams ở iteration sau.

---

## AD-005: Tại sao dùng React Flow ngay từ đầu thay vì form-based UI?

### Quyết định
Dùng React Flow cho visual drag-and-drop builder ngay từ Phase 4.

### Lý do

Workflow definition có cấu trúc **graph** (nodes + edges). Đây là data structure tự nhiên nhất để visualize bằng node graph — form/list không thể biểu diễn được graph topology.

React Flow là thư viện mature (dùng trong Langflow, Flowise, Activepieces). API ổn định, không lo breaking changes.

Visual builder là **differentiator** — đây là feature demo được ấn tượng nhất so với CLI hoặc form-based workflow.

### Trade-offs

React Flow thêm ~200KB vào bundle size. Acceptable.

Learning curve: Developer cần hiểu React Flow concepts (nodes, edges, handles, viewport). Khoảng 1-2 ngày.

Mobile UX kém — drag-and-drop không hoạt động tốt trên touch. Acceptable vì Cortex là web app, không phải mobile app.

---

## AD-006: Generic CortexWorkflow vs Multiple Workflow Definitions

### Quyết định
Dùng **một** Temporal Workflow Definition duy nhất (`CortexWorkflow`) cho tất cả workflows của user. Logic cụ thể được đọc từ JSON definition trong input.

### Alternative
Mỗi workflow của user compile thành một Temporal Workflow class riêng.

### Lý do chọn Generic

**Đơn giản**: Không cần code generation. Không cần compile/deploy mỗi khi user tạo workflow mới.

**Safe**: Code execution là Python code do developer viết, không phải user-generated code. Không có security risk.

**Flexible**: Thêm node type mới chỉ cần thêm Action class mới, không cần thay đổi Temporal registration.

### Trade-offs

**Performance**: Mỗi execution phải parse JSON definition và build execution graph. Thêm ~10-50ms overhead. Acceptable.

**Debugging**: Tất cả executions đều hiện là "CortexWorkflow" trong Temporal UI, không phân biệt được bằng workflow name ngay. Giải pháp: dùng `temporal_workflow_id = f"cortex-wf-{workflow_name}-{instance_id}"` để dễ filter.

---

## AD-007: Workflow Definition lưu trong PostgreSQL, không phải MongoDB

### Quyết định
`workflow_definitions` và `workflow_instances` lưu trong PostgreSQL, không phải MongoDB (dù Cortex đang dùng MongoDB cho OCR/STT data).

### Lý do

Workflow definitions có **schema cố định** — id, name, status, trigger_type, definition (JSON). Phù hợp với relational DB.

Cần **ACID transactions**: Khi tạo workflow + webhook record phải là atomic.

Cần **foreign key constraints** (dù không enforce strict, nhưng có index).

`definition` field (React Flow JSON) lưu dưới dạng `JSONB` trong PostgreSQL — linh hoạt như MongoDB nhưng vẫn có transactional guarantees.

### Khi nào dùng MongoDB cho workflow data
Execution logs với unstructured output data — phù hợp hơn. Nhưng để đơn giản, Phase 1-6 vẫn dùng PostgreSQL cho cả execution logs.

---

## AD-008: Template Variables — `{{trigger.xxx}}` syntax

### Quyết định
Dùng `{{variable.path}}` syntax cho template variables trong action config. Ví dụ: `{{trigger.note_title}}`, `{{steps.node-1.summary}}`.

### Lý do chọn syntax này

Quen thuộc với Jinja2/Handlebars/n8n. Developer hiểu ngay không cần học thêm.

Dễ implement với regex: `re.sub(r'\{\{(.+?)\}\}', replace_fn, template)`.

Không conflict với Python f-string hoặc JavaScript template literals.

### Scope của template variables

```
{{trigger.*}}        → trigger_data dict từ event
{{steps.NODE_ID.*}}  → output của node có id = NODE_ID
{{workflow.*}}       → workflow metadata (id, name, version)
{{user.*}}           → user info (id, email)
```

### Trade-offs

Chỉ hỗ trợ string substitution, không hỗ trợ logic (if/else, filters). Đủ dùng cho MVP. Nếu cần logic phức tạp, dùng `action.condition` node thay vì inline expression.

---

## AD-009: Error handling — Fail Fast vs Continue on Error

### Quyết định
Mặc định: **Fail Fast** — nếu một step fail sau 3 retry, toàn bộ workflow instance fail.

### Lý do

Predictable behavior — user biết workflow đang fail, không bị "zombie workflow" chạy một phần.

Temporal retry policy xử lý transient errors (network timeout, API rate limit) tự động. Chỉ fail workflow khi error thực sự không thể recover.

Dễ implement hơn "continue on error" — không cần track error state per-node.

### Khi nào muốn "continue on error"
Phase sau có thể thêm node config `on_error: "continue" | "fail"`. Không cần implement ngay.

---

## AD-010: Authentication — Reuse Cortex JWT

### Quyết định
workflow_service verify JWT token bằng cùng `JWT_SECRET_KEY` với Cortex backend. Không có auth service riêng.

### Lý do

Zero additional infrastructure. User đăng nhập vào Cortex lấy JWT, dùng JWT đó để gọi workflow_service.

Đơn giản: `jwt.decode(token, settings.jwt_secret_key)` — 5 dòng code.

### Trade-offs

Nếu Cortex thay đổi JWT format hoặc secret, workflow_service phải update đồng thời.

Không có token refresh logic riêng — dùng access token từ Cortex, có thể hết hạn. Frontend xử lý refresh như với Cortex backend.

### Internal API calls (workflow_service → Cortex backend)

Dùng `X-Internal-API-Key` header với shared secret — không dùng JWT cho service-to-service calls. Đơn giản và đủ cho development scale.
