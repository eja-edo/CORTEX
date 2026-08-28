# Cortex — Thiết Kế Hệ Thống

**Bản 1 · 2026-08-24 · Nguồn sự thật duy nhất**

**Sửa đổi:**

| Ngày | Thay đổi |
|---|---|
| 2026-08-25 | QĐ-2 — project neo vào Mezon channel, không neo vào lịch (mục 15) |
| 2026-08-25 | QĐ-3 — 10.4 và 10.5 hoãn, vào sổ hoãn 13.5 mới (mục 15) |
| 2026-08-28 | Mục 16 — thiết kế trigger chủ động cho agent, hoãn theo 13.4 (vào sổ hoãn 13.5) |

---

## 0. Trạng thái tài liệu

Bản này **thay thế toàn bộ** các tài liệu kế hoạch trước đó, đã chuyển vào `docs/archive/`:

| Tài liệu cũ | Vì sao ngừng dùng |
|---|---|
| `planning-v3.md` | Xây quanh giả định Cortex là trợ lý cá nhân đa năng. Hướng đã đổi |
| `requeirment.md` | Định nghĩa sản phẩm bằng phủ định và bằng vòng lặp trừu tượng — không nói được "lúc nào dùng". Xem mục 1 |
| `CORTEX_ANALYSIS_REPORT.md` | Kiểm kê tại 2026-07-28, đã lạc hậu |
| `tasks/plan.md`, `tasks/phase1/*` | Phase cũ, không còn phản ánh đường tới hạn |
| `workflow_feature/*` | `workflow_service` bị đóng băng — xem mục 11 |
| `mezon-bot-plan.md` | Đã triển khai xong. Phần phát hiện về SDK còn giá trị tra cứu, giữ trong archive |

**Không lạc hậu, vẫn dùng:** `docs/architecture/memory-architecture.md`, `docs/architecture/conversation-summary.md` (kiến trúc, không phải kế hoạch).

**Quy tắc dùng tài liệu này:**

- Mỗi mục 13.x là một Epic. Mỗi tiêu chí nghiệm thu là một Story verify độc lập.
- **Mục tiêu là tiêu chí nghiệm thu.** Code xong mà mục tiêu chưa đạt thì chưa done.
- Khi một thiết kế mâu thuẫn với nguyên tắc ở mục 2: **sửa thiết kế, không sửa nguyên tắc.**
- Khi thực tế buộc phải đổi nguyên tắc: **sửa tài liệu này trước, rồi mới code.** Bản 2 lạc hậu chính vì bước này bị bỏ qua.

---

## 1. Sản phẩm là gì

> **Việc đã được ghi ra ở đâu đó rồi. Cortex nhận về, gom theo dự án, và quyết định lúc nào nói với ai về việc gì — nói ít hơn mọi công cụ khác, nhưng mỗi lần nói đều đáng.**

### 1.1 Ba tầng, một tầng là sản phẩm

```
Tầng 1 — THU THẬP           Phần lớn KHÔNG tự xây.
                             Bot họp cho action item. Google Calendar
                             cho sự kiện. Cortex nhận qua webhook.

Tầng 2 — GOM THEO DỰ ÁN      Một bảng, xác định lúc ghi, sửa được tại chỗ.

Tầng 3 — QUYẾT ĐỊNH NÓI      ← Sản phẩm nằm ở đây và chỉ ở đây.
                             Attention Gate 5 bước. 0 token.
```

Dừng ở tầng 2 thì đây là một công cụ tổng hợp việc — Motion, Sunsama, Akiflow, Todoist đều đã làm và làm tốt. Giá trị chỉ xuất hiện ở tầng 3; hai tầng dưới tồn tại để nuôi nó.

### 1.2 Tiêu chí thành công ngược với công cụ tổng hợp

| | Công cụ tổng hợp | Cortex |
|---|---|---|
| Đánh giá bằng | Có hiện đủ mọi thứ không | Có im đúng lúc và nói đúng lúc không |
| Bản năng | Hiện **nhiều** hơn | Nói **ít** đi |
| Thất bại khi | Bỏ sót một việc | Nói một câu không đáng nói |

Hệ quả lên roadmap: **mục tiêu là chọn lọc, không phải tổng hợp** — nên chỉ cần *đủ* đầu vào để quyết định tốt. Thêm nguồn chỉ đáng khi nó làm *quyết định* tốt lên, không phải khi nó làm *danh sách* dài ra.

### 1.3 Cortex không phải là

Nơi tổng hợp việc · phần mềm quản lý dự án · công cụ trích xuất · trợ lý cá nhân đa năng · nơi ghi chú · nền tảng automation.

**Cả sáu thứ này đều đã tồn tại trong repo.** Mục 11 nói cách gỡ chúng khỏi đường chính.

### 1.4 Bối cảnh của quyết định

Truy vấn DB ngày 2026-08-24: **95 tài khoản, 94 là `*-test-*` do integration test sinh ra, 1 người dùng thật.** 11 task · 1 note · 5 lịch · 0 asset · 1 notification · 1 dòng `attention_log` · 0 workflow.

Nghĩa là toàn bộ hệ thống được thiết kế và nghiệm thu **chưa từng đi qua một người dùng ngoài tác giả**. Mọi hạng mục nhằm cải thiện tính đúng đắn nội bộ có kỳ vọng giá trị ≈ 0 cho tới khi có người dùng thứ hai. Đó là lý do mục 12 (phép thử) đứng trước mọi thứ khác.

**Hai hướng đã bị loại, ghi lại để không quay vòng:**

| Hướng | Chết vì |
|---|---|
| Bot nghe channel Mezon, tự trích lời hứa | Tập thể trả giá (cho bot vào nghe), cá nhân hưởng (nhắc riêng). Lỗi cấu trúc, không sửa bằng code. Cộng thêm: channel không có ranh giới hội thoại để định cửa sổ trích xuất |
| Cortex tự làm biên bản + trích action item từ cuộc họp | Đã có bot họp làm khâu này. Cạnh tranh khâu trích xuất là tự chọn trận thua — và không cần, vì output của nó dùng được ngay |

Cả hai đều nhắm vào **tầng 1**. Quyết định cuối cùng là giao hẳn tầng đó cho hệ thống khác.

---

## 2. Nguyên tắc ràng buộc

Vi phạm bất kỳ nguyên tắc nào dưới đây là lý do đủ để từ chối một thiết kế.

**P1 — Một cổng duy nhất.** Mọi thứ làm phiền người dùng phải qua Attention Gate. Không component nào được ghi thẳng vào `notifications`. *(Giữ nguyên từ bản cũ.)*

**P2 — Detection ≠ Delivery ≠ Channel.** Phát hiện điều đáng nói, quyết định có nói không, và chọn kênh phát là ba việc tách rời. Gate quyết định **có nói không**; delivery layer quyết định **nói qua đâu**. *(Giữ nguyên; F0 đã kéo dài thêm một nấc.)*

**P3 — Deterministic trước, AI sau.** Hạn chế AI mà vẫn đạt mục tiêu; khi AI vào thì phải tạo đột phá lớn. Gate, State Evaluator, ranking, xác định project: **0 token**. AI chỉ được vào khi đo được rằng logic deterministic không quyết nổi, và tỷ lệ đó cao dai dẳng. *(Giữ nguyên.)*

**P4 — Suy ra trước, khai báo sau.** *(Mới.)* Thực thể nào cần người dùng tự khai và tự duy trì thì sẽ rỗng mãi mãi — `goals` đã chết đúng như vậy. Mọi thực thể mới phải xuất hiện từ dữ liệu đang chảy sẵn. Khai báo tay là **lối sửa**, không phải cửa chính.

> **Phép thử P4:** người dùng không bao giờ mở màn hình X — Cortex có còn hữu ích không? **Phải là CÓ.**

**P5 — Nói ít hơn, không nhiều hơn.** *(Mới.)* Mọi tính năng phải trả lời được: nó làm Cortex nói **ít đi mà đúng hơn**, hay chỉ làm nó nói **nhiều hơn**? Cái sau bị từ chối kể cả khi thông tin thêm vào là đúng.

**P6 — Một bề mặt chỉ vào nav nếu nó làm lời nhắc kế tiếp thông minh hơn.** *(Mới.)* Không phải "hữu ích", không phải "user có thể cần". Phải chỉ ra được dữ liệu từ đó đi vào `StateEvaluator` hoặc `TodayService` bằng đường nào.

**P7 — Nghi ngờ thì bỏ.** Một gợi ý sai đắt hơn một gợi ý thiếu nhiều lần. Áp cho trích xuất, cho gán project, cho mọi phỏng đoán. *(Giữ nguyên từ `task_extraction.py`.)*

**P8 — Không xây tầng thứ hai trước khi tầng thứ nhất có 10 người dùng.** *(Mới.)* Goal trên Task, AI reasoning trên Gate, workflow trên predicate, dashboard trên project — đều là tầng hai xây trên nền chưa ai đứng.

---

## 3. Mô hình dữ liệu

### 3.1 Bảng mới: `projects`

**Project là thực thể dùng chung, không thuộc về một người**, và **neo vào một Mezon channel** — xem QĐ-1 và QĐ-2 ở mục 15.

```sql
CREATE TABLE projects (
    id                  UUID PRIMARY KEY,          -- uuid7
    owner_id            UUID NOT NULL REFERENCES users(id),  -- người/luồng tạo ra nó
    name                VARCHAR(255) NOT NULL,
    status              projectstatus NOT NULL DEFAULT 'active',   -- active | closed
    deadline            TIMESTAMP NULL,            -- suy ra được, sửa được
    deadline_is_manual  BOOLEAN NOT NULL DEFAULT false,
    source_channel_id   VARCHAR(255) NULL,         -- Mezon channel — danh tính CHUNG (xem 3.1.1)
    origin              projectorigin NOT NULL,    -- derived | manual | personal
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX uq_projects_source_channel
    ON projects (source_channel_id) WHERE source_channel_id IS NOT NULL;
```

```sql
CREATE TABLE project_members (
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    joined_via  projectjoinsource NOT NULL,   -- derived | manual
    joined_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE INDEX ix_project_members_user ON project_members (user_id);
```

**`project_members` cố ý KHÔNG có cột `role`.** Đó là thứ đã làm `WorkspaceMember` sai ngữ nghĩa (3.6 lý do 2). Thêm `role` chỉ khi có một quyết định cụ thể cần tới nó — hiện chưa có.

**Thành viên cũng được suy ra, không phải mời** (P4): khi task của người B rơi vào một chuỗi đã có project, B tự động vào `project_members` với `joined_via='derived'`. Không có luồng mời/duyệt trong v1.

### 3.1.1 `source_channel_id` — danh tính chung của một dự án

