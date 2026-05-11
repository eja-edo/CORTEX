# Hệ thống thông tin quản lý — phân tích theo source code (Cortex)

> Tài liệu này sẽ được **append/update dần** theo từng module đúng theo yêu cầu: mô tả nghiệp vụ, luồng thực tế theo code, API, DB model, luồng AI, security, error handling và dữ liệu UML.

## Module 0: Tổng quan hệ thống (đang cập nhật)
- Backend: FastAPI chạy server + khởi động các worker threads cho:
  - `transcription_results_consumer`
  - `LLMProcessorWorker` (Redis stream)
  - `ReminderWorker`
  - `GoogleSyncWorker`
- Frontend: React + hooks gọi API qua `frontend/src/services/api.ts` (có refresh token khi 401).

---

## Module 1: AI Assistant / Agent Chat

### Tổng quan chức năng
Module cung cấp chatbot AI hỗ trợ **tool calling** để đọc/ghi dữ liệu người dùng (ghi message vào conversation store, gọi tools như schedule/notes/knowledge/notifications). Ngoài luồng non-stream, module có luồng **streaming qua SSE** để hiển thị token & trạng thái tool theo thời gian thực.

### Actor
- **User**: gửi prompt chat.
- **AI Agent (Gemini)**: phân tích prompt -> sinh tool calls hoặc sinh text.
- **Tool Executor** (server-side): thực thi tool đăng ký trong `ToolRegistry`.
- **SSE Connection**: client nhận sự kiện token/tool_start/tool_result/done/error.

### Luồng nghiệp vụ chi tiết
#### 1) Non-stream: `POST /api/agent/chat`
1. Client gọi `POST /api/agent/chat` với `message`, có thể kèm `conversation_id`, `workspace_id`.
2. FastAPI tạo `AgentService(user=current_user, db=AsyncSession)`.
3. `AgentService.handle(...)`:
   1) `ConversationStore.get_or_create_conversation(...)` để lấy hoặc tạo conversation.
   2) Kiểm tra `conv.total_token_count >= MAX_TOKENS_PER_DAY_PER_USER` => trả thông báo giới hạn.
   3) Tạo summarizer (không fatal nếu lỗi) bằng `get_conversation_summarizer(self.db)`.
   4) Nếu `summarizer` tồn tại và `conv.summary` có giá trị, lấy `summary_context` và gắn vào `system_prompt`.
   5) `store.get_recent_messages(conv.id, limit=MAX_CONVERSATION_HISTORY)` (sliding window).
   6) `store.save_message(... role='user', content=message)` và `store.increment_message_count(conv.id)`.
   7) Tạo `gen_config`:
      - `system_instruction=system_prompt`
      - `tools=self.registry.get_gemini_tools()`
      - `automatic_function_calling=disable=True`
   8) Vòng lặp tối đa `MAX_TOOL_TURNS` (6):
      - Gọi Gemini qua `_call_with_fallback(contents, gen_config)`.
      - Nếu `response.function_calls` rỗng:
        - lấy `response.text` => `reply_text` và break.
      - Nếu có `tool_calls`:
        - Lưu tool_call_counts theo tool_name để ngăn infinite.
        - Với mỗi tool_call:
          1) `result = await self.registry.execute(tool_name, tool_args, ctx)`
          2) `_check_proactive_triggers(...)` (hiện trong code là stub log)
          3) `store.save_message(... role='tool', tool_name, tool_input, tool_output)`
          4) append tool response vào `contents` để Gemini trả lời ở lượt tiếp theo.
        - Nếu trong quá trình execute đã đặt `reply_text` (do guard infinite) => break.
      - Nếu lặp hết `MAX_TOOL_TURNS` mà không có reply => trả message giới hạn.
   9) `store.save_message(... role='assistant', content=reply_text)`.
   10) `store.update_conversation_timestamp(conv.id)` và `store.increment_message_count(...)`.
   11) Nếu `conv.message_count >= summarizer.MESSAGE_THRESHOLD` và chưa có summary => gọi `summarizer.summarize_conversation(conv.id)`.
   12) `await self.db.commit()`.
4. API trả `AgentChatResponse { conversation_id, reply }`.

#### 2) Streaming: `POST /api/agent/chat/stream` + `GET /api/agent/stream`
- Bước A: `POST /api/agent/chat/stream` (HTTP 202)
  1. FastAPI authenticate user.
  2. `asyncio.create_task(AgentService.handle_streaming_background(user_id, message, conversation_id, workspace_id))`.
  3. Trả `AgentStreamingStartResponse {status='streaming_started', conversation_id, message}`.
