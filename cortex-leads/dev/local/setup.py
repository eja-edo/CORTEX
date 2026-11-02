"""`setup`: dựng lại DB local sạch, migrate, seed tenant/sandbox/catalog/connector/key/skill."""
import hashlib
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from cortex_leads.skills.loader import load_yaml
from dev.local import env

LIVE_SKILLS = ("hoi-lai-khach-im", "hoi-lai-dung-hen", "tra-loi-khach")
TZ = "Asia/Ho_Chi_Minh"
SAMPLE_FILE = env.ROOT / "dev/samples/trung_tam_mau.yaml"  # dữ liệu giả lập đầy đủ: khoá học + thông tin chung
SAMPLE = load_yaml(SAMPLE_FILE.read_text(encoding="utf-8"))


def _catalog(today):
    """(code, name, category, price, unit, attrs). Khai giảng = hôm nay + start_in_days, dạng dd/mm (R38)."""
    for c in SAMPLE["courses"]:
        attrs = dict(c.get("attrs") or {})
        if c.get("start_in_days"):
            attrs["lich_khai_giang"] = [f"{today + timedelta(days=d):%d/%m}" for d in c["start_in_days"]]
        yield c["code"], c["name"], c.get("category"), c.get("price"), c.get("unit"), attrs, None
    for i in SAMPLE.get("info") or []:
        yield i["code"], i["name"], "thong_tin", None, None, dict(i.get("attrs") or {}), None
    for n, sl in enumerate(SAMPLE.get("slots") or [], 1):  # WP18: valid_until = the start
        day = today + timedelta(days=sl["in_days"])
        hh, mm = map(int, sl["time"].split(":"))
        start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=ZoneInfo(TZ))
        yield (f"LH-{day:%d-%m}-{sl['time'][:2]}", f"{sl['label']} {day:%d/%m}", "lich_hoc_thu", None, None,
               {"suc_chua": sl["capacity"]}, start)  # date and time are read off `start`, never typed (DESIGN §5.13)


async def _recreate_db(admin_url: str, name: str) -> None:
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            await c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            await c.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()


def _migrate() -> None:
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=False, cwd=env.ROOT,
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("alembic upgrade head lỗi:\n" + r.stdout[-2000:] + r.stderr[-2000:])


async def _seed(connector_secret: str, staff_key: str, sup_key: str) -> dict[str, str]:
    from cortex_leads.core.ids import new_connector_id, uuid7
    from cortex_leads.db import models as m
    from cortex_leads.db.session import system_session, tenant_session
    from cortex_leads.domain.pack import load_pack_file
    from cortex_leads.skills.loader import sync_dir
    from cortex_leads.skills.registry import promote

    care = env.ROOT / "sandboxes" / "customer_care"
    tid, sid, cid = uuid7(), uuid7(), new_connector_id()
    today = datetime.now(ZoneInfo(TZ)).date()
    async with system_session() as s:
        s.add(m.Tenant(id=tid, name=SAMPLE["business"]["name"], timezone=TZ))
    async with tenant_session(tid) as s:
        s.add(m.Sandbox(
            id=sid, tenant_id=tid, name="customer_care", profile_ref="customer_drafter@1",
            domain_pack=load_pack_file(care / "domain.yaml").model_dump(mode="json"),
            budget={"runs_per_day": 500, "drafts_per_staff_per_day": 100, "tokens_per_day": 20_000_000},
            business_hours={"start": "00:00", "end": "23:59"}, send_mode="manual"))
        for code, name, cat, price, unit, attrs, until in _catalog(today):
            s.add(m.CatalogItem(tenant_id=tid, code=code, name=name, category=cat, unit=unit, attrs=attrs,
                                price=Decimal(str(price)) if price is not None else None, valid_until=until))
    async with system_session() as s:
        s.add(m.Connector(
            id=cid, tenant_id=tid, sandbox_id=sid, channel_kind="messenger", trust="official",
            outbound={"enabled": True, "url": f"{env.CHANNEL_URL}/actions"},
            secret_enc=Fernet(os.environ["CL_CONNECTOR_SECRET_KEY"]).encrypt(connector_secret.encode())))
        for role, ref, key in (("staff", "nv1", staff_key), ("supervisor", None, sup_key)):
            s.add(m.ApiKey(tenant_id=tid, role=role, staff_ref=ref,
                           key_hash=hashlib.sha256(key.encode()).hexdigest()))
    async with tenant_session(tid) as s:
        rows_sk = await sync_dir(s, tid, sid, care / "skills")
        for name in LIVE_SKILLS:  # phiên bản mới nhất loader sinh ra, không hardcode
            latest = max((r for r in rows_sk if r.name == name), key=lambda r: r.version)
            for status in ("shadow", "live"):
                await promote(s, sid, name, latest.version, status)
    from cortex_leads.auth.passwords import temporary_password
    from cortex_leads.auth.users import create_user

    logins = {}
    async with tenant_session(tid) as s:
        for role, ref, email, name in (("owner", "owner", "chu@trungtam.test", "Chủ trung tâm"), ("staff", "nv1", "nv1@trungtam.test", "Nhân viên một")):
            pw = temporary_password()
            await create_user(s, tid, email=email, name=name, role=role, password=pw, created_by="dev.local setup", staff_ref=ref)
            logins[f"LOCAL_{role.upper()}_EMAIL"], logins[f"LOCAL_{role.upper()}_PASSWORD"] = email, pw
    return {**logins, "LOCAL_TENANT_ID": str(tid), "LOCAL_SANDBOX_ID": str(sid), "LOCAL_CONNECTOR_ID": cid,
            "LOCAL_CONNECTOR_SECRET": connector_secret, "LOCAL_STAFF_KEY": staff_key,
            "LOCAL_SUPERVISOR_KEY": sup_key, "LOCAL_PAGE_ID": env.PAGE_ID}


