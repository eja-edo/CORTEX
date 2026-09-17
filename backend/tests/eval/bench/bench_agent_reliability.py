"""Đo model nào **không im lặng** — độ tin cậy cho vai trò agent.

Đo trên một vòng eval thật: 7 trong 54 lượt (13%) model trả về
`completion_tokens=0` với `finish_reason=stop`. Không phải lỗi, không phải
timeout — nó "hoàn thành" mà không sinh một token nào, và người dùng nhận
một câu xin lỗi rồi phải gõ lại.

Hai giả thuyết đã thử và **đều không cứu được**:

* gọi lại y nguyên → rỗng tiếp, 4/4 lần;
* gọi lại với prompt ngắn hơn (37k → 26k ký tự) → vẫn rỗng, 7/7 lần.

Nên nghi can còn lại là chính model. `free_auto` là một combo *tự chọn*
backend giữa các lời gọi, nên một backend hay trả rỗng sẽ kéo cả tỉ lệ
xuống mà không để lại dấu vết nào trong log ngoài con số 0.

Bài đo này không hỏi model nào thông minh hơn. Nó hỏi đúng một câu: **gọi
100 lần thì bao nhiêu lần nó không nói gì?** Với trải nghiệm người dùng,
một model khá mà luôn trả lời tốt hơn một model giỏi mà thỉnh thoảng im.

Chạy:
    venv/bin/python -m tests.eval.bench.bench_agent_reliability [số_lần]
"""

from __future__ import annotations

import asyncio
import sys
import time

from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import GenerationConfig, Message
from app.ai.agents.tool_registry import get_tool_registry

CANDIDATES = [
    "free_auto",
    "kr/claude-haiku-4.5",
    "kr/deepseek-3.2",
    "kr/minimax-m2.5",
    "gemini/gemini-3.6-flash",
    "gemini/gemini-3.5-flash-lite",
    "gh/gpt-5-mini",
    "ollama/gpt-oss:120b",
]

# Ba lượt nói ngắn — đúng kiểu đã làm model im lặng trong đo đạc thật.
# Ngắn là cách người ta dùng app, nên model phải chịu được nó.
PROMPTS = [
    "Tuần sau nộp báo cáo.",
    "đặt lịch họp team 10h thứ 5",
    "Đúng. Đặt lịch 19h tối mai.",
]

_client = ModelClient()


def _padded_history(target_tokens: int) -> list[Message]:
    """Lịch sử hội thoại giả, đủ dài để tổng prompt đạt `target_tokens`.

    Bản đầu của bài đo này chỉ gửi **một** message, nên tổng prompt chỉ
    ~11.5k token — và ở mức đó không model nào im, kể cả `free_auto`. Nhưng
    lượt rỗng thật xảy ra ở **18.8k**. Bài đo không tái hiện được điều kiện
    gây lỗi thì nó chỉ chứng minh rằng lỗi không xảy ra khi không có lỗi.

    Nội dung là hội thoại thật về công việc, không phải chuỗi rác: một khối
    "lorem ipsum" có thể bị model xử lý khác hẳn một hội thoại có nghĩa.
    """
    turn = [
        Message(role="user", content="Tuần này tôi có mấy việc cần theo dõi."),
        Message(
            role="assistant",
            content=(
                "Mình đã ghi nhận. Hiện tại bạn có ba việc đang mở: rà soát "
                "hợp đồng, gửi báo cáo tiến độ, và chuẩn bị tài liệu cho buổi "
                "họp với khách. Cả ba đều chưa có hạn cụ thể — bạn muốn đặt "
                "hạn cho việc nào trước không?"
            ),
        ),
    ]
    history: list[Message] = []
    used = 0
    from app.utils.tokens import estimate_tokens

    per_pair = sum(estimate_tokens(m.content or "") for m in turn)
    while used < target_tokens:
        history.extend(turn)
        used += per_pair
    return history


async def probe(
    model: str, system_prompt: str, tools, message: str, pad_tokens: int = 0
) -> tuple[bool, int]:
    """Trả (có nói gì không, số token sinh ra)."""
    messages = _padded_history(pad_tokens) if pad_tokens else []
    messages.append(Message(role="user", content=message))
    try:
        _, response = await _client.generate(
            messages,
            GenerationConfig(system_instruction=system_prompt, max_output_tokens=500),
            tools=tools,
            preferred_model=model,
        )
    except Exception:
        return False, 0

    if response is None:
        return False, 0
    said = bool(
        (response.content or "").strip()
        or (response.reasoning or "").strip()
        or response.tool_calls
    )
    completion = (response.usage or {}).get("completion_tokens", 0) or 0
    return said, completion


async def bench(
    model: str, system_prompt: str, tools, repeat: int, pad_tokens: int = 0
) -> dict:
    silent = 0
    total = 0
    started = time.perf_counter()
    for message in PROMPTS:
        for _ in range(repeat):
            said, _tok = await probe(model, system_prompt, tools, message, pad_tokens)
            total += 1
            if not said:
                silent += 1
    elapsed = time.perf_counter() - started
    return {
        "model": model,
        "im": silent,
        "total": total,
        "tỉ lệ im": silent / total if total else 1.0,
        "giây/lượt": elapsed / total if total else 0.0,
    }


async def main() -> None:
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 2

    from app.ai.agents.agent_service import SYSTEM_PROMPT

    tools = get_tool_registry().get_provider_tools()
    print(
        f"{len(PROMPTS)} lượt ngắn × {repeat} lần, system prompt "
        f"{len(SYSTEM_PROMPT)} ký tự, {len(tools)} tool\n"
    )

    # Ba mức, bao quanh ngưỡng nghi vấn: bài đo cũ chạy ở ~11.5k và không
    # thấy gì; lượt rỗng thật ở 18.8k.
    for pad in (0, 6000, 12000):
        label = "không pad (~11k)" if not pad else f"pad {pad} (~{11 + pad // 1000}k)"
        print(f"\n━━ {label} ━━")
        rows = []
        for model in CANDIDATES:
            row = await bench(model, SYSTEM_PROMPT, tools, repeat, pad)
            rows.append(row)
            print(
                f"{row['model']:34} im {row['im']}/{row['total']} "
                f"({row['tỉ lệ im']:.0%})  {row['giây/lượt']:.1f}s/lượt"
            )
        worst = [r for r in rows if r["tỉ lệ im"] > 0]
        if worst:
            print(f"  → im ở mức này: {', '.join(r['model'] for r in worst)}")
        else:
            print("  → không model nào im")


if __name__ == "__main__":
    asyncio.run(main())
