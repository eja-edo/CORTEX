"""Model trả rỗng hoặc lửng thì hệ thống thử lại, không bắt người dùng gõ lại.

Đo trên sáu cuộc trò chuyện mô phỏng: model trả về rỗng **ba lần**, và cả ba
lần đều sau một câu người dùng gõ ngắn:

    "Tuần sau nộp báo cáo."          → rỗng → người dùng phải gõ lại
    "đặt lịch họp team 10h thứ 5"    → rỗng → người dùng phải gõ lại
    "Đúng. Đặt lịch 19h tối mai."    → rỗng → người dùng phải gõ lại

Lần hai thì được. Tức hệ thống đẩy việc sửa sang cho người dùng trong khi
chính nó thử lại là xong — gõ ngắn là cách người ta dùng app thật, không
phải lỗi cần họ khắc phục.

Cộng hai câu **lửng** trong cùng đợt, cả hai để người dùng treo:

    "Theo quy trình làm việc bạn đã thiết lập:"
    "Thứ Năm, ngày 17/09/2026, bạn có một sự kiện duy nhất:"
"""

import pytest

from app.ai.agents.agent_service import (
    MAX_EMPTY_REPLY_RETRIES,
    _reply_looks_incomplete,
)


class TestIncompleteDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "Theo quy trình làm việc bạn đã thiết lập:",
            "Thứ Năm, ngày 17/09/2026, bạn có một sự kiện duy nhất:",
            "Các bước còn lại —",
            "Gồm có,",
        ],
    )
    def test_detects_a_dangling_opener(self, text):
        assert _reply_looks_incomplete(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Đã xong.",
            "Đã tạo task Nộp báo cáo, hạn 18/09.",
            "Mình chưa tra được thời tiết.",
            "Bạn muốn đặt 19h hay 17h?",
        ],
    )
    def test_leaves_complete_replies_alone(self, text):
        """Câu ngắn vẫn có thể là câu đủ — không được bắt oan."""
        assert not _reply_looks_incomplete(text)

    @pytest.mark.parametrize("text", [None, "", "   "])
    def test_empty_is_not_incomplete(self, text):
        """Rỗng đi theo nhánh riêng; hàm này chỉ nói về câu bỏ dở."""
        assert not _reply_looks_incomplete(text)


class TestRetryPolicy:
    def test_retries_at_least_once(self):
        assert MAX_EMPTY_REPLY_RETRIES >= 1

    def test_does_not_retry_forever(self):
        """Model im hai lần liền thì vấn đề không còn là ngẫu nhiên.

        Mỗi lần thử lại tốn một vòng độ trễ mà người dùng phải chờ.
        """
        assert MAX_EMPTY_REPLY_RETRIES <= 2

    def test_retry_is_wired_before_the_apology(self):
        """Thứ tự quan trọng: thử lại TRƯỚC, xin lỗi là phương án cuối."""
        import inspect

        from app.ai.agents.agent_service import AgentService

        src = inspect.getsource(AgentService.handle)
        retry_at = src.index("empty_retries < MAX_EMPTY_REPLY_RETRIES")
        apology_at = src.index("user_messages.EMPTY_REPLY")
        assert retry_at < apology_at, "xin lỗi trước khi thử lại"

    def test_retry_covers_both_empty_and_incomplete(self):
        import inspect

        from app.ai.agents.agent_service import AgentService

        src = inspect.getsource(AgentService.handle)
        window = src[src.index("empty_retries < MAX_EMPTY_REPLY_RETRIES") - 200:]
        assert "_reply_looks_incomplete" in window


