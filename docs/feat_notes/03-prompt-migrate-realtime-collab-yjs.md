# Phase 2 — Real-time collaborative editing bằng Yjs/CRDT

## Phụ thuộc
Nên bắt đầu sau khi Phase 1 (fix mất dữ liệu khi reload) đã đạt Definition of Done và được xác nhận ổn định — vì đây là thay đổi kiến trúc lớn, cần nền tảng lưu trữ hiện tại đã đáng tin cậy trước khi xây thêm lên trên. Độc lập với Phase 1.5.

## Bối cảnh

Hệ thống note hiện tại lưu nội dung dạng markdown string, đồng bộ qua patch-based optimistic locking (`POST /notes/{id}/patch` kèm `version`, trả 409 nếu conflict, client refetch khi conflict). Cơ chế này chỉ cho phép 1 người sửa an toàn tại một thời điểm — hai người cùng gõ đồng thời sẽ liên tục đụng version conflict hoặc ghi đè lẫn nhau tuỳ ai gửi trước.

Yêu cầu: nhiều người có thể gõ đồng thời trên cùng 1 note, thấy thay đổi của nhau gần thời gian thực (như Google Docs), có presence/cursor.

### Files liên quan (cần agent tự đọc lại và xác nhận, có thể đã đổi do Phase 1)
- `frontend/src/components/editor/WorkspaceNoteEditor.tsx`
- `frontend/src/hooks/useNotes.ts`
- `frontend/src/stores/editorStore.ts`
- `frontend/src/components/editor/EditorSurface.tsx`
- `backend/app/api/notes.py`
- `backend/app/services/notes.py`
- `backend/app/models.py`
- Cấu hình auth hiện tại (JWT/session) — agent cần tự tìm vị trí middleware auth để thiết kế xác thực cho WebSocket.

## Mục tiêu
Thay thế cơ chế patch-based bằng Yjs (CRDT) + Hocuspocus (sync server), để nội dung note hội tụ tự động giữa nhiều client mà không cần version check strict, đồng thời giữ nguyên khả năng các API/search hiện tại đọc được nội dung note dạng markdown.

## Nguyên tắc riêng cho phase này
- Đây là thay đổi kiến trúc lớn nhất trong toàn bộ migration — bắt buộc rollout qua feature flag, không merge thẳng vào luồng chính cho tới khi test kỹ trên ít nhất 1 note thật.
- Giữ khả năng fallback về cơ chế patch cũ nếu phát sinh sự cố nghiêm trọng trong giai đoạn đầu rollout.
- Không xoá `/notes/{id}/patch` trong phase này — chỉ deprecate sau khi Phase 2 chạy ổn định một thời gian và được xác nhận riêng.

## Nhiệm vụ chi tiết

### 2.0 Xác nhận giả định trước khi thiết kế chi tiết
Bắt buộc agent tự xác minh các điểm sau trước khi code, dừng lại hỏi nếu không chắc:
- Block editor hiện tại (`editorStore.ts`) là custom hay dựa trên thư viện có sẵn (ProseMirror/Slate/TipTap)? Việc này quyết định dùng binding có sẵn (`y-prosemirror`/`y-slate`) hay phải viết binding tay — ảnh hưởng lớn tới effort của 2.3.
- Cơ chế auth hiện tại hoạt động thế nào (JWT/session/cookie), để thiết kế `onAuthenticate` cho WebSocket room theo `noteId`.
- Backend Python hiện dùng ORM/DB nào cụ thể, để thiết kế bảng lưu snapshot Yjs cho đúng convention hiện có.

### 2.1 Setup sync server
Triển khai Hocuspocus như một service riêng (Node/TS), tách khỏi backend Python hiện tại (lý do: Yjs core là JS, chạy CRDT logic trong Python cần binding riêng như `pycrdt`, phức tạp hơn không cần thiết ở giai đoạn này — nếu agent có lý do kỹ thuật để chọn `pycrdt` thay vì service Node riêng, nêu rõ trade-off trước khi quyết định).
- Cấu hình `onAuthenticate`: verify token từ client, map tới `noteId` = room.
- Cấu hình `onStoreDocument`: hook để lưu snapshot xuống DB (xem 2.4).

