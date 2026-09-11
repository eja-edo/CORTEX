"""Câu Cortex nói khi có sự cố phải viết cho người dùng, không cho log.

Các câu này từng nằm rải rác tám chỗ trong `agent_service.py` và dùng thuật
ngữ nội bộ. Đo được hậu quả trong một cuộc trò chuyện mô phỏng — người dùng
mới cài app, nói "mình đang rối quá, cái deadline sắp tới làm mình lo muốn
xỉu luôn", và câu **đầu tiên** họ nhận được là:

    Mô hình không trả về nội dung nào. Bạn thử gửi lại sau ít phút nhé.

"Mô hình" là từ của người làm hệ thống. Người dùng không có mô hình nào; họ
có một deadline và đang lo.
"""

import re

import pytest

from app.ai.agents import user_messages

ALL_MESSAGES = {
    name: value
    for name, value in vars(user_messages).items()
    if name.isupper() and isinstance(value, str)
}

# Từ của người làm hệ thống, không phải của người dùng.
JARGON = [
    "mô hình", "model", "dịch vụ ai", "api", "token", "context",
    "server", "backend", "pipeline", "provider", "endpoint",
    "processing limit", "null", "exception", "timeout",
]


class TestNoInternalJargon:
    @pytest.mark.parametrize("name", sorted(ALL_MESSAGES))
    def test_message_avoids_jargon(self, name):
        text = ALL_MESSAGES[name].lower()
        hits = [w for w in JARGON if w in text]
        assert not hits, f"{name} còn thuật ngữ nội bộ: {hits}"

    @pytest.mark.parametrize("name", sorted(ALL_MESSAGES))
    def test_message_is_vietnamese(self, name):
        """Phần còn lại của sản phẩm nói tiếng Việt; câu lỗi cũng vậy."""
        assert re.search(r"[àáảãạăâèéêìíòóôơùúưỳýđ]", ALL_MESSAGES[name].lower())


class TestEveryMessageIsActionable:
    """Một câu xin lỗi không có bước kế tiếp thì bỏ người dùng đứng đó."""

    @pytest.mark.parametrize("name", sorted(ALL_MESSAGES))
    def test_message_tells_the_user_what_to_do(self, name):
        text = ALL_MESSAGES[name].lower()
        cues = ["thử", "đợi", "báo", "chia nhỏ", "nói lại", "nhắc lại", "cụ thể"]
        assert any(c in text for c in cues), f"{name} không nói người dùng làm gì tiếp"

    @pytest.mark.parametrize("name", sorted(ALL_MESSAGES))
    def test_message_is_not_a_wall_of_text(self, name):
        """Người đang bực không đọc một đoạn dài."""
        assert len(ALL_MESSAGES[name].split()) <= 40


class TestAgentUsesThem:
    """Cả hai đường (streaming và không) phải nói cùng một câu."""

    def _agent_source(self) -> str:
        from pathlib import Path

        return Path("app/ai/agents/agent_service.py").read_text(encoding="utf-8")

    def test_no_hardcoded_jargon_left_in_agent(self):
        src = self._agent_source().lower()
        for phrase in ("mô hình không trả về", "dịch vụ ai đang", "processing limit"):
            assert phrase not in src, f"còn câu cũ trong agent_service: {phrase!r}"

    def test_agent_imports_the_module(self):
        assert "from app.ai.agents import user_messages" in self._agent_source()

    def test_both_paths_reference_them(self):
        """Một đường quên là một bề mặt người dùng vẫn thấy thuật ngữ."""
        src = self._agent_source()
        assert src.count("user_messages.") >= 8
