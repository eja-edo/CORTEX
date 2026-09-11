"""Vòng tự đánh giá: người dùng ảo trò chuyện thật với agent thật.

Khác phần còn lại của `tests/eval/`: ở đây không có câu hỏi viết sẵn. Một
LLM đóng vai người dùng, phản ứng với đúng những gì agent trả lời, qua nhiều
lượt — nên nó bắt được các kiểu hỏng chỉ hiện ra khi hội thoại dài: phải
giải thích lại điều đã nói, bị hỏi lại cùng một câu, agent tự ý sửa yêu cầu.

Chạy:
    pytest -m live_llm tests/eval/test_simulated_conversations.py -v -s
    EVAL_ROUND=round11 pytest -m live_llm ...          # đặt tên vòng để so
    EVAL_REPEAT=3 pytest -m live_llm ...              # mỗi persona 3 lần

**Đọc kết quả cho đúng.** Tổng điểm của một lần chạy KHÔNG phải thước đo
tiến bộ: đo được, hai vòng liền nhau khác nhau đúng một thay đổi nhỏ cho ra
74% rồi 38%. Phương sai của model lớn hơn hiệu ứng của phần lớn thay đổi.
Hai thứ đáng đọc là (1) phần **MỚI HỎNG** trong bản so sánh — một tiêu chí
vừa chuyển từ đạt sang trượt là tín hiệu thật, và (2) danh sách **câu đáng
đọc**, vì việc đọc tận nơi mới là thứ tìm ra phần lớn lỗi trong bộ này.

Đặt `EVAL_REPEAT=3` khi cần kết luận về một thay đổi: một tiêu chí trượt cả
ba lần là hỏng, trượt một trong ba là phương sai.
"""

import os

import pytest

from tests.eval.personas import PERSONAS
from tests.eval.report import RoundReport, compare, load_previous
from tests.eval.rubric import score
from tests.eval.simulator import simulate

pytestmark = pytest.mark.asyncio

ROUND_NAME = os.getenv("EVAL_ROUND", "latest")
REPEAT = int(os.getenv("EVAL_REPEAT", "1"))

# Một báo cáo dùng chung cho cả lần chạy, ghi xuống ở test cuối.
_report = RoundReport(round_name=ROUND_NAME)


@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.name)
async def test_simulated_conversation(persona, memory_seeder):
    """Một cuộc trò chuyện mô phỏng, chấm theo thang trong `rubric.py`."""
    failures: list[str] = []

    for attempt in range(REPEAT):
        if persona.memories:
            await memory_seeder(persona.memories)

        convo = await simulate(persona, max_turns=5)
        assert convo.turns, "người dùng ảo không nói được câu nào"

        result = await score(convo)
        label = persona.name if REPEAT == 1 else f"{persona.name}#{attempt + 1}"
        result.persona = label
        _report.add(result, convo)

        print(f"\n{'=' * 70}")
        print(convo.transcript)
        print(f"{'-' * 70}")
        print(result.report())
        print(f"{'=' * 70}")

        if not result.passed:
            failures.append(f"lần {attempt + 1}: {result.failures}")

    # Với REPEAT > 1, trượt **mọi** lần mới là hỏng; trượt một vài lần là
    # phương sai và được ghi lại chứ không làm đỏ.
    if REPEAT > 1 and len(failures) < REPEAT:
        if failures:
            print(f"\n[{persona.name}] trượt {len(failures)}/{REPEAT} lần — phương sai, không phải hỏng")
        return

    assert not failures, f"{persona.name}: " + " | ".join(failures)


async def test_zz_write_report():
    """Ghi báo cáo và in phần so với vòng trước.

    Tên bắt đầu bằng `zz` để nó chạy cuối theo thứ tự khai báo — bộ này luôn
    chạy với `-p no:randomly` (xem README), nên không cần plugin sắp thứ tự.
    Là một test chứ không phải fixture teardown, để bản so sánh vẫn in ra
    khi các persona đỏ — đó chính là lúc nó có giá trị nhất.
    """
    if not _report.verdicts:
        pytest.skip("chưa có persona nào chạy")

    path = _report.save()
    previous = load_previous(exclude=_report.round_name)

    print(f"\n{'#' * 70}")
    print(compare(_report, previous))

    if _report.suspicious:
        print(f"\n── câu đáng đọc ({len(_report.suspicious)}) ──")
        for item in _report.suspicious[:25]:
            print(f"  [{item['persona']}] {item['reason']}")
            print(f"      {item['text'][:130]}")
    print(f"\nbáo cáo: {path}")
    print(f"{'#' * 70}")
