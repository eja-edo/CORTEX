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
vẫn có thể bị bịa thành công theo cách y hệt.

Quy tắc này sống trong đúng MỘT chỗ — mục "After calling a tool — handling
results", cùng với các quy tắc validation-error khác — thay vì lặp lại một
bản riêng trong HARD CONSTRAINTS. Bản đầu tiên có cả hai nơi, mâu thuẫn nhau
về số lần thử lại; gộp lại để tránh phình prompt và tránh hai chỗ nói khác
nhau về cùng một tình huống.
"""

import re
from pathlib import Path

import pytest


def _prompt() -> str:
    return Path("app/ai/prompts/system/assistant_system.md").read_text(
        encoding="utf-8"
    )


def _flat(text: str) -> str:
    """Prose in this prompt wraps at ~80 chars with literal newlines — the
    same sentence can span lines in the source. Collapse whitespace so a
    quoted phrase can be asserted regardless of where the source wraps it."""
    return re.sub(r"\s+", " ", text)


class TestPromptForbidsClaimingSuccessAfterError:
    def test_prompt_bans_saying_action_succeeded_after_tool_error(self):
        prompt = _prompt()
        assert "do NOT tell the user the action succeeded" in prompt

    def test_prompt_cites_the_measured_failure(self):
        """Nêu đúng ví dụ đã đo, không chỉ cấm chung chung."""
        prompt = _flat(_prompt())
        assert "Mình đã ghi nhận lịch họp team vào 10:00 sáng Thứ 5" in prompt

    def test_prompt_bans_retrying_silently_forever(self):
        """Thất bại lần 2 cùng lý do thì phải nói, không thử lần 3 hay bịa."""
        prompt = _flat(_prompt())
        assert "fails a second time for the same reason" in prompt

    def test_rule_lives_in_one_place_not_two(self):
        """Không được lặp lại một bản riêng trong HARD CONSTRAINTS — bản đầu
        tiên làm vậy và mâu thuẫn với mục xử lý lỗi tool ở trên về số lần
        thử lại trước khi dừng."""
        prompt = _prompt()
        hard_constraints = prompt.split("## HARD CONSTRAINTS", 1)[1]
        assert "Mình đã ghi nhận lịch họp team" not in hard_constraints


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
