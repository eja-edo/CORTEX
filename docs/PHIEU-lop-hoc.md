# Phiếu L7 — Gói "Lớp học": `class` làm gốc, `assignment` là thực thể thật

> Trạng thái: **ĐANG LÀM (2026-10-30).** Migration 0037/0038, models, backend và giao diện đã viết theo phiếu này; còn chờ chạy toàn bộ test và áp lên DB demo. Soạn 2026-10-30.
> Sau khi duyệt: thêm một dòng vào bảng quyết định của DESIGN.md và một hàng WP vào PLAN.md (quyền sở hữu tệp).

## 1. L1 — ba câu hỏi

1. **Thuộc gói nào?** Hướng mở rộng "hỗ trợ học viên" (DESIGN 2026-10-21), tức WP31/33 (`lesson_recap`, `classroom_grader`). Không thuộc gói nào trong v0 (§7.2).
2. **Đưa tới cổng nào, bằng cách nào?** Tới G2.5 (khách xác nhận hướng mở rộng): giáo viên thấy một "lớp" duy nhất có bài giảng, bài tập, bài nộp, thay vì ba trang rời nhau.
3. **Bằng chứng trong `docs/customers/`?** **Không có.** Thư mục này chỉ có README. Lý do duy nhất là yêu cầu của chủ dự án (2026-10-30: gộp Bài giảng, Chấm bài, Bài tập vì bản chất liên quan nhau). Phải ghi trung thực như các dòng 2026-10-17/22/23: *đây là xây trước khi có khách, trái LESSONS*. Và mốc G1 (2026-10-23) đã qua: cần chủ dự án xác nhận G1 kết thúc ra sao, vì L4 nói trượt G1 thì dừng code mới.

## 2. Vấn đề của schema hiện tại (đã đọc `db/models.py`)

- "Lớp" nằm ở hai bảng không nối nhau bằng khoá ngoại: `lesson_source` (Drive + Mezon + Classroom đăng bài) và `classroom_source` (khoá chấm bài). Chỉ trùng nhau qua chuỗi `course_id`.
- Nhiều lớp có thể cùng một `course_id` (ràng buộc duy nhất của `lesson_source` là `(tenant, sandbox, kind, ref)`, không phải theo course).
- "Bài tập" không phải bảng: là chuỗi `coursework_id` lặp ở `grading_guide`, `grade_item`, `assignment_draft`. Tiêu đề, điểm tối đa, `ours` bị chép vào từng bài nộp (`work_title`, `max_points`, `course_name`, ...).
- `assignment_draft` và `grading_guide` mô tả cùng một thứ ở hai thời điểm.
- Chính sách tự động chưa có chỗ ở: `classroom_publish` là cờ lẻ, phần còn lại là `write` chọn từng bài nộp ở màn Chấm bài.

## 3. Mô hình đích

```
class ─┬─< lesson
       └─< assignment ─< submission
```

`class` trỏ tới **hai sandbox** (quyết định 2026-10-30): `recap_sandbox_id` (purpose `lesson_recap`) và `grader_sandbox_id` (purpose `classroom_grader`). Cả hai cho phép NULL, nhưng ít nhất một cái phải có (CHECK).

### 3.1 `class` (mới, thay `lesson_source` + `classroom_source`)

| Nhóm | Cột |
|---|---|
| Chung | `id`, `tenant_id`, `name`, `active`, `listed` (false: nguồn tạo bằng dòng lệnh, giữ lại vì bài giảng trỏ vào, không hiện thành lớp), `created_at`, `recap_sandbox_id`, `grader_sandbox_id` |
| Bản ghi (từ `lesson_source`) | `source_kind` (`drive`/`local`/`upload`), `source_ref`, `drive_account_id`, `owned`, `secret_enc` |
| Mezon | `notify_target_id` |
| Classroom (gộp hai bảng) | `classroom_account_id`, `course_id`, `course_name`, `auth_kind` (`delegated`/`oauth`), `subject`, `classroom_secret_enc` |
| Chính sách (cột, CHECK enum, không JSON) | `recap_mode` (`auto`/`review`, mặc định `review`), `grading_mode` (`manual`/`review`/`auto_write`, mặc định `review`), `assignment_post_mode` (`manual` duy nhất, để dành cho tính năng đăng bài tự động) |

Ràng buộc: duy nhất `(tenant_id, grader_sandbox_id, course_id)` khi cả hai khác NULL; duy nhất `(tenant_id, recap_sandbox_id, source_kind, source_ref)` như cũ.

Mặc định an toàn là `review`/`review`: giữ đúng quyết định 2026-10-22 "người duyệt mọi thứ". Chế độ `auto_*` phải bật tường minh, chỉ chủ (`sources.manage`), và có audit.

### 3.2 `lesson` (đổi)

