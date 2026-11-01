from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from cortex_leads.core.errors import ConfigError

# DESIGN §10: values that leaked into the old repo; refuse them everywhere.
KNOWN_LEAKED = {"cortex-internal-key-2024", "change-this-in-production-super-secret-key"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CL_", env_file=".env", extra="ignore")

    DATABASE_URL: str  # app role (subject to RLS)
    DATABASE_OWNER_URL: str | None = None  # migrations only
    CONNECTOR_SECRET_KEY: str  # Fernet key
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_MODEL_LITE: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None  # staff push (WP17); unset = notifications are skipped
    TRANSCRIBER: str = "local"  # lesson_recap (WP31): "local" = faster-whisper on this machine, "api" = a Whisper endpoint
    WHISPER_BASE_URL: str = "https://api.openai.com/v1"  # only for TRANSCRIBER=api: the audio leaves the machine (DESIGN §6)
    WHISPER_API_KEY: str | None = None
    WHISPER_MODEL: str = "whisper-1"
    WHISPER_LANGUAGE: str | None = "vi"  # the language of lesson recordings (a sandbox that knows better passes its own; empty = detect)
    WHISPER_LOCAL_MODEL: str = "small"  # faster-whisper model size; `pip install faster-whisper`
    WEBHOOK_ALLOW_HOSTS: str = "webhook.mezon.ai"  # hosts a push target may name (comma separated); anything else is refused
    WEBHOOK_ALLOW_LOCAL: bool = False  # development only: also allow http://localhost and 127.0.0.1
    CLASSROOM_API_BASE: str = "https://classroom.googleapis.com/v1"  # dev: http://127.0.0.1:8302/v1 (dev/local/fake_classroom.py)
    DRIVE_API_BASE: str = "https://www.googleapis.com/drive/v3"
    DRIVE_UPLOAD_BASE: str = "https://www.googleapis.com/upload/drive/v3"  # dev: the fake Classroom serves it too
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"  # dev: the fake Classroom answers at http://127.0.0.1:8302/token
    GOOGLE_OAUTH_CLIENT_ID: str | None = None  # the OAuth client of this deployment (Google Cloud console, type "Web application"); redirect URI: <PUBLIC_BASE_URL>/api/v1/google/callback
    GOOGLE_OAUTH_CLIENT_SECRET: str | None = None
    GRADER_SEND_IMAGES: bool = False  # photos of a student's work go to the model AS THEY ARE (names in a picture cannot be masked): turn on only with a model under a DPA, or for invented data
    UPLOAD_PER_USER_DAY: int = 20  # recordings one person may start sending to Drive per 24 hours (the bytes no longer pass here, so this is the brake)
    UPLOAD_PER_TENANT_DAY: int = 100
    UPLOAD_MAX_MB: int = 1024
    PUBLIC_BASE_URL: str | None = None  # link in the push, e.g. https://cortex.example.vn
    TRUST_PROXY_HEADERS: bool = False  # read the client address from X-Forwarded-For (only behind a proxy you control)
    CELL: str = "c1"  # which cell this process serves (own database, own workers); see cells/router.py
    SESSION_ABSOLUTE_HOURS: int = 12  # a sign-in ends this long after it began, whatever the activity
    SESSION_IDLE_MINUTES: int = 120  # ...or this long after the last request
    LOGIN_MAX_FAILURES: int = 5  # wrong passwords for one account before it is locked
    LOGIN_LOCK_MINUTES: int = 15
    LOGIN_IP_MAX_FAILURES: int = 30  # wrong passwords from one address in LOGIN_IP_WINDOW_MINUTES before it is locked
    LOGIN_IP_WINDOW_MINUTES: int = 10
    INGEST_MAX_SKEW_S: int = 300
    INGEST_MAX_BATCH: int = 100


@lru_cache
def get_settings() -> Settings:
    try:
        s = Settings()  # type: ignore[call-arg]
    except ValidationError as e:
        missing = [".".join(map(str, err["loc"])) for err in e.errors()]
        raise ConfigError(f"invalid or missing configuration: {missing}") from e
    for name, value in s.model_dump().items():
        if isinstance(value, str) and any(bad in value for bad in KNOWN_LEAKED):
            raise ConfigError(f"CL_{name} uses a known leaked secret; generate a new one")
    try:
        Fernet(s.CONNECTOR_SECRET_KEY)
    except ValueError as e:
        raise ConfigError("CL_CONNECTOR_SECRET_KEY is not a valid Fernet key") from e
    return s
