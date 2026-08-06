# Phase 1: Intent & Event Bus — Overview

**Timeline:** 4-6 tuần (Week 1-6)  
**Status:** ✅ Hoàn thành 2026-08-06 — cả 10/10 milestone đã triển khai, test, tích hợp thật (không chỉ plan). 1.9 và 1.10 là bổ sung sau khi 1.1-1.8 xong, phát hiện qua yêu cầu review thêm. Xem "Status: hoàn thành" ở cuối mỗi file `0X_*.md` để biết chi tiết sai khác so với bản kế hoạch gốc.  
**Prerequisites:** Phase 0 completed (structured logging, Redis Streams, ToolRegistry exists)

---

## 🎯 Mục tiêu tổng

Xây nền tảng kiến trúc mà mọi năng lực proactive, planning, và workflow đều phụ thuộc vào:
1. **Event Bus thống nhất** — Centralized event routing thay thế ad-hoc pub/sub
2. **Command Layer** — Tách biệt giữa AI intent và execution, có validation/permission/audit

---

## 📊 Đánh giá hiện trạng

> Cập nhật 2026-08-06 sau khi đối chiếu lại với codebase thật qua codebase-memory-mcp. Bản đánh giá gốc (2026-08-04) có vài điểm sai/lạc hậu — xem chi tiết bên dưới.

### ✅ Đã có (Phase 0)

| Component | Status | Notes |
|-----------|--------|-------|
| Redis Streams | ⚠️ Không phải pub/sub | `RedisStreamService` là **task queue** kiểu Celery (Generic[T], 1 consumer-group cố định/instance, XREADGROUP pull, không có `add_message()`/`publish()`). **Không tương thích trực tiếp** với mô hình EventBus multi-subscriber wildcard mà Milestone 1.2 cần — xem 02_EVENT_BUS.md |
| ToolRegistry | ✅ Ready | 15 tools đã đăng ký, có schema validation |
| ActionSnapshotStore | ✅ Ready | Redis (24h) + PG (90d) cho undo/revert |
| Structured Logging | ✅ Ready | `get_logger()` + JSONL tool logs |
| Test Framework | ✅ pytest đã cài | `pytest==8.3.5` + `pytest-asyncio==0.25.3` đã có trong venv. Cái **thực sự thiếu** là scaffolding: chưa có `backend/tests/unit/`, `integration/`, `e2e/`, `load/`, và **không có `conftest.py`** định nghĩa fixture `async_db`, `test_user`, `test_workspace`, `sync_db` mà mọi test mẫu trong 8 milestone đều giả định có sẵn |
| Workflow event pub/sub | ⚠️ Đã có, chưa dùng | `backend/app/services/redis/workflow_event_publisher.py` publish qua Redis Pub/Sub channel `cortex:workflow:events` với đúng naming `note.created`/`schedule.created`/... nhưng **chưa nơi nào gọi nó** (in_degree=0). `workflow_service/app/triggers/internal_event_listener.py` (dự án **Workflow Runtime** riêng — xem `workflow_feature/`, ~2-3 tháng, Temporal, port 8001) đã lắng nghe sẵn kênh này để trigger workflow. **Quyết định:** EventBus mới sẽ **thay thế hoàn toàn** kênh cũ này — Milestone 1.2/1.3 phải viết lại `internal_event_listener.py` để tiêu thụ EventBus mới thay vì Pub/Sub cũ (xem task mới trong 02_EVENT_BUS.md) |
| Note update flow | ⚠️ Có Proposal/approval, plan chưa tính tới | `update_note_handler` thật không update trực tiếp — nó gọi `ProposalService.create_proposal()`, trả `proposal_id`, chờ người dùng duyệt. Milestone 1.4-1.6 (`NoteUpdateArgs`, `note.update` command, default-revert) thiết kế theo mô hình "update ngay + revert bằng snapshot", **không khớp** luồng thật. Xem điều chỉnh trong 04/05/06 |

### 🔨 Cần xây dựng

