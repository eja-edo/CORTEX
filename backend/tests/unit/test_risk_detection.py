from app.models import TaskPriority
from app.services.risk_detection import compute_risk


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
