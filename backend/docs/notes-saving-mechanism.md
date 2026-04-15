# Notes Saving Mechanism (Current Behavior)

Tài liệu này mô tả chính xác cơ chế lưu note đang chạy trong code hiện tại (frontend + backend).

## 1) Tổng quan kiến trúc lưu

- Frontend không gửi full content mỗi lần gõ.
- Frontend tính patch diff từ nội dung gốc đã đồng bộ -> nội dung mới.
- Backend áp dụng patch theo optimistic concurrency bằng `version`.
- Mỗi lần cập nhật content thành công:
  - `notes.version` tăng +1.
  - Ghi thêm 1 bản ghi vào `note_revisions`.
- Cập nhật metadata-only (ví dụ đổi `parent_note_id` khi drag-drop) không tăng version.

## 2) Trigger lưu từ UI

### 2.1 WorkspaceNoteEditor

- Khi gõ: gọi `onChange(id, contentMd)` liên tục.
- `onChange` cập nhật state local và đặt lịch lưu debounce.
- Blur textarea: gọi flush ngay để đảm bảo không mất thay đổi trước khi rời focus.

Flow:

1. User nhập nội dung.
2. Frontend cập nhật `recentNotes` local.
3. Debounce khoảng 280ms để gom lần gõ.
4. Khi tới hạn, gọi `persistNoteContent(noteId)`.
5. Nếu đang có request in-flight, đánh dấu `queued=true` để chạy tiếp sau khi request hiện tại xong.

### 2.2 NoteSidebar (editor trong card)

- Có autosave khi đang gõ trong card editor (debounce cục bộ khoảng 350ms).
- Khi `Done`, `Esc`, hoặc click ra ngoài card (collapse) sẽ flush lưu ngay.
- Sau khi `onNoteChange`, vẫn đi chung pipeline persist của App (debounce + patch).

## 3) Pipeline đồng bộ ở App.tsx

Cơ chế trung tâm nằm ở `noteSyncStatesRef` và các hàm:

- `scheduleNotePersist(noteId)`
- `persistNoteContent(noteId)`
- `handleNoteChange(id, contentMd)`

`NoteSyncState` theo từng note gồm:

- `baseContent`: nội dung đã sync thành công gần nhất.
- `baseVersion`: version đã sync thành công gần nhất.
- `inFlight`: đang có request save.
- `queued`: có thay đổi mới phát sinh trong lúc request đang chạy.

Logic chính:

1. Nếu `nextContent === baseContent` thì bỏ qua.
2. Tạo patch bằng `buildTextPatch(baseContent, nextContent)`.
3. Gửi `POST /notes/{id}/patch` với payload:
   - `version = baseVersion`
   - `patch = [...]`
4. Thành công:
   - Cập nhật `baseContent`, `baseVersion` từ response.
   - Nếu user đã gõ thêm trong lúc request đang chạy (`queued=true`) thì gửi vòng tiếp.
5. Thất bại 409:
   - Báo conflict.
   - Xóa sync state note đó.
   - Reload toàn bộ notes từ server (`fetchNotes()`).

## 4) API và semantics hiện tại

### 4.1 Content editing

- Endpoint chính frontend đang dùng: `POST /notes/{note_id}/patch`.
- Backend bắt buộc `current.version == payload.version`; sai thì trả 409.
- Thành công thì `version` tăng +1.

### 4.2 Full/partial update bằng PATCH

- Endpoint: `PATCH /notes/{note_id}`.
- Nếu payload có `content`:
  - Cũng kiểm tra version (optimistic lock).
  - Tạo revision và tăng version.
- Nếu metadata-only (không có `content`), ví dụ:
  - `parent_note_id`, `position`, `size`, `style`
  - Không check version conflict theo nhánh content update.
  - Không tăng `version` (theo rule hiện tại).

### 4.3 Batch update

- `PATCH /notes/batch` yêu cầu `version` cho từng item.
- Dùng cho partial updates theo lô, có check version.

## 5) Backend data model liên quan lưu

### 5.1 Bảng `notes`

- `content`: checkpoint content.
- `version`: version hiện tại của note.
- `checkpoint_version`: version của checkpoint content.

### 5.2 Bảng `note_revisions`

- Lưu patch increment theo từng version.
- Trường chính: `note_id`, `version`, `base_version`, `patch`, `patch_format`, `content_length`.

## 6) Materialize nội dung khi đọc

Khi `GET /notes`:

1. Lấy `note.content` (checkpoint).
2. Lấy revisions từ `checkpoint_version + 1` đến mới nhất.
3. Apply patch tuần tự để tạo nội dung cuối cùng trả về frontend.

## 7) Compaction revisions

- Ngưỡng hiện tại: `PATCH_COMPACTION_THRESHOLD = 20`.
- Nếu số version kể từ checkpoint >= 20:
  - Gộp nội dung cuối vào `notes.content`.
  - Cập nhật `checkpoint_version = current_version`.
  - Xóa revisions cũ tới mốc đó.

Mục tiêu: giảm chi phí đọc khi số patch tích lũy quá nhiều.

## 8) Conflict behavior người dùng sẽ thấy

- Nếu 2 phiên cùng sửa content 1 note:
  - Phiên gửi với version cũ sẽ nhận 409.
  - Frontend hiện tại reload lại notes và hiện thông báo conflict.
- Nếu chỉ kéo-thả đổi parent (metadata-only):
  - Không bump version.
  - Không gây conflict kiểu content-edit version mismatch theo rule hiện tại.

## 9) Lưu ý thực tế

- WorkspaceNoteEditor có 2 lớp debounce trên flow gõ:
  - Debounce ngoài ở App (`~280ms`).
  - Debounce cục bộ editor (`~300ms`) trước khi gọi onChange.
- NoteSidebar editor cũng autosave theo debounce cục bộ (`~350ms`) rồi đi tiếp qua debounce ở App.
- Vì vậy độ trễ save cảm nhận được phụ thuộc nhịp gõ và batch request, không phải save tức thời từng phím.
- WorkspaceNoteEditor `onBlur` và NoteSidebar collapse (`Done`/`Esc`/click ngoài) đều flush ngay để giảm nguy cơ mất dữ liệu.

## 10) File tham chiếu

- Frontend editor và trigger lưu:
  - `frontend/src/components/WorkspaceNoteEditor.tsx`
  - `frontend/src/components/NoteSidebar.tsx`
  - `frontend/src/App.tsx`
- Frontend patch builder:
  - `frontend/src/utils/textPatch.ts`
- Backend API/service/repository:
  - `backend/app/api/notes.py`
  - `backend/app/services/notes.py`
  - `backend/app/repositories/notes.py`
  - `backend/app/utils/note_delta.py`
- Backend model/schema:
  - `backend/app/models.py`
  - `backend/app/schemas.py`
