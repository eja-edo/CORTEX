import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from cortex_leads.db import models as m
from cortex_leads.db.session import (
    list_active_tenants,
    supervisor_session,
    system_session,
    tenant_session,
)


async def _two_tenants(tenant_factory, sandbox_factory, connector_factory, conversation_factory,
                       message_factory):
    out = []
    for name in ("A", "B"):
        t = await tenant_factory(name)
        sb = await sandbox_factory(t)
        cn = await connector_factory(sb)
        cv = await conversation_factory(cn)
        await message_factory(cv, f"secret of {name}")
        out.append((t, sb, cn, cv))
    return out


async def test_rls_blocks_cross_tenant_reads(tenant_factory, sandbox_factory, connector_factory,
                                             conversation_factory, message_factory) -> None:
    (a, *_), (b, *_) = await _two_tenants(tenant_factory, sandbox_factory, connector_factory,
                                          conversation_factory, message_factory)
    async with tenant_session(a.id) as s:
        texts = (await s.execute(select(m.Message.text))).scalars().all()
        assert texts == ["secret of A"]
    async with tenant_session(b.id) as s:
        assert (await s.execute(select(m.Message.text))).scalars().all() == ["secret of B"]


async def test_rls_blocks_cross_tenant_writes(tenant_factory, sandbox_factory, connector_factory,
                                              conversation_factory, message_factory) -> None:
    (a, _, _, cv_a), (b, *_) = await _two_tenants(
        tenant_factory, sandbox_factory, connector_factory, conversation_factory, message_factory)
    async with tenant_session(b.id) as s:
        # tenant B cannot update A's rows ...
        res = await s.execute(text("update conversation set state='lost' where id=:i"),
                              {"i": cv_a.id})
        assert res.rowcount == 0
    with pytest.raises(DBAPIError):  # ... nor insert rows labelled as A (WITH CHECK)
        async with tenant_session(b.id) as s:
            s.add(m.DecisionLog(tenant_id=a.id, decision="x"))


async def test_missing_tenant_setting_reads_nothing(tenant_factory, sandbox_factory,
                                                    connector_factory, conversation_factory,
                                                    message_factory) -> None:
    await _two_tenants(tenant_factory, sandbox_factory, connector_factory, conversation_factory,
                       message_factory)
    async with system_session() as s:  # no app.tenant_id set
        for table in (m.Message, m.Conversation, m.Sandbox, m.Contact):
            assert (await s.execute(select(table.id))).all() == []
        assert len(await list_active_tenants(s)) == 2  # tenant has no RLS


async def test_app_role_is_not_owner_and_rls_forced(owner_engine) -> None:
    async with owner_engine.connect() as c:
        rows = (await c.execute(text(
            "select relname, relrowsecurity, relforcerowsecurity from pg_class "
            "where relname in ('message','draft','trigger_run','sandbox')"))).all()
        assert len(rows) == 4 and all(r[1] and r[2] for r in rows)
        assert not (await c.execute(text(
            "select rolsuper or rolbypassrls from pg_roles where rolname='cl_app'"))).scalar()


async def test_supervisor_sees_only_metadata_of_own_tenant(
        tenant_factory, sandbox_factory, connector_factory, conversation_factory, message_factory,
        seed) -> None:
    (a, sb_a, *_), (b, sb_b, *_) = await _two_tenants(
        tenant_factory, sandbox_factory, connector_factory, conversation_factory, message_factory)
    for t, sb in ((a, sb_a), (b, sb_b)):
        await seed(m.TriggerRun(tenant_id=t.id, sandbox_id=sb.id, skill_name="s", skill_version=1,
                                profile="p", profile_version=1, event_type="conversation.silent",
                                status="ok", act="draft", reason_code="soc_gia"))
    async with supervisor_session(a.id) as s:
        rows = (await s.execute(text("select * from supervisor_run_view"))).mappings().all()
        assert len(rows) == 1 and rows[0]["sandbox_name"] == "customer_care"
        assert "text" not in rows[0] and "job_id" not in rows[0]
    for table in ("message", "draft", "conversation"):
        with pytest.raises(DBAPIError):  # no grant at all
            async with supervisor_session(a.id) as s:
                await s.execute(text(f"select * from {table}"))
    with pytest.raises(DBAPIError):  # column grant excludes job_id
        async with supervisor_session(a.id) as s:
            await s.execute(text("select job_id from trigger_run"))
