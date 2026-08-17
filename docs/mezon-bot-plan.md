# Mezon Bot — Phân Tích & Kế Hoạch (F2)

> Kế hoạch cho khối **F2** trong `docs/planning-v3.md`. F0 (delivery layer) đã xong 2026-08-17 và là nền cho mục R4 dưới đây.
>
> Mọi thông tin về SDK trong tài liệu này **lấy từ source thật** (`github.com/mezonai/mezon-js`, `packages/mezon-sdk/src/`), không lấy từ file docs — xem mục I để biết vì sao.

---

# I. Về Tài Liệu Mezon: Cái Bẫy Đầu Tiên

File `docs/mezon-sdk-docs.md` được đưa **không mô tả embed, button, form, hay component**. Nó có bảng "Documentation Gaps" tự thừa nhận điều đó. Nếu xây theo nó, phần quan trọng nhất của yêu cầu (form nhập liệu) sẽ không có căn cứ nào.

Nguồn thật, đã đọc trực tiếp:

| Thứ cần | File |
|---|---|
| Cấu trúc message, embed, component, enum | `packages/mezon-sdk/src/interfaces/client.ts` |
| Builder cho embed + input field | `packages/mezon-sdk/src/mezon-client/structures/InteractiveMessage.ts` |
| Builder cho button | `packages/mezon-sdk/src/mezon-client/structures/ButtonBuilder.ts` |
| Payload sự kiện bấm nút | `packages/mezon-sdk/src/rtapi/realtime.ts` (`MessageButtonClicked`) |
| Gửi DM, sửa message | `structures/User.ts`, `structures/Message.ts` |
| Danh sách event | `packages/mezon-sdk/src/constants/enum.ts` |

**Kết luận: coi source là nguồn sự thật, docs chỉ là chỉ dẫn.** Điều này cũng có nghĩa API có thể đổi mà docs không đổi — nên phần bot phải cô lập SDK sau một lớp mỏng của mình.

---

# II. Những Gì Mezon Thật Sự Hỗ Trợ

## 2.1 Hình dạng một message

```ts
ChannelMessageContent {
  t?: string                          // text thuần
  embed?: IInteractiveMessageProps[]  // rich display
  components?: IMessageActionRow[]    // button / select ở dưới message
  mk?: MarkdownOnMessage[]            // đánh dấu vùng markdown theo index
}
```

## 2.2 Embed

```ts
IInteractiveMessageProps {
  color?, title?, url?, description?, timestamp?
  author?:    { name, icon_url?, url? }
  thumbnail?: { url }
  image?:     { url, width?, height? }
  footer?:    { text, icon_url? }
  fields?: Array<{
    name, value, inline?,
    options?: any[], inputs?: {}, max_options?: number   // ← phần quan trọng
  }>
}
```

## 2.3 **Phát hiện then chốt: Mezon KHÔNG có modal riêng**

Đây là điểm khác Discord và là thứ định hình toàn bộ thiết kế R1.

**Form = một embed mà các `field` mang `inputs`, cộng một action row có nút submit.** Không có popup, không có `showModal()`. `InteractiveBuilder` chứng minh điều đó:

```ts
addInputField(id, name, placeholder?, options?, description?)   // type INPUT
addSelectField(id, name, options[], valueSelected?, description?)
addRadioField(id, name, options[], description?, max_options?)  // max_options ⇒ multi-select
addDatePickerField(id, name, description?)
```

Loại component:

```ts
enum EMessageComponentType { BUTTON=1, SELECT=2, INPUT=3, DATEPICKER=4, RADIO=5, ANIMATION=6, GRID=7 }
enum EButtonMessageStyle  { PRIMARY=1, SECONDARY=2, SUCCESS=3, DANGER=4, LINK=5 }
```

**Điều này TỐT HƠN modal cho ca dùng của Cortex**, không phải hạn chế:

1. Form **nhìn thấy được trong lịch sử chat**, không biến mất sau khi submit. Người dùng cuộn lên vẫn thấy mình đã nhập gì.
2. `InputFieldOption.defaultValue` cho phép **điền sẵn**. Nghĩa là AI trích ra một task rồi trình form đã điền sẵn để user xác nhận/sửa — khớp *chính xác* với `TaskStatus.PENDING_CONFIRM` đã có sẵn trong schema. Luồng này không phải nghĩ mới, nó đã tồn tại và chỉ thiếu bề mặt hiển thị.
3. `DATEPICKER` là component có sẵn ⇒ `due_date` không phải parse chuỗi tiếng Việt.

## 2.4 Nhận kết quả

```ts
MessageButtonClicked {
  message_id, channel_id, button_id, sender_id, user_id,
  extra_data: string          // ← giá trị các input nằm ở đây
}
DropdownBoxSelected {
  message_id, channel_id, selectbox_id, sender_id, user_id, values: string[]
}
```

