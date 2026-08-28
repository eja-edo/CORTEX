from datetime import date, datetime, time, timedelta
from uuid import uuid4

import pytest

from app.models import Task, TaskPriority
from app.services.risk_detection import compute_risk, project_risk


def test_not_yet_overdue_scores_zero_regardless_of_priority():
    assert compute_risk(TaskPriority.URGENT, overdue_days=0, open_subtask_count=5) == 0.0
    assert compute_risk(TaskPriority.URGENT, overdue_days=-1, open_subtask_count=5) == 0.0


def test_childless_overdue_task_scores_its_priority_weight_times_days():
    # priority weight 3 (HIGH) * 2 days overdue * (1 + 0 subtasks)
    assert compute_risk(TaskPriority.HIGH, overdue_days=2, open_subtask_count=0) == 6.0


def test_unset_priority_still_carries_baseline_risk():
    # weight 1 (never zero) * 3 days * 1
    assert compute_risk(None, overdue_days=3, open_subtask_count=0) == 3.0


def test_open_subtasks_amplify_rather_than_replace_the_base_score():
    base = compute_risk(TaskPriority.MEDIUM, overdue_days=4, open_subtask_count=0)
    with_cascade = compute_risk(TaskPriority.MEDIUM, overdue_days=4, open_subtask_count=3)

    assert with_cascade == base * 4  # (1 + 3)
    assert with_cascade > base


def test_higher_priority_always_outranks_lower_priority_at_equal_lateness():
    urgent = compute_risk(TaskPriority.URGENT, overdue_days=5, open_subtask_count=1)
    low = compute_risk(TaskPriority.LOW, overdue_days=5, open_subtask_count=1)
    assert urgent > low


def test_negative_subtask_count_is_clamped_not_subtracted():
    # A defensive case — nothing in the codebase produces a negative count,
    # but the formula must not invert into a discount if one ever leaks in.
    assert compute_risk(TaskPriority.LOW, overdue_days=2, open_subtask_count=-4) == compute_risk(
        TaskPriority.LOW, overdue_days=2, open_subtask_count=0
    )


# ============================================================================
# project_risk — DESIGN 7.1
# ============================================================================


class TestProjectRisk:
    """Rủi ro ở phạm vi dự án, dùng lại đúng công thức của `compute_risk`."""

    TODAY = date(2026, 8, 25)

    def _task(self, *, priority=None, overdue_days=0, task_id=None):
        return Task(
            id=task_id,
            title="t",
            priority=priority,
            due_date=datetime.combine(self.TODAY - timedelta(days=overdue_days), time(9, 0)),
        )

    def test_no_deadline_is_zero_which_is_what_protects_loose_tasks(self):
        """Bất biến chịu lực, không phải trường hợp biên.

        Dự án cá nhân không bao giờ có deadline (DESIGN 3.4). Nhánh này là
        thứ giữ cho màn Hôm nay của người chưa có dự án nào xếp đúng như
        trước khi có tầng một.
        """
        task = self._task(priority=TaskPriority.URGENT, overdue_days=10)
        assert project_risk(None, [task], today=self.TODAY) == 0.0

    def test_a_project_with_nothing_overdue_is_not_at_risk(self):
        """Deadline gần **tự nó** không phải rủi ro.

        Nếu không có nhánh này thì mọi dự án sắp tới hạn đều nhảy lên đầu
        màn Hôm nay kể cả khi mọi việc đều đúng tiến độ — đúng kiểu tạo ra
        khẩn cấp giả mà P5 cấm.
        """
        on_time = Task(
            title="t",
            priority=TaskPriority.URGENT,
            due_date=datetime.combine(self.TODAY + timedelta(days=3), time(9, 0)),
        )
        deadline = datetime.combine(self.TODAY + timedelta(days=1), time(9, 0))
        assert project_risk(deadline, [on_time], today=self.TODAY) == 0.0

    def test_an_empty_project_scores_zero(self):
        deadline = datetime.combine(self.TODAY + timedelta(days=1), time(9, 0))
        assert project_risk(deadline, [], today=self.TODAY) == 0.0

    def test_the_worst_task_sets_the_floor(self):
        """`max`, không phải `sum`: một dự án 40 việc trễ nhẹ không được
        vượt mặt một dự án có một việc trễ nặng chỉ vì nó dài hơn."""
        mild = self._task(priority=TaskPriority.LOW, overdue_days=1)
        severe = self._task(priority=TaskPriority.URGENT, overdue_days=5)
        far = datetime.combine(self.TODAY + timedelta(days=365), time(9, 0))

        both = project_risk(far, [mild, severe], today=self.TODAY)
        only_severe = project_risk(far, [severe], today=self.TODAY)
        assert both == pytest.approx(only_severe)

    def test_the_same_slippage_costs_more_as_the_deadline_closes(self):
        """Đây là điều một điểm số cấp task không nói được, và là lý do
        tầng một tồn tại."""
        task = self._task(priority=TaskPriority.HIGH, overdue_days=3)
        far = project_risk(
            datetime.combine(self.TODAY + timedelta(days=365), time(9, 0)),
            [task],
            today=self.TODAY,
        )
        near = project_risk(
            datetime.combine(self.TODAY, time(9, 0)), [task], today=self.TODAY
        )
        assert near > far
        # Biên của công thức: 1.0 khi còn xa, 3.0 khi tới hạn.
        base = compute_risk(TaskPriority.HIGH, 3)
        assert near == pytest.approx(base * 3.0)
        assert far == pytest.approx(base * 1.0, rel=0.01)

    def test_a_deadline_already_past_does_not_go_negative(self):
        """`days_left` bị chặn ở 0 — quá hạn thì urgency dừng ở mức trần,
        không lật dấu và đẩy dự án xuống đáy danh sách."""
        task = self._task(priority=TaskPriority.HIGH, overdue_days=3)
        overdue_deadline = datetime.combine(self.TODAY - timedelta(days=30), time(9, 0))
        base = compute_risk(TaskPriority.HIGH, 3)
        assert project_risk(overdue_deadline, [task], today=self.TODAY) == pytest.approx(
            base * 3.0
        )

    def test_open_subtasks_compound_through_the_reused_formula(self):
        task_id = uuid4()
        task = self._task(priority=TaskPriority.HIGH, overdue_days=2, task_id=task_id)
        far = datetime.combine(self.TODAY + timedelta(days=365), time(9, 0))

        without = project_risk(far, [task], today=self.TODAY)
        with_subtasks = project_risk(far, [task], {task_id: 3}, today=self.TODAY)
        assert with_subtasks == pytest.approx(without * 4)