**Lịch không mang thông tin dự án.** Calendar không sync chéo giữa người dùng, và trong một lịch công việc không có tín hiệu nào phân biệt *"chuỗi này là dự án Alpha"* với *"chuỗi này là standup / 1:1 / ăn trưa"*. Tài khoản chỉ tách được **cá nhân ↔ công việc**, không tách được **dự án ↔ dự án**. Mọi suy ra project từ hình dạng lịch đều là phỏng đoán, và P7 cấm.

Mezon channel thì ngược lại, ở cả bốn mặt:

| | Chuỗi sự kiện lịch | Mezon channel |
|---|---|---|
| Danh tính chung giữa người dùng | ❌ Mỗi người một `Schedule` row | ✅ Một id, mọi người thấy như nhau |
| Có sẵn thành viên | ❌ Phải suy từ attendee | ✅ Thành viên channel |
| Có tên do người đặt | Tên cuộc họp | ✅ Tên channel — đúng thứ người ta gọi là dự án |
| Bot họp ở đâu | Không ở đó | ✅ Nó đăng biên bản vào channel |
| Ánh xạ tới kênh phát (8.1) | Phải thiết kế riêng | ✅ **Project *chính là* channel** |

`source_channel_id` là id channel Mezon. `NULL` cho dự án cá nhân và dự án tạo tay.

- `deadline` mặc định suy ra (mục 4.3); `deadline_is_manual` khoá lại khi người dùng sửa tay.
- `owner_id` là *ai tạo ra*, không phải *ai sở hữu duy nhất*. Truy vấn "dự án của tôi" đi qua `project_members`, không qua `owner_id`.

### 3.2 Cột thêm: `schedules.project_id`

```sql
ALTER TABLE schedules ADD COLUMN project_id UUID NULL REFERENCES projects(id) ON DELETE SET NULL;
CREATE INDEX ix_schedules_project_id ON schedules (project_id);
```

**Chỉ đặt trên hàng template** (`recurrence_id IS NULL`). Không đặt lên occurrence exception — nếu không, một chuỗi 30 lần lặp sinh 30 hàng cùng project và quy tắc suy ra sẽ trôi.

### 3.3 `tasks.project_id` — cột thật, bắt buộc

```sql
-- Ba bước. ADD COLUMN ... NOT NULL trên bảng đã có dữ liệu sẽ lỗi.
ALTER TABLE tasks ADD COLUMN project_id UUID REFERENCES projects(id);

-- backfill: mọi task hiện có → dự án cá nhân của chủ sở hữu
-- (tạo dự án cá nhân trước nếu chưa có)
UPDATE tasks t SET project_id = p.id
  FROM projects p
 WHERE p.user_id = t.user_id AND p.origin = 'personal';

ALTER TABLE tasks ALTER COLUMN project_id SET NOT NULL;
CREATE INDEX ix_tasks_project_id ON tasks (project_id);
```

**Mọi task thuộc đúng một project.** Task có thể không gắn sự kiện nào, nhưng không bao giờ không có project.

`Task.related_event_id` (đã có, `models.py:851`) vẫn giữ nguyên và vẫn có ý nghĩa — nó nói *task này sinh ra từ cuộc họp nào*. Nhưng nó **không còn là đường tra project**. Hai quan hệ độc lập:

```
Task ──project_id──▶ Project        bắt buộc, luôn có
Task ──related_event_id──▶ Schedule tuỳ chọn, chỉ nói nguồn gốc
```

> **Ghi lại một thiết kế đã bị bác bỏ, để không quay lại:** bản nháp trước tính project lúc đọc qua `related_event_id → schedule → project_id`, không có cột trên `tasks`. Nó **không diễn đạt được** trường hợp phổ biến nhất: một task thuộc dự án Alpha nhưng không gắn cuộc họp nào. Mô hình đó sẽ đẩy task vào dự án cá nhân — sai, không phải mặc định hợp lý. Project đi qua sự kiện là *một* con đường, không phải con đường duy nhất.

### 3.4 Dự án cá nhân — mặc định, không phải nơi chứa đồ thất lạc

Mỗi người dùng có **một** dự án cá nhân: tên mặc định là tên hiển thị của họ, `origin='personal'`, `source_schedule_id = NULL`, `deadline = NULL`.

```sql
CREATE UNIQUE INDEX uq_projects_personal_per_user
    ON projects (owner_id) WHERE origin = 'personal';
```

**Tạo lười**, lần đầu người dùng cần một project mà chưa có ngữ cảnh nào — không tạo lúc `POST /auth/register`. Tạo lúc đăng ký sẽ lặp lại đúng lỗi của `workspaces` (`api/auth.py:136`): mỗi tài khoản test cũng đẻ một hàng, và vi phạm P4.

Nó là **giá trị mặc định khi người dùng không nói gì khác**, không phải nơi hứng những task mà hệ thống không biết xếp vào đâu. Khác biệt này quan trọng: nếu người dùng đang mở dự án Alpha và tạo một việc, việc đó thuộc Alpha — kể cả khi không có cuộc họp nào liên quan.

> ⚠️ **`deadline IS NULL` là bất biến chịu lực.** Nó là thứ **duy nhất** ngăn dự án cá nhân sinh thông báo cấp dự án (6.1, 6.2, 7.1 đều guard theo nó). Bắt buộc có test khoá: *dự án cá nhân với 50 task quá hạn không sinh predicate cấp dự án nào.* Không có test đó thì sớm muộn xuất hiện câu "Cá nhân có 47 việc quá hạn" — đúng loại vi phạm P5.

Dự án cá nhân **không bao giờ** gắn Mezon channel (8.1), không vào thống kê ở 4.4, và **luôn có đúng một thành viên** — chính chủ. Không ai được thêm vào nó.

### 3.5 Xác định project lúc tạo task

Không có resolver lúc đọc. `project_id` được quyết một lần lúc ghi, theo thứ tự ưu tiên:

```
1. Chỉ định tường minh      UI: dự án đang mở
                            Tool: project_ref  (9.2)
                            Webhook: project_ref nếu bot họp gửi kèm

2. Từ sự kiện liên quan     related_event_id → chuỗi template → project_id
                            (bao gồm cả tạo lười project cho chuỗi — 4.1)

3. Dự án cá nhân            khi không có ngữ cảnh nào ở trên
```

**Sửa sau bằng `move_task`** (9.2) hoặc dropdown tại chỗ (10.1). Vì `project_id` là giá trị ghi một lần, mọi lượt sửa là tín hiệu đo chất lượng bước 2 — xem 4.4.

**Hệ quả phải xử lý:** gán một chuỗi sự kiện vào project khác (`PATCH /api/schedules/{id}/project`) **không** tự đổi project của các task đã tạo từ nó. Đây là chủ ý — task đã có project riêng, ghi đè hàng loạt là hành vi phá hoại. API trả về số task bị ảnh hưởng để UI hỏi *"chuyển N việc cũ sang theo không?"*.

### 3.6 Vì sao KHÔNG đổi tên `workspaces` thành `projects`

Đã cân nhắc và bác bỏ. Bốn lý do, tất cả kiểm chứng được trong code:

1. **Workspace tự sinh lúc đăng ký** (`api/auth.py:136`, `is_personal=True`). Đổi tên nghĩa là mỗi tài khoản mới đã có sẵn một "dự án" rỗng mang tên mình — danh sách dự án thành sản phẩm phụ của việc đăng ký.
2. **Ngữ nghĩa thành viên khác nhau.** `WorkspaceMember.role` là *ai được xem tài liệu* (`VIEWER`, `invited_by`, `joined_at`). Thành viên dự án là *ai chịu trách nhiệm việc gì*.
3. **Nó kéo Notes và Assets trở lại đường chính.** Workspace tồn tại để nhóm note và asset — cả hai bị đóng băng ở mục 11. Đổi tên thì danh sách dự án = danh sách thư mục.
4. **Mất khả năng phân biệt nguồn** (`origin`), thứ quyết định project sống hay chết như Goal.

**Chi phí đo thật (2026-08-24), không phải ước lượng:**

| | Đổi tên workspace → project | Bảng `projects` mới *(đang chọn)* |
|---|---|---|
| Tham chiếu phải sửa | ~1.565 (backend 499 / frontend 1.066) | **0** |
| Tệp phải chạm | 62 (backend 38 / frontend 24) | ~15–20 |
| Bảng phải migrate | 6 bảng có `workspace_id` | 1 bảng mới + 2 cột |
| Kéo theo phần đóng băng | **Có — 4/6 bảng** | Không |
| Di trú dữ liệu | Notes/assets phải theo | **Không có gì để di trú** |

Sáu bảng có `workspace_id`: `notes`, `assets`, `agent_conversations`, `workflow_definitions`, `workspace_members`, `workspace_workflow_settings`. **Bốn trong sáu thuộc phần đã đóng băng ở mục 11** — nên đổi tên buộc phải sửa đúng khối code vừa quyết định không đụng tới. Đóng băng và đổi tên là hai thao tác mâu thuẫn nhau trên cùng một khối code.

Thêm một va chạm ngữ nghĩa: `AgentConversation.workspace_id` (`models.py:748`) — đổi tên nghĩa là mọi hội thoại thuộc về một project, đúng thứ mục 9.2 đã bác bỏ.

Đổi tên **máy móc** thì dễ (IDE làm được). Cái đắt nằm ở 6 migration đổi cột FK, ở việc phải diễn giải lại `WorkspaceMember.role` cho từng chỗ dùng, và ở chỗ nó lôi bốn tính năng đã đóng băng trở lại bàn làm việc.

**Kết luận: `workspaces` giữ nguyên, tiếp tục phục vụ Notes và Assets, chỉ bị ẩn khỏi nav. `projects` là bảng mới sống song song. Không convert, không di trú.**

---

## 4. Quy tắc suy ra project

### 4.1 Tạo lười — project sinh ra từ channel có việc

```
Khi một action item của người U đến từ channel C:

    P := project có source_channel_id = C
    nếu chưa có → tạo project(source_channel_id=C,
                              name=tên channel, origin='derived', owner_id=U)

    task.project_id = P.id
    thêm (P, U) vào project_members nếu chưa có, joined_via='derived'
```

**Channel nào không sinh ra việc thì không bao giờ thành project** — nên channel tán gẫu, thông báo chung, random không làm ngập bảng. Cùng bộ lọc như bản trước, chỉ đổi nguồn.

Người thứ hai nhận việc từ cùng channel **tìm thấy project đã có** và tự vào làm thành viên — không tạo bản thứ hai.

### 4.2 Lịch ↔ project — một lớp phủ, không phải nền móng

