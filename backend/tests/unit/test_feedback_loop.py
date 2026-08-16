from app.config import settings
from app.models import AttentionLevel
from app.services.feedback_loop import apply_downgrade


def test_zero_dismissals_never_changes_the_level():
    for level in AttentionLevel:
        assert apply_downgrade(level, 0) is level


def test_one_threshold_worth_of_dismissals_drops_one_rung():
    threshold = settings.FEEDBACK_LOOP_DISMISS_THRESHOLD
    assert apply_downgrade(AttentionLevel.RECOMMEND, threshold) is AttentionLevel.INFORM


def test_below_threshold_does_not_yet_downgrade():
    threshold = settings.FEEDBACK_LOOP_DISMISS_THRESHOLD
    assert apply_downgrade(AttentionLevel.RECOMMEND, threshold - 1) is AttentionLevel.RECOMMEND


def test_enough_dismissals_floor_at_silent_not_negative_index():
    threshold = settings.FEEDBACK_LOOP_DISMISS_THRESHOLD
    assert apply_downgrade(AttentionLevel.RECOMMEND, threshold * 100) is AttentionLevel.SILENT


def test_downgrade_never_raises_a_level():
    threshold = settings.FEEDBACK_LOOP_DISMISS_THRESHOLD
    # SILENT has nowhere lower to go.
    assert apply_downgrade(AttentionLevel.SILENT, threshold * 5) is AttentionLevel.SILENT


def test_ask_downgrades_two_full_thresholds_to_recommend_then_inform():
    threshold = settings.FEEDBACK_LOOP_DISMISS_THRESHOLD
    assert apply_downgrade(AttentionLevel.ASK, threshold) is AttentionLevel.RECOMMEND
    assert apply_downgrade(AttentionLevel.ASK, threshold * 2) is AttentionLevel.INFORM
