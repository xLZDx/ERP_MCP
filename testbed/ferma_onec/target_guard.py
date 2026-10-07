"""Test-only target authorization; never authorizes a production source or arbitrary path."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SyntheticTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    environment: Literal["SYNTHETIC_TEST"]
    marker: Literal["ERP_MCP_SYNTHETIC_TESTBED_V1"]
    source_id: str = Field(min_length=1, max_length=128)
    base_path: str
    metadata_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    write_secret_ref: str = Field(min_length=1, max_length=256)
    read_secret_ref: str = Field(min_length=1, max_length=256)


def validate_target(target: SyntheticTarget, *, allowed_paths: frozenset[Path],
                    production_source_ids: frozenset[str], run_id: str,
                    expected_metadata: str) -> Path:
    # Pydantic model_copy/model_construct can bypass validation; revalidate at the write guard.
    target = SyntheticTarget.model_validate(target.model_dump())
    if not run_id or target.source_id in production_source_ids:
        raise PermissionError("synthetic target/run is not authorized")
    path = Path(target.base_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise PermissionError("synthetic target path is not approved")
    if path.resolve() not in {item.resolve() for item in allowed_paths}:
        raise PermissionError("synthetic target is outside the allowlist")
    if target.write_secret_ref == target.read_secret_ref:
        raise PermissionError("test write and observation identities must be distinct")
    if target.metadata_fingerprint != expected_metadata:
        raise PermissionError("synthetic target metadata drifted")
    marker = path / ".erp_mcp_synthetic_target.json"
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 4096:
        raise PermissionError("synthetic target marker is absent or invalid")
    recorded = SyntheticTarget.model_validate_json(marker.read_bytes())
    if recorded != target:
        raise PermissionError("synthetic marker does not bind this exact target")
    return path.resolve()