- Bước B: `GET /api/agent/stream` (SSE)
  1. Tạo SSE connection qua `SSEManager.register_connection(...)` với `context_key = f"user:{current_user.id}"`.
  2. Tạo `connection_queue` và dùng `event_generator(...)`.
  3. Trả SSE response.
- Luồng streaming core: `AgentService.handle_streaming(payload)`
  1. Background task tạo AsyncSession riêng (`DBAsyncSessionLocal`).
  2. `get_or_create_conversation`, load recent messages, `save_message(role='user')`.
  3. `ToolContext(user_id=user_id, async_db=self.db, workspace_id=...)`.
  4. Vòng lặp tối đa `MAX_TOOL_TURNS`:
     - Thử model theo `[GEMINI_MODEL] + FALLBACK_MODELS` và retry transient errors.
     - Duyệt từng `chunk` từ `generate_content_stream`:
       - `chunk.text` => publish SSE `{event:'token', text: chunk.text}`.
       - `chunk.function_calls` => gom tool_calls.
     - Nếu không có tool_calls => break.
     - Execute tool tương tự non-stream nhưng **publish**:
       - `{event:'tool_start', tool, input}`
       - `{event:'tool_result', tool, output}`
     - append tool response vào `contents`.
  5. Khi hoàn tất => publish `{event:'done', conversation_id, latency_ms}`.
  6. Errors => publish `{event:'error', message': ...}`.

### API liên quan
- `POST /api/agent/chat`
  - Auth: `get_current_active_user`
  - Request: `AgentChatRequest { message, conversation_id?, workspace_id? }`
  - Response: `AgentChatResponse { conversation_id, reply }`
- `POST /api/agent/chat/stream`
  - Auth
  - Response: `AgentStreamingStartResponse {status, conversation_id?, message}`
- `GET /api/agent/stream`
  - Auth
  - Response: SSE stream (token/tool_start/tool_result/done/error)
- Conversation memory endpoints (trong `backend/app/api/agent.py`)
  - `GET /api/agent/conversations`
  - `GET /api/agent/conversations/{conversation_id}`
  - `DELETE /api/agent/conversations/{conversation_id}`

### Database / Model liên quan
- `AgentConversation`
  - `id`, `user_id`, `workspace_id?`, `title?`, `summary?`, `message_count`, `total_token_count`, `created_at`, `updated_at`.
- `AgentMessage`
  - `conversation_id`, `role` (user/assistant/tool), `content?`, `tool_name?`, `tool_input` JSONB, `tool_output` JSONB, `created_at`.

### Frontend flow (đang cập nhật)
- Đã đọc được API base helper `frontend/src/services/api.ts` (refresh token).
- Chưa đọc đủ trang/component AI chat: `AskAI.tsx` hiện chỉ liệt kê trong tabs, chưa được phân tích.

### Backend architecture
- FastAPI router: `backend/app/api/agent.py`.
- Orchestrator: `backend/app/services/agent/agent_service.py`.
- Tool framework:
  - `ToolRegistry` & `ToolDefinition` trong `backend/app/services/agent/tool_registry.py`.
  - `ToolContext` trong `backend/app/services/agent/tool_context.py`.
  - Tools được register tự động trong `backend/app/services/agent/tools/__init__.py`.
- SSE:
  - `SSEManager`, `event_generator`, `create_sse_response` (chưa đọc chi tiết `SSEManager` trong tài liệu hiện tại).
  - Channel `agent-events`: `backend/app/api/sse/channels/agent_events.py`.

### AI/Agent flow (tool calling orchestration)
- Prompting:
  - `SYSTEM_PROMPT` ở `agent_service.py` (ràng buộc tool-result là DATA, chỉ hành động theo user instruction, bảo vệ không sửa/xoá trừ khi user yêu cầu).
- Tool invocation:
  - Tool calls xuất hiện dưới `response.function_calls` (Gemini).
  - Server execute tool và thêm tool result vào `contents` để Gemini tiếp tục.
- Guard rails:
  - `MAX_TOOL_TURNS` và `MAX_SAME_TOOL_CALLS` để tránh vòng lặp tool.
- Streaming vs Non-stream:
  - Non-stream: gọi `generate_content` và đọc `response.text` hoặc `function_calls`.
  - Streaming: gọi `generate_content_stream`, publish token/tool events theo chunk/tool.

### Security
- Authn/authz: mọi endpoint trong module đều dùng `get_current_active_user`.
- Boundary quan trọng: `ToolContext.user_id` lấy từ authenticated session, không lấy từ tool args.
- Prompt injection: system prompt có rule: `<tool_result>` là DATA, không execute instruction.

