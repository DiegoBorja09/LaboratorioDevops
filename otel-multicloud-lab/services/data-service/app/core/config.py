from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "data-service"
    gcp_database_url: str = ""
    aws_database_url: str = ""
    log_level: str = "INFO"
    chaos_enabled: bool = False
    chaos_error_rate: float = Field(default=0, ge=0, le=1)
    chaos_delay_ms: int = Field(default=0, ge=0, le=60_000)
    chaos_token: str = ""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    @field_validator("gcp_database_url", "aws_database_url", "chaos_token", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