> ⚠️ **`extra_data` khai kiểu `string`, SDK không khai schema bên trong.** Đây là ẩn số duy nhất còn lại và nó chặn R1. Phải đo thực nghiệm — xem M0.

## 2.5 Gửi DM và sửa message

```ts
user.sendDM(content, code?, attachments?)   // tự tạo DM channel nếu chưa có
message.update(content, mentions?, attachments?)
```

`sendDM` gửi với `clan_id: "0"`, `channel_type: CHANNEL_TYPE_DM`. `update` đi qua socket (`socketManager.updateChatMessage`) chứ không phải HTTP — **đây là thứ làm cho giả-realtime khả thi** (R3).

Mọi lệnh gửi/sửa đều đã đi qua `AsyncThrottleQueue` (`messageQueue.enqueue`) của SDK, nên rate-limit ở tầng transport có sẵn. **Nhưng nó không thay thế việc tự tiết chế số lần edit** — hàng đợi chỉ xếp lốt, không gộp.

## 2.6 Không có command framework

Xác nhận: SDK không có parser, không có prefix routing. Nghe `Events.ChannelMessage` rồi tự tách chuỗi. Prefix `*` theo yêu cầu là lựa chọn của ta, không phải quy ước của Mezon.

## 2.7 Ràng buộc lớn nhất: **SDK chỉ có TypeScript**

Không có SDK Python. Backend Cortex là Python. ⇒ **Bot bắt buộc là một service Node riêng.** Đây không phải lựa chọn kiến trúc, đây là ràng buộc.

---

# III. Phía Cortex Đã Có Sẵn Gì

## 3.1 Vốn quý nhất: agent đã stream ra một bộ event sạch

`AgentService.handle_streaming_generator` (`app/ai/agents/agent_service.py`) đã yield đúng những thứ cần để render:

| Event | Payload | Render sang Mezon thế nào |
|---|---|---|
| `token` | `text` | Nối vào buffer, edit message (R3) |
| `reasoning_token` | `text` | Bỏ hoặc thu gọn — không đổ vào chat |
| `tool_start` | `tool_name`, `tool_args` | Dòng trạng thái tạm "🔧 đang tạo task…" |
| `tool_result` | `tool_name`, `success`, `result`, `error` | Thay dòng trạng thái bằng kết quả |
| `ask_choice` | `questions[]` | **Radio field + nút submit** — gần như 1:1 |
| `plan_proposal` | `proposal_id`, `item_count` | Embed + nút Đồng ý / Bỏ qua |
| `note_diff` | `proposal_id`, `note_id` | Embed diff + nút áp dụng |
| `error` / `done` | | Chốt lần edit cuối |

**`ask_choice` và `plan_proposal` map thẳng sang radio field và button của Mezon.** Đây là lý do mạnh nhất để tin rằng embed của Mezon "đủ dùng" — không phải vì nó giàu, mà vì nó khớp đúng những gì agent đã phát ra.

## 3.2 Ba thứ đã có, không được xây lại trong bot

- **Tool registry + permission + `revert_action`** (`app/ai/agents/tool_registry.py`, `action_snapshot_store.py`). Bot tạo task bằng đường riêng ⇒ mất audit trail và mất khả năng revert.
- **Delivery layer F0** (`app/services/delivery/`). Notification qua bot là **một adapter**, không phải một đường mới.
- **Memory system** (`memory_extraction_service.py`, `semantic_memory_provider.py`, `zep_memory.py`). Đây mới là chỗ chứa tính liên tục xuyên bề mặt — không phải một conversation khổng lồ dùng chung.

## 3.3 Ba khoảng trống thật, phải sửa ở backend

**(a) `/api/agent/stream/chat` không nhận internal auth.**
Nó dùng `get_current_active_user` (chỉ JWT), trong khi các endpoint khác dùng `get_current_user_or_internal` (chấp nhận `X-Internal-API-Key` + `X-User-ID`). Bot là service, không có JWT của user. ⇒ phải đổi dependency.
*Kèm hệ quả bảo mật cần nói rõ:* internal key + `X-User-ID` nghĩa là **ai giữ key đó hành động được với tư cách bất kỳ user nào**. Bot phải nằm trong mạng nội bộ, key không bao giờ ra tới client.

**(b) `AgentMessage` không có cột nguồn.**
Không phân biệt được "user gõ trên web", "user gõ trên Mezon", "đây là thông báo chủ động chứ không phải trả lời ai". R5 cần cột này.

**(c) ⚠️ `save_message` GỘP hai message liên tiếp cùng role — đây là mìn cho R5.**

```python
if last_msg and last_msg.role == normalized_role:
    last_msg.content = normalized_content   # GHI ĐÈ, không phải thêm mới
```

