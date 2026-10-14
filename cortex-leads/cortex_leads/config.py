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