Danh tính dự án đến từ channel (4.1). Việc gắn *sự kiện* vào project là **tuỳ chọn, tích luỹ dần**, và nếu không bao giờ xảy ra thì không có gì gãy.

Cầu nối là **bot họp**, vì nó đứng ở giao điểm: nó biết vừa tóm tắt cuộc họp nào *và* đăng vào channel nào. Đây là dữ liệu thật, không phải phỏng đoán.

Thang bốn mức, dừng ở mức đầu tiên khớp:

```
1. Webhook mang provider_event_id
   → ScheduleExternalMap → Schedule → đặt project_id trên HÀNG TEMPLATE
   CHÍNH XÁC

2. Webhook mang link Meet của phiên ghi
   → khớp Schedule.hangout_link
   CHÍNH XÁC   (cần thêm cột — xem dưới)

3. Không khớp gì
   → sự kiện KHÔNG có project. Dừng.
   KHÔNG đoán theo giờ + tiêu đề na ná (P7): một cuộc 1:1 và một cuộc
   họp dự án cùng 10h thứ Ba sẽ bị trộn

4. Người dùng gắn tay một lần cho cả chuỗi (10.1)
   → lối sửa, luôn có
```

Đặt trên **hàng template** (`recurrence_id IS NULL`): học một lần từ một occurrence, áp cho cả chuỗi về sau.

**Cột phải thêm cho mức 2:** `google_calendar_sync.py:492` chỉ lưu `event.get("location")`. Google để link Meet ở `hangoutLink` / `conferenceData.entryPoints[].uri`, **không phải** `location`. Thêm `schedules.hangout_link` và một dòng đọc trong sync.

**Không có liên kết thì mất đúng hai thứ**, cả hai là tính năng cộng thêm: mục 8.2 (Gate biết bận vì dự án nào) và ngữ cảnh trước họp. Task/predicate/định tuyến kênh/`starts_soon`/`is_user_busy`/`find_free_slots` **đều không cần project trên sự kiện**.

### 4.3 Suy ra `deadline`

```
deadline := max(due_date) của các task thuộc project
         ?? NULL
```

Nhánh "lần lặp cuối của chuỗi" đã bỏ cùng với việc neo project vào channel (3.1.1) — project không còn gắn với một chuỗi lịch nào.

`NULL` là hợp lệ. Predicate nào cần deadline mà không có thì im (mục 6).

Người dùng sửa tay → đặt cờ `deadline_is_manual`, không bị suy ra ghi đè lần sau.

**Chống dao động:** nhánh `max(due_date)` khiến `deadline` nhảy mỗi lần thêm task, và `project.will_miss` sẽ bật/tắt theo. Quy tắc: `deadline` chỉ tính lại **khi chuỗi sự kiện đổi** hoặc **một lần mỗi ngày** trong `StateEvaluator`, không tính lại ở mỗi lần ghi task. Và `will_miss` chỉ phát khi vượt ngưỡng **hai lần đánh giá liên tiếp** — cùng nguyên tắc chống rung mà `StateEvaluatorFlag` đang dùng.

### 4.4 Đo chất lượng quy tắc suy ra

Mỗi lần người dùng sửa quy gán project (mục 10.1) là một nhãn âm. Tỷ lệ sửa trên tổng số gán `origin='derived'` là chỉ số chất lượng của quy tắc.

**Ngưỡng:** nếu > 20% lượt gán bị sửa tay thì quy tắc sai — sửa quy tắc, không thêm UI.

---

## 5. Luồng dữ liệu đầu-cuối

```
   Bot họp (ngoài)          Google Calendar
        │ webhook                │ sync
        ▼                        ▼
   POST /api/internal/tasks   schedules
        │                        │
        └──► ScheduleExternalMap ┘
                     │
                     ▼
              Task.project_id ──► tạo lười project cho chuỗi (4.1)
                     │
                     ▼
        ┌────────────────────────────┐
        │  StateEvaluator  (0 token) │  ← join thẳng tasks.project_id
        │  9 predicate               │
        └────────────┬───────────────┘
                     │ event bus
                     ▼
        ┌────────────────────────────┐
        │  Attention Gate  (0 token) │
        │  1 importance              │
        │  2 đã biết chưa (dedup)    │
        │  3 có nên im không         │  ← biết đang bận VÌ dự án nào (8.2)
        │  4 gộp với gì              │  ← gộp theo project (7.2)
        │  5 lúc nào                 │
        └────────────┬───────────────┘
                     ▼
              Notification row
                     │
        ┌────────────┴────────────┐
        │  delivery/dispatcher    │  ← định tuyến kênh theo phạm vi (8.1)
        └──┬──────────────────┬───┘
           ▼                  ▼
      in_app (SSE)      Mezon (DM hoặc channel dự án)
```

Không có nhánh nào đi qua `workflow_service`. Đó là quyết định đã chốt từ bản cũ (mục A2) và giữ nguyên.

---

## 6. Predicate dự án

Bổ sung vào `state_evaluator.py`. Cả hai **deterministic, 0 token**, dùng `StateEvaluatorFlag` cho idempotency đúng như 7 predicate hiện có.

### 6.1 `project.slipping`

| | |
|---|---|
| Điều kiện | Số task mở của project **tăng** so với lần đánh giá trước, **và** `deadline` còn ≤ 14 ngày |
| Vì sao đáng nói | Đây là tín hiệu goal-progress đã mất khi `goals` bị xoá. Không gì khác phát hiện được |
| `flag_key` | `project.slipping:{project_id}` |
| Trạng thái cần lưu | Số task mở của lần đánh giá trước. `StateEvaluatorFlag` chỉ lưu cờ, không lưu số — thêm cột `snapshot JSONB NULL` vào bảng đó, hoặc một bảng `project_snapshots(project_id, open_count, evaluated_at)`. **Chọn cái sau**: nó cũng là dữ liệu cho `will_miss` và cho biểu đồ sau này, và không làm `StateEvaluatorFlag` phình ra |
| `reason_key` | `project.slipping` → mức nền **RECOMMEND** |
| Im khi | `deadline IS NULL` — không có chân trời thì không có khái niệm trượt |

### 6.2 `project.will_miss`

| | |
|---|---|
| Điều kiện | Theo tốc độ hoàn thành hiện tại, dự án kết thúc **sau** `deadline` |
| Công thức | `tốc_độ := số task completed trong 14 ngày qua / 14`; `ngày_cần := task_mở / tốc_độ`; phát khi `now + ngày_cần > deadline` |
| Vì sao đáng nói | Cảnh báo **trước** khi trễ, không phải sau |
| `flag_key` | `project.will_miss:{project_id}` |
| `reason_key` | `project.will_miss` → mức nền **ASK** (ngang `task.at_risk`) |
| Im khi | `deadline IS NULL`, hoặc `tốc_độ = 0` và task_mở = 0 |

**Số học thuần trên `completed_at`. Không ML, không token.** Nếu thấy mình định gọi LLM ở đây thì đã sai P3.

### 6.3 Ranh giới không được vượt

> **Task = tiến độ. Event = khung thời gian. Không trộn.**

Tiến độ dự án **chỉ đếm Task**. Không bao giờ tính từ số cuộc họp đã diễn ra. `CalendarItemService` đang merge Task + Schedule để *hiển thị* — đó là chuyện khác, và không được dùng làm đầu vào cho rủi ro.

Đây là kiểu hỏng kinh điển của mọi công cụ PM: dự án nhiều họp trông như đang hoạt động mạnh.

---

## 7. Xếp hạng và gộp

### 7.1 `TodayService._rank_actions` — sắp theo rủi ro dự án

Hiện sắp theo "không làm hôm nay thì mất gì" ở mức từng task. Đổi thành hai tầng:

```
khoá sắp xếp := (rủi_ro_dự_án(project) desc, khoá_task_hiện_tại)
```

`rủi_ro_dự_án` tái dùng `compute_risk` (`risk_detection.py`) ở phạm vi project:

```python
def project_risk(project, tasks) -> float:
    if project.deadline is None:
        return 0.0                      # dự án cá nhân và mọi dự án không hạn
    base = max((compute_risk(t.priority, overdue_days(t), open_subtasks(t))
                for t in tasks), default=0.0)
    days_left = max((project.deadline.date() - today()).days, 0)
    urgency = 1.0 + 2.0 / (1.0 + days_left)   # 1.0 khi còn xa, 3.0 khi tới hạn
    return base * urgency
```

Hàm thuần, không chạm DB — test được không cần fixture, đúng như `compute_risk`.

Task thuộc dự án cá nhân (3.4) → không có `deadline` → `rủi_ro_dự_án = 0` → sắp đúng như hôm nay ở tầng hai. **Không được thay đổi hành vi hiện tại cho việc lẻ.**

Lý do đây là hạng mục quan trọng nhất mục 13: nó nâng cấp đúng phần lõi mỏng nhất (`today.py`, 305 dòng), và là thứ khiến Gate thắng cách biệt trong phép thử mục 12 — nhắc ngây thơ không có dữ liệu này.

### 7.2 Gộp theo project

`attention_bundle` hiện gộp theo *người + thời điểm*. Thêm project làm khoá gộp:

```
"Alpha có 3 việc cần chú ý"
```

thay vì ba lần rung riêng lẻ về ba việc không liên quan. Việc thuộc dự án cá nhân gộp như hiện tại — nhưng nhãn gộp là tên dự án cá nhân, không phải một nhóm vô danh.

---

## 8. Định tuyến kênh

### 8.1 Phạm vi quyết định kênh

| Phạm vi | Ví dụ `reason_key` | Kênh |
|---|---|---|
| **Cá nhân** | `task.overdue`, `task.due_soon`, `task.at_risk`, `task.stale` | Mezon **DM** |
| **Dự án** | `project.slipping`, `project.will_miss` | Mezon **channel dự án** |

Đây là **thứ duy nhất trong thiết kế tạo ra giá trị tập thể ở đúng chi phí tập thể** — nó gỡ chính lỗi cấu trúc đã giết hướng "bot nghe channel" (mục 1.4).

Cơ chế: thêm trường phạm vi vào `attention_reason_catalog`, `delivery/dispatcher.py` đọc nó để chọn kênh. **Không sửa `attention_gate.py`** — đúng tiêu chí nghiệm thu của F0.

**Channel đích không cần thiết kế thêm:** `projects.source_channel_id` (3.1.1) *chính là* channel phát. Project neo vào channel nào thì nhắc cấp dự án về channel đó. Dự án cá nhân và dự án tạo tay có `source_channel_id = NULL` → mọi nhắc của chúng về DM.

### 8.2 Gate biết bạn bận *vì cái gì*

**Chỉ chạy khi sự kiện đã được gắn project qua 4.2.** Sự kiện chưa gắn → hành xử đúng như hôm nay (im khi bận, không phân biệt dự án).

