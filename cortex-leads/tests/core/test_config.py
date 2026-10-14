import pytest
from cryptography.fernet import Fernet

from cortex_leads.config import KNOWN_LEAKED, get_settings
from cortex_leads.core.errors import ConfigError


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CL_DATABASE_URL", "postgresql+asyncpg://x:y@h/db")
    monkeypatch.setenv("CL_CONNECTOR_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.chdir("/")  # no stray .env
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_valid_config_loads(clean_env) -> None:
    s = get_settings()
    assert s.INGEST_MAX_SKEW_S == 300 and s.INGEST_MAX_BATCH == 100


def test_missing_secret_rejected(clean_env) -> None:
    clean_env.delenv("CL_CONNECTOR_SECRET_KEY")
    with pytest.raises(ConfigError, match="CONNECTOR_SECRET_KEY"):
        get_settings()


@pytest.mark.parametrize("leaked", sorted(KNOWN_LEAKED))
def test_leaked_secret_rejected(clean_env, leaked: str) -> None:
    clean_env.setenv("CL_LLM_API_KEY", leaked)
    with pytest.raises(ConfigError, match="leaked"):
        get_settings()


def test_invalid_fernet_key_rejected(clean_env) -> None:
    clean_env.setenv("CL_CONNECTOR_SECRET_KEY", "not-a-key")
    with pytest.raises(ConfigError, match="Fernet"):
        get_settings()
