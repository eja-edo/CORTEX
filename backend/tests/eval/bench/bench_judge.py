"""Đo model nào làm judge tốt — chính xác và nhanh.

Judge không cần thông minh. Nó cần **nhất quán**: cùng một đầu vào phải cho
cùng một phán quyết, và phán quyết phải khớp với điều một người đọc tận nơi
sẽ kết luận. Một judge sai không chỉ cho điểm sai — nó gửi người sửa code đi
sai hướng, như đã xảy ra ở vòng 1.

Chạy:
    venv/bin/python -m tests.eval.bench.bench_judge [repeat]
"""

from __future__ import annotations

import asyncio
import sys
import time

from app.ai.agents.provider_types import GenerationConfig, Message
from app.ai.agents.model_client import ModelClient
from tests.eval.bench.judge_cases import CASES
from tests.eval.judge import _JUDGE_SYSTEM

# Ứng viên: nhanh/rẻ trước, một model mạnh làm mốc so sánh.
CANDIDATES = [
    "free_auto",
    "gemini/gemini-3.5-flash-lite",
    "gc/gemini-2.5-flash-lite",
    "kr/claude-haiku-4.5",
    "gh/gpt-4o-mini-2024-07-18",
    "gh/gpt-5-mini",
    "openrouter/google/gemma-4-26b-a4b-it:free",
    "ollama/gpt-oss:120b",
]

_client = ModelClient()


async def _ask(model: str, criterion: str, content: str) -> bool | None:
    prompt = (
        f"=== CRITERION ===\n{criterion}\n\n"
        f"=== ASSISTANT OUTPUT ===\n{content}\n\n"
        "Does the assistant output satisfy the criterion? PASS or FAIL."
    )
    try:
        _, response = await _client.generate(
            [Message(role="user", content=prompt)],
            GenerationConfig(
                system_instruction=_JUDGE_SYSTEM, temperature=0.0, max_output_tokens=150
            ),
            tools=None,
            preferred_model=model,
        )
    except Exception:
        return None

    text = ((response.content if response else "") or "").strip().upper()
    if "PASS" in text and "FAIL" not in text:
        return True
    if "FAIL" in text and "PASS" not in text:
        return False
    return None


async def bench(model: str, repeat: int) -> dict:
    correct = unusable = 0
    total = 0
    flips = 0
    started = time.perf_counter()

    for label, criterion, content, expected in CASES:
        answers = []
        for _ in range(repeat):
            got = await _ask(model, criterion, content)
            total += 1
            if got is None:
                unusable += 1
            else:
                answers.append(got)
                if got == expected:
                    correct += 1
        # Cùng đầu vào, khác phán quyết giữa các lần → không nhất quán.
        if len(set(answers)) > 1:
            flips += 1

    elapsed = time.perf_counter() - started
    return {
        "model": model,
        "đúng": f"{correct}/{total - unusable}" if total > unusable else "0/0",
        "acc": correct / (total - unusable) if total > unusable else 0.0,
        "lỗi": unusable,
        "lật": flips,
        "giây/ca": elapsed / total if total else 0.0,
    }


async def main() -> None:
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(f"{len(CASES)} ca × {repeat} lần, {len(CANDIDATES)} model\n")
    rows = []
    for model in CANDIDATES:
        row = await bench(model, repeat)
        rows.append(row)
        print(
            f"{row['model']:45} acc={row['acc']:.0%} ({row['đúng']:>6}) "
            f"lỗi={row['lỗi']:<3} lật={row['lật']:<3} {row['giây/ca']:.1f}s/ca"
        )

    print("\n── xếp theo độ chính xác, rồi tốc độ ──")
    for row in sorted(rows, key=lambda r: (-r["acc"], r["giây/ca"])):
        print(f"  {row['acc']:.0%}  {row['giây/ca']:5.1f}s/ca  {row['model']}")


if __name__ == "__main__":
    asyncio.run(main())