Bước 3 của Gate đã có `is_user_busy` (`availability.py`). Bổ sung: nếu sự kiện đang diễn ra thuộc project P thì

- lời nhắc thuộc **P** → giữ lại tới ngay sau buổi họp (hoặc đẩy lên ngay *trước*, tuỳ mức)
- lời nhắc thuộc **project khác** → im như hiện tại

### 8.3 `find_free_slots` — nối vào

Hàm đã viết và test xong (`availability.py`, 2026-08-16), chưa nối vào đâu. Ghép với project thì có nội dung thật:

> *"Chiều nay bạn trống 3 tiếng, và Alpha đang chậm 2 việc."*

Hiện ở dòng trạng thái màn Hôm nay và trong card `project.slipping`.

---

## 9. API

### 9.1 Endpoint

Chỉ những gì cần. Mọi endpoint đều dưới auth người dùng trừ `/internal/*`.

| Method | Đường dẫn | Mục đích |
|---|---|---|
| `POST` | `/api/internal/tasks` | Bot họp đẩy action item vào. Nhận `provider_event_id` tuỳ chọn để tra `ScheduleExternalMap`. Dùng `X-Internal-Token` |
| `GET` | `/api/projects` | Liệt kê project đang mở + số liệu tóm tắt (task mở/xong, deadline, rủi ro) |
| `GET` | `/api/projects/{id}` | Chi tiết một project |
| `PATCH` | `/api/projects/{id}` | Sửa `name`, `deadline`, `status`. Đặt cờ "đã sửa tay" cho `deadline` |
| `POST` | `/api/projects` | Tạo tay — `origin='manual'`. **Lối phụ, không phải cửa chính** |
| `PATCH` | `/api/tasks/{id}/project` | Ghi thẳng `tasks.project_id`. **Không đụng `related_event_id`** — nguồn gốc task không đổi khi đổi dự án. Ghi lại một nhãn cho 4.4 |
| `PATCH` | `/api/schedules/{id}/project` | Gán chuỗi sự kiện vào project khác. Chỉ hợp lệ trên hàng template |

Không có endpoint xoá project — `status='closed'` là đủ, và xoá sẽ mồ côi lịch sử `attention_log`.

### 9.2 Tool cho agent — thao tác nhiều dự án trong một hội thoại

**Quyết định nền tảng: không có "project hiện tại" ở mức phiên hội thoại.**

Nếu tồn tại ngữ cảnh project ngầm, sẽ gặp đúng lỗi kinh điển: người dùng nói *"đánh dấu xong việc gửi spec"*, agent lặng lẽ thao tác nhầm dự án, và không ai biết cho tới lúc quá muộn. Thay vào đó **mọi lời gọi tool mang `project_ref` tường minh**, giải tên ngay tại thời điểm gọi.

| Tool | Trạng thái | Ghi chú |
|---|---|---|
| `list_projects(status?)` | **Mới** | Cửa vào. Trả tên, deadline, số việc mở/xong, rủi ro. **Bắt buộc có giới hạn số dòng** — trả 50 dự án kèm task là thổi bay context |
| `get_project_tasks(project_ref, status?)` | **Mới** | Việc trong một dự án. Cùng dữ liệu màn **Việc** (10.2) hiển thị |
| `move_task(task_id, project_ref)` | **Mới** | Ghi thẳng `tasks.project_id`. Không đụng `related_event_id` — nguồn gốc task không đổi khi đổi dự án |
| `create_task(..., project_ref?)` | Mở rộng | Thiếu `project_ref` → theo thứ tự ưu tiên ở 3.5 |
| `list_pending_tasks(..., project_ref?)` | Mở rộng | Thiếu `project_ref` → mọi dự án |
| `create_project(name)` | **Mới, hạn chế** | Chỉ khi người dùng nói thẳng tên và ý định. **Không bao giờ tạo từ suy luận** |

#### Quy tắc giải `project_ref` — chỗ dễ hỏng nhất

```
khớp đúng 1 tên       → dùng
khớp nhiều tên        → ask_user_choice   (tool đã có sẵn)
không khớp gì         → trả danh sách dự án,
                        KHÔNG đoán, KHÔNG tự tạo
```

Nhánh cuối là **P7**. Agent tự tạo dự án `"Alpah"` vì người dùng gõ sai chính tả là kiểu hỏng im lặng tệ nhất — nó tạo dữ liệu rác mà không ai nhận ra cho tới khi báo cáo sai.

Dự án cá nhân (3.4) **không hiện** trong `list_projects` trừ khi người dùng hỏi rõ, để nó không chiếm chỗ trong ngữ cảnh mỗi lần agent liệt kê.

#### Ngân sách tool

Mục 11 cắt từ 21 xuống ~8 tool. Bốn tool mới ở đây nằm trong ngân sách đó, nhưng **mỗi tool là một đường agent có thể đi sai** — thêm tool thứ chín phải trả lời được P5: nó làm agent quyết định *đúng hơn*, hay chỉ làm agent *nói nhiều hơn*.

---

## 10. Giao diện

### 10.1 Sửa tại chỗ, không phải trang quản lý

```
Trong lời nhắc / chi tiết task:

    Nộp spec cho Minh              Alpha ▾
                                   ├ Beta
                                   ├ Cá nhân          ← dự án cá nhân (3.4)
                                   └ Dự án mới…
```

Sửa quy gán **ngay tại chỗ nhìn thấy nó sai** tốt hơn: điều hướng sang trang quản lý → tìm lại task → sửa → quay về. Và nó bỏ được một mục nav.

Tương tự trong chi tiết sự kiện lặp: *"Chuỗi này thuộc: Alpha ▾"* — đổi project của chuỗi, và hỏi *"chuyển N việc đã tạo từ chuỗi này sang theo không?"* (3.5). Không bao giờ ghi đè im lặng.

Mỗi lượt sửa ghi lại làm nhãn cho mục 4.4.

### 10.2 Hai màn hình, hai vai trò khác nhau

| Màn | Phạm vi | Vai trò |
|---|---|---|
| **Hôm nay** (mặc định) | **Tổng hợp mọi dự án**, đã xếp hạng và đã qua Gate | **Bề mặt sản phẩm.** Trả lời *"giờ tôi nên làm gì"* |
| **Việc** | **Chỉ dự án đang mở** | **Bề mặt tra cứu và sửa.** Trả lời *"dự án này đang có gì"* |

Kèm một **bộ chuyển dự án** ở topbar. Component `WorkspaceSwitcher.tsx` dùng lại được về mặt giao diện — nhưng đọc từ bảng `projects`, không phải `workspaces` (3.6).

**Vì sao Hôm nay không lọc theo dự án đang mở:** nếu nó lọc thì người dùng phải tự nhớ đi qua từng dự án để biết mình cần làm gì — tức là chính công việc mà Cortex sinh ra để bỏ đi. Xếp hạng ở 7.1 chỉ có nghĩa khi nó nhìn được toàn bộ.

> ⚠️ **Rủi ro đã biết:** một danh sách việc theo dự án là chỗ sản phẩm bắt đầu trông giống Todoist. Chặn bằng hai điều: **Hôm nay là màn mặc định** khi đăng nhập, và màn Việc **không có** thêm bất kỳ thứ gì ngoài danh sách + dropdown sửa project (10.1). Không sort tuỳ chỉnh, không filter nâng cao, không nhóm, không kéo thả. Mỗi thứ thêm vào đó là một bước về phía sân đã thua.

### 10.3 Nav

| Giữ | Bỏ khỏi nav |
|---|---|
| **Hôm nay** · **Việc** · **Cài đặt** | Schedule · Notes · Records · Workflows · Notifications |

Route vẫn còn, chỉ không hiển thị (11.2). Áp P6: không mục nào trong năm mục bỏ đi có đường dẫn dữ liệu vào `StateEvaluator` hoặc `TodayService`.

Màn **Việc** là ngoại lệ có chủ ý với P6 — nó không làm lời nhắc thông minh hơn, nhưng nó là nơi người dùng *sửa* quy gán project, và mỗi lượt sửa là tín hiệu đầu vào cho 4.4. Ghi lại ngoại lệ này để lần sau ai muốn thêm màn khác phải đưa ra lý do mạnh tương đương.

### 10.4 Làm Gate hiện hình — ⏸ **HOÃN, xem 13.5**

Một dòng trên màn Hôm nay:

> *"Hôm nay đã im 6 lần: 4 lần bạn đang họp, 2 lần gộp vào bản tin chiều."*

Vấn đề nó giải là thật: **một công cụ mà giá trị là im lặng thì trông y hệt một công cụ đã chết**, và tiêu chí thành công ở 12.5 là *"họ không tắt nó"* — người ta tắt thứ có vẻ không làm gì.

Nhưng hoãn, vì hai lẽ.

**Một — tiền đề "dữ liệu đã có" sai.** Kiểm tại 2026-08-25: `attention_log` ghi hàng cho quyết định im, nhưng **không ghi vì sao im**, và loại im thường xuyên nhất thì không ghi gì cả.

| Loại im | Trong `attention_log` |
|---|---|
| Người dùng tắt loại nhắc đó | hàng `level=silent`, không có lý do |
| Bị reason mạnh hơn thay thế | hàng `level=silent`, không có lý do |
| Feedback loop tự hạ cấp | hàng `level=silent`, không có lý do |
| Đang bận / quiet hours | hàng `level=silent`, không có lý do |
| **Dedup — đã nhắc rồi** | **không có hàng nào** (`attention_gate.py` thoát sớm trước khi ghi) |

Nên câu mẫu ở trên không dựng được, và con số "im N lần" sẽ luôn đếm thiếu. Làm đúng cần thêm cột `silence_reason`, ghi một hàng ở nhánh dedup, và **sửa `attention_gate.py`** — đúng tệp mà tiêu chí nghiệm thu của 8.1 lấy làm mốc là không đụng tới.

**Hai — hình dạng sai, và chế độ hỏng rất thật.** Nó là Cortex nói **thêm**, trên màn chính, về **chính nó** (P5), và không có đường dữ liệu nào vào `StateEvaluator` hay `TodayService` (P6 — màn Việc đã là ngoại lệ được ghi nhận, đây sẽ là ngoại lệ thứ hai, lặng lẽ). Tệ hơn: *"đã im 6 lần"* mời câu hỏi *"im về cái gì?"*. Trả lời câu đó là xây một hộp thư các việc bị nén — đúng bản năng "hiện nhiều hơn" mà 1.2 nói là nước cờ thua. Không trả lời thì tạo lo lắng không lối thoát.

**Ba hình dạng tốt hơn, xét lại khi hồi sinh:**

