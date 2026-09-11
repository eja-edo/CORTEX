"""Thang chấm một cuộc trò chuyện mô phỏng.

Bốn tiêu chí, lấy thẳng từ những gì chủ dự án nêu khi đặt hướng cho phần AI:
hiểu người dùng; nhớ những gì đã được dạy; gợi ý đúng lúc và biết lúc nào
không nên; và chất lượng không lệch nhau xa giữa các phiên.

Mỗi tiêu chí chấm **PASS/FAIL kèm lý do**, không chấm điểm số. Điểm số trên
một thang 1–10 do LLM cho nghe như đo được nhưng không so sánh được giữa hai
lần chạy — cùng một transcript có thể nhận 6 rồi 8. Một phán quyết nhị phân
kèm lý do thì vừa ổn định hơn vừa chỉ ra được phải sửa gì.

Thêm vài phép kiểm **tất định** bên cạnh, vì có thứ không cần hỏi model:
số bản ghi đã tạo, số lần lặp lại cùng một câu hỏi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tests.eval.judge import Verdict, judge
from tests.eval.simulator import SimulatedConversation

# Mỗi tiêu chí viết sao cho PASS là hành vi **mong muốn**.
CRITERIA: dict[str, str] = {
    "hiểu_ý": (
        "Trợ lý nắm được điều người dùng thật sự muốn, kể cả khi họ nói vòng "
        "hoặc chưa nói rõ. Nó KHÔNG bắt người dùng diễn đạt lại ý đã nêu."
    ),
    "không_báo_lỗi_vô_cớ": (
        "Trợ lý KHÔNG nói với người dùng rằng hệ thống gặp lỗi/sự cố kỹ "
        "thuật. Một giới hạn có chủ đích (ví dụ dừng lại để xin xác nhận) "
        "phải được nói ra như một câu hỏi bình thường, không như một lỗi. "
        "Không nhắc gì tới lỗi là PASS."
    ),
    "không_hỏi_lại": (
        "Trợ lý KHÔNG hỏi lại một thông tin người dùng đã cung cấp trong "
        "cuộc trò chuyện này, và KHÔNG hỏi thứ nó đã biết từ bộ nhớ."
    ),
    "dùng_bộ_nhớ": (
        "Khi có thông tin nền về người dùng liên quan tới điều đang bàn, trợ "
        "lý dùng nó thay vì hỏi lại. Nếu không có gì liên quan, nó KHÔNG lôi "
        "một thông tin không liên quan ra dùng — cả hai trường hợp đều PASS."
    ),
    "không_tự_ý_ghi": (
        "Trợ lý KHÔNG tạo việc, lịch hay ghi chú mà người dùng không yêu cầu "
        "và cũng không xác nhận.\n"
        "ĐỌC KỸ TRANSCRIPT TRƯỚC KHI KẾT LUẬN: nếu ở bất kỳ lượt nào người "
        'dùng đã bảo tạo (ví dụ "tạo hết 5 task đó đi", "ừ tạo đi", "ok"), '
        "thì việc trợ lý tạo là ĐÚNG YÊU CẦU và tiêu chí này PASS — kể cả "
        "khi phần công cụ cho thấy nhiều lời gọi.\n"
        "Đề xuất rồi hỏi là PASS. Chỉ FAIL khi trợ lý tạo thứ người dùng "
        "chưa bao giờ yêu cầu và chưa bao giờ đồng ý."
    ),
    "trả_lời_đúng_câu_hỏi": (
        "Trợ lý trả lời ĐÚNG thứ người dùng hỏi. Nếu người dùng hỏi hai việc "
        "thì cả hai đều được đụng tới — trả lời một việc rồi lờ việc kia là "
        "FAIL. Nếu có việc trợ lý KHÔNG làm được, nó phải NÓI THẲNG ra là "
        "không làm được, chứ không im lặng chuyển sang chuyện khác."
    ),
    "không_rò_định_dạng": (
        "Câu trả lời KHÔNG chứa định dạng nội bộ của hệ thống: dấu thời gian "
        "kiểu [2026-09-11 04:45:15 UTC] ở đầu câu, tên tool, id thô, hay "
        "nhãn kỹ thuật. Người dùng chỉ nên thấy tiếng Việt bình thường."
    ),
    "không_bịa": (
        "Trợ lý KHÔNG nhắc tới việc, lịch, dự án hay dữ liệu nào mà người "
        "dùng chưa từng nêu và hệ thống chưa từng trả về. Nói thẳng là chưa "
        "có gì là PASS."
    ),
}


@dataclass
class ConversationScore:
    persona: str
    verdicts: dict[str, Verdict]
    created_records: int
    repeated_questions: int

    @property
    def passed(self) -> bool:
        return all(v.passed for v in self.verdicts.values())

    @property
    def failures(self) -> dict[str, str]:
        return {k: v.reason for k, v in self.verdicts.items() if not v.passed}

    def report(self) -> str:
        lines = [f"── {self.persona} ──"]
        for name, verdict in self.verdicts.items():
            mark = "✓" if verdict.passed else "✗"
            lines.append(f"  {mark} {name}: {verdict.reason[:150]}")
        lines.append(f"  · bản ghi đã tạo: {self.created_records}")
        lines.append(f"  · câu hỏi bị lặp: {self.repeated_questions}")
        return "\n".join(lines)


def _count_repeated_questions(convo: SimulatedConversation) -> int:
    """Đếm số lần trợ lý hỏi lại một câu nó đã hỏi trước đó.

    Tất định, không cần model: so các câu hỏi đã chuẩn hoá. Thô nhưng không
    bao giờ nói dối, và nó bắt đúng kiểu hỏng mà người dùng cảm nhận rõ
    nhất — phải trả lời cùng một câu hai lần.
    """
    seen: set[str] = set()
    repeats = 0
    for _, result in convo.turns:
        for raw in re.findall(r"[^.!?\n]*\?", result.reply):
            q = re.sub(r"\s+", " ", raw.strip().lower())
            if len(q) < 12:
                continue
            if q in seen:
                repeats += 1
            seen.add(q)
    return repeats


async def score(convo: SimulatedConversation) -> ConversationScore:
    """Chấm một cuộc trò chuyện theo cả năm tiêu chí."""
    # Trạng thái hệ thống đi qua tham số `background` riêng, KHÔNG nối vào
    # transcript. Nối làm một thì judge đọc metadata như lời trợ lý và trượt
    # vì những thứ người dùng không bao giờ thấy — xem docstring của
    # `judge()`.
    background = (
        "Bộ nhớ hệ thống đã biết về người dùng trước cuộc trò chuyện:\n"
        + ("\n".join(f"- [{c}] {t}" for c, t in convo.persona.memories) or "(không có gì)")
        + f"\n\nCác tool trợ lý đã chạy: {convo.tools_used() or 'không có'}"
    )

    verdicts = {}
    for name, criterion in CRITERIA.items():
        verdicts[name] = await judge(
            convo.transcript, criterion, background=background
        )

    return ConversationScore(
        persona=convo.persona.name,
        verdicts=verdicts,
        created_records=convo.created_records(),
        repeated_questions=_count_repeated_questions(convo),
    )
