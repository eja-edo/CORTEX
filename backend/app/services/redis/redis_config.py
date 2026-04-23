"""
Redis configuration for standardized stream processing.

Extracted from stt_service config - single source of truth for all services.
"""

from dataclasses import dataclass


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


def create_redis_config_from_env() -> RedisConfig:
    """
    Create RedisConfig from environment variables or backend settings.
    
    This function bridges backend's settings with the standardized RedisConfig.
    """
    import os
    from app.config import settings
    
    # Parse REDIS_URL if available
    redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379/0')
    
    # Parse host, port, db from URL
    # Format: redis://[:password@]host[:port][/db]
    host = "localhost"
    port = 6379
    db = 0
    password = ""
    
    if redis_url:
        # Simple URL parsing
        if "://" in redis_url:
            scheme, rest = redis_url.split("://", 1)
            if "@" in rest:
                auth_part, rest = rest.rsplit("@", 1)
                password = auth_part.lstrip(":")
            
            if "/" in rest:
                host_port, db_str = rest.rsplit("/", 1)
                try:
                    db = int(db_str)
                except ValueError:
                    db = 0
            else:
                host_port = rest
            
            if ":" in host_port:
                host, port_str = host_port.rsplit(":", 1)
                try:
                    port = int(port_str)
                except ValueError:
                    port = 6379
            else:
                host = host_port
    
    return RedisConfig(
        host=os.getenv("REDIS_HOST", host),
        port=int(os.getenv("REDIS_PORT", port)),
        password=os.getenv("REDIS_PASSWORD", password),
        db=int(os.getenv("REDIS_DB", db)),
        claim_min_idle_time_ms=int(os.getenv("REDIS_CLAIM_MIN_IDLE_TIME_MS", 60000)),
        block_timeout_ms=int(os.getenv("REDIS_BLOCK_TIMEOUT_MS", 5000)),
        max_retries=int(os.getenv("REDIS_MAX_RETRIES", 3)),
        max_connections=int(os.getenv("REDIS_MAX_CONNECTIONS", 10)),
        socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT", 30.0)),
        socket_connect_timeout=float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", 10.0)),
        heartbeat_interval_sec=float(os.getenv("REDIS_HEARTBEAT_INTERVAL_SEC", 10.0)),
        worker_timeout_sec=float(os.getenv("REDIS_WORKER_TIMEOUT_SEC", 30.0)),
    )
