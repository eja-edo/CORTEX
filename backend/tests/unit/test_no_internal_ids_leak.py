"""Không bao giờ hiện — và không bao giờ **hỏi** — một id nội bộ.

Đo được trong một cuộc trò chuyện mô phỏng, và đây là lỗi do chính tính năng
quy trình tạo ra:

    CORTEX: Tôi cần procedure_id từ quy trình của bạn để đánh dấu bước này.
    CORTEX: Procedure ID `PROC_REMOTE_001` không phải UUID hợp lệ —
            hệ thống cần định dạng UUID tiêu chuẩn.

Người dùng không có cách nào biết `procedure_id`. Hỏi họ biến một yêu cầu
bình thường thành ngõ cụt, rồi câu thứ hai còn bắt họ chịu trách nhiệm cho
một định dạng nội bộ.

Nguyên nhân: `mark_procedure_step` cần `procedure_id`, và id đó chỉ có trong
ngữ cảnh **khi** một quy trình khớp hoàn cảnh. Không khớp thì agent không
có id — và thay vì im, nó đi hỏi.
"""

import pytest


class TestToolForbidsAsking:
    def _description(self) -> str:
        from app.ai.tools.mark_procedure_step import MARK_PROCEDURE_STEP_DEFINITION

        return MARK_PROCEDURE_STEP_DEFINITION["description"]

    def test_tool_says_it_needs_the_context_block(self):
        assert "Quy trình khớp hoàn cảnh vừa nêu" in self._description()

    def test_tool_forbids_asking_for_the_id(self):
        desc = self._description()
        assert "KHÔNG hỏi người dùng procedure_id" in desc

    def test_tool_says_what_to_do_instead(self):
        """Cấm suông thì model vẫn phải làm gì đó."""
        desc = self._description()
        assert "việc bình thường" in desc


class TestPromptForbidsLeaking:
    def _prompt(self) -> str:
        from pathlib import Path

        return Path("app/ai/prompts/system/assistant_system.md").read_text(
            encoding="utf-8"
        )

    def test_prompt_bans_showing_internal_ids(self):
        assert "Never show the user an internal identifier" in self._prompt()

    @pytest.mark.parametrize("marker", ["procedure_id", "UUID", "[S1]"])
    def test_prompt_names_the_specific_leaks_seen(self, marker):
        """Nêu đúng thứ đã rò, không chỉ nói chung chung.

        `[S1]` là nhãn `source_id` mà tool result mang theo để agent trích
        dẫn nguồn — nó cũng đã rò ra người dùng trong cùng đợt đo.
        """
        assert marker in self._prompt()

    def test_prompt_bans_asking_not_just_showing(self):
        """Hiện ra thì xấu; *hỏi* thì chặn hẳn việc người dùng cần làm."""
        prompt = self._prompt()
        assert "never *ask* the user for one" in prompt
