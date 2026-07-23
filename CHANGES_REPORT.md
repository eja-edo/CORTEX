# Báo Cáo Thay Đổi — Memory Pipeline & AskAI Frontend

**Ngày:** 2026-07-23
**Tác giả:** opencode agent

---

## Tổng Quan

Sửa lỗi memory pipeline (Issue 1–8) và cải thiện AskAI frontend. Tất cả 7 issue còn lại (2b–8) đã được implement, test, và commit lên nhánh `develop`.

---

## Issue 1 — System Prompt + Tool Description cho `extract_memory`

**Trạng thái:** ✅ Đã commit trước đó

**Thay đổi:**
- `app/ai/tools/extract_memory.py`: Tool description liệt kê rõ các MUST-call triggers
- `app/ai/prompts/system/assistant_system.md`: MEMORY & CONTEXT block có hướng dẫn `extract_memory`
- `test_issue1_extract_memory_triggers.py`: 5 tests

---

## Issue 2a — Advisory Lock / Race Condition

**Trạng thái:** ✅ Đã commit trước đó

**Thay đổi:**
- `app/ai/agents/agent_service.py`: Thêm `_maybe_trigger_memory_extraction` helper dùng `pg_try_advisory_xact_lock(hashtextextended)` lock theo `conv.id`
- Cả `handle` và `handle_streaming_generator` đều gọi helper này
- `test_issue2a_advisory_lock.py`: 5 tests

---

## Issue 2b — Zep Dedupe (Trùng lặp Semantic Memory)

**Commit:** `12252d0`

**Vấn đề:** `add_semantic_memory` có thể thêm entries trùng lặp vào Zep graph.

**Giải pháp:** Hai lớp dedupe:
1. **In-process LRU cache** — keyed by `(user_id, category, normalized_content)`, giới hạn 4096 entries, bắt các trùng lặp trong cùng process
2. **Zep similarity search** — gọi `search_semantic_memories` với content làm query, nếu score >= 0.95 (configurable via `ZEP_DEDUPE_SCORE`) hoặc nội dung khớp chính xác thì skip

**Files thay đổi:**
- `app/services/zep_memory.py`: Thêm `_normalize_content`, `_dedupe_signature`, `_already_seen`, `_mark_seen`, `_check_zep_duplicate`; tích hợp vào `add_semantic_memory` và `add_semantic_memories_batch`
- `test_issue2b_zep_dedupe.py`: 6 tests (mới)

---

## Issue 3 — Context Injection vào LLM Prompt của Turn Hiện Tại

**Commit:** `b34ff8a`

**Vấn đề:** Context (pills, runtime info) từ frontend được lưu vào DB nhưng **không được inject** vào LLM prompt cho turn hiện tại — chỉ có history turn mới có context.

**Giải pháp:**
- Refactor: tách formatting logic từ `_message_full_text` thành `_inject_context_into_text(text, ctx)` dùng chung
- Áp dụng `_inject_context_into_text(message, context)` ở cả 2 call sites (`handle` và `handle_streaming_generator`)

**Files thay đổi:**
- `app/ai/agents/agent_service.py`: Thêm `_inject_context_into_text`, sửa `_message_full_text` gọi nó; sửa 2 call sites của current message
- `test_issue3_context_injection.py`: 8 tests (mới)

---

## Issue 4 — Timestamps trong Messages

**Commit:** `fe90b34`

**Vấn đề:** LLM không biết thời gian gửi của từng message — `Message` dataclass không có trường `created_at`, và DB `AgentMessage.created_at` bị bỏ qua.

**Giải pháp:**
- Thêm `created_at: datetime | None = None` vào `Message` dataclass
- `_build_history_contents` truyền `created_at` từ DB records qua
- Các message turn hiện tại dùng `datetime.utcnow()`
- OpenAI provider bake timestamp vào content: `[2026-07-23 10:30:00 UTC] message text`