1. Gắn vào tin nhắn Cortex **đang gửi sẵn** — chân card Mezon: *"Hôm nay tôi đã giữ lại 3 lần khác."* Không tạo dịp nói mới nào, nên không đụng P5, và nó xuất hiện đúng lúc người dùng đang đánh giá phán đoán của Cortex.
2. Chỉ hiện ở trạng thái `all_clear` / `nothing_urgent` — đúng chỗ màn hình trống và trông như hỏng.
3. Giữ nội bộ trong 6 tuần thử. Với một người dùng thật, đây thực chất là công cụ debug.

> ⚠️ Nếu xây: **không bấm được, không mở rộng được.** Một con số không có drill-down là sự trấn an; có drill-down là một cái inbox.

**Việc tách rời vẫn còn giá trị:** vá điểm mù dedup trong `attention_log`. Không có nó, câu hỏi *"Cortex đã im đúng bao nhiêu lần"* — chỉ số duy nhất về sau ở 12.5 — là không trả lời được. Nó **không** cần UI đi kèm, và cũng không chặn hai con số nghiệm thu ở 12.3 (cả hai đọc từ `attention_log.response`).

### 10.5 Nút "nhắc sai rồi" — ⏸ **HOÃN, xem 13.5**

Trên mỗi card Mezon. Hiện `feedback_loop` phải *suy* ý người dùng từ tỷ lệ dismiss — tín hiệu nhiễu, vì dismiss có thể chỉ vì đang bận. Một nút tường minh cho tín hiệu sạch hơn nhiều lần.

Hoãn vì **P8, áp đúng chỗ**: một tín hiệu sạch chỉ đáng giá khi có thứ *tiêu thụ* nó, và thứ đó là một vòng học — hạ cấp theo loại nhắc, theo dự án, theo giờ. Xây nút trước vòng học là xây tầng hai trên nền chưa ai đứng, và tệ hơn: nó **buộc** phải xây vòng học ngay sau đó, nếu không người dùng bấm "nhắc sai rồi" ba lần rồi thấy Cortex vẫn nhắc y như cũ — lúc đó nút không phải là trung tính, nó là một lời hứa bị bội.

`feedback_loop.apply_downgrade` hiện tại (hạ cấp theo số lần dismiss) đã là một vòng học thô và **chưa từng chạy với dữ liệu thật**. Đo nó trước; nếu nó đủ, nút này không cần tồn tại.

---

### 10.6 Màu sự kiện theo dự án, không theo `type`

Hiện `CalendarView.tsx:303` gán `cal-event-{type}` với 4 class CSS cố định (`CLASS`/`DEADLINE`/`EXAM`/`PERSONAL`). Loại sự kiện là phân loại **hành chính** — nó không cho biết việc này thuộc về đâu.

Đổi sang tô theo **dự án**:

- Màu suy ra **xác định** từ `project_id` (băm → chỉ số bảng màu), không lưu cột, không bắt người dùng chọn. Cùng dự án luôn cùng màu, mọi máy, mọi phiên.
- Sự kiện **chưa gắn dự án** (phần lớn, theo 4.2) → một màu trung tính, không phải màu của dự án nào. Nó phải trông *khác loại*, không phải "một dự án nữa".
- `type` vẫn còn trong dữ liệu và trong form; chỉ thôi quyết định màu.

### 10.7 Trang Sự kiện — tổng hợp + lọc theo dự án

Một trang, **hiển thị mọi sự kiện từ mọi tài khoản đã sync**, kèm bộ lọc chọn dự án nào được hiện.

- Mặc định: hiện tất cả.
- Bộ lọc là **đa chọn**, kèm hai mục đặc biệt: *"Chưa thuộc dự án"* và *"Theo tài khoản nguồn"* (Google account nào).
- Lọc chỉ **ẩn/hiện**, không đổi dữ liệu — nó là kính lọc, không phải phép gán.

**Vì sao có mục "Theo tài khoản nguồn":** lịch sync theo từng tài khoản; tài khoản chỉ tách được cá nhân ↔ công việc. Đây là chiều phân loại có thật và người dùng nghĩ theo nó — nên để nó là *một chiều lọc*, không phải một phép suy ra dự án (3.1.1).

> ⚠️ Trang này chịu cùng hàng rào như màn Việc (10.2): **chỉ có lịch + bộ lọc**. Không thống kê, không biểu đồ, không chế độ xem tuỳ biến. Nó là kính lọc, không phải dashboard.

---

## 11. Đóng băng — không xoá dòng code nào

**Nguyên tắc: không một tính năng nào bị xoá.** Mọi thứ ở lại repo, ở lại lịch sử git, ở lại nguyên vẹn. Việc duy nhất xảy ra là **gỡ chúng khỏi đường chính**: khỏi luồng khởi động, khỏi `docker-compose` mặc định, khỏi nav, khỏi prompt của agent.

Sau khi phần lõi chạy tốt và có số liệu (mục 12), từng mục được xem xét hồi sinh — và khi đó nền tảng đã tốt hơn, nên xây lại sẽ rẻ hơn và đúng hơn lần đầu.

---

### 11.1 Đóng băng không miễn phí — biết trước để không tự lừa mình

"Để đấy" nghe như chi phí bằng 0. Không phải:

- Code đóng băng **vẫn bị đọc** — bởi bạn, bởi agent, trong mọi lần grep và mọi lần khảo sát codebase.
- Nó **mục dần**: dependency trôi, test hỏng, API bên thứ ba đổi. Hồi sinh sau 6 tháng đắt hơn hồi sinh sau 6 tuần.
- Nó **vẫn kéo sự chú ý**. Đây là chi phí lớn nhất và khó thấy nhất.

Nên đóng băng là một **quyết định có giá**, không phải cách né quyết định. Mục 11.3 tồn tại để giá đó không tăng vô hạn.

### 11.2 Cơ chế — gỡ thế nào cho hồi sinh rẻ

| Loại | Cách gỡ | Cách bật lại |
|---|---|---|
| Service (Temporal, OCR, STT, searxng) | `profiles:` trong `docker-compose.yml` | `docker compose --profile <tên> up` |
| Worker trong backend lifespan | Cờ trong `config.py`, mặc định `False` | Đổi một biến môi trường |
| Mục nav | Gỡ khỏi sidebar `App.tsx`, **giữ nguyên route** | Thêm lại một `<li>` |
| AI tool | Gỡ khỏi `tools/__init__.py` registry, **giữ nguyên file** | Thêm lại một dòng `register` |
| Bảng DB | **Không đụng tới.** Không migration xoá, không drop | Không cần làm gì |

**Không dùng branch riêng, không dùng thư mục `_deprecated/`, không comment-out code.** Cả ba đều làm hồi sinh đắt hơn và làm codebase khó đọc hơn.

**Test của phần đóng băng:** đánh dấu `skip` có lý do (`@pytest.mark.skip(reason="frozen — xem DESIGN.md 11")`), không xoá. Để chúng chạy và hỏng dần sẽ làm hỏng tín hiệu CI cho phần đang sống.

### 11.3 Sổ đóng băng — mỗi mục phải có điều kiện hồi sinh

> **Luật: không mục nào được đóng băng nếu không ghi được điều kiện cụ thể để hồi sinh nó.**
>
> "Khi nào cần" không phải điều kiện. Điều kiện phải là thứ quan sát được và biết được lúc nào nó xảy ra.

| Thành phần | Bằng chứng đóng băng | **Điều kiện hồi sinh** |
|---|---|---|
| `workflow_service` + Temporal | 0 workflow trong DB | Xuất hiện nhu cầu thật cần **nhiều bước / nhiều event** mà không phải "một điều kiện → một nhắc". 7 predicate hiện tại đều không phải loại đó |
| `ocr_service` + MinIO | 0 asset từng xử lý | Có nguồn việc đến từ **ảnh/văn bản chụp** mà bot họp không phủ được |
| `stt_service` (WhisperX + diarization) | 0 asset | **Bot họp hiện tại không đủ** — không đẩy được webhook, hoặc không gán được người nói. Đây là mục có xác suất hồi sinh cao nhất; diarization word-level đã chạy được là đường lùi rẻ |
| searxng + unsearch | Phục vụ một tool phụ | Chi phí API search vượt chi phí vận hành 2 container |
| Notes + Yjs sync-server | 1 note | Ghi chú trở thành **nguồn việc** (note chứa deadline → task), tức là nó nuôi được vòng lặp theo P6 |
| Workspaces | 1 người dùng | Có ≥ 2 đội dùng thật và cần tách dữ liệu giữa các đội |
| Zep | Chưa chứng minh giá trị | `pgvector_memory_provider` đo được là kém hơn rõ rệt trên cùng truy vấn |
| 13 AI tool | Phục vụ bề mặt đã đóng băng | Bề mặt tương ứng được hồi sinh |

Mục tiêu vận hành sau khi gỡ: **≤ 5 container** (`db`, `redis`, `backend`, `mezon_bot`, reverse proxy).

### 11.4 Mô hình cuối cùng — `projects` là container duy nhất

**Đã chốt về đích, chưa tới lúc trả tiền.**

Có hai container song song (`workspaces` cho tài liệu, `projects` cho việc) là một cái wart, và nó không phải trạng thái cuối. Khi Notes hoặc Assets hồi sinh theo điều kiện ở 11.3:

```sql
ALTER TABLE notes  ADD COLUMN project_id UUID REFERENCES projects(id);
ALTER TABLE assets ADD COLUMN project_id UUID REFERENCES projects(id);
-- rồi khai tử workspaces
```

`projects` trở thành container duy nhất cho cả việc lẫn tài liệu.

**Vì sao đi đường này thay vì đổi tên `workspaces` ngay bây giờ:** đổi tên giữ nguyên hành lý của workspace dưới một cái tên mới — `is_personal`, tự tạo lúc đăng ký (`auth.py:136`), `WorkspaceMember.role` là quyền *đọc tài liệu*, `slug` unique toàn hệ thống, `workspace_permission.py` với 7 tệp phụ thuộc. Kết quả là *một container mang tên project*, không phải *một container thật sự là project*.

Con đường này tới cùng một đích với một thực thể sạch. Và thời điểm đứng về phía nó: hiện có **1 note, 0 asset** — migration sau này chạy trên gần như không có dữ liệu. Xem bảng chi phí ở 3.6.

### 11.5 Rà lại định kỳ

Sổ ở 11.3 được đọc lại **mỗi khi đọc số của mục 12**. Mỗi mục có đúng ba kết cục, và phải chọn một:

1. **Điều kiện đã xảy ra** → hồi sinh, ghi ngày.
2. **Điều kiện chưa xảy ra** → tiếp tục đóng băng, không bàn thêm.
3. **Điều kiện sẽ không bao giờ xảy ra** → lúc này mới bàn tới việc xoá, và đó là một quyết định riêng, có chủ đích.