async def run() -> None:
    name = env.db_name()
    app_url, owner_url, admin_url = env.db_urls(name)
    print(f"[1/4] Dựng lại DB '{name}' (xoá dữ liệu cũ)...")
    await _recreate_db(admin_url, name)
    values = {"CL_DATABASE_URL": app_url, "CL_DATABASE_OWNER_URL": owner_url,
              "CL_CONNECTOR_SECRET_KEY": Fernet.generate_key().decode()}
    os.environ.update(values)
    from cortex_leads.config import get_settings
    from cortex_leads.db.session import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    print("[2/4] Migrate (alembic upgrade head)...")
    _migrate()
    print("[3/4] Seed tenant, catalog, connector, API key, skill...")
    values |= await _seed(secrets.token_urlsafe(24), f"clk_{secrets.token_urlsafe(24)}",
                          f"clk_{secrets.token_urlsafe(24)}")
    await get_engine().dispose()
    env.DATA.mkdir(exist_ok=True)
    # Quên mật khẩu qua email: không có máy chủ thư, mỗi thư thành một tệp trong data/mail (mở tệp để lấy liên kết).
    values |= {"CL_MAIL_DIR": str(env.DATA / "mail"), "CL_PUBLIC_BASE_URL": env.CORE_URL}
    env.CHAT_FILE.unlink(missing_ok=True)  # lịch sử chat của kênh giả thuộc về DB cũ
    env.LOCAL_ENV.write_text("# Sinh bởi dev.local setup. KHÔNG commit.\n" + "".join(
        f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    env.LOCAL_ENV.chmod(0o600)
    print("[4/4] Xong.\n")
    print(f"  Trang nhân viên : {env.CORE_URL}/staff/login")
    print(f"  Staff API key   : {values['LOCAL_STAFF_KEY']}   (dán vào ô đăng nhập /staff/login)")
    print(f"  Giao diện chính : {env.CORE_URL}/app/   chủ: {values['LOCAL_OWNER_EMAIL']} / {values['LOCAL_OWNER_PASSWORD']}")
    print(f"                    nhân viên: {values['LOCAL_STAFF_EMAIL']} / {values['LOCAL_STAFF_PASSWORD']}")
    print(f"  Trang khách giả : {env.CHANNEL_URL}/")
    print(f"  Thư 'quên mật khẩu' được ghi thành tệp trong {env.DATA / 'mail'}")
    print(f"  Cấu hình sinh ra: {env.LOCAL_ENV}")
    print("  Tiếp theo       : .venv/bin/python -m dev.local serve")
