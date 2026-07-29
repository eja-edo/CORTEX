# Phase 1.5 — Fix xung đột version giữa agent proposal và user edit (giải pháp ngắn hạn)

## Phụ thuộc
Độc lập với Phase 1 và Phase 2. Không cần chờ phase nào khác, có thể làm song song với Phase 1.

## Bối cảnh

Luồng agent đề xuất sửa note hiện tại:

```
LLM gọi tool update_note(note_id, content)
  → build_text_patch(old_content, new_content)
  → ProposalService.create_proposal()
    → lưu NoteEditProposal: base_revision_id, base_version, patch, status="pending", TTL 24h
  → trả về {proposal_id, updated: false}

AgentService yield SSE event: {"event": "note_diff", proposal_id, note_id}

Frontend nhận event → DiffReviewPanel hiển thị diff
  → User click Approve → POST /note-proposals/{id}/approve
    → optimistic lock: pending → applying
    → kiểm tra proposal.base_version == note.version → khác thì 409, rollback về "pending"
    → nếu khớp: NoteService.patch_note() với patch của proposal → status = approved
  → User click Reject → POST /note-proposals/{id}/reject
```

### Vấn đề chính đã xác nhận
Vì quy trình duyệt có độ trễ không xác định (vài giây đến 24h), gần như chắc chắn user sẽ tiếp tục edit note trong lúc chờ. Kịch bản lỗi:

```
User gõ → version 2→3
Agent tạo proposal (base_version = 2)   ← đã stale ngay từ đây
User gõ tiếp → version 3→4
User approve proposal (base_version=2 ≠ version=4)
→ 409 Version Conflict → status rollback về "pending"
```

Proposal không bao giờ áp dụng được, user thấy lỗi mơ hồ, không có hành động rõ ràng để xử lý.

### Vấn đề phụ cần xử lý trong phase này
- `compute_proposal_content` (trong `proposal_service.py`, khoảng dòng 124-144 theo phân tích trước) nghi vấn double-apply patch: lấy base = nội dung sau tất cả revision, rồi apply lại `rev.patch` — cần xác nhận và fix nếu đúng là bug.
- `note_diff` SSE event chỉ gửi 1 lần; nếu frontend bỏ lỡ (reconnect, tab switch), proposal pending không được hiển thị, không có cơ chế fallback.
- Diff hiển thị trong review panel là diff được tính tại thời điểm tạo proposal, không phải tại thời điểm review — có thể đã lỗi thời.

### Files liên quan (cần agent tự đọc lại và xác nhận)
- `backend/app/ai/tools/update_note.py`
- `backend/app/ai/tools/create_note.py`
- `backend/app/services/proposal_service.py`
- `backend/app/repositories/proposals.py`
- `backend/app/api/proposals.py`
- `backend/app/models.py` (class `NoteEditProposal`, `NoteRevision`)
- `backend/app/ai/agents/agent_service.py` (nơi yield event `note_diff`, cả nhánh sequential lẫn parallel)
- `frontend/src/hooks/useNoteProposals.ts`
- `frontend/src/components/DiffReviewPanel.tsx`

## Mục tiêu
1. Loại bỏ tình trạng proposal bị stuck/rollback vô lý khi user edit ở phần không liên quan tới đề xuất của agent.
2. Khi thực sự có xung đột nội dung (agent và user cùng sửa đúng 1 đoạn), trả về trạng thái rõ ràng thay vì lỗi mơ hồ, kèm hành động cụ thể cho user.
3. Đảm bảo diff hiển thị luôn đúng với nội dung mới nhất tại thời điểm review.
4. Đảm bảo proposal pending luôn hiển thị được cho user kể cả khi bỏ lỡ SSE event.
5. Xác nhận và fix bug double-apply nếu có.

## Nhiệm vụ chi tiết

### 1.5.1 Khảo sát và xác nhận
Đọc lại toàn bộ file liên quan, xác nhận đúng luồng mô tả ở trên còn khớp với code thực tế không. Viết test tái hiện bug double-apply trong `compute_proposal_content` nếu xác nhận có — nếu không có bug, ghi rõ trong báo cáo cuối tại sao (để không ai phải điều tra lại).

