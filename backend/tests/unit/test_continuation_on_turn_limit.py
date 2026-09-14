"""Chạm trần lượt gọi công cụ (`MAX_TOOL_TURNS`) thì mời tiếp tục, không mời sửa câu hỏi.

Trước đây, hết ngân sách một lượt bị đóng khung thành lỗi của người dùng:
câu trả lời bảo họ "chia nhỏ ra, nói cụ thể hơn" — trong khi câu hỏi không
hề mơ hồ, nó chỉ cần nhiều bước hơn một lượt xử lý được. Người dùng bị bắt
tự sửa cách hỏi cho một giới hạn của hệ thống.

Cơ chế "tiếp tục" không cần một bộ nhận diện ý định mới: `_build_history_
contents` (conversation_service.py) đã dựng lại đầy đủ chuỗi tool đã gọi
và kết quả từ DB theo `turn_id`. Lượt kế tiếp bắt đầu lại từ `turn=0` với
ngân sách `MAX_TOOL_TURNS` đầy, và thấy được toàn bộ việc đã làm — nên chỉ
cần câu chốt của lượt trước tóm tắt đúng "đã làm gì / còn gì" là đủ để
người dùng gõ "tiếp tục" và agent đi tiếp đúng chỗ.
"""

from app.ai.agents.agent_service import CONTINUATION_INSTRUCTION
from app.ai.agents import user_messages


class TestFallbackMessageInvitesNotBlames:
    """`TOO_MANY_STEPS` — lưới cuối khi cả lượt tổng hợp cũng hỏng."""

    def test_does_not_ask_the_user_to_split_the_request(self):
        text = user_messages.TOO_MANY_STEPS.lower()
        for phrase in ("chia nhỏ", "nói cụ thể hơn", "diễn đạt lại"):
            assert phrase not in text, f"vẫn đổ việc sang người dùng: {phrase!r}"

    def test_invites_continuation(self):
        assert "tiếp tục" in user_messages.TOO_MANY_STEPS

    def test_says_no_need_to_repeat_the_request(self):
        """Nếu không nói rõ điều này, người dùng sẽ gõ lại nguyên yêu cầu."""
        text = user_messages.TOO_MANY_STEPS.lower()
        assert "không cần" in text and "nhắc lại" in text


class TestSynthesisInstructionShapesTheCheckpoint:
    """Chỉ dẫn ép lượt tổng hợp trả lời đúng khung, không tự đoán."""

    def test_names_the_limit_as_the_systems_not_the_users(self):
        text = CONTINUATION_INSTRUCTION.lower()
        assert "giới hạn của hệ thống" in text
        assert "không phải vì câu hỏi" in text

    def test_forbids_asking_to_clarify_or_split(self):
        text = CONTINUATION_INSTRUCTION.lower()
        assert "đừng bảo họ hỏi lại" in text or "đừng" in text
        assert "chia nhỏ" in text  # nhắc tới để CẤM, không phải để gợi ý

    def test_requires_done_and_remaining_and_an_invitation(self):
        text = CONTINUATION_INSTRUCTION
        assert "đã làm xong" in text
        assert "còn lại" in text
        assert "tiếp tục" in text

    def test_forbids_repeating_the_original_request(self):
        assert "không lặp lại toàn bộ yêu cầu" in CONTINUATION_INSTRUCTION.lower()


class TestWiredIntoBothPaths:
    """Streaming và không-streaming phải dùng cùng chỉ dẫn.

    Một đường quên là một bề mặt người dùng vẫn nhận câu đổ lỗi cũ.
    """

    def _source(self, func) -> str:
        import inspect

        return inspect.getsource(func)

    def test_non_streaming_uses_the_instruction(self):
        from app.ai.agents.agent_service import AgentService

        src = self._source(AgentService.handle)
        assert "CONTINUATION_INSTRUCTION" in src

    def test_streaming_uses_the_instruction(self):
        from app.ai.agents.agent_service import AgentService

        src = self._source(AgentService.handle_streaming_generator)
        assert "CONTINUATION_INSTRUCTION" in src

    def test_instruction_is_appended_not_replacing_the_system_prompt(self):
        """Mất system prompt gốc thì mất mọi ràng buộc an toàn khác của nó."""
        from app.ai.agents.agent_service import AgentService

        for func in (AgentService.handle, AgentService.handle_streaming_generator):
            src = self._source(func)
            assert (
                "(gen_config.system_instruction or \"\") + CONTINUATION_INSTRUCTION"
                in src
            )
