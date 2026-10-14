from datetime import UTC, date, datetime, timedelta

from cortex_leads.channels.policy import window_state
from cortex_leads.clock.schedule import compute_next_check_at

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)  # 10:00 in Ho Chi Minh
TZ = "Asia/Ho_Chi_Minh"


def test_not_open_returns_none() -> None:
    for state in ("won", "lost", "opted_out"):
        assert compute_next_check_at(NOW, None, None, state, TZ, NOW) is None


def test_future_promise_wins_at_0800_local() -> None:
    r = compute_next_check_at(NOW, None, date(2026, 10, 20), "open", TZ, NOW)
    assert r == datetime(2026, 10, 20, 1, 0, tzinfo=UTC)  # 08:00 +07


def test_promise_today_already_past_falls_back_to_silence() -> None:
    r = compute_next_check_at(NOW, None, date(2026, 10, 12), "open", TZ, NOW)
    assert r == NOW + timedelta(hours=24)


def test_customer_last_and_staff_last() -> None:
    staff = NOW + timedelta(hours=1)
    assert compute_next_check_at(NOW, None, None, "open", TZ, NOW) == NOW + timedelta(hours=24)
    assert compute_next_check_at(NOW, staff, None, "open", TZ, NOW) == staff + timedelta(hours=24)
    assert compute_next_check_at(None, NOW, None, "open", TZ, NOW) == NOW + timedelta(hours=24)


def test_custom_silent_after_and_no_messages() -> None:
    assert compute_next_check_at(NOW, None, None, "open", TZ, NOW, timedelta(hours=2)) == NOW + timedelta(hours=2)
    assert compute_next_check_at(None, None, None, "open", TZ, NOW) is None


def test_window_state() -> None:
    h = timedelta(hours=1)
    s = window_state("messenger", NOW - 23 * h, NOW)
    assert s == {"open": True, "basis": "free", "expires_at": NOW + h}
    s = window_state("messenger", NOW - 25 * h, NOW)
    assert s["open"] and s["basis"] == "human_agent"
    assert not window_state("messenger", NOW - 8 * 24 * h, NOW)["open"]
    assert window_state("zalo_oa", NOW - 47 * h, NOW)["open"]
    assert not window_state("zalo_oa", NOW - 49 * h, NOW)["open"]
    assert not window_state("web", NOW, NOW)["open"]
    assert not window_state("unknown", NOW, NOW)["open"]
    assert not window_state("messenger", None, NOW)["open"]


def test_zalo_unverified() -> None:
    from cortex_leads.channels.policy import CHANNEL_POLICIES
    assert CHANNEL_POLICIES["zalo_oa"].verified is False
