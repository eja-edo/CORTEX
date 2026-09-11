"""Vòng tự đánh giá: người dùng ảo trò chuyện thật với agent thật.

Khác phần còn lại của `tests/eval/`: ở đây không có câu hỏi viết sẵn. Một
LLM đóng vai người dùng, phản ứng với đúng những gì agent trả lời, qua nhiều
lượt — nên nó bắt được các kiểu hỏng chỉ hiện ra khi hội thoại dài: phải
giải thích lại điều đã nói, bị hỏi lại cùng một câu, agent quên mục tiêu ban
đầu.

Chạy:  pytest -m live_llm tests/eval/test_simulated_conversations.py -v -s

Đắt hơn hẳn các bài khác (mỗi persona ~6 lượt × 2 lời gọi LLM, cộng 5 lần
chấm), nên đừng chạy nó trong vòng lặp sửa code nhanh — nó là bài kiểm
định kỳ.
"""

import pytest

from tests.eval.personas import PERSONAS
from tests.eval.rubric import score
from tests.eval.simulator import simulate

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.name)
async def test_simulated_conversation(persona, memory_seeder):
    """Một cuộc trò chuyện mô phỏng, chấm theo năm tiêu chí."""
    if persona.memories:
        await memory_seeder(persona.memories)

    convo = await simulate(persona, max_turns=5)
    assert convo.turns, "người dùng ảo không nói được câu nào"

    result = await score(convo)
    print(f"\n{'=' * 70}")
    print(convo.transcript)
    print(f"{'-' * 70}")
    print(result.report())
    print(f"{'=' * 70}")

    assert result.passed, f"{persona.name} trượt: {result.failures}"
