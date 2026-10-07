"""Compare independently supplied scoped observations; never compute an oracle."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def number(value: str) -> Decimal:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("observation amounts must be bounded decimal strings")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError("invalid observation decimal") from None
    if not parsed.is_finite():
        raise ValueError("observation decimal must be finite")
    return parsed


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    plane: Literal["native", "erp_mcp", "ferma"]
    test_level: Literal["L1", "L2-A", "L2-B", "L3"]
    scenario_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    company_id: str = Field(min_length=1, max_length=128)
    period: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=3, max_length=3)
    metadata_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin_ref: str = Field(min_length=1, max_length=256)
    measurements: dict[str, str] = Field(min_length=1, max_length=10_000)
    truncated: bool = False

    @field_validator("measurements")
    @classmethod
    def measurements_are_decimal(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if not key or len(key) > 128:
                raise ValueError("observation key is invalid")
            number(value)
        return values


def reconcile(native: Observation | None, actual: Observation | None,
              oracle: Observation | None = None, *, tolerances: dict[str, str]) -> dict[str, object]:
    if native is None or actual is None:
        return {"status": "EVIDENCE_REQUIRED", "code": "NATIVE_OR_GATEWAY_OBSERVATION_MISSING"}
    native = Observation.model_validate(native.model_dump())
    actual = Observation.model_validate(actual.model_dump())
    oracle = Observation.model_validate(oracle.model_dump()) if oracle else None
    if native.plane != "native" or actual.plane != "erp_mcp" or (oracle and oracle.plane != "ferma"):
        return {"status": "INCONCLUSIVE", "code": "OBSERVATION_PLANE_MISMATCH"}
    observations = [native, actual, *([oracle] if oracle else [])]
    scopes = ("test_level", "scenario_id", "run_id", "source_id", "company_id", "period", "currency",
              "metadata_fingerprint", "profile_fingerprint")
    if any(any(getattr(item, key) != getattr(native, key) for key in scopes) for item in observations):
        return {"status": "INCONCLUSIVE", "code": "OBSERVATION_SCOPE_MISMATCH"}
    if len({item.origin_ref for item in observations}) != len(observations):
        return {"status": "INCONCLUSIVE", "code": "OBSERVATION_ORIGIN_NOT_INDEPENDENT"}
    if any(item.truncated for item in observations):
        return {"status": "INCONCLUSIVE", "code": "OBSERVATION_TRUNCATED"}
    keys = set(native.measurements)
    if any(set(item.measurements) != keys for item in observations) or set(tolerances) != keys:
        return {"status": "INCONCLUSIVE", "code": "MEASUREMENTS_OR_TOLERANCE_INCOMPLETE"}
    tolerance_values = {key: number(value) for key, value in tolerances.items()}
    if any(value < 0 for value in tolerance_values.values()):
        raise ValueError("tolerances must be nonnegative")
    mismatches = []
    for item in observations[1:]:
        for key in sorted(keys):
            if abs(number(item.measurements[key]) - number(native.measurements[key])) > tolerance_values[key]:
                mismatches.append({"plane": item.plane, "measurement": key})
    return {
        "status": "FINDING" if mismatches else "PASS", "test_level": native.test_level,
        "scope_fingerprint": hashlib.sha256(json.dumps([getattr(native, key) for key in scopes]).encode()).hexdigest(),
        "tolerance_fingerprint": hashlib.sha256(json.dumps(tolerances, sort_keys=True).encode()).hexdigest(),
        "observation_fingerprints": {item.plane: hashlib.sha256(json.dumps(item.model_dump(), sort_keys=True).encode()).hexdigest()
                                     for item in observations},
        "mismatches": mismatches, "oracle_compared": oracle is not None,
        "production_approval": False,
    }