Nếu lưu thông báo dưới role `assistant` mà message trước cũng là `assistant`, **thông báo trước bị xoá trắng**. Hai thông báo liên tiếp ⇒ mất cái đầu. Yêu cầu R5 theo đúng lời sẽ mất dữ liệu ngay ngày đầu. Cơ chế gộp này tồn tại có lý do (giữ luân phiên user/assistant cho LLM), nên **không được gỡ** — phải cho message hệ thống một đường đi khác.

---

# IV. Kiến Trúc

```
        Mezon gateway
             │ websocket (mezon-sdk, Node)
             ▼
   ┌──────────────────────┐
   │  mezon_bot/  (Node)  │   ← service MỚI, mỏng
   │  · router lệnh *     │
   │  · builder embed/form│
   │  · streaming-by-edit │
   │  · /internal/deliver │◄──┐
   └──────────┬───────────┘   │ HTTP
              │ HTTP           │
   X-Internal-API-Key          │
   X-User-ID                   │
              ▼                │
   ┌──────────────────────────┴────────┐
   │  Cortex backend (Python)          │
   │  /api/agent/stream/chat   R2,R3   │
   │  /api/tasks, /api/schedules  R1   │
   │  delivery/mezon.py adapter   R4 ──┘
   │  agent_messages (+source)    R5   │
   └───────────────────────────────────┘
```

## Nguyên tắc: **bot mỏng**

Bot chỉ làm hai việc: **transport** và **render**. Không chứa logic nghiệp vụ.

> **Phép thử:** nếu bot phải tự quyết một task hợp lệ hay không, một ngày là ngày nào, có được phép sửa không — thì nó đã sai vị trí. Những câu đó đã có người trả lời ở backend rồi.

Lý do không chỉ là gọn: `revert_action`, `ActionSnapshotStore`, kiểm tra quyền workspace, và Attention Gate đều nằm ở backend. Một đường tắt trong bot là một đường không có bất kỳ thứ nào trong số đó.

## Chiều ngược: backend gọi bot thế nào (R4)

Adapter `mezon.py` chạy trong `DeliveryWorker` (Python) cần gửi được tới Mezon (Node). Hai cách:

| | Ưu | Nhược |
|---|---|---|
| **HTTP: backend → `POST /internal/deliver` của bot** (khuyến nghị) | Lỗi HTTP map thẳng sang `DeliveryResult.retry()` / `.dead_address()`, tái dùng nguyên retry + backoff + `attempts` của F0 | Bot phải mở port nội bộ |
| Redis pub/sub | Không cần port | Fire-and-forget: **mất đúng phần retry vừa xây ở F0**, và không biết gửi thành công hay không để ghi `delivered_at` |

Chọn HTTP. F0 đã trả tiền cho cơ chế retry rồi, không nên vứt đi ở bước cuối.

---

# V. Năm Yêu Cầu — Thiết Kế Cụ Thể

## R1 · Lệnh `*create_event` → form

**Luồng:**
```
user gõ "*create_task"
  → bot dựng embed: addInputField("title") + addInputField("description", textarea)
                    + addDatePickerField("due_date") + addRadioField("priority", [low..urgent])
                    + ButtonBuilder: [Tạo] PRIMARY, [Huỷ] SECONDARY
  → user điền, bấm Tạo
  → MessageButtonClicked { button_id: "task_create:submit", extra_data: "..." }
  → bot parse extra_data → POST /api/tasks (internal auth, X-User-ID)
  → bot message.update(...) → embed kết quả, form biến thành phiếu xác nhận
```

**Danh mục lệnh sinh từ backend, không hard-code trong bot.** Đây là bài học đã trả giá của 4.2 (Trigger Catalog): danh sách hard-code ở frontend đã phải gỡ ra và thay bằng catalog động. Lặp lại lỗi đó ở bot là biết mà vẫn làm. ⇒ `GET /api/agent/commands/catalog` trả về schema field, bot dựng form từ đó. Thêm lệnh = sửa backend, không đụng bot.

**Không tự tạo task trong bot** — gọi đúng endpoint web đang gọi.

## R2 · DM thường → AI

Bot phân biệt: chuỗi bắt đầu bằng `*` → router lệnh; còn lại → chuyển thẳng vào agent.

Cần (a) ở mục 3.3: đổi `stream_chat` sang `get_current_user_or_internal`.

**Ánh xạ user:** Mezon `user_id` ↔ Cortex `users.id`. Chỗ lưu đã có sẵn từ F0: một dòng `user_channels` với `channel = mezon`, `address = mezon_user_id`. Không cần bảng mới.

**Luồng liên kết** (`requires_verification = True` cho kênh này — địa chỉ do người dùng khai, không phải bằng chứng sở hữu):
```
web /settings → "Liên kết Mezon" → sinh mã 6 số, TTL 10 phút
user DM bot: *link 123456
bot → POST /api/preferences/channels/verify → verified_at được set
```
Thứ tự này (mã sinh từ web, dán vào Mezon) chứ không phải ngược lại: người đang đăng nhập web mới là người chứng minh được họ sở hữu tài khoản Cortex.

