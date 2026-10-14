"""dev/scenario.py chạy được trong CI (không mạng, FakeProvider)."""
from dev.scenario import run_scenario


async def test_scenario_sim_runs(app_client) -> None:  # app_client => DB migrated + truncated
    lines: list[str] = []
    out = await run_scenario(lines.append)
    assert len(out["drafts"]) == 1 and out["approve_status"] == 200
    assert out["leaked"] == []  # supervisor numbers carry none of the customer's words
    assert any(line.startswith("[9]") for line in lines)
    assert out["state"] == "won" and out["twenty"]["accepted"] == 1
    assert out["sheet"][1] == ["duplicate"]  # same ma_don + status: idempotent