**Files thay đổi:**
- `app/ai/agents/provider_types.py`: Thêm `created_at` field
- `app/ai/agents/agent_service.py`: Thêm `_get_message_created_at`; truyền `created_at` trong `_build_history_contents` và tất cả current-turn Message constructions
- `app/ai/agents/openai_provider.py`: Thêm `_format_content_with_ts`, tích hợp vào `_messages_to_openai`
- `test_issue4_timestamps.py`: 8 tests (mới)

---

## Issue 5 — Stale Message Count (Atomic UPDATE ... RETURNING)

**Commit:** `213d165`

**Vấn đề:** `increment_message_count` và `increment_token_count` dùng SELECT-then-UPDATE → race condition khi concurrent requests.

**Giải pháp:** Thay bằng `UPDATE ... RETURNING` atomic:
```python
update(AgentConversation)
.where(AgentConversation.id == conversation_id)
.values(message_count=AgentConversation.message_count + 1)
.returning(AgentConversation.message_count)
```

**Files thay đổi:**
- `app/ai/agents/conversation_store.py`: Sửa `increment_message_count` và `increment_token_count` (cùng một pattern)
- `test_issue5_stale_message_count.py`: 4 tests (mới)

---

## Issue 6 — Non-Streaming Title Generation

**Commit:** `5ffaf63`

**Vấn đề:** `handle_streaming_generator()` sinh title cho conversation mới, nhưng `handle()` (non-streaming) thì không.

**Giải pháp:** Thêm title generation vào `handle()` sau khi tạo conversation mới, đưa `title` vào response dict. Lỗi sinh title là non-fatal.

**Files thay đổi:**
- `app/ai/agents/agent_service.py`: Thêm try/except `_generate_conversation_title` trong `handle()`; thêm `generated_title` vào return dict
- `test_issue6_non_streaming_title.py`: 4 tests (mới)

---

## Issue 7 — Tool Output Truncation

**Commit:** `ed84924`

**Vấn đề:** Tool outputs có thể rất lớn (search results, file contents) → LLM prompt bị waste context window.

**Giải pháp:** Thêm `TOOL_OUTPUT_MAX_CHARS = 4000` và `_truncate_tool_output` helper trong `OpenAIProvider`. Khi serialized JSON vượt ngưỡng, truncate với note thông báo. Chỉ áp dụng cho LLM prompt — DB vẫn lưu full content.

**Files thay đổi:**
- `app/ai/agents/openai_provider.py`: Thêm `TOOL_OUTPUT_MAX_CHARS`, `_truncate_tool_output`, áp dụng trong `_messages_to_openai` cho tool results
- `test_issue7_tool_truncation.py`: 5 tests (mới)

---

## Issue 8 — Dead Code Removal

**Commit:** `fb3970a`

**Vấn đề:** `get_or_create_conversation` có tham số `conversation_id` và nhánh `if conversation_id:` — nhưng cả 2 call sites luôn pass `None`.

**Giải pháp:** Xóa tham số `conversation_id` và nhánh dead code. Cập nhật callers.

**Files thay đổi:**
- `app/ai/agents/conversation_store.py`: Simplify `get_or_create_conversation`
- `app/ai/agents/agent_service.py`: Remove `conversation_id=None` từ 2 call sites
- `test_issue8_dead_code.py`: 3 tests (mới)

---

## Thống Kê Chung

| Metric | Giá trị |
|--------|---------|
| Commits mới | 6 (2b–8) |
| Files thay đổi | 12 files |
| Files test mới | 7 files |
| Tổng tests mới | 38 tests |
| Dòng code thêm | ~800 |
| Dòng code xóa | ~60 |

## Frontend Fixes (trước đó)

Ngoài backend issues, cũng đã fix:
- Scroll sync: ratio-based với rAF throttling (không jank)
- Table rendering: h4–h6 support, `parseTable` slice fix
- AskAI message reload: filter `tool` messages, `JSON.parse` safe
- Markdown rendering: chuyển từ custom regex sang `markdown-it` + `DOMPurify`
- Streaming UI: `text` step type interleaved với thinking/tool_start/tool_result; `toolSemanticDescription` + `toolResultSummary`