### 2.2 Frontend: tích hợp `Y.Doc` + `y-indexeddb`
- Thêm `Y.Doc` làm nguồn dữ liệu chính cho nội dung note.
- Tích hợp `y-indexeddb` để persist local tức thời — lưu ý: đây cũng trở thành lưới an toàn thứ hai chống mất dữ liệu (bổ sung cho Phase 1, không thay thế).
- Kết nối `y-websocket` (hoặc client tương thích Hocuspocus) tới sync server ở 2.1, room = `noteId`.

### 2.3 Binding block editor ↔ `Y.Doc`
Phần tốn công nhất trong phase này.
- Nếu dùng thư viện editor có binding sẵn (xác nhận ở 2.0) → dùng binding chuẩn của thư viện đó.
- Nếu là custom editor → viết lớp chuyển đổi giữa block state hiện tại (`editorStore.ts`) và cấu trúc Yjs (`Y.XmlFragment` hoặc `Y.Array` chứa các `Y.Map` cho từng block). Đảm bảo:
  - Thay đổi từ user gõ → phản ánh vào `Y.Doc` → propagate qua sync server → các client khác nhận update và re-render đúng vị trí (không giật con trỏ, không mất selection).
  - Load note lần đầu: khởi tạo `Y.Doc` từ nội dung markdown hiện có trong DB (viết hàm convert markdown → cấu trúc Yjs một lần).

### 2.4 Persistence xuống Postgres
- Dùng hook `onStoreDocument` của Hocuspocus: lưu snapshot binary của `Y.Doc` định kỳ hoặc khi idle sau một khoảng không có thay đổi.
- Đồng thời derive bản markdown từ `Y.Doc` mỗi lần lưu snapshot, ghi vào cột `content_md` hiện có, để các API/search/export hiện tại không cần đổi gì.
- Thiết kế migration schema nếu cần thêm cột lưu snapshot binary — viết migration script rõ ràng, không tự ý đổi schema production mà không có script.

### 2.5 Presence / awareness
Tích hợp `y-protocols/awareness`: hiển thị cursor, tên, avatar của những người đang mở cùng note. Ưu tiên làm sau khi 2.1-2.4 đã chạy ổn định — đây là tính năng bổ sung, không phải điều kiện tiên quyết để merge nội dung đúng.

### 2.6 Rollout theo feature flag
- Bật cho 1 note test nội bộ trước.
- Sau đó mở rộng cho nhóm nhỏ người dùng thật.
- Có cờ tắt nhanh, fallback về cơ chế patch cũ (`/notes/{id}/patch`) nếu phát sinh sự cố nghiêm trọng ở bất kỳ giai đoạn rollout nào.

### 2.7 Kiểm thử
- Test 2 client cùng gõ đồng thời vào 2 vị trí khác nhau trong cùng note → nội dung hội tụ đúng ở cả 2 phía, không mất ký tự.
- Test 1 client offline (ngắt mạng), tiếp tục gõ, rồi reconnect → thay đổi merge đúng vào bản mới nhất.
- Test reload trong lúc đang gõ (kế thừa test case từ Phase 1) → xác nhận `y-indexeddb` giữ được nội dung ngay cả khi Phase 1 chưa kịp flush.
- Test presence: 2 client thấy cursor của nhau đúng vị trí.

## Definition of Done
- Nhiều người gõ đồng thời trên cùng 1 note, thấy thay đổi của nhau gần thời gian thực, không mất nội dung, không cần version-conflict handling thủ công.
- Có presence indicator hoạt động đúng.
- Dữ liệu vẫn được persist đúng xuống Postgres dưới dạng markdown cho các hệ thống khác dùng, không có regression ở API đọc note hiện có.
- Cơ chế patch cũ vẫn hoạt động song song qua feature flag, có thể rollback.
- Có test chứng minh các case ở mục 2.7.

## Báo cáo
1. Tóm tắt kiến trúc đã triển khai, file/service nào thêm mới hoặc thay đổi.
2. Kết quả xác nhận các giả định ở mục 2.0.
3. Liệt kê rủi ro còn tồn đọng (ví dụ giới hạn của binding editor, edge case merge chưa cover).
4. Trạng thái rollout hiện tại (đang ở giai đoạn nào trong 2.6).
5. Cập nhật mục "Phase 2" trong `PROGRESS.md`.
6. Xác nhận rõ ràng: Phase 3 (CRDT-based agent proposal) chỉ nên bắt đầu sau khi phase này được xác nhận ổn định trong thực tế, không chỉ dựa trên test.
