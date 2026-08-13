import os
import json
from dotenv import load_dotenv

load_dotenv()

class Settings:
    """Application settings from environment variables"""
    PROJECT_NAME: str = "Cortex Scheduling API"
    PROJECT_VERSION: str = "1.0.0"
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://user:password@localhost:5434/cortex_db"
    )
    ASYNC_DATABASE_URL: str = os.getenv(
        "ASYNC_DATABASE_URL",
        "postgresql+asyncpg://user:password@localhost:5434/cortex_db"
    )

    # Redis (pub/sub, distributed locks, cross-service signals)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    
    @property
    def REDIS_URL(self) -> str:
        """Construct Redis URL from individual settings or env variable"""
        explicit = os.getenv("REDIS_URL")
        if explicit:
            return explicit
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    REDIS_CHANNEL_PREFIX: str = os.getenv("REDIS_CHANNEL_PREFIX", "cortex")
    REDIS_SAVE_STREAM_KEY: str = os.getenv("REDIS_SAVE_STREAM_KEY", "save_transcription:stream")
    REDIS_SAVE_CONSUMER_GROUP: str = os.getenv("REDIS_SAVE_CONSUMER_GROUP", "backend-save-consumers")
    REDIS_SAVE_READ_BLOCK_MS: int = int(os.getenv("REDIS_SAVE_READ_BLOCK_MS", "5000"))

    # MongoDB for transcription results
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "cortex")


    
    # API Settings
    API_STR: str = "/api"

    # Authentication
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "change-this-in-production-super-secret-key"
    )
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    )
    REFRESH_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("REFRESH_TOKEN_EXPIRE_MINUTES", "10080")
    )
    
    # CORS
    BACKEND_CORS_ORIGINS: list = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # Google Calendar OAuth
    GOOGLE_OAUTH_CLIENT_ID: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    GOOGLE_OAUTH_CLIENT_SECRET: str = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    GOOGLE_OAUTH_REDIRECT_URI: str = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/google-calendar/callback")
    GOOGLE_OAUTH_AUTH_URL: str = os.getenv("GOOGLE_OAUTH_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
    GOOGLE_OAUTH_TOKEN_URL: str = os.getenv("GOOGLE_OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token")
    GOOGLE_CALENDAR_API_BASE_URL: str = os.getenv("GOOGLE_CALENDAR_API_BASE_URL", "https://www.googleapis.com/calendar/v3")
    GOOGLE_CALENDAR_WEBHOOK_URL: str = os.getenv("GOOGLE_CALENDAR_WEBHOOK_URL", "")
    GOOGLE_CALENDAR_CHANNEL_TTL_SECONDS: int = int(os.getenv("GOOGLE_CALENDAR_CHANNEL_TTL_SECONDS", "604800"))
    GOOGLE_CALENDAR_CHANNEL_RENEW_BEFORE_SECONDS: int = int(os.getenv("GOOGLE_CALENDAR_CHANNEL_RENEW_BEFORE_SECONDS", "86400"))
    GOOGLE_CALENDAR_RENEW_CRON_KEY: str = os.getenv("GOOGLE_CALENDAR_RENEW_CRON_KEY", "")
    GOOGLE_OAUTH_STATE_TTL_SECONDS: int = int(os.getenv("GOOGLE_OAUTH_STATE_TTL_SECONDS", "600"))
    GOOGLE_POST_CONNECT_REDIRECT_URL: str = os.getenv("GOOGLE_POST_CONNECT_REDIRECT_URL", "http://localhost:5173")
    GOOGLE_CALENDAR_DEFAULT_ID: str = os.getenv("GOOGLE_CALENDAR_DEFAULT_ID", "primary")
    GOOGLE_CALENDAR_INITIAL_SYNC_PAST_DAYS: int = int(os.getenv("GOOGLE_CALENDAR_INITIAL_SYNC_PAST_DAYS", "90"))
    GOOGLE_CALENDAR_INITIAL_SYNC_FUTURE_DAYS: int = int(os.getenv("GOOGLE_CALENDAR_INITIAL_SYNC_FUTURE_DAYS", "180"))
    GOOGLE_CALENDAR_SYNC_MAX_RESULTS: int = int(os.getenv("GOOGLE_CALENDAR_SYNC_MAX_RESULTS", "250"))
    GOOGLE_CALENDAR_SCOPES: list[str] = json.loads(
        os.getenv(
            "GOOGLE_CALENDAR_SCOPES",
            '["https://www.googleapis.com/auth/calendar.events"]',
        )
    )

    # Encryption key for provider tokens (base64 Fernet key preferred)
    EXTERNAL_TOKEN_ENCRYPTION_KEY: str = os.getenv("EXTERNAL_TOKEN_ENCRYPTION_KEY", "")

    # MinIO / S3-compatible multipart upload
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    MINIO_SECURE: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"
    MINIO_REGION: str = os.getenv("MINIO_REGION", "us-east-1")
    MINIO_BUCKET: str = os.getenv("MINIO_BUCKET", "cortex-videos")
    MINIO_AUTO_CREATE_BUCKET: bool = os.getenv("MINIO_AUTO_CREATE_BUCKET", "false").lower() == "true"

    # Upload guardrails
    PRESIGNED_URL_EXPIRE_SECONDS: int = int(os.getenv("PRESIGNED_URL_EXPIRE_SECONDS", "180"))
    MULTIPART_MIN_PART_SIZE_BYTES: int = int(os.getenv("MULTIPART_MIN_PART_SIZE_BYTES", str(5 * 1024 * 1024)))
    MULTIPART_MAX_PARTS: int = int(os.getenv("MULTIPART_MAX_PARTS", "10000"))
    UPLOAD_MAX_FILE_SIZE_BYTES: int = int(os.getenv("UPLOAD_MAX_FILE_SIZE_BYTES", str(20 * 1024 * 1024 * 1024)))
    UPLOAD_STALE_AFTER_HOURS: int = int(os.getenv("UPLOAD_STALE_AFTER_HOURS", "24"))
    UPLOAD_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "120"))

    # LLM Provider
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")

    # OpenAI / 9Router Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "http://localhost:20128/v1")
    OPENAI_DEFAULT_MODEL: str = os.getenv("OPENAI_DEFAULT_MODEL", "oc/qwen3.6-plus-free")
    OPENAI_VISION_MODEL: str = os.getenv("OPENAI_VISION_MODEL", "oc/qwen3.6-plus-free")
    # Zep Configuration
    ZEP_API_KEY: str = os.getenv("ZEP_API_KEY", "")
    ZEP_API_URL: str = os.getenv("ZEP_API_URL", "https://api.getzep.com")

    LLM_WINDOW_SECONDS: float = float(os.getenv("LLM_WINDOW_SECONDS", "30.0"))
    LLM_MIN_KNOWLEDGE_VALUE: float = float(os.getenv("LLM_MIN_KNOWLEDGE_VALUE", "0.3"))

    # Internal API
    INTERNAL_API_KEY: str = os.getenv("INTERNAL_API_KEY", "")

    UNSEARCH_URL: str = os.getenv("UNSEARCH_URL", "http://localhost:8009")

    # Jina AI Reader
    JINA_API_KEY: str = os.getenv("JINA_API_KEY", "")

    # ── Memory System ─────────────────────────────────────────────────────────
    MEMORY_REDIS_HOST: str = os.getenv("MEMORY_REDIS_HOST", "localhost")
    MEMORY_REDIS_PORT: int = int(os.getenv("MEMORY_REDIS_PORT", "6379"))
    MEMORY_REDIS_DB: int = int(os.getenv("MEMORY_REDIS_DB", "1"))

    @property
    def MEMORY_REDIS_URL(self) -> str:
        explicit = os.getenv("MEMORY_REDIS_URL")
        if explicit:
            return explicit
        return f"redis://{self.MEMORY_REDIS_HOST}:{self.MEMORY_REDIS_PORT}/{self.MEMORY_REDIS_DB}"

    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini/gemini-embedding-2-preview")
    EMBEDDING_DIMENSIONS: int = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))

    WORKING_MEMORY_DEFAULT_TOKENS: int = int(os.getenv("WORKING_MEMORY_DEFAULT_TOKENS", "32000"))
    SUMMARY_TRIGGER_TOKEN_COUNT: int = int(os.getenv("SUMMARY_TRIGGER_TOKEN_COUNT", "8000"))
    MEMORY_EXTRACTION_ENABLED: bool = os.getenv("MEMORY_EXTRACTION_ENABLED", "true").lower() == "true"
    OCR_SERVICE_MODE: str = os.getenv("OCR_SERVICE_MODE", "EXTERNAL")

    # ── Attention Log (Milestone 2.9) ────────────────────────────────────────
    # How long a surfaced (item_id, reason_key) pair stays deduplicated.
    # 24h is the agreed starting value, not a law: the right number is an
    # empirical question the Feedback Loop (6.9) will answer from this very
    # table, so it has to be tunable without a deploy.
    ATTENTION_DEDUP_WINDOW_HOURS: int = int(os.getenv("ATTENTION_DEDUP_WINDOW_HOURS", "24"))

    # ── Agent feature flags ──────────────────────────────────────────────────
    AGENT_PARALLEL_TOOL_EXECUTION: bool = os.getenv("AGENT_PARALLEL_TOOL_EXECUTION", "true").lower() == "true"
    AGENT_TOOL_CALL_COUNT_SCOPE: str = os.getenv("AGENT_TOOL_CALL_COUNT_SCOPE", "turn")
    AGENT_TOKEN_BUDGET_HISTORY: bool = os.getenv("AGENT_TOKEN_BUDGET_HISTORY", "false").lower() == "true"


settings = Settings()