- `source_id` → `class_id` (FK `class`).
- Thêm `released_at`, `released_by`: cổng duyệt. `recap_mode='auto'` thì job tự đặt `released_at` khi xong; `review` thì để NULL tới khi có người bấm "Duyệt và gửi".
- `notify/worker` và `lessons/post.py` chỉ gửi/đăng bản có `released_at`. Không có đường gửi mới (A9 giữ nguyên: vẫn `notify` nội bộ, không qua `outbox`).

### 3.3 `assignment` (mới, thay `assignment_draft` + `grading_guide`)

| Cột | Ghi chú |
|---|---|
| `id`, `tenant_id`, `class_id` | |
| `coursework_id` | NULL khi còn nháp, duy nhất `(tenant, class_id, coursework_id)` khi khác NULL |
| `origin` | `app` (Cortex tạo trong Classroom, chấm điểm ghi lại được) hoặc `classroom` (giáo viên tạo tay, chỉ đọc). Thay `grade_item.ours` |
| `authored_by` | `teacher`/`ai`/NULL (thay `assignment_draft.origin`) |
| `state` | `draft`/`created`/`rejected`/`failed` (giữ nguyên `assignment_draft.status`; `created` = đã có trên Classroom, dù là bản nháp trong Classroom hay đã đăng) |
| `title`, `description`, `max_points`, `due_at`, `publish`, `materials` | từ `assignment_draft` |
| `criteria`, `answer_key`, `language`, `check_prompt` | từ `grading_guide`; **không có tiêu chí thì không chấm** (giữ luật cũ) |
| `created_by`, `decided_by`, `decided_at`, `error`, `created_at` | |

### 3.4 `submission` (đổi tên `grade_item`)

- Thêm `assignment_id` (FK). Bỏ `coursework_id`, `work_title`, `max_points`, `course_name`, `ours`, `source_id`: lấy từ `assignment` và `class`.
- `status` thêm `pending` (bài đã nộp nhưng lớp ở chế độ `manual`, chưa chạy AI). Dòng đầy đủ: `pending, queued, working, proposed, approved, rejected, skipped, failed`.
- **Điều chỉnh so với đề xuất trước:** *không* tách `grade_decision`. Quyết định và bài nộp là 1:1, tách chỉ thêm join. Giữ `final`, `decided_by` (giá trị mới `auto`), `decided_at`, `written_at`; thêm `write_mode` (`none`/`draft`/`return`).
- Giữ nguyên: `submission_id` (mã của Classroom), `student_ref`, `student_name`, `link`, `content`, `content_kind`, `proposal`, `attempts`, `claimed_at`, `error`.

### 3.5 Bỏ

`lesson_source`, `classroom_source`, `grading_guide`, `assignment_draft`, `lesson_source.classroom_publish` (xem câu hỏi mở 2).

### 3.6 RLS và A1

`class` và `assignment` có `tenant_id` + RLS `FORCE` + cấp quyền cho `cl_app` theo mẫu migration 0019. `submission` đổi tên nhưng giữ chính sách.

## 4. Migration (hai revision, tách để quay lại được)

Head hiện tại là **0036** (`check_prompt`). Mới là 0037, 0038. Không sửa `0001`.

**0037 — thêm và chuyển dữ liệu**
1. Tạo `class`, `assignment` (+ RLS).
2. Mỗi `lesson_source` → một `class`. Mỗi `classroom_source` ghép vào `class` có `classroom_course_id` trùng (cùng tenant); không có thì thành `class` chỉ có phía chấm bài.
3. `assignment`: mỗi `assignment_draft`, và mỗi `(source, coursework_id)` khác nhau từ `grade_item`/`grading_guide`. `origin`: `app` nếu có `assignment_draft` đã `created` hoặc `grade_item.ours`.
4. Thêm `lesson.class_id`, `grade_item.assignment_id` (cho phép NULL), điền, rồi đặt NOT NULL.
5. Thêm cột chính sách, `released_at` (backfill bằng `finished_at` cho bài đã xong, để không gửi lại bài cũ).

**0038 — gỡ**: bỏ cột `source_id`/`coursework_id`... và bốn bảng cũ, đổi tên `grade_item` → `submission`. Chỉ chạy khi code đã chuyển hết.

**Rủi ro đã thấy**
- Nhiều `lesson_source` cùng một `course_id`: chỉ một trong số đó ghép được `classroom_source`, các lớp còn lại có `grader_sandbox_id` NULL. Phải chạy truy vấn đếm trên DB demo trước khi viết bước 2.
- `GradingGuide` duy nhất theo `(source, coursework_id)` nhưng `grade_item` có thể có bài không có guide: tạo `assignment` không có tiêu chí (không chấm được, như hôm nay).
- Có hai khoá bí mật (`lesson_source.secret_enc` và `classroom_source.secret_enc`): giữ cả hai cột, không tự gộp.
- Chạy migration trên **DB riêng**, không dùng DB demo trước khi có bản sao (đã mất dữ liệu 2026-10-23).

