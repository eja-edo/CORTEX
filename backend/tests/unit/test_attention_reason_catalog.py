from app.models import AttentionLevel
from app.services.attention_reason_catalog import base_level_for


def test_known_reasons_return_their_registered_baseline():
    assert base_level_for("task.overdue") is AttentionLevel.RECOMMEND
    assert base_level_for("schedule.reminder.due") is AttentionLevel.INFORM


def test_unregistered_reason_falls_back_to_inform_not_silent_or_error():
    # Errs toward "shown once too often" over "silently dropped" — see
    # module docstring. Never SILENT: an unregistered reason isn't a
    # decision to stay quiet, it's a gap in the catalog.
    assert base_level_for("something.nobody.registered") is AttentionLevel.INFORM
