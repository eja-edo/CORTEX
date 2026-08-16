# Cortex — Kế Hoạch Triển Khai (Bản 3)

> **Bản 3 không phải là lập kế hoạch lại từ đầu.** Nó là Bản 2 được **sửa cho khớp thực tế** sau khi schema thay đổi lớn: Goal bị xoá, Commitment gộp vào Task. Bản 2 vẫn còn giá trị cho phần lập luận thiết kế (`docs/planning`); Bản 3 là nguồn sự thật về **cái gì đang tồn tại và làm gì tiếp theo**.
>
> Trạng thái dưới đây được **kiểm chứng bằng code + DB thật** ngày 2026-08-13, không phải suy từ tài liệu.

**Quy ước giữ nguyên từ Bản 2:** số hạng mục không đổi để không phá tham chiếu. Hạng mục chết được đánh `[KHAI TỬ]` kèm lý do, không xoá.

---

# I. Thay Đổi Nền Tảng So Với Bản 2

Bản 2 xây quanh **ba entity**: Goal, Task, Commitment. Thực tế hiện tại chỉ còn **một**.

| Entity | Số phận | Migration |
|---|---|---|
| `goals` | **Đã xoá** | `b0123456789x` |
| `commitments` | **Gộp vào `tasks`** | `a0123456789w` |
| `tasks` | Còn lại, hấp thụ cả hai | `t0123456789p` + 6 migration bổ sung |

`tasks` hiện mang: `priority`, `description`, `parent_task_id` (subtask thay cho milestone), `status` gồm `pending_confirm`/`rejected` (thay cho vòng đời commitment candidate), `source_conversation_id`/`source_message_id` (truy vết ngược về hội thoại), `completed_at`.

**Hệ quả dây chuyền — đây là phần Bản 2 không lường được:**

1. *"Tiến độ mục tiêu"* không còn đối tượng để tính.
2. *"Ai đang chờ tôi phản hồi?"* — câu hỏi lõi của sản phẩm — **mất hoàn toàn**, vì nó phụ thuộc `commitment.direction` (`i_owe` / `owed_to_me`). Task không có khái niệm "người kia".
3. Risk detection mất đầu vào chính (goal progress vs. thời gian còn lại).

Điểm 2 là **mất mát sản phẩm thật, không phải mất mát kỹ thuật**. Xem mục V.

---

# II. Nguyên Tắc — Giữ Nguyên Toàn Bộ

Bốn nguyên tắc P1–P4 và ba ranh giới của Bản 2 **vẫn đúng nguyên vẹn** và vẫn ràng buộc mọi thiết kế. Không sửa. Tóm tắt để tiện tra:

- **P1** — Mọi thứ làm phiền user phải qua **một cổng duy nhất** (Attention Gate). Không component nào ghi thẳng `notifications`.
- **P2** — Detection ≠ Delivery. Workflow phát hiện; Gate quyết định nói hay không.
- **P3** — Hành vi hệ thống **tham chiếu, không copy** vào từng workspace.
- **P4** — Thay đổi trạng thái phải trở thành event (State Evaluator), để chỉ cần một cơ chế trigger.
- **Ranh giới #2** — Trang cấu hình là nơi **tắt**, không phải nơi bật. Phép thử: *user không bao giờ mở trang đó, Cortex có còn hữu ích không?* Phải là **CÓ**.

> ⚠️ **Hiện tại hệ thống đang TRƯỢT phép thử ranh giới #2.** Xem mục IV.

---

# III. Trạng Thái Thật (verified 2026-08-13)

## ✅ Đã xong và chạy được