| Component | Milestone | Effort |
|-----------|-----------|--------|
| Event Schema | 1.1 ✅ Done (2026-08-06) | 2-3 ngày |
| Event Bus | 1.2 ✅ Done (2026-08-06, gồm cả migrate workflow_service listener) | 4-5 ngày |
| Core Event Emission | 1.3 | 3-4 ngày |
| Command Schema | 1.4 | 2 ngày |
| Command Registry | 1.5 | 5-6 ngày |
| Tool→Command Migration | 1.6 | 4-5 ngày |
| Context Service | 1.7 | 3-4 ngày |
| Intent Detection | 1.8 | 3-4 ngày |
| Event Vocabulary (🆕 bổ sung) | 1.9 ✅ Done (2026-08-06) | 1-2 ngày |
| Durable Event Consumer (🆕 bổ sung) | 1.10 ✅ Done (2026-08-06) | 2-3 ngày |

**Total Effort:** ~29-40 ngày (4-6 tuần với 1 developer). 1.9/1.10 không có trong bản kế hoạch gốc — bổ sung sau khi nhận ra event vocabulary lệch giữa 2 service và EventBus.subscribe() chưa hoạt động xuyên process (xem 09_EVENT_VOCABULARY.md, 10_DURABLE_CONSUMER.md).

---

## 🗺️ Roadmap

```
Week 1-2: Event Infrastructure
  ├─ 1.1: Event Schema Design (2-3d)
  ├─ 1.2: Event Bus Implementation (4-5d)
  └─ 1.3: Core Event Definitions (3-4d)

Week 3-4: Command Infrastructure
  ├─ 1.4: Command Schema Design (2d)
  ├─ 1.5: Command Registry (5-6d)
  └─ 1.6: Tool→Command Migration (4-5d)

Week 5-6: Context & Intent
  ├─ 1.7: Context Service (3-4d)
  └─ 1.8: Intent Detection Layer (3-4d)

Bổ sung sau Phase 1 gốc (điều kiện tiên quyết cho Phase 2/4):
  ├─ 1.9: Event Vocabulary Thống Nhất (1-2d)
  └─ 1.10: Durable Event Consumer ở Backend (2-3d)
```

---

## 🎯 Definition of Done

Phase 1 hoàn thành khi:

- [x] **Event Bus hoạt động:** 10 event types thật (+ 2 reserved) được phát ra từ các service operations
- [x] **Command Registry hoạt động:** 4 mutating tools chạy qua CommandRegistry thay vì DB trực tiếp
- [x] **AI không gọi DB trực tiếp:** Mọi mutation đi qua Command với validation/permission/audit
- [x] **Context được tập trung:** ContextService thay thế logic build context rải rác (additive, không thay `_inject_context_into_text`)
- [x] **Intent detection L1:** Rule-based classifier cho các intent rõ ràng (EN+VI, note/schedule/search/revert/help)
- [x] **Event vocabulary thống nhất:** 1 nguồn sự thật (backend), dùng chung cho workflow_service + Trigger Catalog API, không cần restart khi thêm event type (1.9)
- [x] **EventBus subscribe() hoạt động xuyên process:** durable XREADGROUP consumer + XAUTOCLAIM reclaim khi process chết giữa chừng (1.10)
- [x] **Tests pass:** 284 tests (unit+integration) ở backend, 57 tests ở workflow_service — tất cả pass
- [x] **No regression:** Existing chat flow hoạt động không đổi (verified bằng test suite hiện có)

---

## 📁 Files Structure

```
tasks/phase1/
├── 00_OVERVIEW.md              # This file
├── 01_EVENT_SCHEMA.md          # Milestone 1.1 plan
├── 02_EVENT_BUS.md             # Milestone 1.2 plan
├── 03_CORE_EVENTS.md           # Milestone 1.3 plan
├── 04_COMMAND_SCHEMA.md        # Milestone 1.4 plan
├── 05_COMMAND_REGISTRY.md      # Milestone 1.5 plan
├── 06_TOOL_MIGRATION.md        # Milestone 1.6 plan
├── 07_CONTEXT_SERVICE.md       # Milestone 1.7 plan
├── 08_INTENT_DETECTION.md      # Milestone 1.8 plan
├── 09_EVENT_VOCABULARY.md      # Milestone 1.9 plan (🆕 bổ sung)
└── 10_DURABLE_CONSUMER.md      # Milestone 1.10 plan (🆕 bổ sung)
```