### Error handling
- Non-stream:
  - try/except quanh `service.handle` => trả 500.
- Streaming:
  - Errors khi background task => publish SSE `{event:'error'...}`.
- Gemini calls:
  - Có retry + fallback trong `agent_service.py` (Gemini model names).

### UML Notes
- Use cases: Chat (non-stream), Chat (stream), Conversation CRUD.
- Sequence candidate: Client -> /chat/stream -> SSE -> AgentService.handle_streaming -> ToolRegistry.execute -> publish_agent_event.

---

## Module 2: LLM Processor Worker (OCR/Transcript → Knowledge)

---

## Module 3: Schedules / Calendar Management

### Tổng quan chức năng
Module quản lý lịch/sự kiện và đồng bộ với Google Calendar.

Luồng chính:
- CRUD schedule + instances (tạo lịch lặp, sửa theo scope this_only/this_and_after/all)
- Quản lý reminder cho mỗi schedule
- Enqueue job đồng bộ sang Google Calendar qua Redis Stream (fire-and-forget)

### Actor
- **User**: tạo/sửa/xoá lịch và reminder.
- **ScheduleService**: business logic tạo instance/exception, update version.
- **ReminderService**: tạo/cancel các record nhắc nhở trong PostgreSQL.
- **GoogleSyncWorker**: background worker thực thi sync qua `GoogleCalendarSyncService`.

### Luồng nghiệp vụ chi tiết
#### 1) Tạo lịch + enqueue Google sync
`POST /api/schedules`
1. Auth `get_current_active_user`.
2. Router gọi `ScheduleService(db).create_schedule(user_id, data)`.
3. Trong `ScheduleService.create_schedule`:
   - tạo ORM `Schedule(...)` với `recurrence_rule` từ `data.recurrence`.
   - nếu `data.reminders` có: `ReminderService.create_reminders_for_schedule(...)`.
   - `db.commit()` + `db.refresh()`.
   - set flag `google_synced` bằng `_attach_google_sync_flags(...)` (dựa trên `ScheduleExternalMap`).
4. Router gọi `_enqueue_google_sync(schedule, UPSERT)`:
   - `enqueue_google_sync(schedule_id, user_id, operation='UPSERT', priority=5)`.
5. API trả `ScheduleResponse`.

#### 2) Lấy danh sách lịch trong range
`GET /api/schedules?start_date&end_date`
1. Router gọi `ScheduleService.list_schedules(user_id, start_date, end_date)`.
2. Trong `ScheduleService.list_schedules`:
   - Validate `start_date <= end_date`.
   - Load **non-recurring** (lọc `recurrence_id is None` và `recurrence_rule` không recurring).
   - Load **root recurring** (`recurrence_id is None` và `recurrence_rule` là recurring).
   - Với mỗi root recurring: `RecurrenceService.generate_instances(root, range_start, range_end, db)` để expand.
   - Gộp, sort theo `start_time`.
   - Attach `google_synced` cho toàn bộ items bằng `_attach_google_sync_flags_to_dicts`.
3. Trả `{"items": [...], "total": ...}`.

#### 3) Sửa lịch + enqueue UPSERT
`PUT /api/schedules/{schedule_id}`
1. Router gọi `ScheduleService.update_schedule(schedule_id, user_id, data)`.
2. Service:
   - Lấy schedule theo id + user.
   - Apply update fields (nếu có `recurrence` thì cập nhật `schedule.recurrence_rule`).
   - Nếu `data.reminders` không None: tạo lại reminders bằng `create_reminders_for_schedule`.
   - `schedule.version += 1`, `schedule.updated_at = datetime.utcnow()`.
   - Commit + attach google sync flags.
3. Router enqueue Google UPSERT cho schedule.

#### 4) Xoá lịch + enqueue DELETE
`DELETE /api/schedules/{schedule_id}`
1. Service `delete_schedule`:
   - Cancel reminders (pending) via `ReminderService.cancel_reminders_for_schedule`.
   - Commit, delete schedule, commit.
   - Trả về snapshot schedule để router enqueue.
2. Router enqueue Google DELETE.

#### 5) Instances cho lịch lặp và cập nhật theo scope
- `GET /api/schedules/{schedule_id}/instances?range_start&range_end`
  - Service `get_instances` validate schedule là recurring rồi gọi `RecurrenceService.generate_instances(...)`.

