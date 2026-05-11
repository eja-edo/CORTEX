"""
Centralized application configuration management.
"""
import os
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Load .env from stt_service directory
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

from utils.decorator import singleton
from utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    app_log_file: str = "logs/app.log"
    metrics_log_file: str = "logs/metrics.log"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5


@dataclass
class MinIOConfig:
    """MinIO/S3 storage configuration."""
    endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin123"
    bucket: str = "livekit-recordings"
    secure: bool = False  # Use HTTPS

@dataclass
class RedisConfig:
    """Redis configuration for streams and caching."""
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0
    # Timeouts and retries
    claim_min_idle_time_ms: int = 60000  # 60 seconds before claiming orphaned tasks
    block_timeout_ms: int = 5000  # Block for 5s waiting for new messages
    max_retries: int = 3  # Max retries for failed tasks
    # Connection pool
    max_connections: int = 10
    socket_timeout: float = 30.0  # Must be > block_timeout_ms/1000 + buffer
    socket_connect_timeout: float = 10.0
    # Worker heartbeat
    heartbeat_interval_sec: float = 10.0
    worker_timeout_sec: float = 30.0


@dataclass
class WhisperConfig:
    """Whisper transcription configuration."""
    model_size: str = "medium"  # tiny, base, small, medium, large-v3
    device: str = "cuda"  # cuda or cpu
    compute_type: str = "float16"  # float16, int8, int8_float16
    cpu_threads: int = 4
    beam_size: int = 1
    vad_filter: bool = True
    sample_rate: int = 16000
    language: str = ""  # Empty = auto-detect, or specify: "en", "vi", "ja", etc.
    diarization_enabled: bool = True
    hf_token: str = ""

@dataclass
class TranscirptConfig:
    chunk_size: int = 50  # chunk_size is the number of segments to batch together before sending to Redis.

@dataclass
class AppConfig:
    """Main application configuration."""
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    minio: MinIOConfig = field(default_factory=MinIOConfig)
    Transcirpt: TranscirptConfig = field(default_factory=TranscirptConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)

    def __post_init__(self):
        """Post-initialization processing."""
        Path(self.logging.app_log_file).parent.mkdir(parents=True, exist_ok=True)
        Path(self.logging.metrics_log_file).parent.mkdir(parents=True, exist_ok=True)

