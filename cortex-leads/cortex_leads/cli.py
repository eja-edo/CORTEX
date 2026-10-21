"""Operator CLI: python -m cortex_leads.cli <command> (PLAN §4 WP5)."""
import argparse
import asyncio
import csv
import hashlib
import logging
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy import func, select

from cortex_leads.config import get_settings
from cortex_leads.core.ids import new_connector_id, uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import system_session, tenant_session
from cortex_leads.skills.profile import SANDBOXES_DIR

DEFAULT_BUDGET = {"runs_per_day": 200, "drafts_per_staff_per_day": 20, "tokens_per_day": 500_000}


def _gateway():
    from cortex_leads.llm.gateway import LLMGateway
    from cortex_leads.llm.providers import OpenAICompatibleProvider

    return LLMGateway(OpenAICompatibleProvider())


async def cmd_create_tenant(a: argparse.Namespace) -> None:
    tid, sid = uuid7(), uuid7()
    async with system_session() as s:
        s.add(m.Tenant(id=tid, name=a.name, timezone=a.timezone))
    async with tenant_session(tid) as s:  # a tenant is useless without its first sandbox
        s.add(m.Sandbox(id=sid, tenant_id=tid, name="customer_care",
                        profile_ref="customer_drafter@1", budget=DEFAULT_BUDGET))
    print(f"tenant_id={tid}\nsandbox_id={sid}")


PROFILES = {"customer_care": "customer_drafter@1", "owner_digest": "digest_template@1"}


async def cmd_create_sandbox(a: argparse.Namespace) -> None:
    """A second sandbox for a tenant, e.g. `--purpose owner_digest` for the owner's weekly numbers."""
    sid = uuid7()
    async with tenant_session(a.tenant) as s:
        s.add(m.Sandbox(id=sid, tenant_id=a.tenant, name=a.name or a.purpose, purpose=a.purpose,
                        profile_ref=PROFILES[a.purpose], budget=DEFAULT_BUDGET))
    print(f"sandbox_id={sid}")


async def cmd_add_http_connector(a: argparse.Namespace) -> None:
    """A read-only HTTPS source (T1). `--url` holds {q} where the query goes; the host must be --allow-host."""
    from cortex_leads.connectors.http_readonly import pin_of, validate_source

    source: dict = {"url": a.url, "allow_hosts": a.allow_host, **({"auth_header": a.auth_header} if a.auth_header else {})}
    validate_source(source)
    secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(a.secret.encode()) if a.secret else None
    async with tenant_session(a.tenant) as s:
        s.add(m.ToolConnector(tenant_id=a.tenant, sandbox_id=a.sandbox, name=a.name, source=source,
                              description=a.description or "", secret_enc=secret, pin_sha256=pin_of("http_readonly", source)))
    print(f"tool_connector {a.name} (pinned)")


async def cmd_add_mcp_connector(a: argparse.Namespace) -> None:
    """A remote MCP server (T2), read-only. Without --tool it only lists what the server offers; with --tool the
    definition you just read is pinned, and any later change to it makes the connector refuse to run."""
    from cortex_leads.connectors import mcp_remote
    from cortex_leads.connectors.http_readonly import pin_of

    source: dict = {"url": a.url, "allow_hosts": a.allow_host, **({"auth_header": a.auth_header} if a.auth_header else {})}
    tools = await mcp_remote.describe({**source, "expose": [], "tool_pin": ""}, a.secret.encode() if a.secret else None)
    if not a.tool:
        for t in tools:
            print(f"{t['name']}: {t.get('description', '')[:120]}  annotations={t.get('annotations')}")
        return
    chosen = next((t for t in tools if t["name"] == a.tool), None)
    if chosen is None:
        raise SystemExit(f"the server has no tool {a.tool!r}")
    if not mcp_remote.read_only(chosen):
        raise SystemExit("the server marks this tool as writing or destructive: refused")
    source |= {"expose": [{"remote": a.tool, "arg": a.arg}], "tool_pin": mcp_remote.tool_pin([chosen])}
    mcp_remote.validate_source(source)
    secret = Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(a.secret.encode()) if a.secret else None
    async with tenant_session(a.tenant) as s:
        s.add(m.ToolConnector(tenant_id=a.tenant, sandbox_id=a.sandbox, name=a.name, kind="mcp", source=source,
                              description=a.description or "", secret_enc=secret, pin_sha256=pin_of("mcp", source)))
    print(f"tool_connector {a.name} (mcp, tool {a.tool} pinned)")


async def cmd_cron(a: argparse.Namespace) -> None:
    from cortex_leads.cron.runner import cron_once

    print(f"made={await cron_once(datetime.now(UTC), _gateway() if a.llm else None)}")