---

## 🔗 Dependencies

### Milestone Dependencies

```
1.1 (Event Schema)
  ↓
1.2 (Event Bus) ──────┐
  ↓                   │
1.3 (Core Events)     │
                      │
1.4 (Command Schema)  │
  ↓                   │
1.5 (Command Registry)│
  ↓                   │
1.6 (Tool Migration)  │
                      ↓
1.7 (Context Service) ← Can start in parallel
  ↓
1.8 (Intent Detection)
```

### Critical Path

**1.1 → 1.2 → 1.3** (Event infrastructure, ~10 ngày)  
**1.4 → 1.5 → 1.6** (Command infrastructure, ~12 ngày)  
**1.7 → 1.8** (Context & Intent, ~7 ngày)

Milestone 1.7 có thể bắt đầu song song với 1.4-1.6 nếu có nhiều developers.

---

## 🚨 Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| Event emission breaks services | High | Low | Event publish wrapped trong try-except, không throw |
| Command migration breaks tools | High | Medium | Regression tests từ Phase 0, migrate từng tool một |
| Performance degradation từ event overhead | Medium | Low | Load test 1000 events < 100ms, async publishing |
| Existing tests fail sau migration | Medium | Medium | Run full test suite sau mỗi milestone |
| **EventBus không build được trên `RedisStreamService` như dự tính** (class là task-queue 1-consumer-group, không phải multi-subscriber pub/sub) | High | High (đã xác nhận) | Thiết kế lại transport ở 1.2 dùng Redis Streams thô (multiple consumer groups) hoặc XADD/pub-sub riêng cho EventBus, không cố "extend" `RedisStreamService` |
| Rewrite `workflow_service/app/triggers/internal_event_listener.py` phá vỡ Workflow Runtime (dự án riêng, đã có code chạy) | High | Medium | Cần review kỹ trước khi đổi transport; viết test end-to-end cho việc trigger workflow từ EventBus mới trước khi xoá code cũ; phối hợp với whoever đang maintain `workflow_service/` |
| `note.update` command bỏ qua Proposal/approval flow đang chạy thật, khiến AI sửa note không qua duyệt | High | High (đã xác nhận trong plan gốc) | Thiết kế lại `note.update` command để tạo Proposal thay vì apply trực tiếp — xem 04/06 |
| Permission check của CommandRegistry là no-op cho domain Schedule (không có `workspace_id`) | Medium | High (đã xác nhận) | Thêm nhánh permission riêng cho Schedule (ownership-based) thay vì dùng chung `WorkspacePermission` |

---

## 📚 References

- **Product Requirements:** `/docs/CORTEX_ANALYSIS_REPORT.md` Section 17 (Action 2: Event Bus)
- **Current Architecture:** Codebase analysis completed 2026-08-04
- **Redis Streams Docs:** Existing implementation in `backend/app/services/redis/redis_stream_service.py`
- **Tool Registry:** `backend/app/ai/agents/tool_registry.py`

---

## 🚀 Next Steps

1. **Review toàn bộ plan** (8 milestone files, đã cập nhật 2026-08-06)
2. **Setup test scaffolding:** pytest đã cài sẵn — cần tạo `backend/tests/{unit,integration,e2e,load}/` + `conftest.py` với fixture `async_db`, `sync_db`, `test_user`, `test_workspace`
3. **Chốt thiết kế transport cho EventBus** (1.2) trước khi code — không dùng `RedisStreamService` nguyên bản, xem phần "Cần xây dựng" đã sửa
4. **Create branch:** `feature/phase1-event-bus-commands`
5. **Start với Milestone 1.1:** Event Schema Design (quickest win, không đổi)

---

**Last Updated:** 2026-08-06 (revised sau khi đối chiếu codebase — xem lịch sử git cho bản gốc 2026-08-04)
**Plan Status:** ✅ Hoàn thành — Phase 1 đã triển khai đầy đủ 8/8 milestone, có test thật (unit + integration chạy trên Postgres/Redis dev thật), tích hợp vào pipeline chat thật. Tiếp theo: Phase 2 - Goals & Commitments.
