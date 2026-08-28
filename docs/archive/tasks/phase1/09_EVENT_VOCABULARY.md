# Milestone 1.9: Event Vocabulary Thống Nhất

**Status:** ✅ Hoàn thành 2026-08-06
**Dependencies:** 1.1–1.3 (Event Schema, Event Bus, Core Events), 1.6 (Tool Migration — CommandRegistry publishes tool.executed)

---

## Bối cảnh thực tế lúc bắt đầu

Trước milestone này có **ba** danh sách event type độc lập, cả ba đều đã lệch nhau:

1. `EVENT_PAYLOAD_REGISTRY` (`backend/app/events/payloads.py`) — 10 type có payload schema thật.
2. `SUPPORTED_EVENTS` (`workflow_service/app/triggers/internal_event_listener.py`) — hardcode 8 type. Nghe `asset.uploaded`/`asset.processed` (backend chưa từng publish), **không nghe** `schedule.reminder.due`, `conversation.message.created`, `tool.executed` (backend publish thật nhưng workflow_service không nhận ra — một workflow trigger trên `tool.executed` sẽ không bao giờ chạy, không có lỗi nào báo).
3. **Phát hiện thêm khi implement** (không có trong mô tả milestone gốc): `workflow_service/app/api/v1/actions.py::list_actions()` — API công khai cho frontend chọn trigger event — hardcode **một danh sách thứ tư**, chỉ 8 type, còn thiếu nhiều hơn cả `SUPPORTED_EVENTS` (thiếu cả `schedule.reminder.due`, `conversation.message.created`, `tool.executed`, `google_calendar.synced`). Đây chính là "Trigger Catalog" mà milestone gốc nhắc tới ở mục tiêu.

## Giải pháp

**`backend/app/events/vocabulary.py`** — nguồn sự thật duy nhất. `EVENT_VOCABULARY: dict[str, EventVocabularyEntry]` với `event_type`, `description`, `published_by`, `has_payload_schema`. Xây dựng từ `EVENT_PAYLOAD_REGISTRY` (10 type thật) + 2 type "reserved" (`asset.uploaded`, `asset.processed` — giữ lại vì `actions.py` đã public expose chúng từ trước, nhưng đánh dấu `has_payload_schema=False` vì chưa có service nào thật sự publish; asset/upload pipeline có từ trước event bus và chưa được nối vào, ngoài phạm vi Phase 1).

**workflow_service không import trực tiếp package backend** — hai service khác venv, khác Docker build context (`infrastructure/docker-compose.yml`: `workflow_service` build với `context: ../workflow_service`, không thấy toàn bộ monorepo). `workflow_service/tests/test_internal_event_listener.py` đã tự ghi rõ điều này trong docstring gốc trước cả khi tôi chạm vào.

→ **`backend/scripts/generate_event_vocabulary.py`** sinh file JSON checked-in `workflow_service/app/triggers/event_vocabulary.json` từ `EVENT_VOCABULARY`. Chạy lại sau mỗi lần sửa `vocabulary.py`:
```bash
cd backend && python -m scripts.generate_event_vocabulary
```
`tests/unit/test_event_vocabulary.py::test_workflow_vocabulary_is_in_sync` fail nếu quên chạy lại — so sánh file JSON hiện có với những gì generator sẽ sinh ra ngay bây giờ.

**`internal_event_listener.py`**: `SUPPORTED_EVENTS` (constant) → `load_supported_events()` (đọc JSON, tất cả 12 type kể cả reserved — dùng để tạo consumer group) + `load_implemented_event_types()` (chỉ 10 type có `has_payload_schema=True` — dùng cho public API, tránh user chọn trigger event không bao giờ bắn). Vòng lặp chính reload vocabulary mỗi `VOCABULARY_RELOAD_SECONDS` (30s), tự tạo consumer group cho type mới xuất hiện, cập nhật dict `streams` cho lần `XREADGROUP` kế tiếp — **không cần restart**.