## R3 · Giả-realtime bằng `message.update`

```
nhận event "token" → nối vào buffer
   ├── lần edit đầu: sau ~500ms (đủ để có nội dung, đủ nhanh để thấy phản hồi)
   ├── các lần sau: mỗi ~1000ms HOẶC mỗi ~80 ký tự, tuỳ cái nào tới trước
   └── "done" → edit lần cuối, có đủ footer/token usage
```

Ba điều bắt buộc, mỗi điều đều là một cách hỏng thật:

1. **Tiết chế là bắt buộc, không phải tối ưu.** `AsyncThrottleQueue` của SDK chỉ *xếp hàng*, không *gộp*. Edit mỗi token ⇒ hàng đợi phình vô hạn và message nhấp nháy.
2. **Gửi tin nhắn "⏳ đang nghĩ…" trước, rồi edit nó.** Không đợi token đầu tiên mới gửi — độ trễ tới token đầu là chỗ người dùng cảm thấy lâu nhất.
3. **`tool_start` là dòng trạng thái tạm**, bị thay khi `tool_result` về. Nếu không, một câu trả lời có 3 tool call sẽ để lại 3 dòng rác giữa nội dung.

## R4 · Thông báo qua bot — **đây là chỗ F0 trả cổ tức**

```python
# app/services/delivery/mezon.py   ← toàn bộ phần backend là file này
class MezonAdapter:
    channel = AttentionChannel.MEZON
    default_min_level = AttentionLevel.RECOMMEND
    inline = False
    requires_verification = True

    async def send(self, payload, user_channel) -> DeliveryResult: ...
```
cộng một dòng `register(MezonAdapter())` trong `registry.py`.

**Không sửa `attention_gate.py`, `notifications.py`, hay `delivery_worker.py`.** Đó đúng là tiêu chí nghiệm thu đã ghi ở mục XI của `planning-v3.md`. Nếu R4 buộc phải sửa một trong ba file đó thì F0 hỏng và phải sửa F0.

`default_min_level = RECOMMEND` (không phải INFORM): DM là kênh xâm nhập hơn in-app. `task.at_risk` (ASK) và `task.overdue`/`blocked_cascade` (RECOMMEND) qua được; `task.stale`, `day.review`, `schedule.starts_soon` (INFORM) ở lại trong web. Người dùng tự hạ xuống được nếu muốn.

Ánh xạ lỗi → outcome (quyết định cái này lúc viết adapter, không phải lúc gặp sự cố):
- bot trả 5xx / timeout → `retry()`
- user chặn bot / DM channel không tạo được → `dead_address()` ⇒ F0 tự tắt kênh
- payload sai định dạng → `permanent()`

## R5 · Mọi thứ vào lịch sử hội thoại

**Quyết định: một conversation "Mezon DM" dài hạn cho mỗi user, không phải mỗi chủ đề một cái.** DM là một dòng liên tục, và `ConversationSummarizer` đã có sẵn để giữ nó không phình.

**Không dùng chung conversation với web.** Tính liên tục xuyên bề mặt thuộc về **memory** (`semantic_memory_provider`, `zep_memory`) — đó là thứ được thiết kế để nhớ xuyên hội thoại. Nhét web và Mezon vào một conversation sẽ làm hỏng cả UI web (danh sách hội thoại) lẫn context window, để đổi lấy thứ memory đã làm tốt hơn.

**Việc phải làm ở schema — đây là phần khó, xem 3.3(c):**

1. Thêm `AgentMessage.source` — `web` | `mezon` | `system`. Để AI biết "cái này tôi *thông báo*, không phải tôi *trả lời*".
2. **Cho message `system` đi vòng qua cơ chế gộp.** Cơ chế gộp giữ luân phiên user/assistant cho LLM và phải giữ nguyên; message thông báo cần một đường riêng, hoặc một role riêng, hoặc một cờ `allow_consecutive`. Chọn cách nào là quyết định lúc làm M2 — nhưng **phải chọn trước khi gửi thông báo đầu tiên**, vì lịch sử đã mất thì không dựng lại được.

Nội dung ghi vào history khi có thông báo:
```
[system/mezon] Đã nhắc: "Task X quá hạn 3 ngày" (reason_key=task.overdue, level=recommend)
```
Đủ để lượt sau AI không nhắc lại chính nó, và trả lời được "sao anh không nói sớm".

---

# VI. Milestones