@singleton
class ConfigManager:
    """Configuration manager with environment variable support."""
    
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file
        self._config: Optional[AppConfig] = None
    
    def load_config(self) -> AppConfig:
        """Load configuration from environment variables and config file."""
        if self._config is not None:
            return self._config
        
        # Load from environment variables
        config = AppConfig()

        # Logging configuration
        config.logging.level = os.getenv("LOG_LEVEL", config.logging.level)
        config.logging.format = os.getenv("LOG_FORMAT", config.logging.format)
        config.logging.date_format = os.getenv("LOG_DATE_FORMAT", config.logging.date_format)
        config.logging.app_log_file = os.getenv("LOG_APP_FILE", config.logging.app_log_file)
        config.logging.metrics_log_file = os.getenv("LOG_METRICS_FILE", config.logging.metrics_log_file)
        config.logging.max_file_size = int(os.getenv("LOG_MAX_FILE_SIZE", config.logging.max_file_size))
        config.logging.backup_count = int(os.getenv("LOG_BACKUP_COUNT", config.logging.backup_count))
        
        # MinIO configuration
        config.minio.endpoint = os.getenv("MINIO_ENDPOINT", config.minio.endpoint)
        config.minio.access_key = os.getenv("MINIO_ACCESS_KEY", config.minio.access_key)
        config.minio.secret_key = os.getenv("MINIO_SECRET_KEY", config.minio.secret_key)
        config.minio.bucket = os.getenv("MINIO_BUCKET", config.minio.bucket)
        config.minio.secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
        
        # Transcription configuration
        config.Transcirpt.chunk_size = int(os.getenv("TRANSCRIPT_CHUNK_SIZE", config.Transcirpt.chunk_size))

        # Redis configuration
        config.redis.host = os.getenv("REDIS_HOST", config.redis.host)
        config.redis.port = int(os.getenv("REDIS_PORT", config.redis.port))
        config.redis.password = os.getenv("REDIS_PASSWORD", config.redis.password)
        config.redis.db = int(os.getenv("REDIS_DB", config.redis.db))
        config.redis.claim_min_idle_time_ms = int(os.getenv("REDIS_CLAIM_MIN_IDLE_TIME_MS", config.redis.claim_min_idle_time_ms))
        config.redis.block_timeout_ms = int(os.getenv("REDIS_BLOCK_TIMEOUT_MS", config.redis.block_timeout_ms))
        config.redis.max_retries = int(os.getenv("REDIS_MAX_RETRIES", config.redis.max_retries))
        config.redis.max_connections = int(os.getenv("REDIS_MAX_CONNECTIONS", config.redis.max_connections))
        config.redis.socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT", config.redis.socket_timeout))
        config.redis.socket_connect_timeout = float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", config.redis.socket_connect_timeout))
        config.redis.heartbeat_interval_sec = float(os.getenv("REDIS_HEARTBEAT_INTERVAL_SEC", config.redis.heartbeat_interval_sec))
        config.redis.worker_timeout_sec = float(os.getenv("REDIS_WORKER_TIMEOUT_SEC", config.redis.worker_timeout_sec))
        
        # Whisper configuration
        config.whisper.model_size = os.getenv("WHISPER_MODEL_SIZE", config.whisper.model_size)
        config.whisper.device = os.getenv("WHISPER_DEVICE", config.whisper.device)
        config.whisper.compute_type = os.getenv("WHISPER_COMPUTE_TYPE", config.whisper.compute_type)
        config.whisper.cpu_threads = int(os.getenv("WHISPER_CPU_THREADS", config.whisper.cpu_threads))
        config.whisper.beam_size = int(os.getenv("WHISPER_BEAM_SIZE", config.whisper.beam_size))
        config.whisper.vad_filter = os.getenv("WHISPER_VAD_FILTER", "true").lower() == "true"
        config.whisper.sample_rate = int(os.getenv("WHISPER_SAMPLE_RATE", config.whisper.sample_rate))
        config.whisper.language = os.getenv("WHISPER_LANGUAGE", config.whisper.language)  # "" for auto-detect
        config.whisper.diarization_enabled = os.getenv("WHISPER_DIARIZATION_ENABLED", "true").lower() == "true"
        config.whisper.hf_token = os.getenv("WHISPERX_HF_TOKEN", config.whisper.hf_token)
        self._normalize_whisper_runtime(config.whisper)
        
        self._config = config
        logger.info("Configuration loaded successfully")
        return config

    def _normalize_whisper_runtime(self, whisper: WhisperConfig) -> None:
        """Normalize Whisper runtime config against actual CUDA availability."""
        requested_device = (whisper.device or "cpu").strip().lower()
        requested_compute_type = (whisper.compute_type or "int8").strip().lower()

        if requested_device == "gpu":
            requested_device = "cuda"

        cuda_available = False
        try:
            import torch

            cuda_available = torch.cuda.is_available()
        except Exception:
            cuda_available = False

        if requested_device.startswith("cuda") and not cuda_available:
            logger.warning(
                "WHISPER_DEVICE=%s but CUDA is not available. Falling back to CPU/int8.",
                requested_device,
            )
            whisper.device = "cpu"
            whisper.compute_type = "int8"
            return

        whisper.device = "cuda" if requested_device.startswith("cuda") else "cpu"

        if whisper.device == "cuda":
            whisper.compute_type = requested_compute_type or "float16"
            if whisper.compute_type == "int8":
                logger.warning("WHISPER_COMPUTE_TYPE=int8 on CUDA works but is slower than float16.")
        else:
            if requested_compute_type in {"float16", "int8_float16"}:
                logger.warning(
                    "WHISPER_COMPUTE_TYPE=%s is not suitable for CPU. Switching to int8.",
                    requested_compute_type,
                )
                whisper.compute_type = "int8"
            else:
                whisper.compute_type = requested_compute_type or "int8"
    
    def get_config(self) -> AppConfig:
        """Get current configuration."""
        if self._config is None:
            return self.load_config()
        return self._config
    
    def reload_config(self) -> AppConfig:
        """Reload configuration from sources."""
        self._config = None
        return self.load_config()
    