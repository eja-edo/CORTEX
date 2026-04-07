import os
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

settings = Settings()
