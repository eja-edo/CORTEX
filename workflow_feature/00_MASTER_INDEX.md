# CORTEX — WORKFLOW RUNTIME: MASTER INDEX

> **Dành cho**: Solo developer, \~2-3 tháng\
****Mục tiêu**: Thêm Workflow Runtime vào Cortex như một module mới, chạy song song với codebase hiện tại\
****Execution Engine**: Temporal (self-hosted)\
****Frontend**: React Flow (visual drag-and-drop builder)\
****Trigger scope**: Nội bộ (Cortex events) + External (webhook)

---

## Tổng quan kiến trúc

```
Cortex (existing)
├── backend/app/          ← Không thay đổi
├── frontend/             ← Thêm /workflows route
└── infrastructure/
    └── docker-compose.yml ← Thêm Temporal + workflow_service

Workflow Runtime (new)
├── workflow_service/     ← FastAPI service mới (port 8001)
│   ├── api/              ← REST API cho workflow CRUD + trigger
│   ├── temporal/         ← Workflow definitions + Activities
│   ├── triggers/         ← Trigger engine (internal + webhook)
│   └── actions/          ← Action plugins
└── frontend/src/pages/workflows/  ← React Flow builder
```

---

## Danh sách các file kế hoạch

| File | Phase | Nội dung | Thời gian |
| --- | --- | --- | --- |
| `01_PHASE1_FOUNDATION.md` | Phase 1 | Temporal setup + DB schema + service skeleton | Tuần 1–2 |
| `02_PHASE2_BACKEND_CORE.md` | Phase 2 | Workflow CRUD API + Trigger Engine + Action Engine | Tuần 3–4 |
| `03_PHASE3_TEMPORAL_INTEGRATION.md` | Phase 3 | Temporal Workers + Workflow Definitions + State Management | Tuần 5–6 |
| `04_PHASE4_FRONTEND_BUILDER.md` | Phase 4 | React Flow visual builder + Node palette + Canvas | Tuần 7–8 |
| `05_PHASE5_BUILTIN_TRIGGERS_ACTIONS.md` | Phase 5 | Built-in triggers/actions tích hợp với Cortex | Tuần 9–10 |
| `06_PHASE6_POLISH_TESTING.md` | Phase 6 | Testing + monitoring + UI polish + demo scenarios | Tuần 11–12 |
| `07_ARCHITECTURE_DECISIONS.md` | Reference | Các quyết định kiến trúc + lý do chọn + trade-offs | — |
| `08_DATA_SCHEMAS.md` | Reference | Toàn bộ DB schema + Temporal workflow schema | — |
| `09_API_CONTRACTS.md` | Reference | API endpoints đầy đủ với request/response examples | — |
| `10_INTEGRATION_GUIDE.md` | Reference | Cách kết nối workflow_service với Cortex backend hiện tại | — |

---

## Dependency map giữa các phase

```
Phase 1 (Foundation)
    └── Phase 2 (Backend Core)
            ├── Phase 3 (Temporal Integration)
            │       └── Phase 5 (Built-in Triggers/Actions)
            └── Phase 4 (Frontend Builder)
                        └── Phase 5 (Built-in Triggers/Actions)
                                    └── Phase 6 (Polish & Testing)
```

**Phase 1 và 4 có thể bắt đầu song song** sau khi hoàn thành Phase 1.

---

## Định nghĩa "Done" cho toàn bộ project

Workflow Runtime được coi là **hoàn thành** khi:

- [ ] User có thể tạo một workflow bằng drag-and-drop trên browser

- [ ] Workflow trigger được khi một Note mới được tạo trong Cortex

- [ ] Workflow trigger được khi nhận webhook từ Google Calendar

- [ ] Workflow chạy action: tạo Note, gửi notification, gọi AI

- [ ] Workflow có thể bị pause và resume (Temporal durability)

- [ ] User có thể xem lịch sử execution của từng workflow instance

- [ ] Toàn bộ stack chạy được bằng `docker-compose up`

---

## Glossary (thuật ngữ sử dụng xuyên suốt)

| Thuật ngữ | Định nghĩa |
| --- | --- |
| **Workflow Definition** | Template mô tả một workflow (JSON, lưu trong DB) |
| **Workflow Instance** | Một lần thực thi cụ thể của một Workflow Definition |
| **Trigger** | Sự kiện khởi động một Workflow Instance |
| **Action** | Một bước thực thi trong workflow (tạo note, gửi notification...) |
| **Node** | Một block trong React Flow builder (visual representation của Trigger/Action) |
| **Edge** | Kết nối giữa các Node trong React Flow |
| **Temporal Worker** | Process chạy Workflow Definitions và Activities |
| **Activity** | Một unit of work trong Temporal (tương ứng với một Action) |
| **Task Queue** | Hàng đợi Temporal Worker lắng nghe |
| **Execution History** | Log đầy đủ của một Workflow Instance trong Temporal |