class TestRetrySwitchesModel:
    """Lần thử lại phải đổi model, không chỉ đổi prompt.

    Chuỗi giả thuyết đầy đủ, mỗi bước bị chính phép đo sau nó bác bỏ:

    1. *Gọi lại y nguyên sẽ khác.* Sai — rỗng tiếp 4/4.
    2. *Prompt dài là nguyên nhân.* Sai — vẫn rỗng 7/7 dù ngắn đi 10k ký tự.
    3. *`free_auto` là thủ phạm.* Sai — benchmark tự dựng, 6 lần/model, tất
       cả 0% im.
    4. *Im lặng tăng theo độ dài prompt, là đặc tính ổn định của model.*
       Tưởng đúng sau khi đọc lại 2.678 mẫu của router — im lặng tăng rõ
       theo độ dài trong dữ liệu ngày 11/9 (0.2% → 15.7%). Nhưng soát theo
       NGÀY thì sai: cả tháng 8 tới 10/9 gần như 0% ở mọi độ dài, kể cả
       10/9 với 455 lượt và có lượt tới 17.650 token. Hiện tượng chỉ tập
       trung trong khung 08:06–10:17 ngày 11/9 — đúng lúc benchmark chạy.
       Gọi lại 20 lần ngày 14/9 ở cùng model, cùng ~25k token (kịch bản đã
       cho 25.6% hôm đó): 0/20 rỗng. Cũng loại luôn giả thuyết "hết ngân
       sách token" — đổi `max_output_tokens` 500→16.000 không đổi kết quả,
       và `finish_reason` luôn là `stop`, chưa từng là `length`.

    Kết luận đứng vững nhất: một sự cố tạm thời phía backend trong vài giờ,
    không phải quy luật theo độ dài và không sửa được từ cấu hình phía
    chúng ta. Đổi model khi thử lại vẫn giữ vì rẻ và vô hại, không phải vì
    đã xác định được model nào "tin cậy hơn" lâu dài — mẫu quá nhiễu bởi
    sự cố đó để xếp hạng độ tin cậy dài hạn.
    """

    def _handle_source(self) -> str:
        import inspect

        from app.ai.agents.agent_service import AgentService

        return inspect.getsource(AgentService.handle)

    def test_retry_switches_to_the_fallback_model(self):
        src = self._handle_source()
        assert "preferred_model = EMPTY_REPLY_FALLBACK_MODEL" in src

    def test_fallback_differs_from_the_default(self):
        """Đổi sang chính model vừa im thì không đổi gì cả."""
        import os

        from app.ai.agents.agent_service import EMPTY_REPLY_FALLBACK_MODEL

        default = os.getenv("OPENAI_DEFAULT_MODEL", "free_auto")
        assert EMPTY_REPLY_FALLBACK_MODEL != default

    def test_fallback_is_not_the_model_once_picked_from_a_small_sample(self):
        """`kr/claude-haiku-4.5` từng được chọn từ một mẫu quá nhỏ để tin.

        Benchmark tự dựng (6 lần/model) chọn nó vì im 0/6. Dữ liệu router
        (2.678 mẫu) khi đó cho thấy nó im 16/141 (11.3%) ở prompt > 10k —
        nhưng soát theo ngày thì cả hai con số đều là nhiễu từ một sự cố
        tạm thời ngày 11/9, không phải đặc tính ổn định của bất kỳ model
        nào (xem docstring lớp này). Test chỉ còn giữ được khẳng định
        rẻ và chắc: fallback phải khác model chính, không phải "model X
        đáng tin hơn model Y" — điều chưa ai đo được đáng tin cậy.
        """
        from app.ai.agents.agent_service import EMPTY_REPLY_FALLBACK_MODEL

        assert EMPTY_REPLY_FALLBACK_MODEL == "gemini/gemini-2.5-flash"

    def test_both_empty_branches_switch_model(self):
        """Hai nhánh "model không cho gì" phải xử lý giống nhau."""
        src = self._handle_source()
        assert src.count("preferred_model = EMPTY_REPLY_FALLBACK_MODEL") >= 2


class TestRetryIsShorterNotIdentical:
    """Lần thử lại phải **ngắn hơn**, không phải lặp lại lời gọi đã hỏng.

    Bản đầu gọi lại với đúng input cũ và thất bại 4/4 lần:

        thử lại lần 1: prompt_tokens=18850, completion_tokens=0
        thử lại lần 1: prompt_tokens=18147, completion_tokens=0

    Cùng input dài thì cùng kết quả rỗng — model không ngẫu nhiên ở chỗ này.
    Mọi lần rỗng đo được đều ở 18k+ token đầu vào, nên lần thử lại phải bỏ
    bớt, và khối skill là phần lớn nhất bỏ được mà không mất dữ kiện nào về
    người dùng.
    """

    def _handle_source(self) -> str:
        import inspect

        from app.ai.agents.agent_service import AgentService

        return inspect.getsource(AgentService.handle)

    def test_retry_swaps_in_a_slimmer_prompt(self):
        src = self._handle_source()
        assert "system_instruction=slim_prompt" in src

    def test_slim_prompt_keeps_the_user_context(self):
        """Bỏ skill thì được; bỏ ngữ cảnh về người dùng thì không.

        Khối ngữ cảnh mang bộ nhớ, quy trình và mức can thiệp — bỏ nó là
        biến lần thử lại thành một agent không biết gì về người đang nói.
        """
        src = self._handle_source()
        line = next(l for l in src.splitlines() if "slim_prompt =" in l)
        assert "context_string" in line

    def test_slim_prompt_is_built_before_it_is_used(self):
        src = self._handle_source()
        assert src.index("slim_prompt =") < src.index("system_instruction=slim_prompt")
