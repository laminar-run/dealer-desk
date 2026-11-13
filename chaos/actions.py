import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chaos.engine import SCENARIO_MAP

FREEZE_MAX_MS = int(os.environ.get("DEALERDESK_FREEZE_MAX_MS", "60000"))


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeoutMs: int = Field(strict=True, ge=1, le=30000)


class MoveRequest(ActionRequest):
    x: int = Field(strict=True, ge=-(2**31), lt=2**31)
    y: int = Field(strict=True, ge=-(2**31), lt=2**31)


class ScenarioRequest(ActionRequest):
    scenario: Literal[tuple(SCENARIO_MAP)]
    durationMs: int | None = Field(default=None, strict=True, ge=1, le=FREEZE_MAX_MS)

    @model_validator(mode="after")
    def duration_only_for_freeze(self):
        if self.durationMs is not None and self.scenario != "fake_freeze":
            raise ValueError("durationMs is only valid for fake_freeze")
        return self