| Mã | Hạng mục | Bằng chứng |
|---|---|---|
| 1.1–1.10 | Event Bus, vocabulary, durable consumer, Command Registry, Context, Intent | 18 event type trong `app/events/vocabulary.py`; `EventBus.start_consumer()` |
| 2.3 | Task extraction từ hội thoại (L0 signal + idle flush) | `task_extraction.py`, `task_signals.py`, `task_flush_worker.py` |
| 2.5 | Task model + API + state machine | `models.py:768`, `api/tasks.py` |
| 2.6 | Calendar hợp nhất Task + Schedule | `calendar_items.py` — read-only merge, không ghi projection |
| 2.7 | Màn "Hôm nay" | `today.py`, `TodayChecklist.tsx`, `TasksPage.tsx` |
| 2.9 | Attention Log | `attention_log.py` — dedup theo `(item_id, reason_key)`, ghi cả `silent` |
| 3.1 | Daily ranking deterministic | `TodayService._rank_actions` / `_reason_for` |
| 3.2 | AI Planner → Plan Proposals | `plan_proposal_service.py`, tool `propose_plan` |
| 4.1 | Event Bus → Workflow bridge | `internal_event_listener.py`, consumer group + xack |
| 4.3 | `action.request_attention` thay `send_notification` | `workflow_service/app/actions/builtin/request_attention.py` |
| **4.6 (A1)** | **State Evaluator — 6 predicate, tất cả deterministic, gộp qua Gate** | `state_evaluator.py` (`task.overdue`, `task.due_soon`, `task.stale`, `task.blocked_cascade`, `schedule.starts_soon`, `day.review`) + `notification_subscribers.py` + test `tests/integration/test_state_evaluator.py` (13/13 pass) |
| **A3** | **Rà xung đột workflow user ↔ system** | `workflow_service/app/services/workflow_conflicts.py`, `notification_subscribers.py::DIRECT_DELIVERY_HANDLERS`, `GET /workflows/{id}/conflicts`, 14 test |
| **6.1** | **Attention Gate — đủ 5 bước, 0 token AI** | `attention_gate.py`, `attention_bundle.py`, `attention_bundle_worker.py` |
| **6.2** | **Quiet hours (backend + UI)** | `user_preferences.py`, `availability.py`, `SettingsPanel.tsx`'s Notifications card |
| **4.5 (redesigned)** | **Bật/tắt từng loại nhắc theo reason_key — thay cho "system workflow toggle"** | `disabled_reason_keys` (migration `m1234567890n`), `GET/PUT /preferences/reasons`, `attention_gate.py`'s `_decide_level_async/_sync` short-circuit, `SettingsPanel.tsx` |
| **6.9** | **Feedback Loop — auto-downgrade theo tỷ lệ dismiss (M1–M4 đủ cả)** | `app/services/feedback_loop.py` (`apply_downgrade`, ladder ACT→ASK→RECOMMEND→INFORM→SILENT, mỗi `FEEDBACK_LOOP_DISMISS_THRESHOLD` lần dismiss hạ 1 bậc), wired vào Gate, `dismiss_count`/`effective_level` hiện trong `/preferences/reasons` (M2) + `SettingsPanel.tsx`, 16 test (6 unit + 5 gate integration + 1 API) |
| **4.2** | **Trigger Catalog (M1–M4 đủ cả)** | `EventVocabularyEntry.label_vi` (`vocabulary.py`) → `event_vocabulary.json` → `GET /api/v1/actions/triggers/catalog` (workflow_service) → `InternalEventTriggerConfig.tsx` fetch động, xoá `EVENT_TYPES` hard-code cũ. Kèm cảnh báo `has_direct_backend_delivery` (A3) ngay ở bước chọn trigger, không đợi tới Activate. 8 test mới (workflow_service) |

**Gate hiện chạy đủ 5 bước, toàn bộ deterministic:**

```
candidate → 1. importance (catalog + escalate theo priority/overdue)
          → 2. đã biết chưa (attention_log dedup)
          → 3. có nên im không (đang họp? quiet hours?)
          → 4. gộp với gì (attention_bundle_queue)
          → 5. lúc nào (AttentionBundleWorker, flush khi user rảnh)
```

## 🟡 Làm dở — có code nhưng chưa đạt mục tiêu

