# Milestone 1.10: Durable Event Consumer ở Backend

**Status:** ✅ Hoàn thành 2026-08-06
**Dependencies:** 1.2 (Event Bus), 1.9 (Event Vocabulary — cần biết toàn bộ event type để tạo consumer group)

---

## Bối cảnh thực tế lúc bắt đầu

`EventBus.publish()` (Milestone 1.2) làm hai việc: `XADD` vào Redis Stream (persist + cross-process fan-out) rồi gọi `route_event()` **ngay trong cùng tiến trình** (in-process fast path). `subscribe()` chỉ đăng ký handler vào `self._subscribers` — một dict nằm trong bộ nhớ của **một instance `EventBus` cụ thể**.

Grep xác nhận: backend **không có** `XREADGROUP` nào, và **không một `subscribe()` nào được gọi** trong toàn bộ `backend/app/` tính đến trước milestone này. Hệ quả: nếu một event được publish từ một tiến trình/instance khác với tiến trình đang giữ handler đã `subscribe()`, event đó `XADD` thành công rồi **không ai nhận được, không có lỗi nào báo** — đúng loại bug âm thầm milestone mô tả.

## Giải pháp

Thêm layer thứ ba vào `EventBus` (`backend/app/events/event_bus.py`), bên cạnh XADD-persist và fast-path có sẵn:

- **`start_consumer(consumer_name=None)`** / **`stop_consumer()`**: vòng lặp `XREADGROUP` bền vững chạy nền (`asyncio.create_task`), consumer group cố định `CONSUMER_GROUP = "backend-eventbus"`, tạo group cho **mọi** event type trong `app.events.vocabulary.all_event_types()` (Milestone 1.9). Cùng pattern với `TranscriptionResultsConsumer` đã có sẵn trong codebase (`app/services/transcription_results_consumer.py`) — không phát minh cấu trúc mới.
- **Chống double-delivery cùng tiến trình**: khi CÙNG một instance `EventBus` vừa publish (fast path) vừa chạy durable consumer, message tự publish sẽ bị xử lý 2 lần nếu không có cơ chế chống trùng. Giải pháp: `publish()` ghi `message_id` vào `_own_published_ids` (bounded LRU, `OrderedDict`, tối đa 10.000 entry) **ngay sau khi `XADD` trả về, trước bất kỳ `await` nào khác** — đảm bảo không có race với consumer loop (asyncio cooperative, không ai chen được giữa hai dòng lệnh không có await). Durable loop thấy `message_id` trong set này thì bỏ qua route (chỉ ack), không gọi lại handler.
- **Ack/retry/DLQ khi handler lỗi**: tái dùng nguyên `route_event()` có sẵn từ Milestone 1.2 (mỗi handler tự retry + gửi DLQ độc lập qua `_invoke_handler_with_retry`) — durable consumer chỉ ack **sau khi** `route_event()` hoàn tất, không quan tâm handler bên trong có lỗi hay không (đã được cô lập).
- **Ack/retry khi process chết giữa chừng**: nếu tiến trình bị kill trong lúc `route_event()` đang chạy, message ở trạng thái pending (chưa ack) trong Redis. `_reclaim_stale_entries()` dùng `XAUTOCLAIM` (Redis ≥ 6.2, xác nhận Redis 7.4.10 + redis-py 5.0.8 hỗ trợ đầy đủ) — chạy **cả lúc `start_consumer()` khởi động** (bắt kịp ngay, không đợi hết chu kỳ) **và định kỳ mỗi `RECLAIM_INTERVAL_SECONDS`** (60s) trong lúc chạy. `XAUTOCLAIM` không gắn với tên consumer cụ thể — hoạt động đúng kể cả khi tên consumer đổi giữa các lần restart (dùng `f"backend-{hostname}-{uuid4}"`, không cố định).
- **Lỗi khi xử lý message (không phải cancel)**: log rồi vẫn ack — tránh một message hỏng (JSON lỗi, envelope sai schema) chặn stream mãi mãi ("poison message").
- **Wire vào `backend/app/__init__.py` lifespan**: `get_event_bus()` + `start_consumer()` lúc startup (bọc try/except, không chặn app khởi động nếu Redis tạm thời không sẵn sàng — cùng mức độ phòng thủ với `transcription_results_consumer`), `stop_consumer()` lúc shutdown (trước `disconnect()`).

## Sai khác / làm rõ so với mô tả milestone gốc

- Milestone gốc không nhắc tới vấn đề double-delivery cùng tiến trình (fast path + durable path cùng chạy) — đây là hệ quả tất yếu của việc **thêm** durable consumer vào một EventBus vốn đã có fast path, không phải lựa chọn thiết kế tùy ý. Nếu bỏ qua, mọi event tự publish trong tiến trình backend sẽ luôn bị xử lý 2 lần kể từ milestone này — nghiêm trọng hơn cả bug milestone đang sửa.
- Không thay đổi hành vi fast path hiện có (latency tức thời cho subscriber cùng tiến trình vẫn giữ nguyên như benchmark ở Milestone 1.2, ~0.42ms) — durable consumer là bổ sung thuần túy (additive), không thay thế.
- `RECLAIM_MIN_IDLE_MS` mặc định 60s (không claim message đang được xử lý bình thường, chỉ claim cái thực sự bị bỏ rơi) — có thể override per-instance khi cần test nhanh hơn (đã dùng trong test).

## Tests

`backend/tests/integration/test_event_bus_durable_consumer.py` (3 tests, dùng Redis thật, event type `test.durable.*` riêng theo tên test để không đụng backlog thật của `events:note.created` v.v. — vocabulary bị monkeypatch riêng cho từng test):

1. `test_durable_consumer_delivers_event_published_by_another_process` — publish bằng raw `XADD` (không qua `EventBus.publish()`, mô phỏng đúng một tiến trình khác như workflow_service) → handler `subscribe()` ở một `EventBus` instance khác thực sự chạy, qua durable consumer.
2. `test_fast_path_and_durable_consumer_dont_double_deliver` — cùng instance vừa publish vừa chạy durable consumer → handler chỉ chạy đúng 1 lần.
3. `test_reclaims_message_left_pending_by_crashed_consumer` — publish raw `XADD`, consumer A bắt được message, treo trong handler; cancel task giữa chừng (mô phỏng crash, không ack); consumer B (instance mới, `RECLAIM_MIN_IDLE_MS=0`) `start_consumer()` → reclaim + xử lý lại đúng message đó.

## DoD

- [x] Consumer loop `XREADGROUP` ở backend, độc lập với fast path.
- [x] Subscriber đăng ký qua `subscribe()` chạy được kể cả khi event publish từ tiến trình khác.
- [x] Ack/retry/DLQ hoạt động đúng khi handler lỗi (tái dùng route_event's logic có sẵn) hoặc process chết giữa chừng (XAUTOCLAIM reclaim).
- [x] Test: publish từ process A → handler ở process B thực sự chạy.
- [x] Test: kill process B giữa chừng → event được xử lý lại sau khi khởi động lại.
- [x] Không phá vỡ hành vi fast path/latency có sẵn (16 test cũ của Milestone 1.2 vẫn pass nguyên).
