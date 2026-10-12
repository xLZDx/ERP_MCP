"""PostgreSQL-backed chain for labelled machine two-source profiles.

CLI validate (artifacts + plan authority) -> stored profile -> Registry runtime gate -> native-only consumers.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from argparse import Namespace
from pathlib import Path

import asyncpg
import pytest

from business_ai_gateway.analytics_balance import ANALYTICS_BALANCE_CONCEPT
from business_ai_gateway.compatibility import (
    AdapterProfile,
    CompatibilityStatus,
    OneCCapabilities,
)
from business_ai_gateway.evidence_basis import NATIVE_ONLY_SQL, authorization_scope_sha256
from business_ai_gateway.registry import Registry
from business_ai_gateway.semantic import SemanticProfileUnavailable, canonical_fingerprint
from scripts.real1c import machine_reconciliation as mr
from scripts.semantic_profiles import add_mapping, confirm_mapping, create_profile, validate_profile
from tests.test_analytics_balance_mapping import good_mapping

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires the disposable PostgreSQL database")

PLAN_ID = "erp_mcp-test-2026-10-08T00-00-00-000Z-777777"
PLAN_HASH = "a" * 64


class ConnectionDatabase:
    def __init__(self, connection):
        self.connection = connection

    def require_pool(self):
        return self.connection


def _row(ref: str, debit: str) -> dict:
    return {
        "account": "521.1",
        "analytics": [{"type": "counterparty", "ref": ref}, {"type": "contract", "ref": "k-1"}],
        "currency_ref": "MDL",
        "balance_debit": debit,
        "balance_credit": "0.00",
    }


def _run_record(side: str, method: str, as_of: str, digest: str, run_id: str, parameters: dict) -> dict:
    return {
        "run_id": run_id,
        "side": side,
        "source_identity": f"source-{side}",
        "method": method,
        "parameters": parameters,
        "snapshot": {"kind": "database_copy", "identity": f"snapshot-{side}"},
        "started_at": "2026-10-08T10:00:00+00:00",
        "finished_at": "2026-10-08T10:00:05+00:00",
        "artifact_sha256": digest,
        "code_identity": {"git_head": "abc1234", "script_sha256": "e" * 64},
    }


def _build_cases(root: Path, source_id: str, company_id, *, tamper_case: int | None = None) -> list[dict]:
    cases = []
    for index in range(10):
        as_of = f"2025-{index + 1:02d}-28T23:59:59+00:00"
        parameters = {"as_of": as_of, "account": "521.1", "source_id": source_id, "company_id": str(company_id)}
        directory = root / f"case-{index}"
        directory.mkdir(parents=True)
        digests, run_ids = {}, {}
        for side, method in (("A", mr.MACHINE_METHOD_A), ("B", mr.MACHINE_METHOD_B)):
            run_ids[side] = str(uuid.uuid4())
            payload = {
                "run_id": run_ids[side],
                "method": method,
                "side": side,
                "as_of": as_of,
                "truncated": False,
                "context": parameters,
                "rows": [_row("cp-1", f"{100 + index}.00"), _row("cp-2", "5.50")],
            }
            raw = json.dumps(payload).encode()
            (directory / mr.ARTIFACT_FILES[side]).write_bytes(raw)
            digests[side] = hashlib.sha256(raw).hexdigest()
        if tamper_case == index:
            (directory / mr.ARTIFACT_FILES["B"]).write_bytes(b"{}")
        cases.append(
            {
                "case_id": f"machine-{index}",
                "status": "PASS",
                "result": "MATCH",
                "as_of": as_of,
                "evidence_class": "MACHINE_TWO_SOURCE_RECONCILIATION",
                "comparison_kind": "cross_copy_comparison",
                "native_report_ref": f"machine-artifact:case-{index}",
                "authorized_by": f"ROSETTA_PLAN:{PLAN_ID}:{PLAN_HASH}",
                "run_record_a": _run_record("A", mr.MACHINE_METHOD_A, as_of, digests["A"], run_ids["A"], parameters),
                "run_record_b": _run_record("B", mr.MACHINE_METHOD_B, as_of, digests["B"], run_ids["B"], parameters),
            }
        )
    return cases


def _capabilities(source_id: str, metadata_fingerprint: str, discovered_at: str | None, available: bool = True) -> dict:
    caps = {
        "source_id": source_id,
        "metadata_fingerprint": metadata_fingerprint,
        "registers": [{"entity_set": "AccountingRegister_X", "methods": {"balance": {"available": available}}}],
    }
    if discovered_at:
        caps["discovered_at"] = discovered_at
    return caps


async def _save_capabilities(conn, source_id: str, metadata_fingerprint: str, caps: dict) -> None:
    capability = OneCCapabilities(
        source_id=source_id, platform_version=None, metadata_fingerprint=metadata_fingerprint,
        metadata_supported=True, json_supported=True, atom_supported=False, expand_supported=True,
        entity_set_count=1, adapter_profile=AdapterProfile.ODATA_JSON_V3,
        compatibility_status=CompatibilityStatus.SUPPORTED, evidence={"metadata": "ok"},
        register_capabilities=caps,
    )
    await Registry(ConnectionDatabase(conn), production=False).save_capabilities(capability)


async def _validated(conn, tmp_path: Path, monkeypatch, discovered_at: str | None = None):
    source_id, company_id, profile_id = await _profile(conn, tmp_path, discovered_at)
    monkeypatch.setenv("BAG_MACHINE_RECONCILED_SOURCES", source_id)
    evidence = await _manifest(conn, tmp_path, source_id, company_id, profile_id)
    await validate_profile(_validate_args(profile_id, evidence, tmp_path), conn)
    await conn.execute("RESET ROLE")
    return source_id, company_id, profile_id


def _machine_registry(conn, source_id: str) -> Registry:
    return Registry(ConnectionDatabase(conn), production=False, machine_reconciled_sources=(source_id,))


async def _profile(conn, tmp_path: Path, discovered_at: str | None = None):
    """A draft company-specific profile with exactly one confirmed 521.1 analytics mapping."""
    source_id = f"machine-lane-{uuid.uuid4().hex[:12]}"
    company_id = uuid.uuid4()
    await conn.execute("SET LOCAL ROLE business_ai_admin")
    await conn.execute(
        """INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
           VALUES($1, 'onec', 'onec_auto', 'Machine lane source', 'https://onec.example.test/odata')""",
        source_id,
    )
    await conn.execute(
        """INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
           VALUES($1, $2, 'machine-company', 'Machine company')""",
        company_id,
        source_id,
    )
    await conn.execute("RESET ROLE")
    metadata_fingerprint = "e" * 64
    capability = OneCCapabilities(
        source_id=source_id,
        platform_version=None,
        metadata_fingerprint=metadata_fingerprint,
        metadata_supported=True,
        json_supported=True,
        atom_supported=False,
        expand_supported=True,
        entity_set_count=1,
        adapter_profile=AdapterProfile.ODATA_JSON_V3,
        compatibility_status=CompatibilityStatus.SUPPORTED,
        evidence={"metadata": "ok"},
        register_capabilities=_capabilities(source_id, metadata_fingerprint, discovered_at),
    )
    await Registry(ConnectionDatabase(conn), production=False).save_capabilities(capability)
    await conn.execute("SET LOCAL ROLE business_ai_admin")
    profile_id = await create_profile(
        Namespace(
            preset_id="bp30", source_id=source_id, company_id=str(company_id),
            profile_name="Machine 521.1", profile_file=None, actor="integration-operator",
        ),
        conn,
    )
    mapping = good_mapping()
    mapping["accounts"] = [mapping["accounts"][0]]
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps(mapping), encoding="utf-8")
    confirmation = tmp_path / "confirm.json"
    confirmation.write_text(json.dumps({"evidence_refs": ["operator-review/521-1"], "notes": "ok"}), encoding="utf-8")
    await add_mapping(
        Namespace(profile_id=str(profile_id), concept=ANALYTICS_BALANCE_CONCEPT, mapping_file=str(mapping_file),
                  evidence_file=None, actor="integration-operator"),
        conn,
    )
    await confirm_mapping(
        Namespace(profile_id=str(profile_id), concept=ANALYTICS_BALANCE_CONCEPT, evidence_file=str(confirmation),
                  actor="integration-operator"),
        conn,
    )
    return source_id, company_id, profile_id


async def _manifest(conn, tmp_path: Path, source_id, company_id, profile_id, **case_options) -> Path:
    profile = await conn.fetchrow("SELECT * FROM bag.semantic_profiles WHERE profile_id=$1", profile_id)
    stored = await conn.fetchval(
        "SELECT mapping_json FROM bag.semantic_mappings WHERE profile_id=$1", profile_id
    )
    stored = json.loads(stored) if isinstance(stored, str) else stored
    manifest = {
        "native_reconciliation_cases": _build_cases(tmp_path / "artifacts", source_id, company_id, **case_options),
        "evidence_basis": "MACHINE",
        "machine_scope": {
            "source_id": source_id,
            "company_id": str(company_id),
            "concept": ANALYTICS_BALANCE_CONCEPT,
            "mapping_fingerprint": canonical_fingerprint(stored),
            "metadata_fingerprint": profile["metadata_fingerprint"],
            "capability_fingerprint": profile["capability_fingerprint"],
            "authorization_scope_sha256": authorization_scope_sha256(
                source_id=source_id, company_id=str(company_id), concept=ANALYTICS_BALANCE_CONCEPT, mapping=stored
            ),
        },
    }
    plans = tmp_path / "plans"
    plans.mkdir(exist_ok=True)
    (plans / f"{PLAN_ID}.json").write_text(
        json.dumps(
            {
                "plan_id": PLAN_ID,
                "status": "in-progress",
                "plan_hash": PLAN_HASH,
                "scope": f"scope {manifest['machine_scope']['authorization_scope_sha256']} operator GO",
                "approval": {"approved_by": "GPT-PM", "verdict": "APPROVE", "correlated": True,
                             "approved_plan_hash": PLAN_HASH},
            }
        ),
        encoding="utf-8",
    )
    path = tmp_path / "machine-evidence.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _validate_args(profile_id, evidence_path: Path, tmp_path: Path) -> Namespace:
    return Namespace(
        profile_id=str(profile_id), evidence_file=str(evidence_path), actor="integration-operator",
        artifacts_root=str(tmp_path / "artifacts"), plans_dir=str(tmp_path / "plans"),
    )


@pytest.fixture
def machine_env(monkeypatch):
    monkeypatch.setenv("BAG_ENVIRONMENT", "test")


@pytest.mark.asyncio
async def test_machine_profile_chain_validates_serves_and_stays_out_of_native_consumers(
    tmp_path, machine_env, monkeypatch
):
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        source_id, company_id, profile_id = await _profile(conn, tmp_path)
        evidence = await _manifest(conn, tmp_path, source_id, company_id, profile_id)

        # The CLI refuses while the source is not in the allow-list.
        with pytest.raises(ValueError, match="BAG_MACHINE_RECONCILED_SOURCES"):
            await validate_profile(_validate_args(profile_id, evidence, tmp_path), conn)

        monkeypatch.setenv("BAG_MACHINE_RECONCILED_SOURCES", source_id)
        await validate_profile(_validate_args(profile_id, evidence, tmp_path), conn)
        await conn.execute("RESET ROLE")
        assert await conn.fetchval(
            "SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        ) == "VALIDATED"

        served = await Registry(
            ConnectionDatabase(conn), production=False, machine_reconciled_sources=(source_id,)
        ).require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)
        assert served["profile_kind"] == "VALIDATED_MACHINE_RECONCILED"
        assert served["audit_detail_code"] == "MACHINE_RECONCILED_PROFILE"

        # Without the allow-list (production-like registry) the same stored row is refused.
        with pytest.raises(SemanticProfileUnavailable):
            await Registry(ConnectionDatabase(conn), production=False).require_semantic_mapping(
                source_id, company_id, ANALYTICS_BALANCE_CONCEPT
            )
        # Another concept on the same source never resolves.
        with pytest.raises(SemanticProfileUnavailable):
            await Registry(
                ConnectionDatabase(conn), production=False, machine_reconciled_sources=(source_id,)
            ).require_semantic_mapping(source_id, company_id, "payable.balance")
        # The native-only SQL twin excludes the profile for every other VALIDATED consumer.
        native_visible = await conn.fetchval(
            f"SELECT count(*) FROM bag.semantic_profiles p WHERE p.profile_id=$1 AND {NATIVE_ONLY_SQL}",
            profile_id,
        )
        assert native_visible == 0
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_machine_validate_refuses_tampered_artifact_and_keeps_profile_unvalidated(
    tmp_path, machine_env, monkeypatch
):
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        source_id, company_id, profile_id = await _profile(conn, tmp_path)
        monkeypatch.setenv("BAG_MACHINE_RECONCILED_SOURCES", source_id)
        evidence = await _manifest(conn, tmp_path, source_id, company_id, profile_id, tamper_case=3)
        with pytest.raises(mr.MachineReconciliationError):
            await validate_profile(_validate_args(profile_id, evidence, tmp_path), conn)
        await conn.execute("RESET ROLE")
        assert await conn.fetchval(
            "SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        ) == "NEEDS_VALIDATION"
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_native_only_consumers_refuse_the_machine_profile(tmp_path, machine_env, monkeypatch):
    from types import SimpleNamespace

    from business_ai_gateway.admin_access import explain_access
    from business_ai_gateway.company_scope import CompanyScopeResolver, CompanyScopeUnavailable

    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        source_id, company_id, profile_id = await _validated(conn, tmp_path, monkeypatch)
        await conn.execute(
            """INSERT INTO bag.company_scope_mappings(scope_mapping_id, profile_id, entity_set, company_property,
               literal_kind, created_by) VALUES($1,$2,'Document_X','Организация_Key','guid','test')""",
            uuid.uuid4(),
            profile_id,
        )
        row = await conn.fetchrow(
            "SELECT metadata_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        )
        with pytest.raises(CompanyScopeUnavailable):
            await CompanyScopeResolver(ConnectionDatabase(conn)).mapping(
                source=SimpleNamespace(id=source_id),
                company=SimpleNamespace(id=company_id),
                entity_set="Document_X",
                metadata_fingerprint=row["metadata_fingerprint"],
                drift_status="STABLE",
            )
        ctx = SimpleNamespace(token=SimpleNamespace(subject="s"), groups=[])
        explained = await explain_access(
            conn, ctx=ctx, kind="subject", principal_id="s", source_id=source_id,
            entity_set="Document_X", limit=50, offset=0,
        )
        text = json.dumps(explained, default=str)
        assert "company_operation" in text  # the company row is present ...
        assert "mapping_candidate_requires_live_checks" not in text  # ... and the machine profile is no candidate
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_registry_refuses_tampered_machine_profile(tmp_path, machine_env, monkeypatch):
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        source_id, company_id, profile_id = await _validated(conn, tmp_path, monkeypatch)
        registry = _machine_registry(conn, source_id)
        await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)  # baseline serves

        evidence = await conn.fetchval(
            "SELECT validation_evidence_json FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        )
        evidence = json.loads(evidence) if isinstance(evidence, str) else evidence

        mixed = json.loads(json.dumps(evidence))  # one native case slipped in behind the CLI's back
        mixed["native_reconciliation_cases"][0] = {"case_id": "n", "status": "PASS", "native_report_ref": "r"}
        forged = json.loads(json.dumps(evidence))  # scope no longer matches the profile mapping
        forged["machine_scope"]["mapping_fingerprint"] = "0" * 64
        for tampered in (mixed, forged):
            await conn.execute(
                "UPDATE bag.semantic_profiles SET validation_evidence_json=$2::jsonb WHERE profile_id=$1",
                profile_id, json.dumps(tampered),
            )
            with pytest.raises(SemanticProfileUnavailable):
                await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)
        await conn.execute(
            "UPDATE bag.semantic_profiles SET validation_evidence_json=$2::jsonb WHERE profile_id=$1",
            profile_id, json.dumps(evidence),
        )
        await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_probe_stamp_does_not_stale_the_profile_but_a_capability_change_does(
    tmp_path, machine_env, monkeypatch
):
    from business_ai_gateway.semantic import SemanticProfileStale

    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        source_id, company_id, profile_id = await _validated(
            conn, tmp_path, monkeypatch, discovered_at="2026-10-08T01:00:00Z"
        )
        meta = (
            await conn.fetchrow(
                "SELECT metadata_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
            )
        )["metadata_fingerprint"]
        registry = _machine_registry(conn, source_id)
        await _save_capabilities(conn, source_id, meta, _capabilities(source_id, meta, "2026-10-08T09:00:00Z"))
        served = await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)
        assert served["profile_kind"] == "VALIDATED_MACHINE_RECONCILED"
        await _save_capabilities(
            conn, source_id, meta, _capabilities(source_id, meta, "2026-10-08T10:00:00Z", available=False)
        )
        with pytest.raises(SemanticProfileStale):
            await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["no_artifacts_root", "no_plans_dir", "company_less", "other_account", "extra_key", "not_test_env"]
)
async def test_cli_refuses_machine_evidence_outside_its_limits(tmp_path, machine_env, monkeypatch, case):
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        source_id, company_id, profile_id = await _profile(conn, tmp_path)
        monkeypatch.setenv("BAG_MACHINE_RECONCILED_SOURCES", source_id)
        evidence_path = await _manifest(conn, tmp_path, source_id, company_id, profile_id)
        args = _validate_args(profile_id, evidence_path, tmp_path)
        if case == "no_artifacts_root":
            args.artifacts_root = None
        elif case == "no_plans_dir":
            args.plans_dir = None
        elif case == "company_less":
            await conn.execute("UPDATE bag.semantic_profiles SET company_id=NULL WHERE profile_id=$1", profile_id)
        elif case == "other_account":
            mapping = await conn.fetchval(
                "SELECT mapping_json FROM bag.semantic_mappings WHERE profile_id=$1", profile_id
            )
            mapping = json.loads(mapping) if isinstance(mapping, str) else mapping
            mapping["accounts"][0]["code"] = "521.2"
            await conn.execute(
                "UPDATE bag.semantic_mappings SET mapping_json=$2::jsonb WHERE profile_id=$1",
                profile_id, json.dumps(mapping),
            )
        elif case == "extra_key":
            manifest = json.loads(evidence_path.read_text(encoding="utf-8"))
            manifest["unexpected"] = 1
            evidence_path.write_text(json.dumps(manifest), encoding="utf-8")
        elif case == "not_test_env":
            monkeypatch.setenv("BAG_ENVIRONMENT", "development")
        with pytest.raises((ValueError, mr.MachineReconciliationError)):
            await validate_profile(args, conn)
        await conn.execute("RESET ROLE")
        status = await conn.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id)
        assert status != "VALIDATED"
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_cli_refuses_a_legacy_shaped_machine_manifest(tmp_path, machine_env, monkeypatch):
    """Removing every label must not turn machine-origin cases into native evidence (GPT-PM M-01)."""
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        source_id, company_id, profile_id = await _profile(conn, tmp_path)
        monkeypatch.setenv("BAG_MACHINE_RECONCILED_SOURCES", source_id)
        evidence_path = await _manifest(conn, tmp_path, source_id, company_id, profile_id)
        manifest = json.loads(evidence_path.read_text(encoding="utf-8"))
        manifest.pop("machine_scope")
        manifest.pop("evidence_basis")
        for case in manifest["native_reconciliation_cases"]:
            case.pop("evidence_class")
        evidence_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ValueError):
            await validate_profile(_validate_args(profile_id, evidence_path, tmp_path), conn)
        await conn.execute("RESET ROLE")
        status = await conn.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id)
        assert status != "VALIDATED"
    finally:
        await tx.rollback()
        await conn.close()