**`actions.py::list_actions()`**: enum của `config_schema.properties.event` giờ lấy từ `load_implemented_event_types()` thay vì literal thứ tư đã lệch — sửa một bug thật (4 event type thật không bao giờ chọn được trên UI trước đây).

## Sai khác so với mô tả milestone gốc

- Milestone gốc chỉ nhắc "hai list" (backend + workflow_service); thực tế có **ba**, và list thứ ba (Trigger Catalog API) lệch nặng nhất. Đã sửa cả ba trong cùng một lần thay vì chỉ hai cái được nêu tên.
- "M1: shared package hoặc file sinh tự động" → chọn **file sinh tự động** (không phải shared package) vì ràng buộc triển khai thực tế: build context Docker của workflow_service không bao gồm phần còn lại của monorepo, và test có sẵn từ trước đã minh định "không import backend package".
- Giữ `asset.uploaded`/`asset.processed` trong vocabulary dưới dạng "reserved" thay vì xóa hẳn — tránh phá vỡ hành vi hiện có (workflow_service đã nghe 2 type này từ trước), đồng thời làm rõ ràng trạng thái "chưa implement" thay vì im lặng như trước.

## Tests

- `backend/tests/unit/test_event_vocabulary.py` (5 tests): mọi type có payload schema đều nằm trong vocabulary; `implemented_event_types()` khớp `EVENT_PAYLOAD_REGISTRY`; reserved type không có payload schema; JSON checked-in khớp generator.
- `workflow_service/tests/test_event_vocabulary.py` (2 tests): load list đầy đủ + list đã implement từ file JSON thật.
- `workflow_service/tests/test_internal_event_listener.py::test_listener_picks_up_new_event_type_without_restart` (1 test, `@pytest.mark.slow`): mô phỏng regenerate vocabulary giữa lúc listener đang chạy — xác nhận consumer group mới được tạo và message được nhận, không cần sửa code/restart. Dùng event type `test.*` riêng, không đụng `events:note.created` thật (tránh backlog từ traffic thật trong dev Redis).

## Lưu ý vận hành (đã xử lý)

- `internal_event_listener.py::test_listener_consumes_stream_and_triggers_matching_workflow` (test có từ Milestone 1.2) từng flaky khi chạy chung với toàn bộ suite — nguyên nhân gốc: test dùng stream `events:note.created` và consumer group `workflow_service` **thật** (không namespace theo test); `events:note.created` là stream production thật, tích lũy hàng trăm entry thật qua cả phiên làm việc, và consumer group tạo ở `id="0"` (deliver-from-beginning, đúng cho production để phục hồi sau crash) sẽ nhận toàn bộ backlog đó khi có message mới bất kỳ — mỗi entry backlog trùng `event_type="note.created"` đều khớp với workflow tạm thời của test, làm `trigger_mock.call_count` bị thổi phồng (gặp cả 3 và 118 trong lúc debug).
  **Đã sửa** (2026-08-06): test tự tạo một consumer group **dùng riêng, đặt tên ngẫu nhiên mỗi lần chạy**, tại `id="$"` (chỉ nhận entry mới từ bây giờ) **trước khi** khởi động listener — nhờ vậy lệnh `xgroup_create(..., id="0", ...)` bên trong listener chỉ gặp `BUSYGROUP` và bỏ qua, không đụng tới con trỏ `id="$"` đã đặt. Đã thử cách "tạo group ở id=0 rồi SETID về $ sau 0.5s" trước — vẫn flaky vì listener bắt đầu rút backlog ngay khi group được tạo (XREADGROUP không thực sự block khi còn dữ liệu sẵn có), nên có thể rút xong một phần backlog trước khi lệnh SETID kịp chạy. Verify: 5/5 lần chạy solo sạch, 3/3 lần chạy cả suite sạch.