async def cmd_create_connector(a: argparse.Namespace) -> None:
    cid, secret = new_connector_id(get_settings().CELL), secrets.token_urlsafe(32)
    async with system_session() as s:
        s.add(m.Connector(id=cid, tenant_id=a.tenant, sandbox_id=a.sandbox, channel_kind=a.channel_kind,
                          trust=a.trust, secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(secret.encode())))
    print(f"connector_id={cid}\nsecret={secret}  (shown once)")


async def cmd_create_api_key(a: argparse.Namespace) -> None:
    raw = f"clk_{secrets.token_urlsafe(32)}"
    async with system_session() as s:
        s.add(m.ApiKey(tenant_id=a.tenant, role=a.role, staff_ref=a.staff_ref,
                       key_hash=hashlib.sha256(raw.encode()).hexdigest()))
    print(f"api_key={raw}  (shown once)")


async def cmd_sync_skills(a: argparse.Namespace) -> None:
    from cortex_leads.skills.loader import sync_dir

    async with tenant_session(a.tenant) as s:
        sb = await s.get(m.Sandbox, a.sandbox)
        directory = Path(a.dir) if a.dir else SANDBOXES_DIR / sb.name / "skills"
        for row in await sync_dir(s, a.tenant, a.sandbox, directory):
            print(f"{row.name}@{row.version} {row.status}")


async def cmd_sync_domain(a: argparse.Namespace) -> None:
    from cortex_leads.domain.pack import load_pack_file

    async with tenant_session(a.tenant) as s:
        sb = await s.get(m.Sandbox, a.sandbox)
        pack = load_pack_file(Path(a.file) if a.file else SANDBOXES_DIR / sb.name / "domain.yaml")
        sb.domain_pack = pack.model_dump(mode="json")
        print(f"intents={len(pack.intents)} reason_codes={len(pack.reason_codes)} "
              f"fact_kinds={sorted(pack.all_fact_kinds)}")


async def cmd_sweep(a: argparse.Namespace) -> None:
    from cortex_leads.clock.sweeper import sweep_once

    print(f"fired={await sweep_once(datetime.now(UTC), gateway=_gateway() if a.run else None)}")


async def cmd_run_pending(a: argparse.Namespace) -> None:
    from cortex_leads.runner.customer_run import run_pending

    print(f"runs={await run_pending(datetime.now(UTC), _gateway())}")


async def worker_once(gateway) -> tuple[int, int, int]:
    """One pass of the always-on loop: due conversations -> LLM runs -> outbox delivery."""
    from cortex_leads.clock.sweeper import sweep_once
    from cortex_leads.outbound.worker import deliver_once
    from cortex_leads.runner.customer_run import run_pending

    from cortex_leads.notify.worker import notify_once

    fired = await sweep_once(datetime.now(UTC))
    runs = await run_pending(datetime.now(UTC), gateway)
    sent = await deliver_once(datetime.now(UTC))
    from cortex_leads.cron.runner import cron_once

    await cron_once(datetime.now(UTC), gateway)  # morning list, weekly digest, supervisor signals (WP19, WP21)
    await notify_once(datetime.now(UTC))  # staff push (WP17): not part of the customer-facing counts
    return fired, runs, sent


async def cmd_worker(a: argparse.Namespace) -> None:
    """DESIGN §5.7 `turn` needs seconds, not a 10-minute cron. Ctrl+C stops it between passes."""
    gateway = _gateway()
    print(f"worker: sweep -> run -> deliver every {a.interval}s (Ctrl+C to stop)")
    try:
        while True:
            try:
                fired, runs, sent = await worker_once(gateway)
                if fired or runs or sent:
                    print(f"[{datetime.now():%H:%M:%S}] fired={fired} runs={runs} sent={sent}", flush=True)
            except Exception:  # one bad pass must not kill the loop
                logging.getLogger(__name__).exception("worker pass failed")
            await asyncio.sleep(a.interval)
    except asyncio.CancelledError:
        print("worker stopped")


async def cmd_promote_skill(a: argparse.Namespace) -> None:
    from cortex_leads.skills.registry import promote

    async with tenant_session(a.tenant) as s:
        row = await promote(s, a.sandbox, a.name, a.version, a.to)
        print(f"{row.name}@{row.version} {row.status}")


async def cmd_set_send_mode(a: argparse.Namespace) -> None:
    async with tenant_session(a.tenant) as s:
        sb = await s.get(m.Sandbox, a.sandbox)
        if sb is None:
            raise SystemExit("sandbox not found")
        s.add(m.ActionLog(tenant_id=a.tenant, action_id=uuid7(), actor="system:cli", tool="cli.set_send_mode",
                          args_masked={"from": sb.send_mode, "to": a.mode}, status="ok", evidence={}))
        sb.send_mode = a.mode
        print(f"send_mode={sb.send_mode}")


async def cmd_deliver_outbox(a: argparse.Namespace) -> None:
    from cortex_leads.outbound.worker import deliver_once

    print(f"delivered={await deliver_once(datetime.now(UTC))}")