Không có kết cục thứ tư là "để đó xem sao". Đó chính là trạng thái đã tạo ra 84.000 dòng code cho một người dùng.

### 11.6 Vì sao đây không phải là vứt bỏ công sức

Không dòng nào mất đi. Phần lớn những gì đóng băng ở đây được xây tử tế — `stt_service` có diarization word-level đã qua 6 vòng sửa lỗi, delivery layer có tiêu chí nghiệm thu rõ ràng, workflow runtime chạy trên Temporal đúng bài.

Vấn đề chưa bao giờ là chất lượng của chúng. Vấn đề là **cả bảy thứ cùng ở trên đường chính một lúc**, nên không thứ nào đủ tốt để có người dùng.

Xây lại sau — khi phần lõi đã có số liệu thật, khi biết chính xác người dùng cần gì từ chúng — sẽ **rẻ hơn và đúng hơn lần đầu**. Đóng băng là để dành, không phải để bỏ.

---

## 12. Cổng nghiệm thu — phép thử A/B

### 12.1 Giả định đang đặt cược

> **Nhắc qua Attention Gate hơn nhắc ngây thơ đủ nhiều để người dùng cảm nhận được.**

Nếu sai: bot họp thêm chức năng nhắc trong hai tuần và Cortex không còn sản phẩm. **Không có phòng thủ nào khác.** Nên phép thử này đứng trước mọi việc ở tuần 3 trở đi.

### 12.2 Cách chạy

20–30 action item thật, chia đôi, cùng người dùng, cùng khoảng thời gian, tối thiểu 2 tuần.

```
Nhóm A   đến hạn → ping một lần
Nhóm B   qua Gate đầy đủ:
         dedup · im khi bận · quiet hours · gộp theo project · chọn thời điểm
```

Cơ chế: một cờ per-user bỏ qua Gate và gọi thẳng `create_notification_*`.

### 12.3 Hai con số

1. **Tỷ lệ dismiss** — thấp hơn là tốt hơn
2. **Tỷ lệ được làm trong 24h sau khi nhắc** — cao hơn là tốt hơn

### 12.4 Quy tắc quyết định

| Kết quả | Làm gì |
|---|---|
| B hơn A rõ rệt trên cả hai số | Có hào. Đi tiếp, và biết chính xác đang bán cái gì |
| B hơn A không đáng kể | Gate không phải hào ở sân này. Chuyển sang bán chính engine cho bài toán **alert fatigue** — nơi vấn đề gay gắt hơn và có ngân sách. Sáu tuần không phí, vì Gate cuối cùng cũng có số liệu vận hành thật |

### 12.5 Chỉ số duy nhất về sau

> **Số lần Cortex nói một điều người dùng chưa biết, và họ hành động theo.**

DAU sai với sản phẩm này — mục tiêu là người dùng **không cần** mở nó. Dữ liệu đã nằm sẵn trong `attention_log` (ghi cả trường hợp im lặng) join với phản hồi trên card Mezon.

**Thành công sau 6 tuần:** một đội thật, mỗi người ≥ 1 lần/tuần, và họ **không tắt nó**.

---

## 13. Kế hoạch

### 13.0 Trước tuần 0 — không phải code

Mang câu này đi hỏi 5 người:

> *"Nếu có thứ tự động nhận việc từ biên bản họp, gom theo dự án, rồi nhắn riêng nhắc bạn trước hạn — bạn có muốn tắt nó ngay không?"*

Trả lời **"có, tắt ngay"** có giá trị ngang **"muốn thử"**. Chi phí 0 dòng code, 2 ngày. Không ai muốn thì dừng tại đây và tiết kiệm 3 tuần.

### 13.1 Tuần 0 — Gỡ khỏi đường chính và dựng chỗ đứng

- Đóng băng theo mục 11 · nav xuống 3 mục · tool xuống ~8
- VPS: `db` + `redis` + `backend` + `bot` + Caddy TLS
- Xoay secret (`SECRET_KEY`, `INTERNAL_API_KEY` hiện là giá trị mặc định trong code)
- Migration một lượt:
  - bảng `projects` + `project_members` — 3.1
  - `schedules.project_id` — 3.2
  - `tasks.project_id` ba bước add→backfill→NOT NULL — 3.3
  - **sửa `uq_schedule_external_maps_provider_event` để kèm `user_id`** — chặn thật, xem QĐ-1 phát hiện #2
- Quy tắc xác định 3.5 + suy ra 4.1 (kèm tự thêm thành viên)

**Nghiệm thu:** khởi động còn ≤ 5 container · hệ thống chạy ngoài laptop · `tasks.project_id` là `NOT NULL` và mọi task hiện có đã được backfill · tạo một chuỗi sự kiện lặp + một task gắn vào nó → project tự xuất hiện, không ai bấm gì · tạo task khi đang mở dự án Alpha mà không gắn sự kiện nào → task thuộc **Alpha**, không phải dự án cá nhân · **hai người cùng sync một cuộc họp không còn lỗi ràng buộc, và cả hai vào chung một project** (QĐ-1).

### 13.2 Tuần 1 — Làm Gate nói được câu không ai nói được

- 7.1 xếp hạng theo rủi ro dự án
- 8.1 định tuyến kênh theo phạm vi
- 6.1 + 6.2 hai predicate
- 10.1 dropdown sửa tại chỗ · 10.2 hai màn Hôm nay / Việc + bộ chuyển dự án

> **10.4 và 10.5 đã rời tuần này** — chuyển xuống sổ hoãn 13.5 (quyết định 2026-08-25). Cả hai là bề mặt *về cơ chế*, không phải về việc của người dùng; và 10.5 kéo theo một vòng học phải xây ngay sau nó. Tuần 1 cần ổn định trước, không cần thêm bề mặt.

**Nghiệm thu:** một lời nhắc thật có nội dung Todoist không tạo ra được — ví dụ *"Alpha còn 5 ngày, 3 việc quá hạn, 2 việc đang chờ Minh"* · nhắc cấp dự án về đúng channel, nhắc cá nhân về đúng DM · **test khoá bất biến 3.4:** dự án cá nhân với 50 task quá hạn không sinh predicate cấp dự án nào · agent thao tác được hai dự án khác nhau trong cùng một hội thoại mà không nhầm (9.2).

### 13.3 Tuần 2 — Nối nguồn thật và chạy phép thử

- 9 `POST /api/internal/tasks` + tra `provider_event_id`
- 12.2 cờ bật/tắt Gate per-user
- Chạy A/B trên 20–30 action item thật

**Nghiệm thu:** có số.

### 13.4 DỪNG

**Không tính năng nào ở tuần 3 cho tới khi đọc xong hai con số của mục 12.3.** Đây là điểm dừng bắt buộc, không phải gợi ý.

### 13.5 Sổ hoãn — mỗi mục phải có điều kiện làm lại

> **Cùng luật với sổ đóng băng ở 11.3: không mục nào được hoãn nếu không ghi được điều kiện cụ thể để làm lại nó.** *"Khi nào ổn định"* không phải điều kiện. Điều kiện phải quan sát được và biết được lúc nào nó xảy ra.
>
> Khác 11.3 ở một điểm: 11.3 là code **đã có**, gỡ khỏi đường chính. Đây là thứ **chưa xây**. Nên chi phí hoãn ở đây gần bằng 0 — không có gì mục dần, không có gì phải đọc lướt qua khi grep.

| Mục | Vì sao hoãn | **Điều kiện làm lại** |
|---|---|---|
| **10.4** dòng "đã im N lần" | Tiền đề "dữ liệu đã có" sai — `attention_log` không ghi *lý do* im, và nhánh dedup không ghi gì cả. Cộng thêm P5/P6: Cortex nói thêm, về chính nó, trên màn chính | Điểm mù dedup đã vá **và** có bằng chứng quan sát được rằng người dùng tưởng nó chết — họ hỏi *"nó còn chạy không?"*, hoặc mở app chỉ để kiểm tra. Không có bằng chứng đó thì đây là giải pháp cho một vấn đề chưa tồn tại |
| **10.5** nút "nhắc sai rồi" | P8 — tín hiệu sạch chỉ đáng giá khi có thứ tiêu thụ nó, và thứ đó là một vòng học chưa có. Nút không có vòng học phía sau là một lời hứa bị bội | `feedback_loop.apply_downgrade` đã chạy với dữ liệu thật **và** đo được là không đủ: tỷ lệ dismiss vẫn cao dai dẳng sau khi nó đã tự hạ cấp. Lúc đó mới biết cần học *thêm gì*, và nút được thiết kế theo cái đó thay vì theo phỏng đoán |
| **16** trigger chủ động cho agent | Nó **bơm nhiễu vào chính phép đo của mục 12**: `ab_test_numbers.py` lọc theo `level != 'silent'` và `item_type == TASK`, không lọc `reason_key` — nên một lời nhắc từ watch rơi vào mẫu số của nhóm B và được chấm bằng "task xong trong 24h". Cộng thêm P8: nếu 12.4 rẽ nhánh hai thì tầng này đứng trên một giả định vừa bị bác | Hai con số 12.3 đã đọc **và** nhóm B thắng **và** có người dùng thật hỏi *"sao nó không tự theo dõi giúp tôi cái này"*. Thiết kế đầy đủ đã ghi ở mục 16 — không phải nghĩ lại từ đầu |

**Việc tách rời, vẫn nên làm nhưng không gấp:** vá điểm mù dedup trong `attention_log` (10.4). Nó là điều kiện cần cho chỉ số duy nhất về sau ở 12.5, nhưng **không** chặn hai con số nghiệm thu ở 12.3 — cả hai đọc từ `attention_log.response`, không liên quan tới đếm im lặng. Nên nó xếp sau tuần 2, và nó sửa `attention_gate.py` nên đừng làm cùng lúc với bất kỳ thay đổi nào khác trên Gate.

---

## 14. Không làm

Danh sách từ chối. Mỗi mục đều đã được cân nhắc và bác bỏ có lý do — đưa lại phải kèm lý do mới, không phải lý do cũ.

| Không làm | Vì sao |
|---|---|
| Board / Kanban / Gantt | Là Jira. Thua chắc |
| Template dự án, workflow riêng từng dự án | Hồi sinh `workflow_service` qua cửa sau |
| Thảo luận trong dự án | Mezon đã là chỗ đó |
| Phân bổ nguồn lực, capacity planning | PM doanh nghiệp, sân khác |
| Quyền theo dự án | Workspace tập hai |
| Dashboard, báo cáo, biểu đồ | Điểm đến. Không ai mở lần thứ hai. Vi phạm P5 |
| Dựng lại Goal | Đã chết vì P4. Project là bản thay thế |
| AI reasoning trong Gate (6.4 cũ) | Vi phạm P3 cho tới khi đo được tỷ lệ Gate không quyết nổi |
| Cortex tự trích action item từ chat / họp | Đã có hệ thống khác làm. Mục 1.4 |
| App mobile native | Bot Mezon phủ ~95% giá trị với ~5% chi phí |
| Inbound Email / GitHub | Vi phạm 1.2 — làm danh sách dài ra, không làm quyết định tốt lên |

