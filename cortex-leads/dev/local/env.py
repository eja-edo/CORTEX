"""Cấu hình chạy thử local: DB riêng, file data/local.env (gitignore), llm.env tuỳ chọn."""
import os
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("CL_LOCAL_DATA") or ROOT / "data")  # đổi được để chạy song song
LOCAL_ENV = DATA / "local.env"
LLM_ENV = DATA / "llm.env"
CHAT_FILE = DATA / "local_chat.json"
CORE_PORT = int(os.environ.get("CL_LOCAL_CORE_PORT", "8200"))
CHANNEL_PORT = int(os.environ.get("CL_LOCAL_CHANNEL_PORT", "8300"))
HOST = os.environ.get("CL_LOCAL_HOST", "127.0.0.1")  # địa chỉ nghe; 0.0.0.0 để mở ra ngoài (cần mở cổng ở firewall/security group)
PUBLIC_URL = os.environ.get("CL_LOCAL_PUBLIC_URL", "")  # địa chỉ người ngoài mở console, vd http://1.2.3.4:8200 (chỉ để dựng liên kết trong trang)
CORE_URL = f"http://127.0.0.1:{CORE_PORT}"
CHANNEL_URL = f"http://127.0.0.1:{CHANNEL_PORT}"
PAGE_ID = "page_local"
PROTECTED_DBS = {"cortex_leads", "cortex_leads_review"}  # pytest TRUNCATE trên các DB này


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip("'\"")
    return out


def db_name() -> str:
    name = os.environ.get("CL_LOCAL_DB", "cortex_leads_local")
    if name in PROTECTED_DBS or not name.replace("_", "").isalnum():
        raise SystemExit(f"Tên DB {name!r} không dùng được (cấm {sorted(PROTECTED_DBS)}).")
    return name


def db_urls(name: str) -> tuple[str, str, str]:
    """(app url, owner url, DB quản trị để chạy CREATE DATABASE), host/role lấy từ .env.test."""
    base = read_env_file(ROOT / ".env.test")
    app, owner = make_url(base["CL_DATABASE_URL"]), make_url(base["CL_DATABASE_OWNER_URL"])
    render = lambda u, d: u.set(database=d).render_as_string(hide_password=False)
    return render(app, name), render(owner, name), render(owner, owner.database or "postgres")


def load_local() -> dict[str, str]:
    """Nạp data/local.env vào os.environ (CL_*) và trả toàn bộ giá trị."""
    values = read_env_file(LOCAL_ENV)
    if not values:
        raise SystemExit("Chưa có data/local.env. Chạy trước: .venv/bin/python -m dev.local setup")
    for k, v in values.items():
        if k.startswith("CL_"):
            os.environ[k] = v
    from cortex_leads.config import get_settings

    get_settings.cache_clear()
    return values
