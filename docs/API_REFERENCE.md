# Orchestrator API Reference

Tài liệu này mô tả toàn bộ API do **orchestrator_service** cung cấp — dịch vụ FastAPI đóng vai trò cổng API chính của hệ thống Mezon Call Translation (quản lý phòng, tóm tắt, hàng đợi xử lý, và các kênh streaming thời gian thực qua SSE). Các service nội bộ khác (STT, TTS, agent LiveKit, record-service) không expose API cho client bên ngoài — chúng gọi ngược vào orchestrator qua các endpoint "nội bộ" được liệt kê riêng bên dưới.

| | |
|---|---|
| **Base URL (v2)** | `http://<host>:8002/api/v2` |
| **Định dạng** | JSON · `text/event-stream` (SSE) |
| **Cơ chế xác thực** | JWT Bearer · API Key Bearer |

> **Quy ước response.** Hầu hết endpoint đọc dữ liệu (GET) trả về bọc trong một object có trường `"status": "ok"` cùng dữ liệu thực (`data`, `rooms`, `tasks`…). Các endpoint POST tác vụ (đăng nhập, đẩy sự kiện…) trả thẳng object kết quả không có `status`.

## Mục lục

1. [Xác thực](#1-xác-thực-authentication)
2. [Phân quyền](#2-phân-quyền-permissions)
3. [Bảng tra cứu nhanh](#3-bảng-tra-cứu-nhanh)
4. [Auth API](#4-auth-api-apiv2auth)
5. [Rooms API](#5-rooms-api-apiv2rooms)
6. [Summary API](#6-summary-api-apiv2summary)
7. [Queue Monitoring API](#7-queue-monitoring-api-apiv2queue)
8. [SSE — Transcript](#8-sse--transcript)
9. [SSE — Chat external](#9-sse--chat-external)
10. [SSE — Metadata sự kiện](#10-sse--metadata-sự-kiện)
11. [SSE — Agent requests](#11-sse--agent-requests)
12. [Room Registry API (nội bộ)](#12-room-registry-api-apiv2room-registry--nội-bộ)
13. [Recording Events API (nội bộ)](#13-recording-events-api-apiv2recordings--nội-bộ)
14. [Xử lý lỗi](#14-xử-lý-lỗi)
15. [Endpoint cũ (deprecated)](#15-endpoint-cũ-deprecated)

---

## 1. Xác thực (Authentication)

Orchestrator dùng **hai cơ chế xác thực độc lập**, tuỳ theo endpoint là dành cho người dùng/frontend hay cho service nội bộ gọi lẫn nhau. Cả hai đều truyền qua header `Authorization: Bearer <token>` — điểm khác biệt là token đó là gì.

### ① JWT Bearer

Dùng cho **người dùng cuối và bot** sau khi đăng nhập qua Mezon OAuth2. Token do chính orchestrator phát hành (không phải token của Mezon).

- Thuật toán `HS256`, ký bằng secret `JWT_SECRET` phía server.
- Payload chỉ chứa `jti`, `user_id`, `iat`, `exp` — **không** chứa quyền hạn hay username (những field này được nạp lại từ DB mỗi request).
- Hạn dùng access token: `JWT_EXPIRY_DAYS` (mặc định 1 ngày).
- Access token có thể bị thu hồi tức thì qua blacklist theo `jti` (khi logout hoặc refresh).

### ② API Key Bearer

Dùng cho **giao tiếp service-to-service**: agent LiveKit, agents-bot, record-service, audio-processing-service gọi vào orchestrator để đăng ký phòng, đẩy sự kiện, nhận lệnh điều khiển agent.

- Header: `Authorization: Bearer <INTERNAL_API_SECRET>` — so khớp chuỗi tĩnh với biến môi trường `INTERNAL_API_SECRET` trên server.
- Không gắn với người dùng, không phân quyền chi tiết — coi đây là "chìa khoá chủ" cho hạ tầng nội bộ, **không** phát cho client/frontend.
- Không có cơ chế hết hạn hay thu hồi — xoay vòng bằng cách đổi biến môi trường.

### Luồng đăng nhập người dùng (Mezon OAuth2)

Frontend tự xử lý bước redirect sang Mezon để lấy `code`/`state`, sau đó gọi orchestrator theo thứ tự:

| Bước | Gọi | Mục đích |
|---|---|---|
| 1 | `POST /auth/mezon/exchange` | Đổi `code` lấy `access_token` + `refresh_token` |
| 2 | `Authorization: Bearer <access_token>` | Đính kèm ở mọi request tiếp theo cần JWT |
| 3 | `POST /auth/refresh` | Khi access token hết hạn — token cũ tự động bị blacklist |
| 4 | `POST /auth/logout` | Thu hồi cả access + refresh token khi người dùng đăng xuất |

Bot dùng riêng `POST /auth/mezon/bot/login` với thông tin tài khoản bot (không qua luồng OAuth2 redirect).

---

## 2. Phân quyền (Permissions)

Sau khi JWT hợp lệ, orchestrator nạp **danh sách quyền phẳng (flat permissions)** của user từ PostgreSQL cho từng request (không nhúng trong token, nên thu hồi/cấp quyền có hiệu lực ngay). Mỗi endpoint yêu cầu một hoặc nhiều quyền bằng `require_any_permission(...)` / `require_all_permissions(...)`; thiếu quyền → `403 Forbidden`.

| Permission | Cấp cho ai theo mặc định | Dùng ở API nào |
|---|---|---|
| `rooms:view_own` | Mọi user mới (mặc định) | Rooms, Summary — chỉ thấy phòng mình từng tham gia |
| `rooms:view_all` | Admin/bot được cấp thủ công | Rooms, Summary, SSE transcript — thấy toàn bộ phòng |
| `rooms:delete` | Chưa cấp mặc định | Định nghĩa sẵn, hiện chưa có endpoint nào dùng |
| `queues:view_stats` | Admin được cấp thủ công | Toàn bộ Queue Monitoring API |
| `metadata_events:view_all` | Tài khoản bot (mặc định) | SSE metadata (stream + tra cứu lịch sử) |
| `chat_external:view_all` | Tài khoản bot (mặc định) | SSE chat external |
| `agent:control` | Admin/service được cấp thủ công | Gửi lệnh điều khiển agent, xem participant |
| `resource:delete_any` | Chưa cấp mặc định | Định nghĩa sẵn, hiện chưa có endpoint nào dùng |

> **Không có API tự cấp quyền.** Việc gán permission cho user hiện chỉ thực hiện trực tiếp trong PostgreSQL (bảng quyền người dùng) — chưa có endpoint quản trị nào để admin cấp/thu hồi quyền qua API.

Bộ quyền mặc định khi tạo tài khoản:

| Loại tài khoản | Quyền mặc định |
|---|---|
| User thường | `rooms:view_own` |
| Bot | `metadata_events:view_all`, `chat_external:view_all` |

---

## 3. Bảng tra cứu nhanh

Toàn bộ endpoint đang hoạt động dưới prefix `/api/v2`, trừ các endpoint đánh dấu "nội bộ" (agent/service gọi bằng API Key) và mục Deprecated ở cuối trang.

### Auth & người dùng

| Method | Path | Auth | Quyền |
|---|---|---|---|
| POST | `/auth/mezon/exchange` | Không | — |
| GET | `/auth/mezon/userinfo` | JWT | — |
| POST | `/auth/refresh` | Không (refresh token trong body) | — |
| POST | `/auth/logout` | JWT | — |
| POST | `/auth/mezon/bot/login` | Không | — |

### Rooms

| Method | Path | Auth | Quyền |
|---|---|---|---|
| GET | `/rooms` | JWT | view_all hoặc view_own |
| GET | `/rooms/id/{room_id}` | JWT | view_all hoặc view_own |
| GET | `/rooms/id/{room_id}/statistics` | JWT | view_all hoặc view_own |
| GET | `/rooms/audio_info/{room_id}` | JWT | view_all hoặc view_own |
| GET | `/rooms/participant/{room_id}` | JWT | `agent:control` (chưa triển khai đầy đủ) |

### Summary

| Method | Path | Auth | Quyền |
|---|---|---|---|
| GET | `/summary/room/{room_name}` | JWT | view_all hoặc view_own |
| GET | `/summary/room/id/{room_id}` | JWT | view_all hoặc view_own |

### Queue monitoring

| Method | Path | Auth | Quyền |
|---|---|---|---|
| GET | `/queue/list` | JWT | `queues:view_stats` |
| GET | `/queue/overview` | JWT | `queues:view_stats` |
| GET | `/queue/{queue_name}/stats` | JWT | `queues:view_stats` |
| GET | `/queue/{queue_name}/task/{task_id}` | JWT | `queues:view_stats` |
| GET | `/queue/{queue_name}/pending` | JWT | `queues:view_stats` |
| GET | `/queue/{queue_name}/dlq` | JWT | `queues:view_stats` |
| POST | `/queue/{queue_name}/dlq/retry/{task_id}` | JWT | `queues:view_stats` |

### Streaming thời gian thực (SSE)

| Method | Path | Auth | Quyền / ghi chú |
|---|---|---|---|
| GET | `/sse/stream_transcript` | JWT | `rooms:view_all` |
| POST | `/push_transcript` | API Key | nội bộ — STT pipeline gọi |
| GET | `/sse/chat_external` | JWT | `chat_external:view_all` (bot) |
| POST | `/agent_push_chat_external` | API Key | nội bộ — agent gọi |
| GET | `/sse/metadata` | JWT | `metadata_events:view_all` |
| GET | `/metadata` | JWT | `metadata_events:view_all` |
| GET | `/metadata/{event_id}` | JWT | `metadata_events:view_all` |
| POST | `/push_metadata/session_started` | API Key | nội bộ — agent gọi |
| POST | `/push_metadata/session_ended` | API Key | nội bộ — agent gọi |
| POST | `/push_metadata/session_record_done` | API Key | nội bộ — record-service gọi |
| POST | `/push_metadata/session_summary_done` | API Key | nội bộ |
| GET | `/sse/agent-requests` | API Key | nội bộ — agent tự kết nối để nhận lệnh |
| POST | `/dispatch/agent-request` | JWT | `agent:control` |

### Nội bộ — Room registry & Recording events

| Method | Path | Auth | Ghi chú |
|---|---|---|---|
| POST | `/room-registry/register` | API Key | agent gọi khi vào phòng |
| POST | `/room-registry/participant-joined` | API Key | agent báo có người tham gia |
| POST | `/room-registry/unregister` | API Key | agent gọi khi rời phòng |
| GET | `/room-registry/status/{room_name}` | API Key | kiểm tra phòng đã đăng ký chưa |
| GET | `/room-registry/list` | API Key | liệt kê toàn bộ phòng đang mở |
| DELETE | `/room-registry/clear-all` | API Key | phá huỷ — chỉ dùng vận hành/dev |
| POST | `/recordings/events` | API Key | webhook từ record-service / audio-processing-service |

---

## 4. Auth API (`/api/v2/auth`)

### `POST /auth/mezon/exchange`

**Auth:** không cần token.
Đổi authorization `code` nhận được từ redirect Mezon OAuth2 lấy JWT session của orchestrator.

Request body:

| Field | Kiểu | Bắt buộc | Mô tả |
|---|---|---|---|
| `code` | string | có | Authorization code Mezon trả về |
| `state` | string | có | 11 ký tự chữ/số, chống CSRF |

Response `200`:

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "a1b2c3...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "user": { "...thông tin user từ Mezon..." }
}
```

### `GET /auth/mezon/userinfo`

**Auth:** JWT Bearer.
Lấy thông tin user hiện tại — dùng để khôi phục phiên đăng nhập sau khi tải lại trang.

Response `200`:

```json
{
  "status": "ok",
  "user": {
    "user_id": "123456",
    "username": "john.doe",
    "display_name": "John Doe",
    "avatar": "https://..."
  }
}
```

### `POST /auth/refresh`

**Auth:** không cần token (dùng `refresh_token` trong body).
Cấp access token mới. Access token cũ tự động bị đưa vào blacklist; refresh token vẫn còn hiệu lực để dùng lại lần sau.

Request body:

| Field | Kiểu | Bắt buộc |
|---|---|---|
| `refresh_token` | string | có |

Response `200`:

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "d4e5f6...",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

### `POST /auth/logout`

**Auth:** JWT Bearer.
Thu hồi access token hiện tại (blacklist theo `jti`) và revoke refresh token đi kèm. Client cần tự xoá cả hai token khỏi storage.

Request body:

| Field | Kiểu | Bắt buộc |
|---|---|---|
| `refresh_token` | string | có |

Response `200`:

```json
{ "status": "ok", "message": "Logged out successfully" }
```

### `POST /auth/mezon/bot/login`

**Auth:** không cần token.
Đăng nhập tài khoản bot bằng credentials Mezon trực tiếp (không qua redirect OAuth2), trả về JWT session cho bot.

Request body:

```json
{
  "account": {
    "appid": "string",
    "token": "string"
  }
}
```

Response `200`:

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "...",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

---

## 5. Rooms API (`/api/v2/rooms`)

Truy vấn dữ liệu phòng họp lưu ở PostgreSQL. Với quyền `rooms:view_own`, user chỉ thấy các phòng mình từng tham gia; `rooms:view_all` thấy toàn bộ.

### `GET /rooms`

**Auth:** JWT Bearer · **Quyền:** `rooms:view_all` | `rooms:view_own`
Danh sách phòng, có lọc và phân trang.

Query params:

| Field | Kiểu | Mặc định | Mô tả |
|---|---|---|---|
| `status` | string | — | Lọc theo trạng thái phòng |
| `search` | string | — | Tìm theo tên phòng hoặc identity participant |
| `from_utc` | datetime | — | Từ thời điểm tạo (UTC, ISO 8601) |
| `to_utc` | datetime | — | Đến thời điểm tạo (UTC) |
| `limit` | int | 100 | 1–500 |
| `skip` | int | 0 | 0–100000 |

Response `200`:

```json
{
  "status": "ok", "total": 42,
  "limit": 100, "skip": 0,
  "rooms": [{
    "id": "b3f1c2a4-...", "room_name": "my-room-123",
    "status": "completed",
    "participants": [{ "...": "..." }],
    "created_at": "2026-03-01T10:00:00Z",
    "finalized_at": "...", "completed_at": "...",
    "error": null
  }]
}
```

### `GET /rooms/id/{room_id}`

**Auth:** JWT Bearer · **Quyền:** `rooms:view_all` | `rooms:view_own`
Chi tiết một phòng theo UUID. Trả `{ "status": "ok", "room": {...} }` với cấu trúc `room` giống một phần tử trong `rooms` ở trên.

### `GET /rooms/id/{room_id}/statistics`

**Auth:** JWT Bearer · **Quyền:** `rooms:view_all` | `rooms:view_own`
Thống kê track/segment/thời lượng của phòng.

Response `200`:

```json
{
  "status": "ok",
  "statistics": {
    "room_id": "b3f1c2a4-...", "room_name": "my-room-123",
    "status": "completed",
    "total_tracks": 3, "completed_tracks": 3, "remaining_tracks": 0,
    "total_segments": 128, "total_duration_sec": 1830.4,
    "created_at": "...", "finalized_at": "..."
  }
}
```

### `GET /rooms/audio_info/{room_id}`

**Auth:** JWT Bearer · **Quyền:** `rooms:view_all` | `rooms:view_own`
Danh sách file audio đã ghi cho từng participant trong phòng.

Response `200`:

```json
{
  "status": "ok",
  "file_results": [{
    "participant_identity": "user_1", "filename": "user_1_audio.mp3",
    "started_at_ns": 1730000000000, "ended_at_ns": 1730003600000
  }]
}
```

### `GET /rooms/participant/{room_id}`

**Auth:** JWT Bearer · **Quyền:** `agent:control`
Liệt kê participant đang có mặt trong phòng.

> **Chưa triển khai đầy đủ:** endpoint này hiện luôn trả về `{"status": "ok", "participants": []}` — phần logic lấy participant thật (TODO trong code) chưa được viết.

---

## 6. Summary API (`/api/v2/summary`)

Lấy bản tóm tắt cuộc họp do pipeline tóm tắt (LLM) sinh ra sau khi phòng kết thúc.

### `GET /summary/room/{room_name}`

**Auth:** JWT Bearer · **Quyền:** `rooms:view_all` | `rooms:view_own`
Lấy tóm tắt theo tên phòng (một tên phòng có thể ứng với nhiều phiên/cuộc gọi khác nhau theo thời gian).

Query params:

| Field | Kiểu | Mô tả |
|---|---|---|
| `start_time` | datetime | ISO 8601, ví dụ `2026-01-01T00:00:00Z` |
| `end_time` | datetime | phải sau `start_time` |

Response `200`:

```json
{
  "status": "ok", "count": 1,
  "data": [{
    "room_id": "...", "room_name": "my-room-123",
    "participants": ["1801234567890", "1801234567891"],
    "summary_data": {
      "summary": "Context\nBuổi họp thảo luận về tiến độ dự án Q1...\n\nKey Discussions\n[1801234567890] Đề xuất chuyển deadline sang tuần sau\n[1801234567891] Đồng ý, cần thêm thời gian test",
      "action_items": {
        "1801234567890": ["Cập nhật lại timeline dự án", "Gửi báo cáo tiến độ trước thứ 6"],
        "1801234567891": ["Hoàn thành test case cho module thanh toán"],
        "general": ["Lên lịch họp review vào tuần sau"]
      },
      "detail": ["Đã chốt phương án dùng PostgreSQL thay vì MongoDB cho bảng summary"]
    },
    "messages": [{ "timestamp": "10:00:01", "participant_id": "1801234567890", "content": "..." }],
    "speech_durations": [{ "participant_identity": "1801234567890", "duration": 812.4 }],
    "total_segments": 128,
    "created_at": "...", "finalized_at": "...", "completed_at": "..."
  }]
}
```

### `GET /summary/room/id/{room_id}`

**Auth:** JWT Bearer · **Quyền:** `rooms:view_all` | `rooms:view_own`
Lấy tóm tắt của đúng một phiên theo UUID. Trả `{ "status": "ok", "data": {...} }` với cùng cấu trúc phần tử ở trên.

### Cấu trúc chi tiết `summary_data` (và cách dùng `action_items`)

`summary_data` không có model Pydantic riêng (khai báo là `dict[str, Any]`) — đây là object do `summary_service.py` build thủ công sau khi gọi LLM, luôn có đúng 3 field sau:

| Field | Kiểu | Mô tả |
|---|---|---|
| `summary` | string | Văn bản tóm tắt dạng plain text, ghép từ 2 khối `"Context\n..."` và `"Key Discussions\n..."` (ngăn cách bởi dòng trống). Có thể là chuỗi rỗng `""` nếu LLM không trả context nào. |
| `action_items` | `object<string, string[]>` | **Việc cần làm, được nhóm sẵn theo người phụ trách** — xem chi tiết bên dưới. |
| `detail` | `string[]` | Danh sách gạch đầu dòng các điểm thảo luận/quyết định chi tiết (kỹ thuật, số liệu…), không nhóm theo người. |

> **Phòng chưa có tóm tắt / đang xử lý lại:** nếu LLM lỗi và tác vụ được đưa vào outbox để retry, `summary_data` có thể là **object rỗng `{}`** (không có cả 3 field trên) cho tới khi worker retry thành công. Luôn kiểm tra `summary_data` có field `action_items` hay không trước khi đọc, đừng giả định nó luôn tồn tại.

#### `action_items` — schema chính xác

```
action_items: {
  [participant_identity: string]: string[]   // 1 người -> danh sách task dạng câu, tiếng Việt
}
```

- **Key** là `participant_identity` thật của Mezon (cùng giá trị xuất hiện ở `participants`, `messages[].participant_id`, `speech_durations[].participant_identity` trong response) — **không phải** display name/username. Việc này được đảm bảo trong code: LLM được yêu cầu gắn tag `[username]` vào đầu mỗi dòng "next focus", sau đó server thay thế mọi `username` bằng `participant_identity` thật (`decode_aliases` trong `utils/participant_identity.py`) trước khi nhóm — nên bạn luôn nhận được ID ổn định để map ngược sang user, không cần tự parse tên.
- **Key đặc biệt `"general"`**: dùng cho các dòng "next focus" mà LLM không gắn được tag người phụ trách rõ ràng (không đúng định dạng `[ai đó] nội dung`). Luôn kiểm tra key này riêng — đây là các việc "chưa rõ người phụ trách", không nên gán nhầm cho một user cụ thể.
- **Value** là mảng string — mỗi phần tử là một task/việc cần làm dạng câu hoàn chỉnh (đã bỏ tiền tố `[user] -`/`[user]:`), có thể rỗng `[]` nếu người đó được nhắc tới nhưng không có task cụ thể nào khớp định dạng.
- Nếu toàn bộ phiên họp không có "next focus" nào (hoặc LLM lỗi), `action_items` là object rỗng `{}` — **không phải** `null`/không tồn tại field.
- Với phòng dài (> ngưỡng cấu hình, xử lý theo "Light Summary" nhiều đoạn), `action_items` là kết quả **gộp** từ `action_items` của từng đoạn (section) theo cùng key `participant_identity` — cùng một người xuất hiện ở nhiều đoạn sẽ có task được nối (`extend`) vào chung một mảng, không bị ghi đè.

Ví dụ dùng trong code (JS/TS phía client):

```ts
const items = summary.summary_data.action_items ?? {};
for (const [participantId, tasks] of Object.entries(items)) {
  if (participantId === "general") {
    // việc chưa gán được người phụ trách cụ thể
    continue;
  }
  // participantId khớp trực tiếp với participants[] / messages[].participant_id
  renderActionItemsForUser(participantId, tasks);
}
```

---

## 7. Queue Monitoring API (`/api/v2/queue`)

Giám sát các hàng đợi Redis Stream dùng cho pipeline xử lý (transcription, TTS, …) — tự động phát hiện queue tồn tại trong Redis, không cần đăng ký thủ công.

### `GET /queue/list`

**Auth:** JWT Bearer · **Quyền:** `queues:view_stats`
Danh sách toàn bộ queue phát hiện được.

```json
{ "count": 2, "queues": [
  { "queue_name": "transcription", "stream_key": "queue:transcription",
    "stream_length": 4, "active_workers": 2, "exists": true }
]}
```

### `GET /queue/overview`

**Auth:** JWT Bearer · **Quyền:** `queues:view_stats`
Thống kê tổng hợp mọi queue trong một lần gọi — phù hợp cho dashboard.

```json
{
  "count": 2, "timestamp": 1730450000.12,
  "queues": { "transcription": { "...": "QueueStatsResponse" }, "tts": { "...": "..." } }
}
```

### `GET /queue/{queue_name}/stats`

**Auth:** JWT Bearer · **Quyền:** `queues:view_stats`
Thống kê chi tiết một queue.

```json
{
  "queue_name": "transcription", "stream_key": "queue:transcription",
  "stream_length": 4, "pending_count": 1,
  "total_enqueued": 982, "total_processed": 975, "total_failed": 3,
  "active_workers": 2, "error": null
}
```

### `GET /queue/{queue_name}/task/{task_id}`

**Auth:** JWT Bearer · **Quyền:** `queues:view_stats`
Trạng thái một task cụ thể. `404` nếu queue hoặc task không tồn tại.

```json
{
  "task_id": "tsk_9f2...", "status": "completed", "filename": "chunk_012.wav",
  "created_at": 1730449000.0, "started_processing_at": 1730449001.2,
  "completed_at": 1730449003.9, "result": "...", "error": null
}
```

### `GET /queue/{queue_name}/pending`

**Auth:** JWT Bearer · **Quyền:** `queues:view_stats`
Danh sách task đang chờ/đang xử lý trong queue.

### `GET /queue/{queue_name}/dlq`

**Auth:** JWT Bearer · **Quyền:** `queues:view_stats`
Task đã thất bại vĩnh viễn (vượt quá số lần retry, mặc định 3) nằm trong Dead Letter Queue.

Query params:

| Field | Kiểu | Mặc định |
|---|---|---|
| `limit` | int | 100 |

```json
{ "queue_name": "transcription", "count": 1,
  "dlq_stream_key": "queue:transcription:dlq",
  "tasks": [{ "...": "PendingTask + dead_letter_at, final_error, retry_count" }] }
```

### `POST /queue/{queue_name}/dlq/retry/{task_id}`

**Auth:** JWT Bearer · **Quyền:** `queues:view_stats`
Đẩy lại một task từ DLQ vào queue xử lý chính.

```json
{ "queue_name": "transcription", "success_count": 1,
  "failed_count": 0, "total": 1,
  "message": "Successfully retried task tsk_9f2..." }
```

---

## 8. SSE — Transcript

Kênh phát trực tiếp nội dung transcript (kết quả STT) của một phòng qua Server-Sent Events.

### `GET /sse/stream_transcript`

**Auth:** JWT Bearer · **Quyền:** `rooms:view_all`
Client (frontend) mở kết nối này để nhận transcript realtime của một phòng đang diễn ra.

Query params:

| Field | Bắt buộc | Mô tả |
|---|---|---|
| `room` | có | Tên phòng cần theo dõi |

Response: `Content-Type: text/event-stream` — mỗi sự kiện là một transcript segment mới trong phòng, giữ kết nối mở cho đến khi client đóng hoặc server shutdown.

### `POST /push_transcript`

**Auth:** API Key (nội bộ)
STT pipeline gọi endpoint này để phát một đoạn transcript mới tới mọi client SSE đang lắng nghe phòng đó.

Request body:

```json
{
  "room_name": "my-room-123",
  "message": "xin chào mọi người",
  "message_type": "final",
  "participant_identity": "user_1"
}
```

Response `200`:

```json
{ "status": "ok", "room": "my-room-123",
  "message": "xin chào mọi người", "message_type": "final",
  "active_connections": 3, "broadcast_to": 3 }
```

---

## 9. SSE — Chat external

Kênh cho bot bên ngoài (Mezon bot) nhận tin nhắn chat phát sinh trong phòng gọi.

### `GET /sse/chat_external`

**Auth:** JWT Bearer · **Quyền:** `chat_external:view_all`
Bot mở kết nối này (đăng nhập bằng `/auth/mezon/bot/login`) để nhận toàn bộ sự kiện chat external theo thời gian thực.

### `POST /agent_push_chat_external`

**Auth:** API Key (nội bộ)
Agent LiveKit gọi khi có participant gửi tin nhắn chat trong phòng, để phát cho mọi bot đang lắng nghe.

Request body:

```json
{
  "room_name": "my-room", "room_id": "room-12345",
  "participant_identity": "user@example.com",
  "message": "Hello from room",
  "time": "2026-03-01T10:30:00Z"
}
```

Response `200`:

```json
{ "status": "ok", "room_name": "my-room",
  "room_id": "room-12345", "participant_identity": "user@example.com",
  "message": "Hello from room", "time": "2026-03-01T10:30:00Z",
  "active_connections": 2, "broadcast_to": 2 }
```

---

## 10. SSE — Metadata sự kiện

Vòng đời phiên gọi (bắt đầu / kết thúc / ghi âm xong / tóm tắt xong) — vừa phát realtime qua SSE, vừa lưu lịch sử (TTL 3 ngày) để tra cứu qua REST.

### `GET /sse/metadata`

**Auth:** JWT Bearer · **Quyền:** `metadata_events:view_all`
Bot mở kết nối để nhận mọi sự kiện vòng đời phòng theo thời gian thực.

### `POST /push_metadata/session_started` · `/session_ended` · `/session_record_done` · `/session_summary_done`

**Auth:** API Key (nội bộ)
4 endpoint tương ứng 4 loại sự kiện, do agent / record-service gọi để phát tới bot đang lắng nghe. Cùng response shape `MetadataPushResponse`.

Request body theo loại event:

| Event | Body |
|---|---|
| `session_started` | `{ room_id, room_name }` |
| `session_ended` | `{ room_id, room_name, duration_seconds? }` |
| `session_record_done` | `{ room_id, room_name }` — file kết quả tự lấy từ PostgreSQL theo `room_id` |
| `session_summary_done` | `{ room_id, room_name }` |

Response `200`:

```json
{
  "status": "ok", "event_type": "room_ended",
  "event_id": "a1b2c3...", "room_id": "abc123",
  "room_name": "Interview Room 1", "timestamp": "2026-03-01T10:30:00Z",
  "active_connections": 2, "broadcast_to": 2,
  "duration_seconds": 3600
}
```

### `GET /metadata`

**Auth:** JWT Bearer · **Quyền:** `metadata_events:view_all`
Tra cứu lịch sử sự kiện (lưu tối đa 3 ngày, tự động xoá theo TTL).

Query params:

| Field | Kiểu | Mặc định |
|---|---|---|
| `event_type` | enum | — |
| `room_id` | uuid | — |
| `from_utc` / `to_utc` | datetime | — |
| `limit` | int | 100 (1–1000) |
| `skip` | int | 0 |
| `sort_order` | `asc`\|`desc` | desc |

4 giá trị `event_type`: `room_started`, `room_ended`, `room_record_done`, `room_summary_done`.

Response `200`:

```json
{ "status": "ok", "total": 57, "limit": 100, "skip": 0,
  "ttl_seconds": 259200,
  "data": [{ "id": "...", "event_id": "...", "event_type": "room_ended",
    "room_id": "...", "room_name": "...", "metadata": { "...": "..." },
    "timestamp": "...", "created_at": "..." }] }
```

### `GET /metadata/{event_id}`

**Auth:** JWT Bearer · **Quyền:** `metadata_events:view_all`
Chi tiết một sự kiện metadata theo UUID. Trả `{ "status": "ok", "data": {...} }` cùng cấu trúc phần tử ở trên.

---

## 11. SSE — Agent requests

Kênh để orchestrator gửi lệnh điều khiển xuống agent LiveKit đang chạy trong một phòng (bật/tắt transcript, phát TTS, gửi tin nhắn chat).

### `GET /sse/agent-requests`

**Auth:** API Key (nội bộ)
Chính agent LiveKit mở kết nối này khi vào phòng, để nhận lệnh điều khiển theo thời gian thực.

Query params:

| Field | Bắt buộc | Mô tả |
|---|---|---|
| `agent_id` | có | Định danh agent |
| `room_name` | có | Phòng agent đang phục vụ |

### `POST /dispatch/agent-request`

**Auth:** JWT Bearer · **Quyền:** `agent:control`
Gửi một lệnh tới agent đang kết nối SSE. Trường `payload.request_type` quyết định schema còn lại (discriminated union) — có 3 loại lệnh.

Request body — field chung:

| Field | Kiểu | Mô tả |
|---|---|---|
| `room_name` | string | Phòng chứa agent đích |
| `agent_id` | string | Định danh agent đích |
| `payload` | object | Một trong 3 dạng bên dưới |

`payload` — `transcript_control`:

```json
{ "request_type": "transcript_control", "action": "enable" }
```
(`action` là `"enable"` hoặc `"disable"`.)

`payload` — `send_chat_message`:

```json
{ "request_type": "send_chat_message", "message": "Hello from orchestrator!" }
```

`payload` — `tts_play`:

```json
{
  "request_type": "tts_play",
  "text": "Hello from orchestrator",
  "sender_identity": "orchestrator",
  "voice": "af_heart",
  "speed": 1.0
}
```

`voice` (tuỳ chọn) — một trong: `af_heart`, `af_bella`, `af_sarah`, `am_adam`, `am_michael`, `bf_emma`, `bf_isabella`, `bm_george`, `bm_lewis`. `speed` (tuỳ chọn) trong khoảng 0.5–2.0.

Response `200`:

```json
{ "status": "ok", "request_id": "req_9c1...",
  "request_type": "tts_play", "context": "room:my-room-123:agent_123",
  "active_agents": 1, "sent_to": 1 }
```

---

## 12. Room Registry API (`/api/v2/room-registry` — nội bộ)

> **Chỉ dành cho service nội bộ** (agent LiveKit, agents-bot). Đây là nơi orchestrator biết một tên phòng Mezon hiện đang ánh xạ tới phiên gọi (`room_id`) nào, để webhook/route sự kiện đúng chỗ.

### `POST /room-registry/register`

**Auth:** API Key
Agent gọi khi bắt đầu phục vụ một phòng. Đăng ký mới luôn ghi đè đăng ký cũ cùng tên phòng (kênh voice Mezon là pool cố định, tái sử dụng tên).

```json
{ "room_name": "my-room-123",
  "room_id": "b3f1c2a4-4e5d-4a1b-9c3e-7a2f6d8e9c10" }
```

`room_id` là UUID do chính agent sinh ra và làm chủ vòng đời — gọi lại với cùng cặp giá trị là idempotent.

Response `200`:

```json
{ "status": "ok", "message": "Room 'my-room-123' registered successfully",
  "room_name": "my-room-123", "room_id": "b3f1c2a4-..." }
```

### `POST /room-registry/participant-joined`

**Auth:** API Key
Agent báo có participant mới tham gia phòng (chỉ gửi Mezon user id — việc resolve username thuộc về agents-bot).

```json
{ "room_name": "my-room-123", "room_id": "b3f1c2a4-...",
  "participant_identity": "123456789" }
```

Response `200`:

```json
{ "status": "ok",
  "room_name": "my-room-123", "room_id": "b3f1c2a4-...",
  "participant_identity": "123456789" }
```

(`status` có thể là `"ok"` hoặc `"ignored_stale_session"`.)

### `POST /room-registry/unregister`

**Auth:** API Key
Agent gọi khi rời phòng — chốt trạng thái phiên gọi trong STT service. Nếu tên phòng đã bị một phiên mới chiếm lại, registry giữ nguyên (chỉ chốt phiên của chính caller).

```json
{ "room_name": "my-room-123", "room_id": "b3f1c2a4-..." }
```
(`room_id` tuỳ chọn.)

Response `200` / `404`:

```json
{ "status": "ok", "message": "Room 'my-room-123' unregistered successfully",
  "room_name": "my-room-123" }
```

### `GET /room-registry/status/{room_name}`

**Auth:** API Key
Kiểm tra một tên phòng có đang được đăng ký không.

```json
{ "room_name": "my-room-123", "registered": true, "room_id": "b3f1c2a4-..." }
```

### `GET /room-registry/list`

**Auth:** API Key
Toàn bộ phòng đang được đăng ký (đang mở).

```json
{ "status": "ok", "total": 2,
  "rooms": { "my-room-123": "b3f1c2a4-...", "my-room-456": "c4a2d3b5-..." } }
```

### `DELETE /room-registry/clear-all`

**Auth:** API Key

> **Phá huỷ toàn bộ:** xoá mọi đăng ký phòng hiện có. Chỉ dùng cho vận hành/khắc phục sự cố, không gọi trong luồng nghiệp vụ bình thường.

```json
{ "status": "ok", "message": "Cleared 2 rooms from registry", "cleared_count": 2 }
```

---

## 13. Recording Events API (`/api/v2/recordings` — nội bộ)

> **Webhook nội bộ:** record-service và audio-processing-service post sự kiện vòng đời file ghi âm về đây. Idempotent theo thiết kế — gọi lại nhiều lần với cùng payload là an toàn.

### `POST /recordings/events`

**Auth:** API Key
Một endpoint duy nhất xử lý 3 họ sự kiện, phân biệt bằng field `event` (discriminated union).

**1. Sự kiện ghi âm — record-service gửi**

| Field | Kiểu | Mô tả |
|---|---|---|
| `event` | enum | `recording.started` \| `recording.completed` \| `recording.failed` |
| `recording_id` | string | `room_id:track_id` |
| `room_id`, `track_id` | string | Định danh phòng / track |
| `participant_identity` | string | Người nói tạo ra track |
| `source`, `sample_rate`, `channels` | — | Thông số audio |
| `bucket`, `object_key` | string | Vị trí file trong object storage |
| `status` | string | Trạng thái ghi |
| `started_at`, `ended_at?`, `duration_seconds?` | float | Mốc thời gian (epoch) |
| `raw_bytes_received`, `dropped_frame_count` | int | Mặc định 0 |
| `quality_annotations` | array | `[{start_offset_ms, end_offset_ms?, reason}]` |

**2. Sự kiện derivative — audio-processing-service gửi**

```json
{ "event": "derivative.completed",
  "recording_id": "...",
  "bucket": "...", "object_key": "...", "error": null }
```
(`event` cũng có thể là `"derivative.failed"`.)

**3. Sự kiện TTS transcript — agent gửi**

```json
{ "event": "tts.transcript",
  "room_id": "...", "track_id": "...",
  "text": "...", "start": 0.0, "end": 2.4 }
```
(`event` cũng có thể là `"tts.completed"`.)

Response `200` (mọi loại):

```json
{ "received": true, "action": "upserted", "error": null }
```

---

## 14. Xử lý lỗi

Mọi lỗi (validation, HTTP, hoặc lỗi nghiệp vụ) đều trả về cùng một khuôn dạng chuẩn:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Request validation failed",
  "details": [
    { "location": ["query", "limit"], "message": "Input should be less than or equal to 500", "type": "less_than_equal" }
  ]
}
```

| HTTP | code | Khi nào xảy ra |
|---|---|---|
| 401 | `HTTP_401` | Thiếu/sai/hết hạn JWT hoặc API Key |
| 403 | `HTTP_403` | JWT hợp lệ nhưng thiếu permission yêu cầu |
| 404 | `HTTP_404`, `QUEUE_NOT_FOUND`, `SUMMARY_RETRY_NOT_FOUND` | Không tìm thấy tài nguyên (phòng, queue, task…) |
| 422 | `VALIDATION_ERROR` | Body/query param sai kiểu hoặc vi phạm ràng buộc (độ dài, pattern, khoảng giá trị) |
| 500 | `INTERNAL_SERVER_ERROR` | Lỗi không mong muốn phía server |

> **Ràng buộc dữ liệu thường gặp:** tên phòng (`room_name`) chỉ chấp nhận `a-z A-Z 0-9 _ - .`, dài 1–128 ký tự; phân trang mặc định `limit=100` (tối đa 500), `skip` tối đa 100000.

---

## 15. Endpoint cũ (deprecated)

> **Không dùng cho tích hợp mới.** Song song với `/api/v2/...`, orchestrator vẫn đang mount một bộ endpoint cũ hơn trực tiếp dưới `/api/...` (không có `/v2`) để tương thích ngược. Một số trong đó **hoàn toàn không có xác thực** — bản thân code đã đánh dấu TODO để gỡ bỏ. Chỉ liệt kê ở đây để nhận diện và tránh vô tình public chúng ra ngoài; đừng tích hợp mới vào các path này.

| Path cũ | Thay bằng | Vấn đề |
|---|---|---|
| `GET /api/sse/stream_transcript` | `/api/v2/sse/stream_transcript` | Xác thực bằng query `appid`+`token` gọi thẳng Mezon mỗi lần connect, không theo permission model |
| `POST /api/push_transcript` | `/api/v2/push_transcript` | **Không có xác thực** |
| `GET /api/sse/chat_external` | `/api/v2/sse/chat_external` | Xác thực bằng query `appid`+`token` |
| `POST /api/agent_push_chat_external` | `/api/v2/agent_push_chat_external` | **Không có xác thực** |
| `GET /api/sse/metadata` | `/api/v2/sse/metadata` | Xác thực bằng query `appid`+`token` |
| `POST /api/push_metadata/*` | `/api/v2/push_metadata/*` | **Không có xác thực** |
| `GET /api/sse/agent-requests` | `/api/v2/sse/agent-requests` | **Không có xác thực** |
| `POST /api/dispatch/agent-request` | `/api/v2/dispatch/agent-request` | **Không có xác thực** |
| `GET /api/summary/room/{room_name}` | `/api/v2/summary/room/{room_name}` | **Không có xác thực** (comment trong code xác nhận đây là lý do cần xoá) |
| `GET /api/summary/room/id/{room_id}` | `/api/v2/summary/room/id/{room_id}` | **Không có xác thực** |

---

Tài liệu tổng hợp từ mã nguồn `orchestrator_service` (FastAPI, cổng mặc định 8002) trong monorepo Mezon Call Translation — bám sát router, model Pydantic và middleware xác thực thực tế tại thời điểm viết.
