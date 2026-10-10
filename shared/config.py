from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    pulsepay_currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    service_name: str = "api"
    log_level: str = "INFO"
    db_pool_size: int = Field(default=8, ge=1, le=32)
    db_timeout_seconds: float = Field(default=5, gt=0, le=30)
    request_timeout_seconds: float = Field(default=12, gt=0, le=60)
    cache_ttl_seconds: int = Field(default=5, ge=1, le=60)
    stream_name: str = "pulsepay:events:v1"
    consumer_group: str = "pulsepay-projection-v1"
    worker_poll_seconds: float = Field(default=1, ge=0.1, le=10)
    reclaim_idle_ms: int = Field(default=10000, ge=100, le=60000)
    seed_account_count: int = Field(default=200, ge=2, le=500)
    seed_balance_minor: int = Field(default=100000, ge=1, le=1000000000)
    seed_version: str = "pulsepay-v1"
    api_url: str = "http://api:8080"
    verifier_interval_seconds: float = Field(default=15, ge=1, le=300)
    verifier_report_url: str = "http://verifier:9100/report"


@lru_cache
def settings() -> Settings:
    return Settings()
