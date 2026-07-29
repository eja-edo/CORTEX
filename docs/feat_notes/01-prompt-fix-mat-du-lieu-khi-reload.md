# Phase 1 — Fix mất dữ liệu khi reload

## Phụ thuộc
Không phụ thuộc phase nào khác. Có thể bắt đầu ngay.

## Bối cảnh
Frontend (React/TS) dùng 2 tầng debounce timer nối tiếp trước khi lưu nội dung note lên server:

```
Gõ phím → handleTextareaChange
  → setLocalMd + queueFlush (350ms timer #1, trong WorkspaceNoteEditor.tsx)
    → onChange() → handleNoteChange (trong useNotes.ts)
      → scheduleNotePersist (280ms timer #2)
        → persistNoteContent()
          → buildTextPatch(baseContent, nextContent)
          → POST /notes/{id}/patch (HTTP request)
```

Tổng độ trễ tối thiểu trước khi request thực sự gửi đi là ~630ms + network. Nếu người dùng reload hoặc đóng tab trong khoảng thời gian này, nội dung vừa gõ bị mất, vì:

1. `window.setTimeout` bị huỷ khi trang unload, timer không kịp chạy.
2. Cleanup effect trong `useNotes.ts` hiện tại chỉ `clearTimeout` mà không flush nội dung đang chờ:
```js
useEffect(() => {
    return () => {
        Object.values(noteSyncTimersRef.current).forEach((timerId) => window.clearTimeout(timerId))
        noteSyncTimersRef.current = {}
    }
}, [])
```
3. Không có `beforeunload`/`pagehide` handler nào để flush trước khi trang đóng.
4. Không có backup cục bộ (localStorage/IndexedDB) làm lưới an toàn nếu request chưa kịp gửi.

### Files liên quan (cần agent tự đọc lại và xác nhận, code có thể đã đổi so với mô tả này)
- `frontend/src/components/editor/WorkspaceNoteEditor.tsx`
- `frontend/src/hooks/useNotes.ts`
- `frontend/src/stores/editorStore.ts` (hoặc vị trí tương đương chứa block editor store)
- `frontend/src/components/editor/EditorSurface.tsx`
- `frontend/src/utils/textPatch.ts`
- `backend/app/api/notes.py`
- `backend/app/services/notes.py`

## Mục tiêu
Loại bỏ hoàn toàn khả năng mất nội dung khi reload/đóng tab/chuyển tab/mất mạng tạm thời, mà không cần đổi kiến trúc lưu trữ lớn (không đụng tới cơ chế patch/version hiện tại, phần đó thuộc Phase 2).

## Nhiệm vụ chi tiết

### 1.1 Khảo sát và xác nhận
Đọc các file liên quan ở trên, xác nhận: vị trí chính xác của 2 tầng timer, nội dung cleanup effect hiện tại, có nơi nào khác trong code cũng debounce-save mà chưa được liệt kê ở đây không (ví dụ auto-save cho title, tags...).

### 1.2 Gộp 2 tầng timer thành 1
Thay `queueFlush` (350ms) + `scheduleNotePersist` (280ms) bằng một debounce duy nhất (khuyến nghị 400-500ms) gọi thẳng tới bước persist. Giữ nguyên hành vi flush ngay lập tức khi `note.id` đổi (chuyển sang note khác) — logic này đã đúng, không sửa.

### 1.3 Flush khi rời trang
- Thêm listener `visibilitychange`: khi `document.hidden === true`, flush ngay nội dung đang pending. Đây là tín hiệu đáng tin cậy hơn `beforeunload` trên mobile Safari.
- Thêm listener `pagehide` (và `beforeunload` như fallback cho trình duyệt cũ): dùng `navigator.sendBeacon(url, blob)` hoặc `fetch(url, {keepalive: true, ...})` thay vì `fetch` thường, vì fetch thông thường hay bị trình duyệt abort giữa chừng khi trang đang đóng.
- Lưu ý: `sendBeacon` giới hạn payload nhỏ và luôn là POST — kiểm tra kích thước patch trung bình trước khi chọn giữa `sendBeacon` và `fetch keepalive`.

### 1.4 Backup nội dung cục bộ
- Mỗi lần debounce chạy (trước khi gọi API, không cần chờ network), ghi `{noteId, content, baseVersion, updatedAt}` vào `localStorage` (hoặc `IndexedDB` nếu nội dung note thường lớn — agent tự đánh giá dựa trên kích thước note thực tế trong hệ thống).
- Khi note được load: so `updatedAt`/`baseVersion` của bản backup local với bản server trả về.
  - Nếu local mới hơn và nội dung khác server → hỏi người dùng "khôi phục bản nháp chưa lưu?" thay vì tự động ghi đè theo bất kỳ hướng nào.
  - Nếu đã sync thành công lên server → xoá backup local tương ứng.

### 1.5 Sửa cleanup effect
Cleanup effect hiện tại chỉ `clearTimeout`. Sửa thành: nếu còn `pendingFlushValue` chưa gửi, gọi flush trước, rồi mới clear timer.

### 1.6 Kiểm thử
- Test tự động (nếu hạ tầng test frontend cho phép giả lập unmount/visibilitychange): gõ nội dung, trigger sự kiện rời trang trước khi debounce timeout, assert request đã được gửi (qua `sendBeacon`/`keepalive`) hoặc backup local tồn tại đúng nội dung.
- Test thủ công, ghi rõ các bước để người review làm theo:
  1. Mở 1 note, gõ vài ký tự.
  2. Reload trang trong vòng <300ms sau ký tự cuối (có thể giả lập bằng cách set timeout ngắn trong devtools hoặc thao tác tay nhanh).
  3. Xác nhận nội dung không mất sau khi trang load lại.
  4. Lặp lại với hành vi "đóng tab" và "chuyển sang tab khác rồi quay lại".

## Definition of Done
- Không còn kịch bản nào (reload, đóng tab, chuyển tab, mất mạng tạm thời) khiến nội dung vừa gõ biến mất mà không có cách khôi phục.
- Có test (tự động hoặc quy trình test thủ công ghi lại rõ ràng) chứng minh điều này cho từng kịch bản ở mục 1.6.
- Không có regression ở luồng chuyển note (switch note vẫn flush đúng như cũ).

## Báo cáo
Sau khi hoàn thành, agent phải:
1. Tóm tắt đã làm gì, file nào thay đổi.
2. Liệt kê rủi ro/vấn đề còn tồn đọng nếu có (ví dụ: giới hạn kích thước payload của `sendBeacon` nếu note quá lớn).
3. Cập nhật mục "Phase 1" trong `PROGRESS.md` (xem format ở file `00-tong-quan-va-thu-tu-thuc-hien.md`).
4. Xác nhận Definition of Done đã đạt trước khi coi phase này là "done".