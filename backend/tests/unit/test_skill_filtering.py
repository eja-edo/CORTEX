"""Không nạp skill mà mọi tool của nó đã bị gỡ.

`research` là ca cụ thể: cả `web_search` lẫn `web_fetch` nằm trong
`FROZEN_TOOLS`, nên skill đó dạy agent một quy trình nó không thực hiện
được — và tốn **3.589 token** mỗi lượt để làm việc đó.

Hai cái giá, cái thứ hai đắt hơn: token (prompt gốc 7.689 + skills 7.971,
đo trên một lượt thật), và **nói sai về khả năng của mình** — system prompt
nói web search không có, rồi một skill được nạp vào lại mô tả cách dùng nó.

Prompt dài có hậu quả đo được: ba lượt trong vòng eval thứ bảy trả về
`completion_tokens=0` với `finish_reason=stop` ở 18–20k token đầu vào.
Agent câm, người dùng nhận một câu "mình chưa trả lời được".
"""

from dataclasses import dataclass

from app.ai.agents.conversation_service import _drop_skills_with_no_live_tools


@dataclass
class FakeSkill:
    name: str
    tools: list[str]


class TestFiltering:
    def test_drops_a_skill_whose_tools_are_all_gone(self):
        kept = _drop_skills_with_no_live_tools(
            [FakeSkill("research", ["web_search", "web_fetch"])]
        )
        assert kept == []

    def test_keeps_a_skill_with_at_least_one_live_tool(self):
        """Một tool sống là đủ — phần còn lại của skill vẫn dùng được."""
        kept = _drop_skills_with_no_live_tools(
            [FakeSkill("planning", ["create_schedule", "propose_plan"])]
        )
        assert len(kept) == 1

    def test_keeps_a_toolless_skill(self):
        """`reasoning` không khai tool nào: nó dạy cách nghĩ, không cần tool."""
        kept = _drop_skills_with_no_live_tools([FakeSkill("reasoning", [])])
        assert len(kept) == 1

    def test_never_raises_on_bad_input(self):
        """Lọc skill hỏng không được giết lượt chat."""
        assert _drop_skills_with_no_live_tools([]) == []


class TestAgainstTheRealRegistry:
    def test_research_is_filtered_out_today(self):
        from app.ai.skills import get_skill_registry

        metas = get_skill_registry().scan()
        kept_names = {m.name for m in _drop_skills_with_no_live_tools(metas)}
        assert "research" not in kept_names, (
            "research vẫn được nạp dù web_search/web_fetch đang đóng băng"
        )

    def test_the_working_skills_survive(self):
        """Phép lọc phải hẹp: chỉ bỏ cái chết hẳn."""
        from app.ai.skills import get_skill_registry

        metas = get_skill_registry().scan()
        kept_names = {m.name for m in _drop_skills_with_no_live_tools(metas)}
        for name in ("memory", "schedule", "task", "planning", "reasoning"):
            assert name in kept_names, f"bỏ nhầm skill còn dùng được: {name}"

    def test_filter_is_wired_into_prompt_building(self):
        import inspect

        from app.ai.agents.conversation_service import ConversationService

        src = inspect.getsource(ConversationService._build_skill_section)
        assert "_drop_skills_with_no_live_tools" in src