async def cmd_add_notify_target(a: argparse.Namespace) -> None:
    """A Telegram chat that receives staff pushes. Needs CL_TELEGRAM_BOT_TOKEN on the worker."""
    async with tenant_session(a.tenant) as s:
        s.add(m.NotifyTarget(tenant_id=a.tenant, kind="telegram", address=a.chat_id, label=a.label))
    print(f"notify_target telegram:{a.chat_id}")


async def cmd_import_catalog(a: argparse.Namespace) -> None:
    """CSV columns: code,name,category,price,unit,valid_until(ISO). A changed row becomes version+1."""
    new = same = 0
    async with tenant_session(a.tenant) as s:
        for r in csv.DictReader(Path(a.csv).read_text(encoding="utf-8-sig").splitlines()):
            price = Decimal(r["price"]) if r.get("price") else None
            cur = (await s.execute(select(m.CatalogItem).where(
                m.CatalogItem.code == r["code"], m.CatalogItem.active.is_(True)))).scalars().first()
            if cur and cur.name == r["name"] and (cur.price is None) == (price is None) \
                    and (price is None or Decimal(cur.price) == price) and (cur.unit or "") == r.get("unit", ""):
                same += 1
                continue
            version = (await s.execute(select(func.coalesce(func.max(m.CatalogItem.version), 0)).where(
                m.CatalogItem.code == r["code"]))).scalar_one() + 1
            if cur:
                cur.active = False
            vu = datetime.fromisoformat(r["valid_until"]).replace(tzinfo=UTC) if r.get("valid_until") else None
            s.add(m.CatalogItem(tenant_id=a.tenant, code=r["code"], name=r["name"], category=r.get("category") or None,
                                price=price, unit=r.get("unit") or None, version=version, valid_until=vu))
            new += 1
    print(f"new_versions={new} unchanged={same}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="cortex_leads.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, *args: tuple[str, dict]) -> None:
        sp = sub.add_parser(name)
        for flag, kw in args:
            sp.add_argument(flag, **kw)
        sp.set_defaults(fn=fn)

    uid = {"type": UUID, "required": True}
    add("create-tenant", cmd_create_tenant, ("--name", {"required": True}),
        ("--timezone", {"default": "Asia/Ho_Chi_Minh"}))
    add("create-sandbox", cmd_create_sandbox, ("--tenant", uid), ("--purpose", {"required": True, "choices": sorted(PROFILES)}),
        ("--name", {"default": None}))
    add("add-mcp-connector", cmd_add_mcp_connector, ("--tenant", uid), ("--sandbox", uid), ("--name", {"required": True}),
        ("--url", {"required": True}), ("--allow-host", {"required": True, "action": "append"}), ("--tool", {"default": None}),
        ("--arg", {"default": "query"}), ("--description", {"default": None}), ("--secret", {"default": None}),
        ("--auth-header", {"default": None}))
    add("cron", cmd_cron, ("--llm", {"action": "store_true", "help": "also write the weekly summary with the LLM"}))
    add("add-http-connector", cmd_add_http_connector, ("--tenant", uid), ("--sandbox", uid), ("--name", {"required": True}),
        ("--url", {"required": True}), ("--allow-host", {"required": True, "action": "append"}),
        ("--description", {"default": None}), ("--secret", {"default": None}), ("--auth-header", {"default": None}))
    add("create-connector", cmd_create_connector, ("--tenant", uid), ("--sandbox", uid),
        ("--channel-kind", {"required": True}), ("--trust", {"default": "custom"}))
    add("create-api-key", cmd_create_api_key, ("--tenant", uid),
        ("--role", {"required": True, "choices": ["staff", "owner", "supervisor"]}),
        ("--staff-ref", {"default": None}))
    add("sync-skills", cmd_sync_skills, ("--tenant", uid), ("--sandbox", uid), ("--dir", {"default": None}))
    add("sync-domain", cmd_sync_domain, ("--tenant", uid), ("--sandbox", uid), ("--file", {"default": None}))
    add("sweep", cmd_sweep, ("--run", {"action": "store_true", "help": "also run pending jobs"}))
    add("run-pending", cmd_run_pending)
    add("worker", cmd_worker, ("--interval", {"type": float, "default": 5.0}))
    add("promote-skill", cmd_promote_skill, ("--tenant", uid), ("--sandbox", uid), ("--name", {"required": True}),
        ("--version", {"type": int, "required": True}),
        ("--to", {"required": True, "choices": ["shadow", "live"]}))
    add("set-send-mode", cmd_set_send_mode, ("--tenant", uid), ("--sandbox", uid),
        ("mode", {"choices": ["auto", "manual"]}))
    add("deliver-outbox", cmd_deliver_outbox)
    add("add-notify-target", cmd_add_notify_target, ("--tenant", uid), ("--chat-id", {"required": True}),
        ("--label", {"default": None}))
    add("import-catalog", cmd_import_catalog, ("csv", {}), ("--tenant", uid))
    args = p.parse_args(argv)
    try:
        asyncio.run(args.fn(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
