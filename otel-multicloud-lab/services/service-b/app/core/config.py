from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "service-b"
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@postgres:5432/orders_db",
        min_length=1,
    )
    log_level: str = "INFO"

    model_config = SettingsConfigDict(extra="ignore", frozen=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
