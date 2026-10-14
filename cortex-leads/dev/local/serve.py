"""`serve`: lõi (:8200) + Messenger giả (:8300) + vòng đồng hồ, một process asyncio. Ctrl+C để dừng."""
import asyncio
import contextlib
import logging
import signal
import socket
from datetime import UTC, datetime
from typing import Any

import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from dev.local import env
from dev.local.channel import create_channel_app
from dev.local.fakellm import LocalFakeProvider

TICK_EVERY_S = 5  # WP16: lượt khách cần phản hồi trong ~30 giây
log = logging.getLogger("dev.local")


def make_gateway():
    from cortex_leads.llm.gateway import LLMGateway
    from cortex_leads.llm.providers import OpenAICompatibleProvider

    cfg = env.read_env_file(env.LLM_ENV)
    keys = ("CL_LLM_BASE_URL", "CL_LLM_API_KEY", "CL_LLM_MODEL_LITE")
    if all(cfg.get(k) for k in keys):
        print(f"LLM: THẬT ({cfg['CL_LLM_MODEL_LITE']} @ {cfg['CL_LLM_BASE_URL']}) từ data/llm.env")
        print("  CẢNH BÁO: chỉ gõ dữ liệu tự bịa. Không dán dữ liệu khách thật nếu endpoint này "
              "không có DPA (REVIEW R2). SĐT/email/tên được che trước khi gọi, nhưng đó chỉ là lớp giảm thiểu.")
        return LLMGateway(OpenAICompatibleProvider(
            base_url=cfg["CL_LLM_BASE_URL"], api_key=cfg["CL_LLM_API_KEY"],
            default_model=cfg["CL_LLM_MODEL_LITE"]))
    print("LLM: giả (chưa có data/llm.env) - nháp soạn sẵn từ catalog, không gọi mạng")
    return LLMGateway(LocalFakeProvider(), retry_delay_s=0)


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


class Clock:
    """sweep_once -> run_pending -> deliver_once, mỗi lần một người chạy (khoá)."""

    def __init__(self, gateway: Any) -> None:
        self.gateway, self.lock = gateway, asyncio.Lock()
        self.engine = create_async_engine(__import__("os").environ["CL_DATABASE_OWNER_URL"])

    async def counts(self) -> tuple[int, int]:
        async with self.engine.connect() as c:
            drafts = (await c.execute(text("select count(*) from draft"))).scalar_one()
            errs = (await c.execute(text(
                "select count(*) from trigger_run where status = 'error'"))).scalar_one()
        return drafts, errs

    async def __call__(self) -> dict[str, Any]:
        from cortex_leads.clock.sweeper import sweep_once
        from cortex_leads.outbound.worker import deliver_once
        from cortex_leads.runner.customer_run import run_pending

        async with self.lock:
            d0, e0 = await self.counts()
            fired = await sweep_once(datetime.now(UTC))
            runs = await run_pending(datetime.now(UTC), self.gateway)
            sent = await deliver_once(datetime.now(UTC))
            d1, e1 = await self.counts()
        res = {"hoi_thoai_den_gio": fired, "job_da_chay": runs, "nhap_moi": d1 - d0,
               "tin_xu_ly_gui": sent, "job_loi": e1 - e0}
        if any(res.values()):
            print(f"[đồng hồ {datetime.now():%H:%M:%S}] {fired} hội thoại tới giờ, {runs} job chạy, "
                  f"{d1 - d0} nháp mới, {sent} tin gửi" + (f", {e1 - e0} job LỖI (xem log)" if e1 - e0 else ""))
        return res


async def _loop(clock: Clock, stop: asyncio.Event) -> None:
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), TICK_EVERY_S)
        if stop.is_set():
            return
        try:
            await clock()
        except Exception as e:
            print(f"[đồng hồ] LỖI: {type(e).__name__}: {e}")
            log.exception("tick lỗi")


def _server(app: Any, port: int) -> uvicorn.Server:
    s = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    s.capture_signals = contextlib.nullcontext  # type: ignore[method-assign]  # ta tự bắt Ctrl+C
    return s


async def run() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    local = env.load_local()
    for port in (env.CORE_PORT, env.CHANNEL_PORT):
        if not _port_free(port):
            raise SystemExit(f"Cổng {port} đang bận. Tắt process đang giữ cổng rồi chạy lại.")
    from cortex_leads.app import create_app

    clock = Clock(make_gateway())
    core, chan = _server(create_app(), env.CORE_PORT), _server(create_channel_app(local, clock), env.CHANNEL_PORT)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    tasks = [asyncio.create_task(core.serve()), asyncio.create_task(chan.serve()),
             asyncio.create_task(_loop(clock, stop))]
    for _ in range(100):
        if core.started and chan.started:
            break
        await asyncio.sleep(0.1)
    else:
        stop.set()
    if stop.is_set():
        print("Server không lên được.")
    else:
        print(f"\nĐang chạy. Trang khách giả: {env.CHANNEL_URL}/   Trang nhân viên: {env.CORE_URL}/staff/login")
        print(f"Staff API key: {local['LOCAL_STAFF_KEY']}\nĐồng hồ tự chạy mỗi {TICK_EVERY_S}s. Ctrl+C để dừng.\n")
    await stop.wait()
    print("Đang dừng...")
    core.should_exit = chan.should_exit = True
    await asyncio.wait(tasks, timeout=10)
    for t in tasks:
        t.cancel()
    await clock.engine.dispose()
    from cortex_leads.db.session import get_engine

    await get_engine().dispose()
    print("Đã dừng.")
