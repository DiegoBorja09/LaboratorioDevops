from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "service-a"
    service_b_url: str = Field(default="http://service-b:8080", min_length=1)
    service_b_timeout_seconds: float = Field(default=5, gt=0)
    data_service_url: str | None = None
    data_service_audience: str | None = None
    data_service_auth_enabled: bool = False
    data_service_timeout_seconds: float = Field(default=5, gt=0)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    @field_validator("data_service_url", "data_service_audience", mode="before")
    @classmethod
    def _blank_data_service_url(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            return None
        return stripped.rstrip("/")

    @property
    def data_service_token_audience(self) -> str | None:
        return self.data_service_audience or self.data_service_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
