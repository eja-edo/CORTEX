"""WP8: dev/scenario.py end to end - no TODO left; the numbers it reports are the ones that matter."""
from dev.scenario import run_scenario


async def test_scenario_covers_send_memory_and_auto(app_client) -> None:
    lines: list[str] = []
    out = await run_scenario(lines.append)
    assert "TODO" not in "\n".join(lines)
    # [5] "Duyệt & gửi": staff message went out through the bridge with the HUMAN_AGENT tag
    assert out["approve_status"] == 200 and out["staff_outbox"] == ["sent"]
    assert [g.get("tag") for g in out["graph"]] == ["HUMAN_AGENT"]
    # [6] memory written by the model's facts; the next silence costs no token
    assert out["promised_date"] is not None and out["decision_maker"] == "vo_chong"
    assert out["llm_calls_after_promise"] == 0
    # [10] auto: one message sent by the system, one case falls back to a person
    assert out["auto"] == {"sent": ["sent"], "graph": 1, "fallbacks": 1, "manual_for": ["psid_3003"]}
    assert out["leaked"] == []
