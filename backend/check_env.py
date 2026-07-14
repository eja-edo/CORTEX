"""Check env vars for API keys."""
from dotenv import load_dotenv
import os
load_dotenv('.env')

print(f'LLM_PROVIDER: {os.getenv("LLM_PROVIDER", "NOT SET")}')
print(f'OPENAI_BASE_URL: {os.getenv("OPENAI_BASE_URL", "NOT SET")}')
print(f'OPENAI_DEFAULT_MODEL: {os.getenv("OPENAI_DEFAULT_MODEL", "NOT SET")}')
ak = os.getenv("OPENAI_API_KEY", "")
print(f'OPENAI_API_KEY: {"SET" if ak else "NOT SET"} (len={len(ak)})')
zk = os.getenv("ZEP_API_KEY", "")
print(f'ZEP_API_KEY: {"SET" if zk else "NOT SET"} (len={len(zk)})')
print(f'ZEP_API_URL: {os.getenv("ZEP_API_URL", "NOT SET")}')
