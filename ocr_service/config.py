"""
OCR Service Configuration

All configuration via environment variables with Pydantic validation.
"""

import os
from pydantic import Field
from pydantic_settings import BaseSettings


class OCRServiceConfig(BaseSettings):
    """OCR Service configuration from environment variables."""
    
    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    input_stream_key: str = Field(default="ocr:processor:stream", alias="OCR_INPUT_STREAM")
    output_stream_key: str = Field(default="llm:processor:stream", alias="LLM_OUTPUT_STREAM")
    consumer_group: str = Field(default="ocr-external-workers", alias="OCR_CONSUMER_GROUP")
    consumer_id: str = Field(default_factory=lambda: f"ocr-worker-{os.getpid()}", alias="OCR_CONSUMER_ID")
    
    # MinIO
    minio_endpoint: str = Field(default="localhost:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="cortex-videos", alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")
    
    # MongoDB
    mongodb_url: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URL")
    mongodb_db: str = Field(default="cortex", alias="MONGODB_DB_NAME")
    
    # Processing
    transcript_wait_timeout: float = Field(default=300.0, alias="TRANSCRIPT_WAIT_TIMEOUT_SECONDS")
    temp_dir: str = Field(default="/tmp/ocr_processing", alias="OCR_TEMP_DIR")
    
    # Logging
    log_level: str = Field(default="INFO", alias="OCR_LOG_LEVEL")
    
    class Config:
        env_file = ".env"
        populate_by_name = True


settings = OCRServiceConfig()