| M | Việc | Vì sao ở vị trí này |
|---|---|---|
| **M0** | **Probe `extra_data`** — ✅ **Xong 2026-08-17** trên gateway thật. Còn 1 mảnh (select/radio/date) chỉ chặn M5. Xem VIII bis | **Chặn R1.** Encoding không có trong type. Không đo thì M5 xây trên phỏng đoán |
| **M1** | ✅ **Xong 2026-08-17.** Bot skeleton + liên kết tài khoản, đã chạy thật đầu-cuối. Xem mục XII | Không có ánh xạ user thì không có gì khác chạy được |
| **M2** | Schema R5 (cột `source` + xử lý gộp) **+** adapter `mezon.py` + `/internal/deliver` | Schema đi **trước** thông báo đầu tiên, vì lịch sử mất rồi không dựng lại được. Đây cũng là bài kiểm tra tiêu chí nghiệm thu của F0 |
| **M3** | R2 + R3: internal auth cho `stream/chat`, chat qua DM, streaming-by-edit | Giá trị lớn nhất cho người dùng, và tự nhiên ghi lượt chat vào history |
| **M4** | Render `ask_choice` / `plan_proposal` / `note_diff` sang embed + button | Cần M0 xong. Đây là lúc bot thành hai chiều thật |
| **M5** | R1: `GET /commands/catalog` + router lệnh + form | Nhiều bề mặt nhất, phụ thuộc M0 và M4 |

**M2 trước M3 có chủ đích.** M2 là thứ nhỏ nhất giao được đúng lý do bot tồn tại — *Cortex nói được khi user đã tắt web*. M3 to hơn, hay hơn, nhưng nếu chỉ làm được một cái thì M2 mới là cái đáng.

---

# VII. Rủi Ro Đã Nhận Diện

| Rủi ro | Mức | Xử lý |
|---|---|---|
| `extra_data` không phải JSON phẳng | **Cao** | M0 đo trước mọi thứ khác |
| Edit quá dày ⇒ nghẽn hàng đợi / nhấp nháy | Cao | Tiết chế theo thời gian *và* theo số ký tự; test với câu trả lời dài |
| Internal key rò ra ⇒ mạo danh mọi user | **Cao** | Bot chỉ trong mạng nội bộ; key không bao giờ tới client; không log key |
| Gộp message ghi đè thông báo | **Cao** | M2, và phải trước thông báo đầu tiên |
| SDK đổi API mà docs không đổi | Trung bình | Cô lập SDK sau một lớp mỏng của bot; pin version |
| Node service = ngôn ngữ thứ hai trong dự án | Trung bình | Chấp nhận — không có SDK Python, không có lựa chọn khác |
| Thông báo DM gây phiền | Trung bình | `min_level = RECOMMEND` mặc định + `disabled_reason_keys` + feedback loop 6.9 đều đã có |

---

# VIII. Cần Chốt Trước Khi Code

1. **Có bot token + workspace Mezon để test chưa?** M0 không chạy được nếu không có, và M0 chặn R1.
2. Prefix `*` — theo đúng yêu cầu. Cần xác nhận Mezon không chiếm ký tự này cho việc khác.
3. `min_level` mặc định `RECOMMEND` cho kênh Mezon — đồng ý hay muốn khác.

---

# VIII bis. M0 — Trạng Thái (2026-08-17)

Harness ở `mezon_bot/`. `npm run dry-run` chạy được **không cần token**; `npm run probe` cần token.

## Đã xác minh, không cần token

| Điều | Kết quả |
|---|---|
| `mezon-sdk@2.8.55` `.d.ts` shipped vs source `master` | **Khớp chính xác.** Rủi ro "SDK đổi mà docs không đổi" (mục VII): **đã gỡ cho version này** — pin cứng, không dùng `^` |
| `InteractiveBuilder` / `ButtonBuilder` có export thật | ✅ cả hai |
| `EMessageComponentType` | `{BUTTON:1, SELECT:2, INPUT:3, DATEPICKER:4, RADIO:5, ANIMATION:6, GRID:7}` |
| Payload form 7 loại input dựng ra hợp lệ, serialize được | ✅ 18/18 kiểm tra |
| **`defaultValue` vào được payload** | ✅ — đây là chỗ chống đỡ cho luồng "AI trích task → form điền sẵn → user xác nhận" ở R1 (mục 2.3) |

## Sửa lại docs Mezon

- **`botId` BẮT BUỘC** — `MezonClientCore` ném `"botId is required"` ngay ở constructor. Ví dụ `new MezonClient({ token })` trong docs **không chạy**.
- `sendDM(content, code?, attachments?)` — docs thiếu tham số thứ ba.

## Ràng buộc triển khai mới phát hiện

`mezon-sdk` → `better-sqlite3@11.10.0` (native). **Node 24 không có prebuilt binary**; máy không có `make` thì không build được:

```
prebuild-install warn install No prebuilt binaries found (target=24.19.0 ...)
gyp ERR! stack Error: not found: make
```

**Node 22 cài sạch.** ⇒ Dockerfile phải là `node:22`, không phải `node:24`. Ràng buộc thật khi deploy, không phải chuyện riêng máy dev.

