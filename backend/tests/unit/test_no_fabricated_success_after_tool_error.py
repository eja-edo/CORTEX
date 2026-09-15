"""Sau khi tool vừa trả lỗi, không được nói với người dùng là đã thành công.

Đo được trong hội thoại thật (persona `ra_lệnh_liên_tiếp`, round12): model
gọi `create_schedule` ba lần liên tiếp, cả ba lần đều thất bại vì thiếu
`title` (nội dung bị nhét sai sang `description`), rồi trả lời:

    "Mình đã ghi nhận lịch họp team vào 10:00 sáng Thứ 5."

Bảng `schedules` rỗng hoàn toàn — không có gì được tạo. Lỗi nằm sẵn trong
ngữ cảnh của model ở cả ba lượt (`success: false`, thông điệp rõ ràng), nên
đây không phải lỗi truyền dữ liệu — model THẤY lỗi và vẫn chọn báo thành
công. `title_fallback.py` chặn được nguyên nhân kích hoạt cụ thể (title
trống), nhưng không chặn được cơ chế chung: tool thất bại vì lý do khác
vẫn có thể bị bịa thành công theo cách y hệt. Vá bằng một quy tắc rõ ràng
trong HARD CONSTRAINTS, không chỉ câu cấm chung "do not fabricate".
"""

from pathlib import Path

import pytest


def _prompt() -> str:
    return Path("app/ai/prompts/system/assistant_system.md").read_text(
        encoding="utf-8"
    )


class TestPromptForbidsClaimingSuccessAfterError:
    def test_prompt_bans_saying_action_succeeded_after_tool_error(self):
        prompt = _prompt()
        assert "never tell the" in prompt
        assert "the action succeeded" in prompt

    def test_prompt_cites_the_measured_failure(self):
        """Nêu đúng ví dụ đã đo, không chỉ cấm chung chung."""
        prompt = _prompt()
        assert "Mình đã ghi nhận lịch họp team vào 10:00 sáng Thứ 5" in prompt

    def test_prompt_tells_model_to_check_success_field(self):
        prompt = _prompt()
        assert "`success` field" in prompt

    def test_prompt_bans_retrying_silently_forever(self):
        """Thất bại 2 lần cùng lý do thì phải nói, không thử lần 3 hay bịa."""
        prompt = _prompt()
        assert "fails twice in a row for the same reason" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