---

## 15. Rủi ro đã biết và câu hỏi mở

### ✅ QĐ-1 — Project dùng chung, có bảng thành viên. **CHỐT 2026-08-24**

`projects` không thuộc về một người. `owner_id` là *ai tạo ra*; ai ở trong dự án thì tra `project_members`. Bảng thành viên **không có cột `role`** (đó là thứ làm `WorkspaceMember` sai ngữ nghĩa) và thành viên được **suy ra, không mời** (P4).

Lo ngại ban đầu là P8 — membership là tầng thứ hai. Bác bỏ: nó là **điều kiện để tầng thứ nhất đúng**. Không có nó thì số liệu cấp dự án gửi vào channel chung là sai.

### ✅ QĐ-2 — Project neo vào Mezon channel, không neo vào lịch. **CHỐT 2026-08-25**

Bản trước neo project vào chuỗi sự kiện Google (`source_event_key`). Sai, vì hai lẽ đã kiểm chứng:

1. **Lịch không sync chéo** — mỗi tài khoản chỉ nhận sự kiện của mình, nên không có danh tính chung.
2. **Lịch không mang thông tin dự án.** Tài khoản chỉ tách được cá nhân ↔ công việc; trong một lịch công việc, standup / 1:1 / ăn trưa / họp dự án nằm lẫn nhau, không có tín hiệu nào phân biệt. Suy ra project từ hình dạng lịch là phỏng đoán, và P7 cấm.

Channel thì có đủ bốn thứ lịch không có: danh tính chung, thành viên sẵn, tên do người đặt, và bot họp đã sống ở đó. Xem bảng ở 3.1.1.

**Lịch trở về đúng vai: khung thời gian, không phải cấu trúc dự án.** Việc gắn sự kiện vào project là lớp phủ tuỳ chọn qua thang bốn mức ở 4.2 — không có nó thì chỉ mất 8.2 và ngữ cảnh trước họp, cả hai là tính năng cộng thêm.

**Ba câu hỏi mở cũ đóng theo:**

| | Trạng thái |
|---|---|
| `iCalUID` có chung giữa người dự không | ✅ Không còn liên quan — danh tính dự án không đi qua lịch |
| Ánh xạ project → Mezon channel | ✅ Không cần — project *là* channel (`source_channel_id`) |
| `uq_schedule_external_maps` thiếu `user_id` | ⚠️ Vẫn là lỗi thật nhưng **không còn chặn**. Sửa trong tuần 0 |

### ✅ QĐ-3 — Không xây bề mặt phản hồi trước khi có vòng học. **CHỐT 2026-08-25**

10.4 (dòng "đã im N lần") và 10.5 (nút "nhắc sai rồi") rời khỏi Tuần 1, vào sổ hoãn 13.5.

Lý do chung, và nó là P8 áp đúng chỗ: **cả hai là bề mặt nói về cơ chế, không nói về việc của người dùng.** 10.4 báo cáo Cortex đã quyết định gì; 10.5 thu tín hiệu mà hiện chưa có gì tiêu thụ. Cái sau nguy hơn cái trước — một nút phản hồi không có vòng học phía sau không trung tính, nó là lời hứa bị bội: bấm ba lần rồi thấy Cortex nhắc y như cũ.

Phát hiện kèm theo, và là lý do 10.4 phải hoãn chứ không chỉ nên hoãn: **tiền đề "dữ liệu đã có" của nó sai.** `attention_log` không lưu *lý do* im, và nhánh dedup — loại im thường xuyên nhất — không ghi hàng nào. Xem bảng ở 10.4.

Cái được đánh đổi là thật và ghi lại ở đây để không quên: một công cụ mà giá trị là im lặng thì trông y hệt một công cụ đã chết, và 12.5 lấy *"họ không tắt nó"* làm tiêu chí. Nếu trong 6 tuần thử có bằng chứng người dùng tưởng nó chết, đó chính là điều kiện làm lại đã ghi ở 13.5 — không phải một lần cân nhắc lại từ đầu.

**Rủi ro 1 — Bot họp thêm chức năng nhắc.** Phòng thủ duy nhất là chất lượng Gate, và nó chưa được chứng minh. Mục 12 tồn tại chính vì rủi ro này.

**Rủi ro 2 — Bước 2 của 3.5 gán sai.** Action item đến từ channel #alpha nhưng thực ra là việc của Beta → task lấy project Alpha, và sai. **Không phát hiện được, và không nên cố.** Giảm thiểu bằng P7 (bước 2 chỉ áp dụng khi sự kiện thuộc chuỗi lặp) + 10.1 (sửa tại chỗ) + 4.4 (đo tỷ lệ sửa).

**Rủi ro 3 — Attention Gate mới chạy 1 lần trong đời.** Toàn bộ tinh vi của nó chưa từng gặp tải thật. Có thể có lỗi mà chỉ tải thật mới lộ.

**Câu hỏi mở 1 —** Bot họp hiện có đẩy được webhook không, và output của nó có mang `provider_event_id` của cuộc họp không? Nếu không thì 4.2 phải đổi và cần một cột nguồn trên `tasks`. **Cần xác nhận trước tuần 2.**

**Câu hỏi mở 2 —** Đã đóng bởi QĐ-2: project *là* channel.

**Câu hỏi mở 3 —** `project.will_miss` cần ≥ 14 ngày dữ liệu `completed_at` mới có tốc độ. Dự án mới sẽ im trong hai tuần đầu. Chấp nhận được, nhưng cần ghi rõ trong card để không trông như hỏng.

---

## 16. Trigger chủ động cho agent — ⏸ **HOÃN, xem 13.5**

Thiết kế đầy đủ, ghi lại để khi điều kiện ở 16.7 xảy ra thì không phải nghĩ lại từ đầu. **Không code mục này trước khi đọc hai con số của 12.3** — lý do ở 16.6, và nó là lý do kỹ thuật, không phải kỷ luật roadmap.

### 16.1 Cái được hỏi, và cái thực sự còn thiếu

Câu hỏi ban đầu: *"làm sao để LLM tự được trigger khi một sự kiện xảy ra, như hook của Claude Code."* Claude Code làm việc đó bằng bốn thứ — hook (matcher xác định trên event), thông báo khi việc nền xong, cron/wakeup, và watch trạng thái ngoài.

Cortex đã có ba trong bốn tầng của cả bốn thứ đó:

| Tầng | Đang có gì | |
|---|---|---|
| **0 — Tín hiệu** | `events/event_bus.py` (Redis Streams, consumer group bền, DLQ, fan-out) + `state_evaluator.py` (vòng lặp poll, 11 predicate, `StateEvaluatorFlag` chống lặp) | ✅ |
| **1 — Khớp** | Không có. `subscribe()` chỉ nối cứng event → handler viết tay trong `notification_subscribers.py` | ❌ |
| **2 — Chạy LLM** | Không có. `AgentService` luôn cần một `message` từ người | ❌ |
| **3 — Nói ra** | `attention_gate.py:request_attention_async` → `delivery/dispatcher.py` → Mezon DM/channel | ✅ |

> **Ghi lại để không bị bán một lần nữa:** Cortex **đã** trigger chủ động rồi. `StateEvaluator` chạy 11 predicate không có người trong vòng lặp, tự bắn event, tự đi qua Gate, tự về DM. Mục này **không** thêm khả năng "chủ động" — nó chỉ đổi *ai viết câu*: template → LLM. Delta giá trị nhỏ hơn cảm giác ban đầu nhiều, và biết điều đó là điều kiện để không xây nó quá sớm.

Phần phải xây là **một tầng khớp 0 token và một agent runner không có người trong vòng lặp**. Ước lượng 400–600 dòng. Không phải một platform.

### 16.2 Bốn tầng và ranh giới token

```
Tầng 0  TÍN HIỆU     event bus · StateEvaluator · cron tick         0 token   (đã có)
   │
Tầng 1  KHỚP         TriggerDispatcher: (event_type, match=)        0 token   ← MỚI
   │                 equality trên payload. KHÔNG expression.
   │                 + cooldown + ngân sách + chống vòng lặp
   ▼   hàng đợi Redis `agent:trigger:runs`
Tầng 2  CHẠY         HeadlessAgentRunner: 1 lượt, ≤3 vòng tool,     CÓ token  ← MỚI
   │                 timeout cứng, tool set thu hẹp
   │                 → {"speak": false}  ← kết cục THƯỜNG GẶP NHẤT
   ▼
Tầng 3  NÓI          request_attention_async(reason_key=...)        0 token   (đã có)
                     → Gate vẫn có quyền im → delivery
```

Hai bất biến giữ cho nó không vi phạm P1 và P3:

- **LLM không bao giờ quyết định có bắn hay không.** Khớp là xác định, 0 token, vĩnh viễn.
- **Output của LLM không phải là một notification.** Nó là một *đề xuất* nộp cho Gate; Gate vẫn im được. Không component nào ghi thẳng vào `notifications` — P1 nguyên vẹn, và `attention_gate.py` không phải sửa một dòng.

**Vì sao tầng 2 xứng đáng tốn token (lập luận P3):** 11 handler trong `notification_subscribers.py` render câu từ template viết sẵn — hợp lệ, vì điều kiện là cố định và biết trước. Một watch thì ngược lại: chỉ dẫn của người dùng là ngôn ngữ tự nhiên tuỳ ý (*"theo dõi Alpha, khi Minh xong phần API thì bảo tôi"*), không template nào viết trước được. Đó đúng là *"logic deterministic không quyết nổi"*.

**Vì sao có hàng đợi giữa tầng 1 và 2, không gọi thẳng:** một lời gọi LLM bên trong `route_event()` sẽ chặn bus, và ngữ nghĩa retry sai — LLM timeout không nên đẩy event vào DLQ. Dùng đúng hình dạng outbox mà `NotificationDelivery` đã dùng, và đó cũng là chỗ duy nhất giới hạn concurrency phải sống.

### 16.3 Mô hình dữ liệu

