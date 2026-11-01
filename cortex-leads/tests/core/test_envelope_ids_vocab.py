from uuid import uuid4

from cortex_leads.core.context import (
    CustomerPrincipal,
    RunContext,
    Scope,
    StaffPrincipal,
    SystemPrincipal,
)
from cortex_leads.core.envelope import BlockedCode, ToolResult, Violation
from cortex_leads.core.ids import new_connector_id, uuid7
from cortex_leads.core.vocabulary import OUTPUT_KINDS


def test_tool_result_serializes() -> None:
    aid = uuid4()
    r = ToolResult(status="blocked", violations=[Violation(code=BlockedCode.OPTED_OUT, span="x")],
                   action_id=aid)
    d = r.model_dump(mode="json")
    assert d["status"] == "blocked"
    assert d["violations"] == [{"code": "OPTED_OUT", "span": "x", "detail": None}]
    assert d["action_id"] == str(aid) and d["replayed"] is False and d["error"] is None
    assert ToolResult.model_validate(d) == r


def test_output_kinds_send_to_customer_is_the_only_sending_kind() -> None:
    # DESIGN A9 (WP8): valid only for a skill whose send_policy allows it (loader lint)
    assert OUTPUT_KINDS == {"draft_for_staff", "send_to_customer", "staff_task", "owner_digest", "lesson_recap", "grade_proposal", "assignment_draft", "none"}  # WP31/33: these go to a teacher, never to a customer
    assert [k for k in OUTPUT_KINDS if any(w in k for w in ("send", "customer", "reply"))] == ["send_to_customer"]


def test_uuid7_is_v7_and_ordered() -> None:
    a, b = uuid7(), uuid7()
    assert a.version == 7 and a.variant == "specified in RFC 4122"
    assert str(a)[:8] <= str(b)[:8]


def test_connector_id_format() -> None:
    cid = new_connector_id()
    assert cid.startswith("conn_") and cid != new_connector_id()


def test_actor_strings() -> None:
    base = dict(run_id=uuid4(), tenant_id=uuid4(), sandbox_id=uuid4(), profile="p",
                profile_version=2, scope=Scope())
    assert RunContext(principal=CustomerPrincipal(uuid4()), **base).actor == "ai:p@2"
    assert RunContext(principal=StaffPrincipal("s1"), **base).actor == "staff:s1"
    assert RunContext(principal=SystemPrincipal("sweep"), **base).actor == "system:sweep"
