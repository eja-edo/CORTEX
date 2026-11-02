"""One test message to a push destination (WP40), through the same two senders the worker uses. Lives here, with them, because a
network call is allowed only in `notify/`, `outbound/`, `llm/`, `connectors/` and `cells/` (tests/e2e: the A9 guard on network imports)."""
import httpx

from cortex_leads.notify import worker

TEXT = "✅ Thử thông báo từ Cortex: nếu bạn đọc được dòng này thì kênh nhận đã nối đúng. (Tin thử, không có dữ liệu khách.)"


async def send_test(kind: str, address: str, telegram_token: str | None) -> bool:
    async with httpx.AsyncClient() as client:
        if kind == "telegram":
            return await worker._send(client, telegram_token or "", address, TEXT)
        return await worker._send_mezon(client, address, TEXT)
