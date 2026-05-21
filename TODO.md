# TODO - Hệ thống thông tin quản lý (Cortex)

## Bước 1: Khảo sát & lập khung tài liệu (đã bắt đầu)
- [x] Xác định các module chính từ source tree
- [ ] Tạo `docs/` và file tổng quan (nếu chưa có)

## Bước 2: Module AI Assistant / Agent Chat (đã có dữ liệu)
- [ ] Thu thập thêm source: tool implementations còn thiếu (search_notes, create_note, search_knowledge, summarize_asset, get_notifications, web_search, neural_search, deep_research)
- [ ] Thu thập thêm SSE: `backend/app/api/sse/*` (event_generator, channels/agent_events)
- [ ] Thu thập thêm ConversationStore + Summarizer
- [ ] Viết tài liệu Markdown: luồng non-stream và streaming, API, DB model, security, error handling, UML notes

## Bước 3: Module LLM Processor Worker (đã có dữ liệu)
- [ ] Thu thập thêm code Gemini service: `app/services/llm_processing.py` (gemini_service) + mongo_service methods
- [ ] Thu thập producer/queue task: `app/services/redis/llm_processor_task.py`, nơi enqueue task
- [ ] Thu thập mongo schemas: `backend/app/mongo_schemas.py` và model knowledge unit lưu ở đâu
- [ ] Viết tài liệu Markdown: luồng windowing OCR/transcript, knowledge units, timeline, synthesis, worker/queue, security, error handling

## Bước 4: Module Schedules/Calendar
- [ ] Đọc `backend/app/api/schedules.py`, `app/services/schedule_service.py`, recurrence/reminder/google sync workers
- [ ] Đọc frontend components: ScheduleForm, calendar pages & hooks
- [ ] Viết tài liệu Markdown

## Bước 5: Module Notes
- [ ] Đọc notes API + services + repositories + embeddings
- [ ] Đọc frontend notes editor/sidebar
- [ ] Viết tài liệu Markdown

## Bước 6: Module Knowledge/Asset knowledge view
- [ ] Đọc `backend/app/api/knowledge.py`
- [ ] Đọc mongo_service + embedding/semantic search
- [ ] Đọc frontend Assetknowledgeview
- [ ] Viết tài liệu Markdown

## Bước 7: Module Upload/Storage
- [ ] Đọc multipart upload + minio integration
- [ ] Đọc asset pipeline entrypoints
- [ ] Viết tài liệu Markdown

## Bước 8: Infrastructure/External integrations
- [ ] Docker-compose, Redis/Mongo/Postgres/Minio service wiring
- [ ] Google Calendar sync flow
- [ ] SSE & queue wiring
- [ ] Viết tài liệu Markdown

## Bước 9: UML candidates
- [ ] Use case diagram candidates
- [ ] Sequence diagram candidates cho: Agent chat, Agent tool calling, LLM processor pipeline
- [ ] ERD candidates theo SQLAlchemy models + mongo knowledge