## 5. Code phải đổi (từ truy vấn tham chiếu)

Backend: `db/models.py`, `console/{classes,flow,google,grading,lessons}.py`, `grader/{assignments,job,writeback}.py`, `lessons/{job,post}.py`, `notify/worker.py`, `cli.py`; `auth/perms.py` cho endpoint mới. Frontend: `Shell.tsx`, `App.tsx`, `Lessons.tsx`, `Grading.tsx`, `Assignments.tsx`, `ClassPage.tsx`, `Classes.tsx`, `api/hooks.ts`.
Test phải viết lại hoặc sửa: `tests/console/{test_classes,test_google,test_grading_screen,test_lessons_screen,test_lesson_upload}.py`, `tests/grader/test_grader_flow.py`, `tests/lessons/{test_classroom_post,test_lessons}.py`, và `lessons.test.tsx`, `grading.test.tsx`, `shell.test.tsx`.

## 6. Hành vi theo chính sách

| `recap_mode` | Khi bài giảng xong |
|---|---|
| `review` | Lưu, hiện "Chờ duyệt". Chưa gửi Mezon, chưa đăng Classroom. Bấm "Duyệt và gửi" thì đặt `released_at` và cả hai đường gửi chạy |
| `auto` | `released_at` đặt ngay, gửi như hôm nay |

| `grading_mode` | Bài nộp mới |
|---|---|
| `manual` | `pending`. Không chạy AI. Có nút "Chấm bằng AI" từng bài |
| `review` | `queued` → `proposed` → giáo viên duyệt (như hôm nay) |
| `auto_write` | Như `review`, nhưng nếu đủ điều kiện an toàn thì `decide(by='auto')` ghi điểm. Điều kiện: `assignment.origin='app'`, mọi tiêu chí `verified`, không có `problems`/`flags`/`concerns`, không bị kill switch. Không đủ thì dừng ở `proposed` chờ người |

**Nhận xét cho học sinh (quyết định 2026-10-30: giữ nguyên):** chỉ ghi **điểm** (và trả bài) lên Classroom. Nhận xét vẫn lưu trong `final.feedback` để giáo viên xem, **không tới học sinh**. Nhãn giao diện dùng "tự động ghi điểm", không dùng "gửi nhận xét".

## 7. Giữ xanh các bất biến

- **A1:** bảng mới có RLS, test tenant.
- **A3:** `class_id` do server lấy từ đường dẫn đã kiểm tenant; chế độ lấy từ cột, không từ body của LLM.
- **A7:** validator chấm điểm không đổi và chạy trước `auto_write`.
- **A9:** không có đường gửi khách mới (Mezon nội bộ qua `notify`).
- Mọi endpoint mới khai `need(...)`; đổi chế độ cần `sources.manage`; ghi `audit_event`.
- Ngày giờ chỉ qua `core/timefmt.py` / `format.ts`.
- Nhóm C: dữ liệu bài nộp của trẻ em. `auto_write` chạy chỉ trên dữ liệu giả cho tới khi nhóm C xong.

## 8. Thứ tự làm (một lượt, theo yêu cầu)

1. Duyệt phiếu này + dòng DESIGN. Chạy truy vấn đếm rủi ro §4 trên bản sao DB demo.
2. Models + migration 0037 + test migration (backfill đúng, RLS, ràng buộc).
3. Backend: `console/classes` (CRUD + chính sách), `lessons` (cổng duyệt), `grader` (assignment, ba chế độ), `console/grading` (lọc theo lớp/bài tập), perms.
4. Frontend: điều hướng "Lớp học", các trang theo thiết kế Pencil 13–19, hộp thoại Sửa lớp.
5. Migration 0038 gỡ bảng cũ, dọn code chết.
6. REVIEW.md ghi mục mới, chạy toàn bộ pytest (DB riêng) + `make web-test`.

## 9. Câu hỏi mở (cập nhật 2026-10-30)

1. G1 (2026-10-23): **kết quả chưa được ghi lại trong repo.** Chủ dự án cần xác nhận kết quả và việc tiếp tục code (L4) trước khi mở gói lớn.
2. `classroom_publish`: **đã bỏ**, quy về `recap_mode` (`auto` đăng ngay, `review` chỉ đăng sau khi người bấm duyệt gửi). Không ai phản đối khi đề xuất; coi là chốt trừ khi chủ dự án nói khác.
3. Màn "Chưa nộp / sĩ số / điểm trung bình": **gói sau** (cần gọi Classroom lấy danh sách học sinh).
