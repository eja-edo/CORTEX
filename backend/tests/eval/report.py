"""Lưu kết quả mỗi vòng và so vòng này với vòng trước.

Vòng lặp tự đánh giá có một lỗ hổng lớn hơn mọi lỗi nó tìm ra: **nó không
đo được tiến bộ.** Đo thật, hai vòng liền nhau khác nhau đúng một thay đổi
nhỏ:

    vòng 8   40/54 tiêu chí (74%)
    vòng 9   17/45 tiêu chí (38%)

Thay đổi giữa hai vòng không thể gây ra 36 điểm phần trăm. Đó là phương sai
của model, và nó lớn hơn hiệu ứng của phần lớn thay đổi ta muốn đo. Một
vòng lặp không phân biệt được "đã cải thiện" với "lần này may" thì không
dùng để cải thiện được gì.

Ba thứ module này thêm vào:

* **Lưu có cấu trúc.** Mỗi vòng thành một file JSON: verdict từng tiêu chí,
  transcript, tool đã gọi, số bản ghi tạo. Trước đây mọi kết luận đến từ
  `grep` một file log rồi biến mất.
* **So với vòng trước.** In ra đúng hai thứ đáng hành động: tiêu chí **mới
  hỏng** (hồi quy) và tiêu chí **mới đạt** (thứ vừa sửa được). Tổng điểm
  lên hay xuống là thông tin kém hơn hẳn.
* **Trích câu đáng đọc.** Việc đọc transcript tìm ra phần lớn lỗi trong
  session này, nhưng đọc 50 lượt mỗi vòng thì không bền. Bộ lọc dưới đây
  chỉ ra những câu *khả nghi* — lửng, có thuật ngữ nội bộ, lặp lại câu hỏi
  — để việc đọc nhắm vào chỗ có khả năng có vấn đề. Nó **không thay** việc
  đọc: nó chỉ sắp xếp thứ tự đọc.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

REPORT_DIR = Path("tests/eval/reports")

# Thuật ngữ người dùng không nên thấy — cùng danh sách mà
# `tests/unit/test_user_messages.py` canh cho các câu lỗi, áp ở đây cho
# **mọi** câu trả lời.
_JARGON = (
    "mô hình", "model", "api", "token", "context", "endpoint", "provider",
    "server", "backend", "exception", "null", "timeout", "tool ",
    "create_task", "create_schedule", "procedure_id", "uuid",
)


@dataclass
class Suspicious:
    """Một câu đáng đọc, kèm lý do."""

    persona: str
    reason: str
    text: str


@dataclass
class RoundReport:
    round_name: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    # persona -> {tiêu chí -> (passed, reason)}
    verdicts: dict[str, dict[str, list]] = field(default_factory=dict)
    created_records: dict[str, int] = field(default_factory=dict)
    transcripts: dict[str, str] = field(default_factory=dict)
    suspicious: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.verdicts.values())

    @property
    def passed(self) -> int:
        return sum(1 for v in self.verdicts.values() for ok, _ in v.values() if ok)

    def add(self, score, convo) -> None:
        self.verdicts[score.persona] = {
            name: [verdict.passed, verdict.reason[:200]]
            for name, verdict in score.verdicts.items()
        }
        self.created_records[score.persona] = score.created_records
        self.transcripts[score.persona] = convo.transcript
        self.suspicious.extend(
            asdict(s) for s in find_suspicious(score.persona, convo)
        )

    def save(self) -> Path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"{self.round_name}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2))
        return path


def find_suspicious(persona: str, convo) -> list[Suspicious]:
    """Những câu trả lời đáng đọc trước, và vì sao.

    Cố ý **thà báo thừa hơn bỏ sót**: mục đích là sắp xếp thứ tự đọc, nên
    một cảnh báo sai chỉ tốn vài giây đọc, còn một câu bị bỏ sót thì không
    ai nhìn thấy nó nữa.
    """
    found: list[Suspicious] = []
    seen_questions: set[str] = set()

    for _, result in convo.turns:
        reply = (result.reply or "").strip()
        if not reply:
            found.append(Suspicious(persona, "câu trả lời rỗng", "(rỗng)"))
            continue

        if reply.endswith((":", "：", "-", "—", ",")):
            found.append(Suspicious(persona, "câu lửng — mở danh sách rồi dừng", reply[-90:]))

        low = reply.lower()
        hits = [w for w in _JARGON if w in low]
        if hits:
            found.append(
                Suspicious(persona, f"thuật ngữ nội bộ: {', '.join(hits[:3])}", reply[:140])
            )

        for raw in re.findall(r"[^.!?\n]*\?", reply):
            q = re.sub(r"\s+", " ", raw.strip().lower())
            if len(q) < 12:
                continue
            if q in seen_questions:
                found.append(Suspicious(persona, "hỏi lại đúng câu đã hỏi", q[:120]))
            seen_questions.add(q)

        # Ngày tháng cụ thể trong câu trả lời mà người dùng không nêu —
        # nguồn "bịa ngày" đã thấy nhiều lần.
        for date in re.findall(r"\d{1,2}/\d{1,2}/\d{4}", reply):
            if date not in convo.transcript.split("CORTEX:")[0]:
                found.append(Suspicious(persona, f"ngày cụ thể {date} — kiểm xem có bịa", reply[:140]))
                break

    return found


def load_previous(exclude: str) -> RoundReport | None:
    """Vòng gần nhất trước vòng `exclude`, để so sánh."""
    if not REPORT_DIR.exists():
        return None
    files = sorted(
        (f for f in REPORT_DIR.glob("*.json") if f.stem != exclude),
        key=lambda f: f.stat().st_mtime,
    )
    if not files:
        return None
    data = json.loads(files[-1].read_text())
    report = RoundReport(round_name=data["round_name"])
    report.__dict__.update(data)
    return report


def compare(current: RoundReport, previous: RoundReport | None) -> str:
    """Hai thứ đáng hành động: mới hỏng, và mới đạt.

    Tổng điểm cố ý không phải kết luận — phương sai giữa hai vòng lớn hơn
    hiệu ứng của phần lớn thay đổi, nên "74% → 38%" nói ít hơn hẳn so với
    "tiêu chí X vừa hỏng ở hai persona".
    """
    lines = [
        f"── {current.round_name}: {current.passed}/{current.total} tiêu chí ──"
    ]
    if previous is None:
        lines.append("  (chưa có vòng trước để so)")
        return "\n".join(lines)

    lines.append(f"  vòng trước ({previous.round_name}): {previous.passed}/{previous.total}")

    broke, fixed = [], []
    for persona, criteria in current.verdicts.items():
        before = previous.verdicts.get(persona, {})
        for name, (ok, reason) in criteria.items():
            was = before.get(name)
            if was is None:
                continue
            if was[0] and not ok:
                broke.append(f"{persona}/{name}: {reason[:100]}")
            elif not was[0] and ok:
                fixed.append(f"{persona}/{name}")

    if broke:
        lines.append(f"  ✗ MỚI HỎNG ({len(broke)}):")
        lines += [f"      {b}" for b in broke]
    if fixed:
        lines.append(f"  ✓ mới đạt ({len(fixed)}): {', '.join(fixed)}")
    if not broke and not fixed:
        lines.append("  (không tiêu chí nào đổi trạng thái)")
    return "\n".join(lines)