```sql
CREATE TABLE agent_triggers (
    id UUID PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID NULL REFERENCES projects(id) ON DELETE SET NULL,
    kind agenttriggerkind NOT NULL,          -- event | schedule | condition

    -- KHỚP (xác định, 0 token)
    event_type VARCHAR(64) NULL,             -- phải thuộc EVENT_VOCABULARY, validate lúc tạo
    match      JSONB NOT NULL DEFAULT '{}',  -- equality trên payload. KHÔNG toán tử, KHÔNG biểu thức
    next_run_at TIMESTAMP NULL,              -- kind=schedule

    -- CHẠY
    instruction TEXT NOT NULL,               -- câu người dùng đã nói, giữ nguyên
    tool_grants JSONB NOT NULL DEFAULT '[]', -- quyền quyết MỘT LẦN lúc tạo; rỗng = chỉ đọc
    reason_key  VARCHAR(100) NOT NULL DEFAULT 'agent.watch',

    -- VÒNG ĐỜI — phần giữ cho bảng không phình
    status      agenttriggerstatus NOT NULL DEFAULT 'active',  -- active|fired|expired|disabled
    fire_limit  INT NOT NULL DEFAULT 1,      -- MẶC ĐỊNH BẮN MỘT LẦN
    fire_count  INT NOT NULL DEFAULT 0,
    expires_at  TIMESTAMP NOT NULL,          -- KHÔNG NULL BAO GIỜ. mặc định +14 ngày
    cooldown_seconds INT NOT NULL DEFAULT 3600,
    last_fired_at TIMESTAMP NULL,
    source_conversation_id UUID NULL,
    created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL
);
CREATE INDEX ix_agent_triggers_dispatch ON agent_triggers (event_type) WHERE status = 'active';
```

Ba cột chịu lực. Bỏ cột nào thì mục này thành thứ khác:

| Cột | Vì sao chịu lực |
|---|---|
| `expires_at NOT NULL` | Một watch là **lời hứa có ngày hết hạn**. Đây là câu trả lời cho **P4**: watch do người dùng khai, nhưng nó *tự chết*, nên không có màn hình nào phải duy trì. Không có cột này thì sáu tháng nữa bảng đầy watch chết đúng như `goals` |
| `fire_limit` mặc định 1 | *"Theo dõi X"* gần như luôn có nghĩa *"báo tôi lần đầu"*. Lặp vô hạn phải là lựa chọn tường minh, không phải mặc định |
| `match` chỉ equality | Thêm `$gt`, `$or`, hay bất kỳ toán tử nào là đang viết DSL, và DSL là `workflow_service` hồi sinh qua cửa sau (11.3). Điều kiện phức tạp hơn thì viết thành một predicate xác định trong `StateEvaluator` rồi bắn event — đường đó đã có sẵn |

```sql
CREATE TABLE agent_trigger_runs (
    id UUID PRIMARY KEY,
    trigger_id UUID NULL REFERENCES agent_triggers(id) ON DELETE SET NULL,
    user_id UUID NOT NULL, event_id VARCHAR(64) NULL,
    started_at TIMESTAMP NOT NULL, finished_at TIMESTAMP NULL,
    status runstatus NOT NULL,           -- ok|no_output|error|budget_denied|timeout
    tokens_in INT, tokens_out INT, model VARCHAR(64),
    outcome_notification_id UUID NULL,   -- NULL = đã chạy nhưng không nói ra
    error TEXT NULL
);
CREATE UNIQUE INDEX uq_trigger_run_event
    ON agent_trigger_runs (trigger_id, event_id) WHERE event_id IS NOT NULL;
```

Unique index đó chống bắn trùng khi `XAUTOCLAIM` reclaim message của một consumer đã chết — không có nó, một lần crash sinh hai tin nhắn cho cùng một sự kiện. Bảng này cũng chính là nguồn số cho 12.5: *bao nhiêu lượt chủ động thực sự dẫn tới hành động*, và chi phí token của chúng.

### 16.4 Thành phần

| Tệp mới | Nội dung |
|---|---|
| `services/triggers/dispatcher.py` | `subscribe()` mọi type trong `EVENT_VOCABULARY`; lọc trigger active theo `(event_type, user_id)`, áp `match`, cooldown, ngân sách → `XADD agent:trigger:runs`. **0 token** |
| `services/triggers/runner.py` | `HeadlessAgentRunner.run(trigger, event)` — dựng `ToolContext(user_id=…, project_id=trigger.project_id)`, system prompt riêng, tool set thu hẹp, `max_tool_iterations=3`, timeout 30s, không streaming |
| `services/triggers/budget.py` | Trần theo ngày/người, concurrency toàn cục, circuit breaker theo trigger |
| `services/triggers/outcome.py` | `speak:true` → `request_attention_async(...)`. **Không bao giờ gọi `create_notification_*`** |
| `services/trigger_worker.py` | `TriggerWorker`, vào lifespan qua `WorkerThread`, sau cờ `ENABLE_AGENT_TRIGGERS=false` — đúng cơ chế 11.2 |
| `ai/prompts/system/proactive_system.md` | Prompt cho lượt không có người |
| `ai/tools/watch.py` | `create_watch` / `list_watches` / `cancel_watch`, đăng ký qua `CommandRegistry` — quyền, snapshot, audit, revert có sẵn |

Hình dạng output bắt buộc của tầng 2:

```json
{"speak": false}
{"speak": true, "title": "…", "body": "…", "level_hint": "inform|recommend|ask"}
```

`{"speak": false}` phải là kết cục **rẻ, bình thường và hay gặp nhất**; prompt nói thẳng điều đó. Và `agent_trigger_runs` phải cho thấy tỷ lệ im **≥ 50%** — nếu thấp hơn, model đang tìm cớ để nói, và đó là **P5 hỏng ngay tại tầng mới**, không phải một tham số cần chỉnh.

### 16.5 Ba ràng buộc giữ cho nó không thành cỗ máy spam

**1 — Chống vòng lặp. Bắt buộc có ở F1, không phải "để sau".** Một headless run tạo task → `task.created` → khớp một watch khác → chạy tiếp. `EventEnvelope` đã có trường `source`: event do một run sinh ra mang `source="agent_trigger"`, và dispatcher **từ chối khớp mọi event có source đó**. Một dòng `if`. Không có nó, một đêm mất vài triệu token và không ai biết cho tới lúc xem hoá đơn.

**2 — Ngân sách cứng, trong code, không phải trong prompt.** ≤ 20 run/người/ngày · ≤ **5 lượt được nói**/người/ngày · concurrency toàn cục 2 · cooldown mỗi trigger 1h. Vượt trần → `budget_denied`, ghi hàng, im. Đây là chỗ **P5 được thi hành**; một câu dặn trong prompt không phải là thi hành. Trigger lỗi 3 lần liên tiếp → `disabled`, và báo cho người dùng **một lần** qua Gate — một watch hỏng âm thầm đúng là loại "lời hứa bị bội" đã mô tả ở 10.5.

**3 — Nội dung không tin được.** Payload của `task.created` có thể chứa văn bản do bot họp bơm vào từ biên bản của người khác, và nó đi vào một lượt LLM **có tool**. Nên: payload luôn được bọc như *dữ liệu* trong prompt, và `tool_grants` mặc định **rỗng** — F1–F3 chỉ có tool đọc. Quyền ghi là F4, sau khi có số.

### 16.6 Vì sao phải hoãn — lý do kỹ thuật, không phải kỷ luật

**Nó bơm nhiễu thẳng vào phép đo của mục 12.** `scripts/ab_test_numbers.py` lọc đúng hai điều kiện: `level != 'silent'` và `item_type == TASK`. **Không lọc theo `reason_key`.** Một watch kiểu *"theo dõi task X"* khi nói ra sẽ rơi vào mẫu số của nhóm B và được chấm bằng "task xong trong 24h" — công của một lời nhắc mà Gate không tạo ra. Kết quả là đo Gate với một cái loa thứ hai trong phòng, trong khi 12.4 bắt ra quyết định sống-chết của sản phẩm dựa trên đúng hai con số đó.

**Và nếu Gate thua thì tầng này là công dã tràng.** Nhánh hai của 12.4 (chuyển sang bài toán alert fatigue) làm cho một tầng LLM **xây trên Gate** không dùng lại được — nó đứng trên giả định vừa bị bác. Đó là **P8** áp đúng chỗ.

### 16.7 Điều kiện làm lại

> Hai con số 12.3 đã đọc **và** nhóm B thắng **và** có người dùng thật hỏi *"sao nó không tự theo dõi giúp tôi cái này"* — chứ không phải mình nghĩ họ sẽ hỏi.

Khi đó, lộ trình:

| | Việc | Nghiệm thu |
|---|---|---|
| **F0** ~0.5 ngày, 0 token | Hai bảng + dispatcher + worker; tầng 2 tạm thời là **template**, chưa gọi LLM | Tạo tay một trigger trên `task.overdue` → có một hàng `agent_trigger_runs` và một notification qua Gate. Chứng minh đường ống trước khi tiêu token nào |
| **F1** ~1.5 ngày | `HeadlessAgentRunner` thật + `budget.py` + chống vòng lặp + prompt | Test khoá: event `source="agent_trigger"` **không** khớp trigger nào · vượt trần ngày → `budget_denied`, không gọi LLM · `{"speak": false}` không sinh notification nào · cùng `event_id` xử lý hai lần chỉ sinh **một** run |
| **F2** ~1 ngày | `create_watch`/`cancel_watch` qua `CommandRegistry` + nút "hủy theo dõi" trên card Mezon | *"Theo dõi task X, xong thì báo tôi"* → có trigger, `expires_at` = +14 ngày, `fire_limit=1` · task xong → **một** tin DM · trigger chuyển `fired` |
| **F3** ~1 ngày | `kind='schedule'` (poll `next_run_at`) và `kind='condition'` (bám cadence `StateEvaluator`) | *"8h sáng thứ Hai tóm tắt Alpha"* chạy đúng một lần mỗi tuần, và **im** khi Alpha không có gì đổi |
| **F4** | `tool_grants` cho tool ghi — agent *làm*, không chỉ *nói* | Không mở trước khi F1–F3 có số vận hành thật |

### 16.8 Ranh giới với `workflow_service`

Mục này **không** phải cửa sau hồi sinh `workflow_service`. Phân biệt bằng một câu:

> `agent_triggers` là **một điều kiện → một lượt agent**. Nhiều bước, nhiều event, trạng thái giữa các bước, retry theo bước — là Temporal, và điều kiện hồi sinh của nó ghi ở 11.3.

Phòng thủ cụ thể là hai mặc định ở 16.3: `match` chỉ equality, `fire_limit` = 1. **Ngày nào thấy mình muốn thêm `$or` vào `match`, dừng lại và đọc 11.3** — lúc đó điều kiện hồi sinh Temporal đã thật sự xảy ra, và xây tiếp ở đây là đi đường vòng đắt hơn.
