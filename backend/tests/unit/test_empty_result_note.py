"""Kết quả rỗng phải tự nói ra rằng nó là sự thật, không phải chỗ trống.

Đo được (2026-09-10, kịch bản eval L3, tái hiện 6/6 lần): người dùng nói
"deadline dự án sắp tới rồi, tôi hơi lo"; agent gọi `get_project_tasks`,
nhận `tasks: []`, rồi tạo sáu task "Create file a.txt with content 'a'"
bằng tiếng Anh. Không chuỗi nào trong đó tồn tại ở prompt, ở DB, hay ở bất
kỳ kết quả tool nào — model gặp khoảng trống và lấp bằng một mẫu quen từ
dữ liệu huấn luyện.

System prompt đã dặn "accept the empty result, do not retry" và bị bỏ qua:
lời dặn đó cách chỗ quyết định hàng nghìn token. Câu dặn đặt ngay trong
kết quả thì model đọc nó đúng lúc đang quyết định.
"""

import pytest

from app.ai.tools.empty_result import empty_note, with_empty_note


class TestNoteContent:
    def test_note_names_what_is_empty(self):
        note = empty_note("Dự án X chưa có việc nào")
        assert "Dự án X chưa có việc nào" in note

    def test_note_forbids_inventing(self):
        """Đây là câu chịu lực — nếu nó biến mất, phép chặn cũng biến mất."""
        note = empty_note("gì đó")
        assert "không tự nghĩ ra" in note

    def test_note_offers_the_alternative(self):
        """Cấm suông thì model vẫn phải làm gì đó; nói cho nó biết làm gì."""
        note = empty_note("gì đó")
        assert "hỏi họ" in note

    def test_note_stays_short(self):
        """Nó đi kèm *mọi* kết quả rỗng, nên mỗi từ thừa nhân lên theo số
        lời gọi."""
        assert len(empty_note("x").split()) < 45


class TestAttachment:
    def test_empty_result_gets_the_note(self):
        out = with_empty_note({"tasks": [], "count": 0}, True, "Chưa có việc nào")
        assert "note" in out
        assert out["count"] == 0

    def test_non_empty_result_is_untouched(self):
        payload = {"tasks": [{"id": "1"}], "count": 1}
        assert with_empty_note(payload, False, "x") == payload

    def test_original_payload_is_not_mutated(self):
        """Tool khác có thể còn giữ tham chiếu tới dict đó."""
        payload = {"tasks": [], "count": 0}
        with_empty_note(payload, True, "x")
        assert "note" not in payload


class TestEveryReadToolUsesIt:
    """Một tool đọc quên gắn note là một lỗ hổng y hệt lỗ hổng đã đo.

    Canh bằng cách đọc mã nguồn thay vì gọi từng tool: gọi thật cần DB và
    một người dùng có đúng trạng thái rỗng cho từng loại, còn thứ cần canh
    ở đây chỉ là "tool này có nối vào helper chung hay không".
    """

    @pytest.mark.parametrize(
        "module",
        [
            "get_project_tasks",
            "list_pending_tasks",
            "list_projects",
            "search_notes",
        ],
    )
    def test_read_tool_wires_the_helper(self, module):
        from pathlib import Path

        src = Path(f"app/ai/tools/{module}.py").read_text(encoding="utf-8")
        assert "with_empty_note(" in src, (
            f"{module} có thể trả về rỗng mà không kèm câu dặn"
        )


class TestPromptBacksItUp:
    """Câu dặn trong kết quả và quy tắc trong prompt là một cặp."""

    def _prompt(self) -> str:
        from pathlib import Path

        return Path("app/ai/prompts/system/assistant_system.md").read_text(
            encoding="utf-8"
        )

    def test_prompt_forbids_inventing_on_empty(self):
        assert "never invent content to fill the gap" in self._prompt()

    def test_prompt_mentions_the_note_field(self):
        assert "`note` field" in self._prompt()
