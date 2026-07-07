from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://cortex:cortex@localhost:5434/cortex_db"

    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "cortex-workflow-queue"

    cortex_backend_url: str = "http://localhost:8000"
    cortex_internal_api_key: str = ""

    redis_url: str = "redis://localhost:6377"

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"

    service_port: int = 8001
    debug: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def resolved_jwt_secret(self) -> str:
        return self.jwt_secret_key or "change-this-in-production-super-secret-key"


settings = Settings()