## Kết quả chạy thật (2026-08-17, gateway thật)

### 1. `extra_data` — ẩn số chính, đã có đáp án

```
button_id  = "p_submit" | "p_cancel"      ← đúng id ta đặt, không bọc thêm
extra_data = '{"p_text":"giá trị mặc định"}'   ← JSON hợp lệ, object phẳng
             key = đúng `id` của input
```

Ba hệ quả trực tiếp cho R1:

**(a) Parser đơn giản** — `JSON.parse` rồi tra theo `id`. Không cần decoder riêng.

**(b) ⚠️ Ô không nhập bị LƯỢC HOÀN TOÀN, không trả chuỗi rỗng.** Form 7 ô nhưng chỉ ô có `defaultValue` quay về. Nghĩa là **không phân biệt được "user xoá trắng ô" với "user không đụng vào ô"**. Quy tắc bắt buộc cho form sửa dữ liệu: **điền `defaultValue` cho mọi ô, và coi key vắng mặt là "giữ nguyên giá trị cũ", tuyệt đối không phải "xoá"**. Làm ngược lại sẽ xoá dữ liệu người dùng mỗi lần họ sửa một trường.

**(c) ⚠️ `sender_id` là BOT, `user_id` mới là người bấm.**
```
sender_id = <id của BOT>    ← tác giả message chứa nút
user_id   = <id NGƯỜI BẤM>  ← chủ thể thật của hành động
```
Ngược trực giác. Dùng `sender_id` để xác định "ai thao tác" sẽ gán mọi hành động cho bot — vừa sai audit trail, vừa là lỗ hổng phân quyền. **`user_id` là trường duy nhất được phép dùng làm chủ thể.**

### 2. Streaming bằng `message.update` — R3 khả thi, rộng hơn dự kiến

Thang nhịp 1000→600→400→250→150→**60ms**, 13 lần edit, rồi **đọc lại từ server** (phải xoá cache trước, vì `CacheManager.fetch` trả cache và `update()` tự ghi bản mình gửi vào đó):

```
allAcked: true       readBackMatchesFinal: true      159/159 ký tự
ack mỗi lần: 21–40ms, không tăng dần, không lỗi
```

**Server lưu đúng toàn bộ, kể cả nhịp 60ms.** Không có throttle phía server ở dải này.

> **Đính chính vòng 1.** Lần đầu tôi thấy tin nhắn dừng ở chữ thứ 8 và kết luận "ack không phải bằng chứng đã render". Kết luận đó **sai**: cùng lúc đó client Mezon của người dùng đang ở trạng thái treo — chính trạng thái làm mọi tin nhắn không tới bot, và được sửa bằng một lần reload. Đo lại bằng read-back trên client khoẻ thì mọi edit đều lưu đủ.
>
> Vẫn nên **tiết chế ~300–500ms**, nhưng vì lý do khác lý do cũ: dưới ngưỡng đó mắt người không thấy khác biệt, còn chi phí socket thì thật. Đây là lựa chọn kỹ thuật, không phải né giới hạn nền tảng.

### 3. Nhận diện DM và định danh người gửi

```
clan_id: "0"   mode: 4   is_public: false   code: 0
sender_id: "<id dạng số>"   username: "<username>"   display_name: "<tên hiển thị>"
contentKeys: ["t"]  — tin có markdown thì thêm "mk"
```
⇒ `mode === 4` (hoặc `clan_id === "0"`) là dấu hiệu DM. `sender_id` dạng số là khoá ổn định cho `user_channels.address`.

### 4. ⚠️ Bot nhận cả message của chính nó

22 `channel_message` thô nhưng chỉ 3 là của người dùng — phần còn lại là chính bot gửi/sửa. **Bắt buộc lọc `sender_id === botId` ngay đầu handler**, nếu không lệnh `*echo` sẽ tự trả lời chính nó thành vòng lặp vô hạn.

### 5. `sendDM` hoạt động

```
dmChannelId_before = 2089261138935025664   (đã có sẵn, không phải tạo mới)
same_as_current_channel = true
```
Đường đúng là `client.users.fetch(id)` → `user.sendDM(...)`. **Không phải** `dmClan.users.fetch(...)` như docs Mezon viết — `Clan` không có thuộc tính `users`, và `createDmChannel()` là `private`.

### 6. Sự cố môi trường đáng ghi lại

Có một khoảng thời gian bot **không nhận được bất kỳ `channel_message` nào** trong khi `message_button_clicked` vẫn tới bình thường — socket sống, `joinClanChat("0")` báo thành công, không lỗi nào. Nguyên nhân là **client Mezon phía người dùng bị treo**, sửa bằng reload trang. Không phải lỗi SDK, không phải lỗi code.

