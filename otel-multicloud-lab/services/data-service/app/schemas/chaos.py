from pydantic import BaseModel, ConfigDict, Field


class ChaosCommand(BaseModel):
    error_rate: float = Field(ge=0, le=1)
    delay_ms: int = Field(ge=0, le=60_000)
    duration_seconds: float = Field(gt=0, le=600)

    model_config = ConfigDict(extra="ignore")
