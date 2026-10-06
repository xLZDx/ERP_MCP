from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScenarioManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: Literal["ferma-1c-scenario/v1"]
    scenario_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    universe_id: str = Field(min_length=1, max_length=128)
    master_seed: int
    generator_version: str = Field(min_length=1, max_length=128)
    ferma_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    profile_id: str = Field(min_length=1, max_length=128)
    profile_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    logical_clock_epoch: str
    mapping_contract_version: Literal["1"]
    created_at_wall_clock: str
    semantic_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("logical_clock_epoch", "created_at_wall_clock")
    @classmethod
    def timestamp(cls, value: str) -> str:
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("scenario timestamps require a timezone")
        return value
