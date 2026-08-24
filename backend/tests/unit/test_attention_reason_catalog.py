from app.models import AttentionLevel
from app.services.attention_levels import LEVEL_RANK
from app.services.attention_reason_catalog import (
    REASON_CATALOG,
    SUPERSEDES,
    base_level_for,
    superseded_by,
)


def test_known_reasons_return_their_registered_baseline():
    assert base_level_for("task.overdue") is AttentionLevel.RECOMMEND
    assert base_level_for("schedule.reminder.due") is AttentionLevel.INFORM


def test_unregistered_reason_falls_back_to_inform_not_silent_or_error():
    # Errs toward "shown once too often" over "silently dropped" — see
    # module docstring. Never SILENT: an unregistered reason isn't a
    # decision to stay quiet, it's a gap in the catalog.
    assert base_level_for("something.nobody.registered") is AttentionLevel.INFORM


# ---------------------------------------------------------------------------
# Supersession
# ---------------------------------------------------------------------------


def test_every_supersession_edge_names_registered_reasons():
    """A typo in SUPERSEDES would silently do nothing — `superseded_by`
    returns an empty set for an unknown key, so the weak notification would
    keep going out and no test would notice."""
    for stronger, weaker_set in SUPERSEDES.items():
        assert stronger in REASON_CATALOG, stronger
        for weaker in weaker_set:
            assert weaker in REASON_CATALOG, weaker


def test_supersession_never_runs_uphill():
    """A superseding reason must never be *quieter* than what it silences —
    that would let the Gate swallow an ASK and leave only an INFORM.

    Equal rank is allowed, and `task.blocked_cascade` over `task.overdue`
    is the case: both are RECOMMEND, but the cascade's text is a strict
    superset ("Trễ 3 ngày, còn 2 việc con chưa xong" contains "Trễ 3
    ngày"), so collapsing to it loses the user nothing. Direction for
    equal-rank pairs comes from SUPERSEDES declaring it, not from the
    levels — which is exactly why the no-cycles test below matters.
    """
    for stronger, weaker_set in SUPERSEDES.items():
        for weaker in weaker_set:
            assert LEVEL_RANK[base_level_for(stronger)] >= LEVEL_RANK[base_level_for(weaker)], (
                f"{stronger} is quieter than {weaker} it supersedes"
            )


def test_supersession_has_no_cycles():
    for stronger, weaker_set in SUPERSEDES.items():
        for weaker in weaker_set:
            assert stronger not in SUPERSEDES.get(weaker, frozenset())


def test_superseded_by_is_the_inverse_of_supersedes():
    assert superseded_by("task.overdue") == frozenset({"task.at_risk", "task.blocked_cascade"})
    assert superseded_by("task.blocked_cascade") == frozenset({"task.at_risk"})
    # The top of the chain and every unrelated reason stand alone.
    assert superseded_by("task.at_risk") == frozenset()
    assert superseded_by("task.stale") == frozenset()
    assert superseded_by("day.review") == frozenset()
