from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from pathlib import Path

import pytest

from testbed.ferma_onec.package_loader import SeedInputs, load_seed_inputs
from testbed.ferma_onec.target_guard import SyntheticTarget, validate_target


def scenario(root: Path, *, total=False, duplicate=False):
    root.mkdir()
    (root / "expected").mkdir()
    manifest = {
        "schema_version": "ferma-1c-scenario/v1", "scenario_id": "fixture-scenario",
        "run_id": "fixture-run", "universe_id": "fixture-universe", "master_seed": 1,
        "generator_version": "contract-fixture", "ferma_commit": "a" * 40,
        "profile_id": "fixture-profile", "profile_digest": "sha256:" + "b" * 64,
        "logical_clock_epoch": "2026-01-01T00:00:00+00:00",
        "mapping_contract_version": "1", "created_at_wall_clock": "2026-01-01T00:00:00+00:00",
        "semantic_digest": "sha256:" + "c" * 64,
    }
    event = {
        "event_id": "event-1", "event_type": "com.ferma.trade.executed.v1",
        "schema_version": "1.0.0", "simulation_tick": 0, "correlation_id": "fixture",
        "business_date": "2026-01-01T00:00:00+00:00", "trade_id": "trade-1",
        "idempotency_key": "trade-1", "quantity": "3", "unit_price": "2",
        "scenario_id": "fixture-scenario", "run_id": "fixture-run",
        "universe_id": "fixture-universe",
    }
    if total:
        event["line_total"] = "6"
    data = {"manifest.json": json.dumps(manifest), "master-data.jsonl": '{"company_id":"A"}\n',
            "events.jsonl": json.dumps(event) + "\n",
            "expected/positions.jsonl": '{"oracle_only":"do-not-seed"}\n'}
    if duplicate:
        data["events.jsonl"] *= 2
    for name, raw in data.items():
        (root / name).write_text(raw, encoding="utf-8")
    (root / "checksums.sha256").write_text("\n".join(
        f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}" for name in data
    ), encoding="utf-8")


def test_seed_inputs_exclude_oracle_and_are_immutable(tmp_path):
    package = tmp_path / "scenario"
    scenario(package)
    loaded = load_seed_inputs(package)
    assert {field.name for field in fields(SeedInputs)} == {"manifest", "master_data", "events"}
    assert "do-not-seed" not in repr(loaded)
    with pytest.raises(TypeError):
        loaded.events[0]["quantity"] = "999"


@pytest.mark.parametrize("kind", ["digest", "traversal", "extra", "duplicate", "derived"])
def test_package_rejects_corruption_and_oracle_contamination(tmp_path, kind):
    package = tmp_path / "scenario"
    scenario(package, total=kind == "derived", duplicate=kind == "duplicate")
    if kind == "digest":
        (package / "events.jsonl").write_text('{}', encoding="utf-8")
    if kind == "traversal":
        with (package / "checksums.sha256").open("a", encoding="utf-8") as stream:
            stream.write("\n" + "d" * 64 + "  ../outside.json")
    if kind == "extra":
        (package / "unverified.json").write_text('{}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_seed_inputs(package)


def test_target_guard_binds_marker_scope_credentials_and_fingerprint(tmp_path):
    target = SyntheticTarget(environment="SYNTHETIC_TEST", marker="ERP_MCP_SYNTHETIC_TESTBED_V1",
                             source_id="synthetic-a", base_path=str(tmp_path.resolve()),
                             metadata_fingerprint="a" * 64, write_secret_ref="test-write",
                             read_secret_ref="test-observe")
    marker = tmp_path / ".erp_mcp_synthetic_target.json"
    marker.write_text(target.model_dump_json(), encoding="utf-8")
    kwargs = {"allowed_paths": frozenset({tmp_path}), "production_source_ids": frozenset(),
              "run_id": "fixture-run", "expected_metadata": "a" * 64}
    assert validate_target(target, **kwargs) == tmp_path.resolve()
    with pytest.raises(PermissionError):
        validate_target(target, **{**kwargs, "production_source_ids": frozenset({"synthetic-a"})})
    with pytest.raises(PermissionError):
        validate_target(target, **{**kwargs, "expected_metadata": "b" * 64})
    with pytest.raises(PermissionError):
        validate_target(target, **{**kwargs, "allowed_paths": frozenset()})
    with pytest.raises(PermissionError):
        validate_target(target.model_copy(update={"write_secret_ref": "test-observe"}), **kwargs)
    with pytest.raises(ValueError):
        validate_target(target.model_copy(update={"environment": "production"}), **kwargs)


def test_production_artifact_excludes_testbed_modules():
    root = Path(__file__).parents[1]
    assert 'where = ["src"]' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "testbed" in (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for source in (root / "src").rglob("*.py"):
        assert "testbed.ferma_onec" not in source.read_text(encoding="utf-8")
