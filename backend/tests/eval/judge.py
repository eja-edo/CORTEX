"""Chấm phần không assert được bằng chuỗi — bằng chính một lời gọi LLM.

Khi nào dùng judge, khi nào không:

* **Không dùng** cho thứ đã là sự thật cứng. "Có gọi `create_task` không"
  nằm trong `agent_messages`; hỏi model về nó là thay một phép kiểm chắc
  chắn bằng một phép đoán.
* **Dùng** cho thứ vốn là ngữ nghĩa: "câu trả lời này có đề xuất quy trình
  làm-việc-từ-xa không?" Model diễn đạt điều đó bằng vô số cách, và một
  danh sách từ khoá sẽ vừa bỏ sót vừa bắt nhầm.

Judge chạy ở `temperature=0` và bị ép trả về đúng một từ, để bản thân nó
không trở thành nguồn phương sai mới trong một bộ đo phương sai.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import GenerationConfig, Message

_client = ModelClient()

_JUDGE_SYSTEM = """You grade one assistant reply against one criterion.

Answer with exactly one word on the first line: PASS or FAIL.
On the second line, give a one-sentence reason.

Judge ONLY the criterion given. Do not judge tone, length, formatting, or
whether you would have answered differently. The reply is in Vietnamese;
judge it in Vietnamese without translating."""


@dataclass
class Verdict:
    passed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.passed

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log khi đỏ
        return f"{'PASS' if self.passed else 'FAIL'}: {self.reason}"


async def judge(reply: str, criterion: str) -> Verdict:
    """`criterion` phải viết sao cho PASS là hành vi **mong muốn**."""
    prompt = (
        f"=== CRITERION ===\n{criterion}\n\n"
        f"=== ASSISTANT REPLY ===\n{reply}\n\n"
        "Does the reply satisfy the criterion? PASS or FAIL."
    )
    _, response = await _client.generate(
        [Message(role="user", content=prompt)],
        GenerationConfig(
            system_instruction=_JUDGE_SYSTEM,
            temperature=0.0,
            max_output_tokens=200,
        ),
        tools=None,
    )
    text = ((response.content if response else "") or "").strip()
    first, _, rest = text.partition("\n")
    verdict = first.strip().upper()

    # Model suy luận đôi khi trả lời dài dòng bất chấp chỉ dẫn. Rơi về quét
    # cả câu chứ không coi là FAIL — một judge hỏng phải lộ ra là hỏng, chứ
    # không được giả trang thành "bài test trượt".
    if verdict not in ("PASS", "FAIL"):
        upper = text.upper()
        if "PASS" in upper and "FAIL" not in upper:
            return Verdict(True, text[:300])
        if "FAIL" in upper and "PASS" not in upper:
            return Verdict(False, text[:300])
        raise AssertionError(
            f"Judge không trả về PASS/FAIL mà trả: {text[:300]!r}"
        )

    return Verdict(verdict == "PASS", rest.strip() or text)
