from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "distributed-rate-limiter"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_socket_timeout: float = 5.0
    redis_socket_connect_timeout: float = 5.0
    redis_max_connections: int = 50
    redis_retry_on_timeout: bool = True

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    rate_limit_strategy: str = "token_bucket"
    rate_limit_fallback_allow: bool = True

    # Token bucket
    token_bucket_capacity: int = 100
    token_bucket_refill_rate: float = 1.67

    # Cache
    cache_enabled: bool = True
    cache_default_ttl: int = 300
    cache_max_key_length: int = 200

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    # Metrics
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"

    # CORS
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