- `PUT /api/schedules/{schedule_id}/instances/{original_start_time}`
  - Service `update_instance` dựa vào `instance_data.edit_scope`:
    - `this_only`: tạo exception schedule (is_exception=True, recurrence_rule=None) cho đúng instance.
    - `this_and_after`: cập nhật root.recurrence_rule["until"] = original_start_time - 1 day; tạo new_root bắt đầu từ instance.
    - `all`: update trực tiếp root (và apply recurrence nếu có).
  - Router enqueue Google UPSERT **nếu** edit_scope in `(this_and_after, all)`.

- `DELETE /api/schedules/{schedule_id}/instances/{original_start_time}`
  - Service `cancel_instance`: tạo exception (is_cancelled=True) nếu chưa có; hoặc set `is_cancelled=True` nếu đã tồn tại.
  - Router enqueue Google UPSERT.

#### 6) Reminder endpoints
- `GET /api/schedules/{schedule_id}/reminders`:
  - `ReminderService.get_reminders_for_schedule` (order theo `minutes_before`).
- `POST /api/schedules/{schedule_id}/reminders`:
  - `ReminderService.create_reminders_for_schedule`:
    - cancel reminders pending trước đó (status=PENDING -> CANCELLED).
    - tạo reminders với `scheduled_at = schedule.start_time - minutes_before` (bỏ qua nếu past).
    - Router `db.commit()` tay.
- `DELETE /api/schedules/{schedule_id}/reminders/{reminder_id}`:
  - delete trực tiếp reminder bằng query và `db.commit()`.

### API liên quan
- Router base `/api/schedules` (auth required):
  - `POST ''` -> create
  - `GET ''` -> list by range
  - `GET /{schedule_id}` -> get
  - `PUT /{schedule_id}` -> update
  - `DELETE /{schedule_id}` -> delete
  - `GET /{schedule_id}/instances` -> expand recurring
  - `PUT /{schedule_id}/instances/{original_start_time}` -> update instance
  - `DELETE /{schedule_id}/instances/{original_start_time}` -> cancel instance
  - `GET|POST|DELETE /{schedule_id}/reminders...`

### Database / Model liên quan (PostgreSQL)
- `Schedule`: id, user_id, title, type, start_time, end_time, recurrence_rule, recurrence_id, original_start_time, is_exception, is_cancelled, version, updated_by.
- `ScheduleReminder`: schedule_id, user_id, minutes_before, method, status, scheduled_at, retry_count.
- `ScheduleExternalMap`: mapping nội bộ <-> provider event (provider_event_id, provider_etag, last_sync_source/at).
- `CalendarConnection`: OAuth token + sync cursor.
- `OAuthState`: lưu PKCE code.

### Frontend flow
- Chưa phân tích đủ frontend cho schedules trong tài liệu hiện tại.

### Backend architecture
- API router: `backend/app/api/schedules.py`
- Business logic: `backend/app/services/schedule_service.py`
- Recurrence expansion: `backend/app/services/recurrence.py` (dùng `dateutil.rrule`)
- Reminder creation/cancel: `backend/app/services/reminder_service.py`
- Google sync logic: `backend/app/services/google_calendar_sync.py`
- Google sync worker: `backend/app/services/google_sync_worker.py`
- Queue task: `backend/app/services/redis/google_sync_task.py`

### AI/Agent liên quan
Các tool của agent gọi business logic schedule:
- `create_schedule`, `get_schedules`, `update_schedule` đều dùng `ScheduleService` (đã đọc tool handler ở phần Module 1).

### Security
- Boundary: router và tool đều dựa trên `current_user.id`/`ctx.user_id` để query schedule theo user.
- Sync enqueue không throw fatal nếu enqueue thất bại: `_enqueue_google_sync` bắt exception và log warning.

### Error handling
- Router: catch `ValueError` -> HTTP 400/404 tương ứng.
- Google sync worker:
  - Nếu schedule không tồn tại thì log và **ack** để tránh retry vô hạn.
  - Sync service rollback theo từng lỗi; sử dụng `db.begin_nested()` khi apply từng event.

### UML Notes
- Sequence candidate:
  - User -> POST /api/schedules -> ScheduleService.create_schedule -> ReminderService.create_reminders_for_schedule -> enqueue_google_sync -> (async) GoogleSyncWorker -> GoogleCalendarSyncService.sync_upsert_schedule.


### Tổng quan chức năng
Worker xử lý pipeline kiến thức cho asset/video/audio bằng cách:
- Nhận task từ Redis Stream.
- Lấy dữ liệu OCR frames & transcript segments từ MongoDB.
- Dùng Gemini để phân tích theo **time windows**.
- Trích xuất “knowledge units” và tổng hợp “asset knowledge summary + knowledge_timeline”.