| Mã | Còn thiếu gì |
|---|---|
| 2.3 M1 | ✅ **Đo được lần đầu (2026-08-16).** `tests/data/task_extraction_dataset.json` — 65 item tự viết (VI/EN/mixed, chủ đề kế hoạch học tập/công việc theo ngày), chạy `evaluate_task_extraction.py` qua model thật: precision **1.000** (≥0.9, PASS), recall **0.967** (1 FN: câu "deploy" bị bỏ sót). ⚠️ Dataset tự viết trong một phiên, không phải hội thoại thật đã log — coi là baseline khởi động, nên bổ sung thêm case thật trước khi dùng số này làm căn cứ nới prompt ở 6.7 |
| ~~3.1 M4~~ | ✅ Xong 2026-08-16 — tool `get_today` (`app/ai/tools/get_today.py`) gọi thẳng `TodayService.get_today`, đăng ký trong `tools/__init__.py`. Prompt hệ thống (`assistant_system.md`'s TOOL USAGE RULES) chỉ đạo agent gọi tool này thay vì tự suy luận khi user hỏi "hôm nay làm gì"/"việc gì gấp". 2 integration test (`test_get_today_tool.py`) |
| ~~3.3~~ | ✅ Xong 2026-08-16 — `find_free_slots(session, user_id, start, end, min_duration)` trong `availability.py`, dùng chung định nghĩa "busy" với `is_user_busy` (`_schedule_intervals_stmt`). 9 unit test cho phần merge/invert (`_gaps`, thuần không cần DB) + 5 integration test qua DB thật. **Chưa nối vào API/UI màn Hôm nay** — hàm đã sẵn sàng để gọi, việc nối dây là bước riêng |
| 4.0 | Hạ tầng đủ (bảng override, copy-on-write, lọc SQL) nhưng **DB có 0 system workflow**. M4 (seed 5 workflow) **không còn áp dụng cho 6 predicate của A1** — xem mục A2 đã đổi hướng bên dưới. Hạ tầng này vẫn chờ dùng cho workflow thật sự cần multi-step/multi-event, chưa có nhu cầu cụ thể |

## ⬜ Chưa bắt đầu

3.4 Dynamic re-planning · 3.5 Next-action endpoint · 6.4 AI proactive reasoning · 6.5 Smart reminders · 6.6 Meeting intelligence · **toàn bộ Phase 5** (integrations) · **toàn bộ Phase 7** (AI cost)

---

# IV. Vấn Đề Lớn Nhất Hiện Nay

> **Gate đã tinh vi, nhưng gần như không có gì để gate.** *(Đúng tại thời điểm viết bản 3 — đã giải quyết, xem cập nhật dưới.)*
>
> **Cập nhật 2026-08-14 (A1 → A3 → 4.5 redesigned):** Cả Detection lẫn phần "cấu hình được" của Delivery giờ đã có, nhưng **không đi qua workflow_service** như bản gốc mục này giả định — quyết định chốt cùng ngày, xem A2's ghi chú "ĐỔI HƯỚNG".

```
DETECTION — có gì đáng nói          DELIVERY — nói thế nào + tắt được không
────────────────────────────        ──────────────────────────────────────
6 predicate (A1, xong)               importance      ✅
  task.overdue                       dedup           ✅
  task.due_soon                      busy check      ✅
  task.stale                         quiet hours     ✅ (+UI, 6.2 M3 xong)
  task.blocked_cascade               bundling        ✅
  schedule.starts_soon               timing          ✅
  day.review                         per-reason toggle ✅ (4.5 redesigned)
  → notification_subscribers.py → Gate, không qua workflow_service

system workflows trong DB: 0 ← vẫn vậy, và không còn là vấn đề cần giải —
                                 xem A2's ghi chú đổi hướng
```

Với một user mới hoàn toàn, Cortex **chủ động nói** khi 1 trong 6 điều kiện trên đúng, và user **tắt được từng loại riêng lẻ** qua `/settings` → Notifications — cả hai vế của ranh giới #2 (mặc định hữu ích + trang cấu hình chỉ để tắt) đã đạt, không cần system workflow.

**Vì sao không đi qua workflow_service (A2 gốc):** `find_trigger_conflicts` (A3) cho thấy seed workflow nghe cùng 6 event mà `notification_subscribers.py` đã xử lý trực tiếp sẽ bắn trùng thông báo — đúng lỗi A3 sinh ra để bắt. Thay vì gỡ đường trực tiếp (đánh đổi độ tin cậy: reminder cốt lõi sẽ phụ thuộc workflow_service + Temporal thay vì chỉ backend + Redis như hiện tại), quyết định là **giữ đường trực tiếp, chuyển phần "tắt được" xuống một cột nhỏ ở backend** (`UserPreferences.disabled_reason_keys`) thay vì tái dùng hạ tầng system-workflow của 4.0.

**Kết luận định hướng:** Detection, Delivery-cấu-hình-được, tự-điều-chỉnh-theo-hành-vi (6.9), và Trigger Catalog (4.2) đều đã đóng (2026-08-14 → 2026-08-16). Việc còn lại không có thứ tự bắt buộc — xem mục VIII.

---

# V. Quyết Định Cần Chốt

### QĐ-1 — Có giữ tính năng *"ai đang chờ tôi phản hồi?"* không?

> **✅ ĐÃ CHỐT (2026-08-14): Phương án B.** Lấy lại tính năng qua 2 cột nullable trên `tasks` (`counterparty`, `direction`) + nới prompt, không dựng lại entity Commitment. Thực thi vẫn chờ đúng thứ tự nêu ở dưới — **B/2.3 M1 (dataset) giờ đã có baseline (2026-08-16, xem mục III), nhưng bước 2 (nới prompt) vẫn chưa làm** — dataset còn nhỏ/tự viết, nên trước khi nới prompt nên bổ sung thêm hội thoại thật, đây chỉ là quyết định hướng đi, không phải đã triển khai xong 6.7.

Đây là quyết định **sản phẩm**, không phải kỹ thuật, và nó chặn 6.7.

| Phương án | Chi phí | Hệ quả |
|---|---|---|
| **A. Khai tử** | 0 | Cortex chỉ quản việc *của tôi*. Đơn giản, nhưng mất một trong bốn câu hỏi lõi ở mục 3 Product Requirement |
| **B. Phục hồi tối thiểu trên Task** (khuyến nghị) | 2 cột nullable + **sửa prompt** — xem bên dưới | Lấy lại tính năng mà **không** dựng lại entity Commitment |
| **C. Dựng lại Commitment** | Cao | Quay lại đúng thứ vừa gộp đi. Không khuyến nghị |

**Khuyến nghị: B**, nhưng cần nói rõ chi phí thật (đã kiểm chứng trong code, không phải ước lượng):

*Phần đã có sẵn:* prompt **đã trích xuất `counterparty`** (`task_extraction_prompt.py:70`). Hiện nó không bị vứt hẳn mà bị **nhét vào title** dưới dạng chuỗi hiển thị — `"nộp proposal (John)"` (`task_extraction.py:207`) — nên không query được. Thêm cột là lấy lại thứ đã có.

*Phần chưa có — đây là chi phí thật:* prompt hiện **cố tình từ chối** lời hứa của người khác. Điều kiện 1 ghi rõ *"A statement about what someone else will do ('John will send the API spec') is not the user's own task."* Nghĩa là `direction` hiện **luôn** là `i_owe`; chiều `owed_to_me` — chính là chiều trả lời *"ai đang chờ tôi"* — **chưa bao giờ được trích xuất**.

Vậy phương án B gồm 3 phần, không phải 1:
1. 2 cột nullable trên `tasks`: `counterparty`, `direction`.
2. **Sửa prompt + validator** để chấp nhận câu ngôi thứ ba (nới điều kiện 1, giữ nguyên điều kiện 2 về tính tường minh).
3. Đo lại precision sau khi nới — **bắt buộc**, vì nới điều kiện là hướng làm tăng false positive, đúng thứ mục 2.3 đặt ngưỡng ≥0.9 để chặn.

→ Phụ thuộc **B/2.3 M1 (dataset)**: không có dataset thì không được nới prompt, vì sẽ không biết precision tụt bao nhiêu.

---

# VI. Roadmap Mới — Theo Thứ Tự Ưu Tiên

Không xếp theo số phase nữa, vì thứ tự phase cũ không còn phản ánh đúng critical path.

## KHỐI A — Làm cho Detection có nội dung *(ưu tiên cao nhất, 0 token AI)*

### A1 · Mở rộng State Evaluator (4.6 tiếp) — ✅ Đã xong (2026-08-14)

- **Mục tiêu:** Từ 1 lên 5–6 predicate trạng thái, tất cả deterministic, dùng dữ liệu đã có.
- **Predicate đề xuất:**

| Event | Điều kiện | Vì sao đáng nói |
|---|---|---|
| `task.due_soon` | hạn trong ≤N giờ, chưa `in_progress` | Ngăn chặn tốt hơn nhắc sau khi đã trễ |
| `task.stale` | tạo >N ngày, chưa động, không hạn | Việc bị bỏ quên — không có gì khác phát hiện được |
| `task.blocked_cascade` | task cha trễ **và** còn ≥1 subtask chưa xong | **Thay thế cho "chặn goal" đã mất** — dùng `parent_task_id` |
| `schedule.starts_soon` | event bắt đầu trong 15–30 phút | Nền cho 6.6, và cho phép Gate im lặng *trước* khi họp |
| `day.review` | cuối ngày, còn việc chưa xong | Mốc tự nhiên để gộp (bước 5 của Gate) |

- **Milestones — cả 4 đã xong:**
  - ✅ M1: Mỗi predicate có payload schema (`app/events/payloads.py`) + khai báo trong `vocabulary.py`.
  - ✅ M2: Idempotency qua `StateEvaluatorFlag`, `flag_key` mở rộng cho từng predicate (`_diff_flags`, dùng chung cho cả 6).
  - ✅ M3: `reason_key` tương ứng đăng ký trong `attention_reason_catalog.py` với baseline level (`task.due_soon`/`task.stale`/`schedule.starts_soon`/`day.review` → INFORM; `task.blocked_cascade` → RECOMMEND, cùng mức `task.overdue`).
  - ✅ M4: `tests/integration/test_state_evaluator.py`, 13/13 pass — mỗi predicate có test lifecycle (phát 1 lần, không lặp, clear khi hết điều kiện, phát lại ở lần chuyển trạng thái tiếp theo).
  - Ghi chú kỹ thuật: `day.review` cần một `item_type` mới (`AttentionItemType.USER`, migration `l1234567890m`) vì nó là digest theo *user*, không theo một task/schedule cụ thể — xem docstring `AttentionItemType.USER`. Mỗi predicate cũng có handler riêng trong `notification_subscribers.py`, subscribe ở `app/__init__.py`, nên đã đi hết đường Detection → Gate → (có thể) Notification, không chỉ dừng ở publish event.
  - Chưa làm trong A1 (đúng như thiết kế — đây là việc của A2/4.5): **0 system workflow** vẫn nghe các event này qua workflow_service, nhưng cả 6 event đã được `notification_subscribers.py` gọi thẳng tới Gate (`item_type`/`item_id`/`reason_key` đầy đủ) độc lập với workflow_service — nên user *đã* nhận được nhắc cho cả 6 predicate ngay bây giờ, chỉ là chưa qua đường tắt/bật được. Hệ quả: cả 6 event giờ **đã nằm trong `event_vocabulary.json`** mà workflow_service đọc — xem cảnh báo ở A2 bên dưới trước khi seed workflow nghe cùng các event này.

### A2 · Seed bộ system workflow mặc định (4.0 M4) — ⚠️ ĐỔI HƯỚNG (2026-08-14), xem quyết định bên dưới

**Vì sao đổi hướng:** A2 nguyên bản giả định "system workflows trong DB: 0" là khoảng trống Delivery cần lấp. Nhưng A1 đã tự lấp khoảng trống đó theo cách khác — `notification_subscribers.py::DIRECT_DELIVERY_HANDLERS` gọi thẳng cả 6 event tới Gate, không qua workflow, và **phép thử ranh giới #2 đã đạt** (tài khoản mới, không mở trang workflow, vẫn nhận nhắc đúng lúc) *trước khi* A2 chạy. Seed 5 workflow nghe cùng 6 event đó với `action.request_attention` sẽ bị chính `find_trigger_conflicts` (A3) báo trùng — đây chính là câu hỏi được đặt ra và chốt ngày 2026-08-14, phương án được chọn (khuyến nghị): **giữ đường phát trực tiếp làm cơ chế delivery cố định cho 6 predicate này; không seed workflow trùng.**

- **Việc thay thế đã làm (không còn qua workflow_service):**
  - Cột `UserPreferences.disabled_reason_keys` (migration `m1234567890n`) — per-user, per-`reason_key`, mặc định bật hết (khớp ranh giới #2: nơi *tắt*, không phải nơi *bật*).
  - `attention_gate.py`'s `_decide_level_async`/`_decide_level_sync` — check đầu tiên, tắt hẳn (SILENT, không bundle) nếu user đã tắt reason đó, kể cả case URGENT lẽ ra sẽ escalate qua bận.
  - API: `GET /preferences/reasons` (liệt kê catalog + trạng thái bật/tắt), `PUT /preferences/reasons/{reason_key}`.
  - UI: `SettingsPanel.tsx`, thẻ "Notifications" — vừa là nơi làm nốt 6.2 M3 (quiet hours, trước đây thiếu UI), vừa là bản thay thế tối giản cho "trang audit + toggle" của 4.5 (xem 4.5 ở bảng ✅).
  - Test: 13 test mới trong `tests/integration/test_user_preferences.py`.
- **4.0's hạ tầng system-workflow (bảng override, copy-on-write) không bị bỏ** — vẫn đúng cho một workflow *thật sự* cần nghe nhiều event/nhiều bước mà bản chất không phải "một điều kiện → một nhắc". Chỉ là 6 predicate của A1 không phải trường hợp đó, nên không có gì để seed vào đó ngay bây giờ. M1–M4 dưới đây giữ nguyên làm tham khảo, không xoá, nhưng **không active** cho tới khi có nhu cầu cụ thể khác A1:
  - M1: Định nghĩa 5 workflow dưới dạng code/seed, không copy vào workspace.
  - M2: Workflow truyền đủ 3 trường định danh → Gate lọc được thật sự.
  - M3: Workspace mới tự động có đủ 5, không cần seed row.
  - M4: Nghiệm thu ranh giới #2 — **đã đạt bằng đường khác (xem trên)**, không còn là tiêu chí nghiệm thu treo cho A2.

### A3 · Rà xung đột workflow user ↔ system — ✅ Đã xong (2026-08-14)

- **Vì sao có mục này:** đã xảy ra thật. Workflow *"Nhắc việc quá hạn"* do user tạo trùng với subscriber backend → mỗi task quá hạn bắn 2 thông báo, một cái lỗi template. Đã tạm pause ngày 2026-08-13.
- **Milestones — cả 2 đã xong:**
  - ✅ M1 (phát hiện trùng, cùng `event` + cùng loại action):
    - Backend: `notification_subscribers.py` giờ có `DIRECT_DELIVERY_HANDLERS` — danh sách tường minh (event → handler) mà trước đây chỉ ngầm định qua từng lời gọi `event_bus.subscribe` rời rạc trong `app/__init__.py`. Export ra `event_vocabulary.json` dưới field `has_direct_backend_delivery` (script `generate_event_vocabulary.py`), kèm test khoá đồng bộ (`test_has_direct_backend_delivery_matches_the_handler_registry`).
    - workflow_service: `app/services/workflow_conflicts.py::find_trigger_conflicts` — so một workflow (event + tập action type) với (a) danh sách trên và (b) mọi workflow ACTIVE khác của cùng user hoặc system trên cùng event, cùng action type (loại trừ `action.wait` — không có output người dùng thấy để mà trùng).
  - ✅ M2 (cảnh báo trong UI, không chặn lưu):
    - `POST /workflows/{id}/activate` giờ trả thêm `warnings: WorkflowConflict[]` (không rỗng thì vẫn activate bình thường — cảnh báo, không chặn).
    - `GET /workflows/{id}/conflicts` mới — check được cả khi còn DRAFT, chưa cần activate.
    - Frontend: `WorkflowBuilder.tsx` hiện banner vàng liệt kê từng cảnh báo sau khi Activate/Run.
  - Test: `backend/tests/unit/test_event_vocabulary.py` (2 test mới) + `workflow_service/tests/test_workflow_conflicts.py` (14 test, dùng `task.overdue` thật — event có `has_direct_backend_delivery` — không phải event giả lập).
  - **Sự cố môi trường phát hiện khi làm việc này (đã sửa, ngoài phạm vi A3 nhưng chặn kiểm thử):** `WorkflowResponse.id`/`user_id`/... khai báo kiểu `UUID4` của Pydantic trong khi toàn bộ id trong hệ thống sinh bằng `uuid7()` — validation luôn ném lỗi với id thật, chỉ chưa lộ ra vì DB chưa từng có bảng `workflow.*` ở môi trường dev này. Đã đổi `UUID4` → `UUID` trong `workflow_service/app/schemas/workflow.py`.
  - Ranh giới đã ghi rõ trong docstring `workflow_conflicts.py`: chỉ xét *primary trigger* (`trigger_config`), chưa xét `WorkflowTrigger` phụ (multi-trigger); phạm vi user coi như "cùng user hoặc system" (không tính đủ workspace-member) — khớp với cách `internal_event_listener` đang xử lý ownership, không phải thiếu sót riêng của A3.

## KHỐI B — Đóng các mục đang dở dang *(rẻ, nên làm xen kẽ)*

| Mã | Việc | Ghi chú |
|---|---|---|
| ~~6.2 M3~~ | ~~UI Settings quiet hours~~ | ✅ Xong 2026-08-14 — `SettingsPanel.tsx`'s "Notifications" card, cùng lúc với reason toggle (4.5 redesigned) vì chung một trang/API |
| ~~2.3 M1~~ | ~~Dataset ≥50 hội thoại gán nhãn (Việt/Anh/trộn)~~ | ✅ Đo lần đầu 2026-08-16 — 65 item, precision 1.000/recall 0.967, xem bảng 🟡→✅ ở mục III. Dataset còn nhỏ và tự viết, nên vẫn cần bổ sung hội thoại thật trước khi dùng làm căn cứ nới prompt ở 6.7 |
| ~~3.3~~ | ~~`find_free_slots(user_id, start, end)`~~ | ✅ Xong 2026-08-16, xem bảng 🟡→✅ ở mục III. Còn lại: nối vào endpoint Hôm nay để hiện câu "bạn có N tiếng trống" — chưa làm, không thuộc milestone gốc |
| ~~3.1 M4~~ | ~~Tool cho agent gọi `TodayService`~~ | ✅ Xong 2026-08-16, xem bảng 🟡→✅ ở mục III |

## KHỐI C — Thiết kế lại phần đã chết

### 6.7 · Follow-up Detection *(viết lại — chờ QĐ-1)*
Nếu chọn **B**, theo đúng thứ tự (không đảo, xem lý do ở QĐ-1):
1. **2.3 M1 trước** — dựng dataset, đo precision hiện tại làm mốc.
2. Thêm `counterparty` + `direction` vào `tasks`; ngừng nhét `counterparty` vào title.
3. Nới prompt để nhận câu ngôi thứ ba; **đo lại precision, phải giữ ≥0.9**.
4. State Evaluator thêm predicate `task.awaiting_other` (`direction=owed_to_me`, quá hạn).
5. Gate soạn sẵn lời nhắc ở cấp **Ask Approval** — không bao giờ tự gửi cho người khác.

### 6.8 · Risk Detection *(viết lại — bỏ Goal)* — ✅ Xong, kèm 4.4 (2026-08-16)
Công thức mới không có goal progress. Đầu vào thay thế: `priority` × số ngày trễ × cascade subtask chưa xong (`parent_task_id`).

`app/services/risk_detection.py`: `compute_risk(priority, overdue_days, open_subtask_count)` — hàm thuần, `overdue_days ≤ 0` luôn trả 0 (chưa trễ thì chưa có rủi ro), subtask mở khuếch đại chứ không thay thế điểm gốc (`× (1 + open_subtask_count)`), priority chưa set vẫn có trọng số nền (không bao giờ nhân về 0). `list_at_risk_tasks(session, user_id, min_risk)` — query thật, tái dùng đúng cách tính cascade của `state_evaluator._evaluate_task_blocked_cascade`, trả danh sách đã sắp theo rủi ro giảm dần. 6 unit test (công thức thuần) + 5 integration test (query thật, DB riêng vì đọc toàn bộ task của user không lọc theo title — như `TodayService`).

**4.4 (biến công thức thành action) làm luôn cùng ngày, không tách riêng nữa:** predicate thứ 7 của State Evaluator, `task.at_risk` — mỗi task quá hạn được chấm điểm qua `compute_risk`, publish khi vượt `settings.STATE_EVALUATOR_RISK_THRESHOLD` (mặc định 6.0). Đây là **escalation chồng lên `task.overdue`**, không thay thế: một task có thể overdue mà không at_risk, nhưng at_risk luôn kèm overdue. `reason_key` mới `task.at_risk` đăng ký mức nền **ASK** (cao hơn RECOMMEND của overdue/blocked_cascade) trong `attention_reason_catalog.py`, đi thẳng tới Gate qua `notification_subscribers.py::DIRECT_DELIVERY_HANDLERS` — **không dùng workflow_service's action framework**, cùng lý do A2 đã chốt: predicate này là "một điều kiện → một nhắc" xác định, seed thành workflow riêng chỉ tạo nguy cơ trùng lặp mà A3 đã phát hiện. 3 test mới trong `test_state_evaluator.py` (publish khi vượt ngưỡng, im lặng khi dưới ngưỡng, tự xoá flag khi cascade rã).

## KHỐI D — Sau khi A + B xong

| Mã | Việc | Điều kiện tiên quyết |
|---|---|---|
| ~~6.9~~ | ~~Rule tự hạ cấp theo tỷ lệ dismiss~~ | ✅ Xong 2026-08-14 — `feedback_loop.py`, xem bảng ✅ ở mục III |
| 6.4 | AI reasoning cho case mơ hồ | **Chỉ khi** đo được tỷ lệ Gate "không quyết được" — xem mục VII |
| ~~4.2~~ | ~~Trigger Catalog (JSON, sinh từ vocabulary)~~ | ✅ Xong 2026-08-16 — xem bảng ✅ ở mục III |
| ~~4.5~~ | ~~Trang audit workflow + nút "đừng nhắc kiểu này nữa"~~ | ✅ Xong 2026-08-14, dạng khác với thiết kế gốc — xem A2 đã đổi hướng. Danh sách reason toggle trong `SettingsPanel.tsx` phủ đúng nhu cầu "đừng nhắc kiểu này nữa" mà không cần trang audit workflow riêng |
| ~~4.4~~ | ~~Chuyển công thức thành action~~ | ✅ Xong 2026-08-16 cùng 6.8, xem mục Khối C |
| 3.4/3.5 | Dynamic re-planning, next-action endpoint | Cần A1 (`task.blocked_cascade`) |

## KHỐI E — Chưa cần bàn

Phase 5 (Email/Telegram/GitHub), Phase 7 (AI cost). Cả hai đứng *trên* A–D nên xây sau vẫn rẻ. Phase 7 đặc biệt: kiến trúc hiện tại đã gần như không tốn token cho proactive, nên **đo lại baseline sau khối A** trước khi kết luận cần tối ưu gì.

---

# VII. Vị Trí Của AI Trong Bản 3

**Nguyên tắc:** *hạn chế AI vẫn hoàn thành mục tiêu; khi AI vào thì phải tạo đột phá lớn.*

Hiện trạng — AI đang ở đúng chỗ:

| Chỗ | Có AI? |
|---|---|
| Attention Gate (đủ 5 bước) | ❌ 0 token — logic + SQL thuần |
| State Evaluator | ❌ 0 token |
| Today ranking | ❌ 0 token |
| Task extraction | ✅ nhưng **ăn ké** lần gọi memory extraction đã có, không thêm call |
| Plan Proposals | ✅ đúng chỗ — biến mong muốn mơ hồ thành việc cụ thể |

**Khi nào AI được vào tiếp (6.4):** *chưa phải bây giờ.* Với đúng 1 predicate thì không tồn tại tình huống mơ hồ nào để AI xử lý. Sau khối A, đo tỷ lệ candidate mà bước 1–3 của Gate không đủ tự tin quyết. **Nếu tỷ lệ đó <30%, sửa logic deterministic; chỉ khi nó cao và dai dẳng thì AI mới có việc thật.** Đây là ngưỡng nghiệm thu, không phải khuyến nghị.

---

# VIII. Bản Đồ Phụ Thuộc (đã cập nhật)

```
✅ A1 State Evaluator mở rộng ─┬─→ ✅ A3 Rà xung đột workflow (đã dùng để
   (6 predicate, xong)         │        soi ra A2 cần đổi hướng, không
                                │        seed workflow trùng nữa)
                                ├─→ ✅ 4.5 redesigned (reason toggle,
                                │        không qua A2/workflow nữa)
                                │        └─→ ✅ 6.9 feedback rule (xong)
                                │              └─→ đo tỷ lệ dismiss thật ─→ 6.4 AI (nếu đạt ngưỡng, xem mục VII)
                                └─→ ✅ 4.2 Trigger Catalog (xong)
                                └─→ 3.4 / 3.5 planning

✅ QĐ-1 = B ──┐
              ├─→ B/2.3 M1 dataset ──→ 6.7 Follow-up  (KHÔNG đảo thứ tự:
B/2.3 ───────┘                                          nới prompt mà chưa có
                                                        mốc đo = mù precision)
B: 3.3 find_free_slots      ────→ status line màn Hôm nay
```

**Critical path mới:** `A1 ✅ → A3 ✅ → 4.5 redesigned ✅ → 6.9 ✅ → 4.2 ✅`. Toàn bộ khối A đã đóng, không còn "chặn cứng" gì cả. Việc còn lại chạy song song, độc lập nhau: khối B (2.3 M1 dataset, 3.3 find_free_slots, 3.1 M4), 3.4/3.5 (giờ có thể đọc Trigger Catalog thay vì tự map event), hoặc đo tỷ lệ Gate "không quyết được" để biết 6.4 (AI) đã tới lúc chưa. A2 (seed system workflow theo thiết kế gốc) **đứng ngoài critical path** — hạ tầng 4.0 vẫn còn đó, chỉ chờ một nhu cầu thật sự cần multi-step workflow.
**Song song được:** toàn bộ khối B, và khối C **sau khi có** dataset 2.3 M1 (QĐ-1 đã chốt = B, không còn là điều kiện chờ).

---

# IX. Hạng Mục Khai Tử

Giữ lại để không mất tham chiếu chéo trong `tasks/` và tài liệu cũ.

| Mã | Tên (Bản 2) | Lý do khai tử |
|---|---|---|
| 2.1a / 2.1b | Goal Tối Thiểu / Goal Đầy Đủ | Bảng `goals` đã drop (`b0123456789x`) |
| 2.2 | Goal Progress Tracking | Không còn đối tượng để tính |
| 2.4 | Commitment Data Model | Gộp vào `tasks` (`a0123456789w`) |
| 2.8 | AI Skills cho Goal/Commitment | Thay bằng `skills/task/SKILL.md` |
| 4.7 | Workflow → Goal Linking | Không còn đối tượng |
| 6.3 | Rule Engine | Đã bỏ từ Bản 2 — detection thuộc Workflow Engine |

**Lưu ý quan trọng:** 6.7 và 6.8 **không** nằm trong bảng này. Chúng chưa chết — chúng cần **viết lại** (khối C), vì mục tiêu sản phẩm vẫn còn giá trị dù entity gốc đã mất.

---

# X. Cách Dùng Tài Liệu Này

- Mỗi mục **A1/A2/B/...** = một Epic; mỗi **Milestone** = một Story verify độc lập.
- **Mục tiêu** là tiêu chí nghiệm thu — code xong mà mục tiêu chưa đạt thì chưa done.
- Khi một thiết kế mâu thuẫn với **P1–P4** hoặc ba ranh giới ở mục II: **sửa thiết kế, không sửa nguyên tắc.**
- Khi schema đổi lần nữa: cập nhật mục III + IX **trước**, rồi mới sửa roadmap. Bản 2 lạc hậu chính vì bước này bị bỏ qua.
