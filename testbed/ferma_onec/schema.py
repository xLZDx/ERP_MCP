from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScenarioManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: Literal["ferma-1c-scenario/v1"]
    scenario_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    universe_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    master_seed: int
    generator_version: str = Field(min_length=1, max_length=128)
    ferma_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    profile_id: str = Field(min_length=1, max_length=128)
    profile_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    logical_clock_epoch: str
    mapping_contract_version: Literal["1"]
    created_at_wall_clock: str
    semantic_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    semantic_digest_scheme: Literal['ERP_MCP_EXPORT_SHA256_JSON_V1'] | None = None
    ferma_digest_scheme: Literal['SEMANTIC_V3'] | None = None
    ferma_event_stream_digest: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    ferma_dataset_digest: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    ferma_profile_digest: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    oracle_rules_version: str | None = Field(default=None, min_length=1, max_length=128)
    output_class: Literal['INTERNAL_TEST_ONLY'] = 'INTERNAL_TEST_ONLY'
    ferma_clock_timezone_policy: Literal['NAIVE_LOGICAL_AS_UTC_V1'] | None = None

    @field_validator("logical_clock_epoch", "created_at_wall_clock")
    @classmethod
    def timestamp(cls, value: str) -> str:
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("scenario timestamps require a timezone")
        return value
