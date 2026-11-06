from pydantic import BaseModel, ConfigDict, Field


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeoutMs: int = Field(strict=True, ge=1, le=30000)


class MoveRequest(ActionRequest):
    x: int = Field(strict=True, ge=-(2**31), lt=2**31)
    y: int = Field(strict=True, ge=-(2**31), lt=2**31)