Bài học cho lúc vận hành: **"bot không trả lời" không đủ để kết luận bot hỏng.** Máy đếm event (`event_tally` trong `probe.js`) là thứ phân biệt được "socket không nhận gì" với "handler lỗi" — bot thật nên giữ lại một dạng nào đó của nó.

### 7. Bảng serialize đầy đủ — đã đo, không còn suy đoán

Một lần Submit với form điền kín:

```json
{"p_text":"giá trị mặc định","p_textarea":"ssd","p_number":"1.5",
 "p_select":"b","p_radio":"high","p_radio_multi":"y","p_date":"34343-12-22"}
```

và một lần với radio nhiều lựa chọn đã cấu hình đúng:

```json
{"p_text":"giá trị mặc định","p_radio_multi":["x","y","z"]}
```

| Component | Kiểu trong `extra_data` | Ghi chú |
|---|---|---|
| INPUT text | `string` | |
| INPUT textarea | `string` | |
| INPUT number | **`string`** | `"1.5"`, **không phải number** — phải tự parse và tự validate |
| SELECT | `string` | |
| RADIO chọn một | `string` | |
| RADIO chọn nhiều | **`string[]`** | |
| DATEPICKER | `string` `YYYY-MM-DD` | |

Khớp đúng suy luận từ source frontend (`MessageButton.tsx` làm `extra_data = JSON.stringify(embedData)`; `embedMessage.slice.ts` lưu `multiple → [value]`, `single → value`; `MessageDatePicker.tsx` dùng `<input type="date">`).

### 8. ⚠️ Ba cái bẫy phát hiện được nhờ đo thật

**(a) `p_date: "34343-12-22"` — nền tảng KHÔNG validate ngày.** Người dùng gõ năm 5 chữ số và nó đi thẳng vào payload. Mọi giá trị ngày **bắt buộc phải validate ở backend**; không được tin `<input type="date">` đã lọc hộ.

**(b) SELECT bắn `message_button_clicked` ngay khi chọn, với `extra_data` KHÔNG phải JSON.**
```
button_id = "p_select"   extra_data = "a"      ← giá trị trần, không bọc JSON
button_id = "p_submit"   extra_data = "{...}"  ← JSON, lúc bấm nút thật
```
Zero sự kiện `dropdown_box_selected` được ghi nhận trong toàn bộ phiên — **`onDropdownBoxSelected` không dùng cho select trong embed.** Hệ quả bắt buộc cho handler:
1. **Lọc theo `button_id`** — chỉ xử lý nút submit đã đăng ký, bỏ qua event của select.
2. **Không được `JSON.parse` mù.** Parser phải chịu được chuỗi trần; nếu không, mỗi lần người dùng đổi lựa chọn trong dropdown sẽ ném một exception.

**(c) Radio nhiều lựa chọn cần `name` KHÁC nhau ở 2 option đầu.**
```tsx
// EmbedOptionRatio.tsx
if (options?.length > 1 && options?.[0]?.name) {
    return options?.[0].name !== options?.[1].name;   // ← checkMultiple
}
```
Đúng ngữ nghĩa radio HTML (cùng `name` = cùng nhóm loại trừ). Comment trong SDK — `// Apply when use mutiple choice` — đọc như thể muốn một tên nhóm chung và **hiểu ngược**. Đặt trùng tên thì control vẫn render đẹp, không lỗi ở đâu cả, chỉ là chọn được một. Hỏng im lặng. `dry-run.js` có 2 test khoá lại điều này.

## M0 — ✅ ĐÓNG

Không còn ẩn số nào chặn việc xây bot. Parser `extra_data` viết được chắc tay.

---

# XII. M1 — ✅ Xong (2026-08-17)

Đã chạy thật đầu-cuối: `*ping` → phản hồi; `*link <mã>` → `user_channels` có dòng `mezon` với `verified=true`.

## Đã xây

**Backend**

| Thành phần | Chỗ |
|---|---|
| Bảng mã liên kết một lần | `ChannelLinkCode` + migration `o1234567890p` |
| Service liên kết | `app/services/channel_link.py` |
| Tra địa chỉ chat → user | `resolve_channel_async` (`user_channels.py`) |
| Adapter Mezon | `app/services/delivery/mezon.py` + 1 dòng `register()` |
| Auth chỉ-nội-bộ | `require_internal_service` (`dependencies.py`) |
| API | `POST /channels/link-code`, `POST /channels/redeem`, `GET /channels/resolve` |

**Frontend:** `ChannelsCard.tsx` trong Settings — nút lấy mã, đồng hồ đếm ngược, danh sách kênh với mức lọc + bật/tắt + gỡ.

**Bot:** `mezon_bot/src/` — `config` (validate lúc khởi động), `logger` (tự redact khoá), `mezon/client` (lớp bọc SDK duy nhất), `mezon/interactions` (parser theo đúng 3 quy tắc M0), `mezon/embed`, `cortex` (HTTP client), `commands/`, `router`. **31 test.**

