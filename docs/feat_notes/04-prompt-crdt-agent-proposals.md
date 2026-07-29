# Phase 3 — Agent proposal dựa trên CRDT

## Phụ thuộc
**Bắt buộc** Phase 2 (Yjs/CRDT cho real-time collaboration) đã hoàn tất và được xác nhận ổn định trong thực tế, không chỉ qua test. Phase này cần hạ tầng `Y.Doc` + sync server (Hocuspocus) đã tồn tại và chạy production. Kế thừa các khái niệm UI đã xây ở Phase 1.5 (trạng thái "conflict/stale", recompute diff khi review) nhưng thay cơ chế merge phía dưới bằng CRDT thật thay vì fuzzy-patch tạm thời.

## Bối cảnh

Sau Phase 1.5, agent proposal đã hết bị stuck vô lý nhờ context-based fuzzy patch, nhưng đó vẫn là giải pháp tạm — bản chất vẫn là "áp một patch vào một snapshot text", vẫn có khả năng thất bại khi ngữ cảnh thay đổi nhiều.

Ý tưởng của phase này: một khi note đã là `Y.Doc` (nhờ Phase 2), khái niệm "version conflict" không còn cần thiết nữa — CRDT đảm bảo hội tụ bất kể thứ tự/độ trễ giữa các update. Ta có thể biến agent proposal thành một **Yjs update** thay vì một text patch, và việc "approve" chỉ đơn giản là áp update đó vào `Y.Doc` sống.

### Files liên quan (cần agent tự đọc lại và xác nhận, đã đổi nhiều sau Phase 2)
- `backend/app/ai/tools/update_note.py`
- `backend/app/services/proposal_service.py`
- `backend/app/repositories/proposals.py`
- `backend/app/api/proposals.py`
- `backend/app/models.py` (`NoteEditProposal`)
- Service Hocuspocus/Node được thêm ở Phase 2 (nơi thực sự có quyền thao tác `Y.Doc`)
- `frontend/src/hooks/useNoteProposals.ts`
- `frontend/src/components/DiffReviewPanel.tsx`

## Mục tiêu
1. Agent proposal được biểu diễn dưới dạng Yjs update (không phải text patch), tính toán dựa trên fork của `Y.Doc` tại thời điểm agent tạo đề xuất.
2. Approve = áp update đó vào `Y.Doc` sống trên sync server — hội tụ tự động, không còn khái niệm "409 version conflict" cho luồng approve.
3. Review UI vẫn hiển thị diff dạng text dễ đọc như hiện tại — không thay đổi trải nghiệm review của user, chỉ thay đổi cơ chế phía dưới.
4. Loại bỏ hoàn toàn class bug "proposal stuck vì version lệch".

## Nguyên tắc riêng cho phase này
- Vì backend chính là Python còn Yjs chạy ở service Node/TS (từ Phase 2), thao tác tạo/áp update phải đi qua service đó — không cố gắng thao tác `Y.Doc` trực tiếp từ Python trừ khi Phase 2 đã chọn `pycrdt`.
- Giữ khả năng review/reject như hiện tại — proposal KHÔNG được tự động merge vào `Y.Doc` sống khi tạo, chỉ merge sau khi user approve tường minh. Đây là ranh giới quan trọng nhất của phase này: agent không phải là một CRDT peer ghi trực tiếp, mà đi qua trạm chờ duyệt.

## Nhiệm vụ chi tiết

### 3.0 Xác nhận thiết kế trước khi code
- Xác nhận cách service Node/TS (Hocuspocus) ở Phase 2 expose API nội bộ để: (a) tạo một `Y.Doc` fork tạm từ trạng thái hiện tại của 1 note, (b) tính Yjs update khi áp nội dung mới vào fork đó, (c) áp một Yjs update cho trước vào `Y.Doc` sống của 1 room. Nếu API này chưa tồn tại, đây là việc cần làm đầu tiên trong phase.
- Xác nhận cơ chế giao tiếp giữa backend Python (nơi tool `update_note` chạy) và service Node (nơi có quyền thao tác `Y.Doc`) — HTTP nội bộ, message queue, hay cách khác. Nếu Phase 2 chưa thiết lập kênh giao tiếp này, thiết kế mới, ưu tiên đơn giản (HTTP nội bộ) trừ khi có lý do rõ ràng để chọn khác.

