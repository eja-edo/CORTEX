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
        "postgresql+psycopg2://user:password@localhost:5433/cortex_db"
    )



    @property
    def ASYNC_DATABASE_URL(self) -> str:
        explicit = os.getenv("ASYNC_DATABASE_URL")
        if explicit:
            return explicit
        if self.DATABASE_URL.startswith("postgresql+psycopg2://"):
            return self.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.DATABASE_URL
    
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

settings = Settings()
