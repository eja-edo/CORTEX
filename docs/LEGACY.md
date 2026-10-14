# Hệ cũ — đã gỡ khỏi cây thư mục, còn nguyên trong git

Ngày 2026-10-10, toàn bộ hệ cũ (bản 1 và nhánh AI companion) được gỡ khỏi repo. Dự án chính bây giờ là [`cortex-leads/`](../cortex-leads/). Mọi dòng code cũ vẫn nằm trong lịch sử git và lấy lại được bằng một lệnh.

**Mốc để lấy lại:** commit `0a22e33` (đầu nhánh `feat_recurring`, trước khi gỡ). Nhánh `develop` cũng còn nguyên hệ cũ.

```bash
# xem lại một tệp cũ
git show 0a22e33:backend/app/ai/agents/model_client.py
# khôi phục cả một thư mục ra chỗ tạm (không đưa lại vào cây chính)
git archive 0a22e33 backend/tests/eval | tar -x -C /tmp/legacy
```

## Những gì có thể cần về sau

| Thứ | Đường dẫn ở `0a22e33` | Khi nào cần |
|---|---|---|
| Bộ eval gọi LLM thật: simulator khách, judge, rubric, report | `backend/tests/eval/` (`simulator.py`, `judge.py`, `README.md`…) | Khi `cortex-leads` cần eval cho skill (DESIGN §5.8: eval là cổng bắt buộc trước shadow). Bỏ phần gắn `AgentService` |
| STT có diarization ở mức từng từ (WhisperX) | `stt_service/` | Nếu có nguồn việc từ ghi âm, cuộc gọi |
| OCR | `ocr_service/` | Nếu có nguồn việc từ ảnh |
| Bot Mezon: card tương tác, DM, ghi chú về SDK (Node 22, better-sqlite3) | `mezon_bot/`, `docs/archive/mezon-bot-plan.md` | Nếu Mezon thành một kênh, khi đó viết thành *bridge* theo DESIGN §5.2 |
| Phân loại sự kiện, Redis Streams bus, `StateEvaluator` | `backend/app/events/`, `backend/app/services/state_evaluator.py` | Tham khảo khi T1 cần predicate `condition` |
| CommandRegistry đầy đủ (snapshot, revert) | `backend/app/commands/` | T1: hoàn tác tool ghi |
| Google Calendar sync | `backend/app/services/google_calendar_sync.py` | T1: `check_availability` |
| Việc dở: model packages + chế độ thực thi manual/auto | `git stash` `stash@{0}` | Gần như chắc chắn không cần. Ý "phải duyệt mới ghi" đã được port |

**Đã port sang `cortex-leads`** (không cần lấy lại): retry và phân loại lỗi LLM, note khi kết quả rỗng, giải tham chiếu không đoán, thứ tự pipeline command, làm sạch args, dòng chốt vẽ shape JSON. Chi tiết ở DESIGN §5.11.

## Server cũ

Server EC2 vẫn chạy hệ cũ từ nhánh `develop`. Gỡ code trên nhánh này **không** ảnh hưởng tới server. **Không merge nhánh này vào `develop` trước khi tắt server**, nếu không thì lần deploy tiếp theo sẽ hỏng. Thứ tự đúng nằm ở DESIGN §10: vá bảo mật, dump DB, tắt.
