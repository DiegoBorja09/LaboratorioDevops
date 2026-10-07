from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "service-a"
    service_b_url: str = Field(default="http://service-b:8080", min_length=1)
    service_b_timeout_seconds: float = Field(default=5, gt=0)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(extra="ignore", frozen=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