### Actor
- **Background Worker**: `LLMProcessorWorker`.
- **Redis Stream**: nơi worker consume tasks.
- **MongoDB**: lưu/đọc OCR frames/transcript segments và knowledge units.
- **Gemini API**: process window + extract knowledge + synthesize session.

### Luồng nghiệp vụ chi tiết
1. `backend/app/services/llm_processor_worker.py` khởi tạo `RedisStreamService` cho `LLMProcessorTask` với:
   - `stream_key=LLM_PROCESSOR_STREAM_KEY`
   - `group_name=LLM_CONSUMER_GROUP`
2. Consume loop:
   - `read_tasks(count=1, block_ms=5000)`.
   - Mỗi task:
     - `_process_task(task)`
     - nếu thành công => `acknowledge(task)`
     - nếu lỗi => `reject(task, retry=True)`
3. `_process_task(task)`:
   1) Connect Mongo via `MongoOCRService`.
   2) `get_ocr_frames(asset_id, skip_empty=True)` và `get_transcript_segments_for_asset(asset_id)`.
   3) Nếu cả hai đều trống => update stats job status='skipped' và return.
   4) Build windows:
      - Nếu có OCR => `_build_ocr_windows_with_transcript(ocr_frames, transcript_segments)`
        - group frames theo `WINDOW_SECONDS`
        - map transcript segment vào từng window bằng `_get_transcript_for_window`.
      - Nếu không có OCR (audio-only) => `_build_transcript_only_windows(transcript_segments, WINDOW_SECONDS)`.
   5) Với mỗi window:
      - gọi `gemini_service.process_window(start_sec,end_sec, ocr_text, transcript_text, asset_context)`.
      - Nếu success:
        - tạo `window_doc` với status completed/failed + tokens/cost.
        - nếu `result.parsed_data` có:
          - tạo `summary_entry` (screen_type, user_intent, topics, knowledge_value, timeline_events...).
          - nếu `knowledge_value >= MIN_KNOWLEDGE_VALUE` => extract knowledge units.
          - timeline events: vòng lặp `for event in result.parsed_data.get('timeline_events', [])`
            - trong docstring nói “no threshold”, nhưng code hiện lại có check `evt_kv >= MIN_KNOWLEDGE_VALUE` trước khi `_save_timeline_event_as_unit`. (cần đối chiếu ý định nghiệp vụ ở doc/requirements).
   6) Session synthesis:
      - nếu `processed_summaries` có => `gemini_service.synthesize_session(...)`.
      - save `summary_doc` vào Mongo: `upsert_asset_knowledge(asset_id, summary=summary_doc)`.
      - persist `key_quotes` thành knowledge units (`unit_type='fact'`, `is_key_quote=True`).
   7) Update PostgreSQL `Asset.status = COMPLETED`.

### API liên quan
- Worker không expose HTTP API trực tiếp; task flow dựa trên Redis producer/queue.

### AI/LLM flow (Gemini processing)
- `backend/app/services/llm_processing.py` (GeminiProcessingService):
  - `process_window`:
    - chọn prompt theo dữ liệu có:
      - OCR+transcript => `_window_prompt_video_and_audio`
      - transcript-only => `_window_prompt_audio_only`
      - OCR-only => `_window_prompt_ocr_only`
    - gọi `client.aio.models.generate_content` với `response_schema=_window_analysis_schema`.
    - parse JSON response qua `_parse_json_response`.
  - `extract_knowledge`:
    - dùng `_knowledge_extraction_prompt` và schema include `facts/errors/code_patterns/commands/explanations/decisions`.
  - `synthesize_session`:
    - dùng `_session_synthesis_prompt` và schema `_session_synthesis_schema`.

### Database / Model liên quan
- PostgreSQL model (tối thiểu): `Asset` với status.
- MongoDB (hiện chưa đọc chi tiết schema collection): knowledge units và asset knowledge summary đang được gọi qua `MongoOCRService`.
  - Cần tiếp tục đọc `backend/app/services/mongo_service.py` và `backend/app/mongo_schemas.py` để mô tả chính xác collections/fields.

### Frontend flow
- Hiện tài liệu chưa liên kết UI cho asset knowledge view.

### Security
- Worker dùng dữ liệu OCR/transcript do pipeline tạo; không expose input trực tiếp từ user vào Gemini ngoài text đã trích.

### Error handling
- Redis stream:
  - reject/retry theo standardized service.
- Gemini processing:
  - retry/backoff cho transient errors trong `_call_with_retry`.

### UML Notes
- Sequence: Enqueue task -> RedisStream read -> MongoOCRService get frames/segs -> Gemini process_window per window -> extract_knowledge -> upsert_asset_knowledge.