### 3.1 Sửa `update_note` tool để tạo proposal dạng Yjs update
- Khi agent gọi tool, thay vì chỉ tính text patch, gọi sang service Node để: lấy trạng thái `Y.Doc` hiện tại của note → tạo fork → áp nội dung agent đề xuất vào fork → lấy ra Yjs update đại diện cho phần chênh lệch.
- Lưu proposal gồm cả: Yjs update (binary, để áp khi approve) và bản diff text (để hiển thị review UI, tính bằng cách so nội dung markdown trước/sau như hiện tại).
- Bỏ trường `base_version` khỏi vai trò gatekeeper cho việc approve (có thể giữ lại chỉ để hiển thị thông tin, không dùng để chặn).

### 3.2 Sửa endpoint approve
- Khi user approve: gửi Yjs update đã lưu sang service Node để áp vào `Y.Doc` sống của room tương ứng.
- Không còn bước kiểm tra version trước khi áp — CRDT tự đảm bảo hội tụ.
- Trước khi hiển thị nút approve, recompute diff hiển thị dựa trên nội dung `Y.Doc` mới nhất (kế thừa nguyên tắc từ Phase 1.5 mục 1.5.3), để user không bị bất ngờ nếu note đã thay đổi nhiều — đây là cảnh báo về mặt *ngữ nghĩa* (đề xuất có còn hợp lý không), khác với version conflict về mặt *kỹ thuật* (không còn tồn tại nữa).

### 3.3 Sửa endpoint reject
Đơn giản: đánh dấu proposal là rejected, không áp update, không cần thao tác gì trên `Y.Doc`.

### 3.4 Dọn dẹp cơ chế cũ
- Xác nhận không còn code path nào dựa vào `base_version` để chặn approve.
- Cân nhắc giữ lại cơ chế fuzzy-patch từ Phase 1.5 như fallback nếu service Node không khả dụng tạm thời (agent tự đánh giá có cần thiết không, nêu rõ quyết định trong báo cáo).

### 3.5 Review UI
- `DiffReviewPanel.tsx`: giữ nguyên trải nghiệm hiển thị diff text, chỉ thêm banner cảnh báo "ngữ nghĩa" nếu nội dung đã thay đổi nhiều kể từ lúc tạo đề xuất (kế thừa từ 1.5.5, đổi nội dung banner cho phù hợp bối cảnh mới — không còn "conflict" theo nghĩa kỹ thuật, mà là "đề xuất có thể không còn phù hợp, xem lại trước khi duyệt").

### 3.6 Kiểm thử
- Case 1: user edit note ở đoạn không liên quan trong lúc chờ duyệt → approve vẫn thành công, nội dung agent đề xuất được áp đúng, nội dung user gõ không bị mất.
- Case 2: user edit đúng đoạn agent đề xuất sửa trong lúc chờ duyệt → approve vẫn không lỗi kỹ thuật (CRDT luôn merge được), nhưng UI phải cảnh báo rõ ràng để user tự quyết định có nên approve hay huỷ.
- Case 3: nhiều proposal cùng lúc trên 1 note (2 lệnh gọi tool khác nhau) → cả hai đều approve được, xác nhận thứ tự áp update không làm hỏng nội dung.
- Case 4: service Node tạm thời không khả dụng khi agent đang tạo proposal → xử lý lỗi rõ ràng, không để proposal ở trạng thái không xác định.

## Definition of Done
- Không còn bug loại "proposal stuck vì version lệch" dưới bất kỳ hình thức nào.
- Approve luôn thành công về mặt kỹ thuật khi user chọn approve; mọi cảnh báo còn lại là về ngữ nghĩa (nội dung có thể đã đổi), hiển thị rõ ràng cho user tự quyết định.
- Review UI không thay đổi trải nghiệm cơ bản so với trước (vẫn xem diff text, approve/reject).
- Có test chứng minh 4 case ở mục 3.6.
- Cập nhật mục "Phase 3" trong `PROGRESS.md`.

## Báo cáo
1. Tóm tắt kiến trúc giao tiếp Python ↔ Node đã triển khai.
2. Xác nhận đã loại bỏ hoàn toàn phụ thuộc vào `base_version` cho việc approve.
3. Quyết định về việc có giữ fallback fuzzy-patch từ Phase 1.5 hay không, kèm lý do.
4. Liệt kê rủi ro còn tồn đọng.
5. Cập nhật `PROGRESS.md`, đánh dấu toàn bộ migration 4 phase là hoàn tất nếu đây là phase cuối cùng đạt Definition of Done.
