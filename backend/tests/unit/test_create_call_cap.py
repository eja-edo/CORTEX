"""Trần cho các tool tạo dữ liệu.

Lý do là một mẫu lỗi đo được: model gateway hiện tại, khi gặp tình huống mơ
hồ, rơi vào một mẫu quen từ dữ liệu huấn luyện và tạo hàng loạt việc
"Create file a.txt with content 'a'". Không chuỗi nào trong đó tồn tại ở
prompt, ở DB, hay ở kết quả tool nào — đã kiểm tasks, notes, conversations,
memories và projects, tất cả rỗng.

Phân bố số lời gọi `create_task` trong một lượt, đo trên 14 kịch bản eval:

    lượt lành   0 lời gọi
    lượt bịa    4 và 6 lời gọi

Không lượt nào nằm giữa, nên ngưỡng 3 tách đúng hai nhóm — và vẫn để lọt ca
hợp lệ thường gặp nhất: một quy trình ba bước được xác nhận thì tạo ba việc.
"""

import pytest

from app.ai.agents.tool_execution_service import (
    CREATE_TOOLS,
    MAX_CREATE_CALLS_PER_REQUEST,
)


class TestWhatTheCapCovers:
    def test_cap_leaves_room_for_a_three_step_routine(self):
        """Ca hợp lệ hay gặp nhất không được chạm trần.

        Quy trình remote có ba bước; người dùng xác nhận thì agent tạo ba
        việc. Một trần ở 2 sẽ chặn đúng tính năng vừa xây xong.
        """
        assert MAX_CREATE_CALLS_PER_REQUEST >= 3

    def test_cap_is_below_the_observed_hallucination_bursts(self):
        """Hai lượt bịa đo được dùng 4 và 6 lời gọi."""
        assert MAX_CREATE_CALLS_PER_REQUEST < 4

    def test_create_tools_are_the_ones_that_invent_records(self):
        assert CREATE_TOOLS == {"create_task", "create_schedule", "create_note"}

    @pytest.mark.parametrize("tool", ["update_note", "update_schedule", "move_task"])
    def test_update_tools_are_not_capped(self, tool):
        """Sửa và xoá nhắm vào một hàng người dùng đã biết.

        Chúng không có kiểu hỏng "bịa ra N thứ để lấp chỗ trống", nên đưa
        vào trần chỉ làm agent kẹt giữa một thao tác sửa hợp lệ.
        """
        assert tool not in CREATE_TOOLS

    def test_counter_is_not_the_per_turn_dict(self):
        """Bộ đếm phải sống qua cả request, không reset mỗi turn.

        Bản đầu của trần này dùng `tool_call_counts`, và dict đó bị xoá sau
        mỗi turn khi `AGENT_TOOL_CALL_COUNT_SCOPE == "turn"` — mặc định.
        Hệ quả đo được: trần **chưa bao giờ chạm**, kể cả ở lượt model gọi
        sáu lần. Nó gọi ba lần ở turn 1 (thiếu `title`, validation loại cả
        ba) rồi ba lần nữa ở turn 2; không turn nào vượt ba.
        """
        import inspect

        from app.ai.agents.tool_execution_service import ToolExecutionService

        src = inspect.getsource(ToolExecutionService.execute_tools_pass)
        assert "self._create_calls_this_request" in src, (
            "bộ đếm lại dựa vào dict per-turn — trần sẽ không bao giờ chạm"
        )
        assert "tool_call_counts.get(_CREATED" not in src

    def test_counter_starts_at_zero_per_service(self):
        """`AgentService` dựng service này một lần mỗi request."""
        import inspect

        from app.ai.agents.tool_execution_service import ToolExecutionService

        assert "_create_calls_this_request = 0" in inspect.getsource(
            ToolExecutionService.__init__
        )


class TestCountingIsShared:
    """Đếm gộp mọi tool tạo, không đếm riêng từng cái.

    Ba việc cộng ba lịch cộng ba ghi chú trong một lượt cũng là tạo hàng
    loạt, dù không tool nào vượt trần của riêng nó.
    """

    def test_one_shared_counter_not_one_per_tool(self):
        import inspect

        from app.ai.agents.tool_execution_service import ToolExecutionService

        src = inspect.getsource(ToolExecutionService.execute_tools_pass)
        # Một bộ đếm duy nhất cho cả nhóm, không phải một bộ đếm mỗi tool.
        assert src.count("self._create_calls_this_request") >= 2
        assert "tool_name in CREATE_TOOLS" in src

    def test_every_call_counts_not_only_successful_ones(self):
        """Đếm cả lời gọi bị validation loại, và đó là điểm quyết định.

        Nếu chỉ đếm bản ghi tạo thành công, trần vô dụng đúng ở ca nó sinh
        ra để chặn: ca đo được tạo **ba** bản ghi — bằng y ca hợp lệ (một
        quy trình ba bước được người dùng xác nhận). Đếm mọi lời gọi thì ba
        lời gọi lỗi ở turn 1 đã dùng hết trần, và turn 2 bị chặn.
        """
        import inspect

        from app.ai.agents.tool_execution_service import ToolExecutionService

        src = inspect.getsource(ToolExecutionService.execute_tools_pass)
        tail = src[src.index("tool_name in CREATE_TOOLS"):]
        # Bộ đếm tăng ngay tại chỗ kiểm, trước khi tool chạy — không phải
        # sau khi biết kết quả.
        assert tail.index("self._create_calls_this_request = created + 1") < tail.index(
            "execution_list.append"
        )


class TestRefusalIsInformative:
    """Lời gọi bị từ chối phải nói cho agent biết làm gì thay vì chỉ "không".

    Một lỗi trần câm lặng sẽ khiến agent thử lại cùng thứ đó, hoặc im luôn
    giữa câu — cả hai đều tệ hơn một câu hướng dẫn.
    """

    def _refusal_source(self) -> str:
        import inspect

        from app.ai.agents.tool_execution_service import ToolExecutionService

        return inspect.getsource(ToolExecutionService.execute_tools_pass)

    def test_refusal_tells_the_agent_to_list_and_ask(self):
        src = self._refusal_source()
        assert "LIỆT KÊ" in src
        assert "hỏi họ xác nhận" in src

    def test_refusal_names_the_hallucination_case(self):
        """Nói thẳng ca đang được chặn, vì đó là ca agent đang mắc."""
        assert "danh sách" in self._refusal_source()

    def test_refusal_does_not_break_the_whole_turn(self):
        """Từ chối một lời gọi, không cắt cả lượt.

        `MAX_SAME_TOOL_CALLS` cắt cả lượt và trả một câu xin lỗi chung —
        đúng cho một vòng lặp tool chạy dại, sai ở đây: agent vẫn phải trả
        lời người dùng, và kết quả từ chối là chỗ nó đọc được vì sao.
        """
        src = self._refusal_source()
        assert "refused.append" in src
        assert "continue" in src