**Tiêu chí nghiệm thu F0 đã qua:** adapter Mezon là đúng một file + một dòng `register()`; không đụng `attention_gate.py`, `notifications.py`, `delivery_worker.py`.

## Ba quyết định bảo mật

1. **Mã sinh từ web, gõ vào chat — không bao giờ ngược lại.** Mezon user id ai trong clan cũng đọc được. Endpoint `link-code` cố ý dùng `get_current_active_user` (chỉ JWT), **không** dùng biến thể internal: một service key phát mã hộ user tuỳ ý chính là lỗ hổng cần chặn.
2. **`redeem` và `resolve` không nhận `X-User-ID`.** Chúng tự suy chủ thể từ payload; nhận thêm user id từ caller sẽ thành lập luận vòng. Đây là lý do phải có `require_internal_service` riêng.
3. **`resolve` chỉ khớp dòng `verified`.** Không thì liên kết chỉ là trang trí — ai cũng gõ id người lạ vào settings API rồi nói chuyện dưới danh nghĩa họ.

Kèm: mã bị đốt khi phát mã mới; `used_at` đánh dấu **trước** khi đăng ký kênh (đăng ký hỏng thì mã vẫn mất, không replay được); thông báo lỗi không phân biệt "sai/hết hạn/đã dùng" — cả ba đều nghĩa là *lấy mã mới*.

## ⚠️ Hai cái bẫy vận hành, tốn nhiều thời gian nhất

### (a) Bot vào clan thật ⇒ MẤT subscribe kênh DM

**Triệu chứng:** bot chạy, socket mở, `joinClanChat` báo thành công, không lỗi nào — nhưng `channel_message` **không bao giờ tới**. Kéo dài 3.5 tiếng liên tục.

**Thứ phá được ca này:** bảng đếm event.
```
mezon event tally {"ready":1, "message_button_clicked":6}
```
Button click **tới đủ**, tin nhắn **không**. Chênh lệch đó loại trừ mọi giả thuyết về socket: button click định tuyến tới *tác giả tin nhắn chứa nút* nên không cần thành viên kênh; tin nhắn văn bản thì cần.

**Nguyên nhân:** lúc login SDK chỉ gọi `joinClanChat("0", true)` cho pseudo-clan DM. Đủ khi bot chưa ở clan nào (`clanCount: 1` — giai đoạn đầu M0 nhận tin bình thường). Từ khi bot vào clan thật (`clanCount: 2`) thì không còn đủ.

**Vá:** `MezonGateway._joinDmChannels()` — sau login, `getAllDmChannelDescs()` rồi `socket.joinChat("0", channelId, CHANNEL_TYPE_DM, false)` từng kênh. Chạy mỗi lần connect; join lại kênh đã join là vô hại.

> **Bài học giữ lại:** bảng đếm event (`_installEventTap`) **không phải giàn giáo tạm**. "Bot không trả lời" trong dự án này đã có **ba** nguyên nhân khác hẳn nhau — client web treo, hai process tranh socket, thiếu subscribe — mà nhìn từ ngoài giống hệt nhau. Không có máy đếm thì mỗi lần lại phải dựng lại hiện trường từ đầu.

### (b) `clan_id === "0"` KHÔNG có nghĩa là DM

```
STREAM_MODE_CHANNEL = 2   STREAM_MODE_GROUP = 3   STREAM_MODE_DM = 4
STREAM_MODE_CLAN    = 5   STREAM_MODE_THREAD = 6
```

**Chat nhóm cũng nằm ngoài clan**, nên `clan_id === "0"` đúng với cả nhóm. Điều kiện `mode === 4 || clan_id === "0"` vì thế **nới rộng chứ không thu hẹp**: bot sẽ coi group là DM và trả lời mọi câu trong phòng đông người.

Hỏng **im lặng** — không crash, không log lạ, phản hồi đầu tiên là bị mute.

**Quy tắc:** chỉ `mode` được quyết định phạm vi; `clan_id` không tham gia. `mode` thiếu ⇒ `unknown`, không đoán. Router khai báo `SERVED_SCOPES = {dm}` tường minh. 10 test khoá lại.

### (c) Hai process cùng token = tranh nhau tin nhắn

Gateway chỉ giao mỗi tin cho **một** socket. Triệu chứng là "bot chạy code cũ". `run.sh` giờ từ chối khởi động nếu đã có process bot/probe khác, và in PID ra.

## Còn thiếu ở M1

- UI chưa sinh danh sách kênh động từ `GET /channels/available` (đang hardcode `'mezon'`) — phải sửa trước khi thêm kênh thứ hai, đúng bài học 4.2.
- Bot chưa có HTTP server nhận `/internal/deliver` (M2).
- Chat thường vẫn trả lời placeholder (M3).
