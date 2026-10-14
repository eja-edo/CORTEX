"""Kiểm nhanh data/llm.env: một câu JSON + một lần gọi tool. Không gửi dữ liệu khách.

    .venv/bin/python -m dev.local.llm_ping"""
import asyncio
import time

from cortex_leads.llm.providers import OpenAICompatibleProvider
from cortex_leads.llm.shape import parse_json_object
from dev.local import env

TOOL = {"type": "function", "function": {"name": "lookup_catalog", "description": "Tra giá khoá học",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}


async def main() -> None:
    cfg = env.read_env_file(env.LLM_ENV)
    if not cfg.get("CL_LLM_API_KEY") or "DIEN-KEY" in cfg["CL_LLM_API_KEY"]:
        raise SystemExit("Chưa điền CL_LLM_API_KEY trong data/llm.env")
    env.load_local()  # config lõi (CL_*) cần có mặt; chạy `dev.local setup` trước
    p = OpenAICompatibleProvider(base_url=cfg["CL_LLM_BASE_URL"], api_key=cfg["CL_LLM_API_KEY"],
                                 default_model=cfg["CL_LLM_MODEL_LITE"])
    t = time.monotonic()
    r = await p.complete([{"role": "user", "content": 'Trả về đúng JSON: {"ok": true, "loi_chao": "<một câu chào khách>"}'}])
    print(f"[1] JSON ({time.monotonic() - t:.1f}s, {r.tokens_in}+{r.tokens_out} token, model {r.model}):")
    print("    thô :", (r.content or "")[:200].replace("\n", " "))
    print("    đọc :", parse_json_object(r.content))
    t = time.monotonic()
    r = await p.complete([{"role": "user", "content": "Khoá IELTS giá bao nhiêu? Hãy tra catalog bằng tool."}],
                         tools=[TOOL])
    print(f"[2] Tool ({time.monotonic() - t:.1f}s):", [(c.name, c.arguments, c.parse_error) for c in r.tool_calls] or
          f"KHÔNG gọi tool - nội dung: {(r.content or '')[:150]!r}")


if __name__ == "__main__":
    asyncio.run(main())
