"""Dấu thời gian hệ thống không được lọt vào câu trả lời người dùng.

Mọi message trong lịch sử được chèn tiền tố `[YYYY-MM-DD HH:MM:SS UTC] ` để
model biết mỗi lượt nói lúc nào. Model học mẫu đó và đôi khi mở câu trả lời
của chính nó bằng đúng tiền tố ấy.

Đo được trong một cuộc trò chuyện mô phỏng — người dùng nhận nguyên văn:

    [2026-09-11 04:45:15 UTC] Rõ. Nếu cần hỗ trợ gì khác…

Đáng nói về cách tìm ra nó: cuộc trò chuyện đó **đạt 5/5** theo thang chấm
tự động. Không tiêu chí nào hỏi "câu trả lời có rò định dạng nội bộ không",
nên thang chấm mù hoàn toàn. Nó chỉ lộ ra khi có người đọc transcript.
"""

import pytest

from app.ai.agents.conversation_service import strip_injected_timestamp


class TestStripping:
    def test_strips_a_leading_timestamp(self):
        assert strip_injected_timestamp(
            "[2026-09-11 04:45:15 UTC] Rõ rồi bạn nhé"
        ) == "Rõ rồi bạn nhé"

    def test_strips_only_one(self):
        """Hai tiền tố liền nhau vẫn là một lần copy, không phải nội dung."""
        out = strip_injected_timestamp(
            "[2026-09-11 04:45:15 UTC] [2026-09-11 04:45:16 UTC] Rõ"
        )
        assert out.startswith("[2026-09-11 04:45:16 UTC]")

    def test_keeps_a_timestamp_in_the_middle(self):
        """Giữa câu có thể là nội dung thật người dùng vừa hỏi."""
        text = "Cuộc họp lúc [2026-09-11 04:45:15 UTC] nhé"
        assert strip_injected_timestamp(text) == text

    def test_leaves_normal_text_alone(self):
        assert strip_injected_timestamp("Bình thường") == "Bình thường"

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_input_is_safe(self, value):
        assert strip_injected_timestamp(value) == value

    def test_does_not_eat_a_bracketed_sentence(self):
        """Chỉ đúng định dạng hệ thống mới bị cắt."""
        text = "[Quan trọng] Bạn có 3 việc quá hạn"
        assert strip_injected_timestamp(text) == text


class TestWiredEverywhere:
    """Cắt ở mọi đường mà câu trả lời đi qua.

    Một đường quên cắt là một bề mặt người dùng vẫn thấy tiền tố — và cả
    hai đường (streaming/không) đều có người dùng thật.
    """

    def _source(self, func):
        import inspect

        return inspect.getsource(func)

    def test_non_streaming_strips_before_saving(self):
        from app.ai.agents.agent_service import AgentService

        src = self._source(AgentService.handle)
        assert "strip_injected_timestamp(reply_text)" in src

    def test_streaming_strips_each_turn(self):
        from app.ai.agents.agent_service import AgentService

        src = self._source(AgentService.handle_streaming_generator)
        assert "strip_injected_timestamp(turn_text)" in src

    def test_prompt_also_tells_the_model_not_to(self):
        """Code là phép chặn; prompt giảm tần suất phải chặn."""
        from pathlib import Path

        prompt = Path("app/ai/prompts/system/assistant_system.md").read_text(
            encoding="utf-8"
        )
        assert "Never start a reply with a timestamp" in prompt