### 1.5.2 Thay strict version check bằng context-based fuzzy patch
- Không so sánh `proposal.base_version == note.version` để quyết định pass/fail nhị phân nữa.
- Áp patch của proposal vào nội dung hiện tại theo kiểu context-matching (mỗi patch hunk có kèm N dòng/ký tự ngữ cảnh trước-sau; khi apply, tìm vị trí ngữ cảnh đó trong nội dung hiện tại thay vì dùng offset tuyệt đối cố định theo version cũ). Cân nhắc dùng thư viện có sẵn kiểu port của `diff-match-patch` cho Python thay vì tự viết thuật toán fuzzy-match từ đầu; nếu không có thư viện phù hợp, nêu rõ lý do trước khi tự viết.
- Nếu tìm được ngữ cảnh và áp sạch → apply, tạo revision mới, `status = "approved"`.
- Nếu KHÔNG tìm được ngữ cảnh (đoạn text agent định sửa đã bị xoá/thay đổi hoàn toàn bởi user) → **không** rollback âm thầm về "pending". Thêm trạng thái mới `status = "conflict"` vào enum hiện có của `NoteEditProposal`, lưu kèm thông tin cụ thể phần nào không áp được, để hiển thị cho user.

### 1.5.3 Recompute diff tại thời điểm review
Sửa `GET /note-proposals/{id}` để tính lại diff (old vs new) dựa trên nội dung note đã materialize mới nhất, không dùng diff cache từ lúc tạo proposal. Nếu nội dung hiện tại đã khác đáng kể so với base lúc tạo, trả thêm cờ báo cho frontend hiển thị (ví dụ banner "Note đã thay đổi từ lúc đề xuất này được tạo").

### 1.5.4 Endpoint list pending proposals + fallback UI
- Thêm `GET /notes/{note_id}/proposals?status=pending`.
- Frontend (`useNoteProposals.ts`): gọi endpoint này khi mount note editor và khi reconnect (không chỉ dựa vào SSE event `note_diff` để biết có proposal đang chờ).

### 1.5.5 UI xử lý trạng thái "conflict"
`DiffReviewPanel.tsx` cần thêm state hiển thị khi proposal ở trạng thái "conflict", với hành động rõ ràng — ví dụ nút "yêu cầu agent tạo lại đề xuất" (gọi lại tool với nội dung mới nhất) hoặc "huỷ đề xuất". Không được để user bế tắc như hành vi hiện tại.

### 1.5.6 Kiểm thử
- Case 1: user edit note ở đoạn KHÔNG liên quan tới đoạn agent đề xuất sửa → approve phải **thành công** (đây là case hiện đang fail sai, ưu tiên cao nhất).
- Case 2: user edit đè lên đúng đoạn agent đề xuất sửa → approve phải trả về `status = "conflict"` rõ ràng, kèm thông tin, không stuck ở pending vô thời hạn.
- Case 3: test double-apply patch nếu xác nhận có bug ở 1.5.1.
- Case 4: proposal pending không có SSE event tới nơi (giả lập mất kết nối) → vẫn hiển thị được qua endpoint list.

## Definition of Done
- Proposal không còn bị stuck ở "pending" một cách vô lý khi user edit ở chỗ không liên quan.
- Có trạng thái "conflict" tường minh khi thực sự không áp được, kèm hành động rõ ràng cho user, không còn lỗi mơ hồ.
- Diff hiển thị trong review panel luôn khớp với nội dung hiện tại của note.
- Proposal pending luôn hiển thị được dù bỏ lỡ SSE event.
- Có test chứng minh 4 case ở mục 1.5.6.
- Cập nhật mục "Phase 1.5" trong `PROGRESS.md`.

## Báo cáo
1. Tóm tắt đã làm gì, file nào thay đổi.
2. Kết luận rõ ràng về bug double-apply (có hay không, đã fix chưa).
3. Liệt kê rủi ro/vấn đề còn tồn đọng.
4. Cập nhật `PROGRESS.md`.
5. Lưu ý rõ trong báo cáo: cơ chế fuzzy-patch xây ở phase này sẽ được thay thế bằng CRDT merge thật ở Phase 3 (sau khi Phase 2 hoàn tất) — không cần tối ưu quá mức cho giải pháp tạm thời này.
