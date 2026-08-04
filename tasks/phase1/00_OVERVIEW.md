# Phase 1: Intent & Event Bus — Overview

**Timeline:** 4-6 tuần (Week 1-6)  
**Status:** Ready to Start  
**Prerequisites:** Phase 0 completed (structured logging, Redis Streams, ToolRegistry exists)

---

## 🎯 Mục tiêu tổng

Xây nền tảng kiến trúc mà mọi năng lực proactive, planning, và workflow đều phụ thuộc vào:
1. **Event Bus thống nhất** — Centralized event routing thay thế ad-hoc pub/sub
2. **Command Layer** — Tách biệt giữa AI intent và execution, có validation/permission/audit

---

## 📊 Đánh giá hiện trạng

### ✅ Đã có (Phase 0)

| Component | Status | Notes |
|-----------|--------|-------|
| Redis Streams | ✅ Ready | `RedisStreamService` với publish/subscribe/consumer groups |
| ToolRegistry | ✅ Ready | 15 tools đã đăng ký, có schema validation |
| ActionSnapshotStore | ✅ Ready | Redis (24h) + PG (90d) cho undo/revert |
| Structured Logging | ✅ Ready | `get_logger()` + JSONL tool logs |
| Test Framework | ⚠️ Setup needed | Tests exist nhưng pytest chưa được install |

### 🔨 Cần xây dựng

| Component | Milestone | Effort |
|-----------|-----------|--------|
| Event Schema | 1.1 | 2-3 ngày |
| Event Bus | 1.2 | 4-5 ngày |
| Core Event Emission | 1.3 | 3-4 ngày |
| Command Schema | 1.4 | 2 ngày |
| Command Registry | 1.5 | 5-6 ngày |
| Tool→Command Migration | 1.6 | 4-5 ngày |
| Context Service | 1.7 | 3-4 ngày |
| Intent Detection | 1.8 | 3-4 ngày |

**Total Effort:** ~26-35 ngày (4-6 tuần với 1 developer)

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
```

---

## 🎯 Definition of Done

Phase 1 hoàn thành khi:

- [ ] **Event Bus hoạt động:** 8 event types được phát ra từ các service operations
- [ ] **Command Registry hoạt động:** 4 mutating tools chạy qua CommandRegistry thay vì DB trực tiếp
- [ ] **AI không gọi DB trực tiếp:** Mọi mutation đi qua Command với validation/permission/audit
- [ ] **Context được tập trung:** ContextService thay thế logic build context rải rác
- [ ] **Intent detection L1:** Rule-based classifier cho các intent rõ ràng (reminder, note, schedule)
- [ ] **Tests pass:** Integration tests cho event emission, command execution, context building
- [ ] **No regression:** Existing chat flow hoạt động không đổi (verified bằng test suite Phase 0)

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
└── 08_INTENT_DETECTION.md      # Milestone 1.8 plan
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

---

## 📚 References

- **Product Requirements:** `/docs/CORTEX_ANALYSIS_REPORT.md` Section 17 (Action 2: Event Bus)
- **Current Architecture:** Codebase analysis completed 2026-08-04
- **Redis Streams Docs:** Existing implementation in `backend/app/services/redis/redis_stream_service.py`
- **Tool Registry:** `backend/app/ai/agents/tool_registry.py`

---

## 🚀 Next Steps

1. **Review toàn bộ plan** (8 milestone files)
2. **Setup test environment:** Install pytest + dependencies
3. **Create branch:** `feature/phase1-event-bus-commands`
4. **Start với Milestone 1.1:** Event Schema Design (quickest win)

---

**Last Updated:** 2026-08-04  
**Plan Status:** Ready for Implementation
