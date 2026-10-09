"""Functional PostgreSQL tests for the machine two-source profile chain (gaps left by the sprint tests).

Synthetic data only.  Every test runs inside a transaction that is rolled back.
"""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace

import asyncpg
import pytest

from business_ai_gateway.analytics_balance import ANALYTICS_BALANCE_CONCEPT
from business_ai_gateway.evidence_basis import (
    BASIS_NATIVE,
    NATIVE_ONLY_SQL,
    EvidenceBasisError,
    stored_evidence_basis,
)
from business_ai_gateway.registry import Registry
from business_ai_gateway.semantic import SemanticProfileUnavailable
from scripts.semantic_profiles import validate_profile
from tests.test_machine_profile_postgres import (
    ConnectionDatabase,
    _machine_registry,
    _manifest,
    _profile,
    _validate_args,
    _validated,
)

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires the disposable PostgreSQL database")


@pytest.fixture
def machine_env(monkeypatch):
    monkeypatch.setenv("BAG_ENVIRONMENT", "test")


class _Tx:
    async def __aenter__(self):
        self.conn = await asyncpg.connect(DATABASE_URL)
        self.tx = self.conn.transaction()
        await self.tx.start()
        return self.conn

    async def __aexit__(self, *exc):
        await self.tx.rollback()
        await self.conn.close()


def _native_manifest(n: int = 10) -> dict:
    return {
        "native_reconciliation_cases": [
            {"case_id": f"n-{i}", "status": "PASS", "native_report_ref": f"r-{i}"} for i in range(n)
        ]
    }


async def _native_validated(conn, tmp_path):
    source_id, company_id, profile_id = await _profile(conn, tmp_path)
    path = tmp_path / "native.json"
    path.write_text(json.dumps(_native_manifest()), encoding="utf-8")
    args = SimpleNamespace(
        profile_id=str(profile_id), evidence_file=str(path), actor="op", artifacts_root=None, plans_dir=None
    )
    await validate_profile(args, conn)
    await conn.execute("RESET ROLE")
    return source_id, company_id, profile_id


async def _insert_scope_mapping(conn, profile_id, entity_set="Document_X"):
    await conn.execute(
        """INSERT INTO bag.company_scope_mappings(scope_mapping_id, profile_id, entity_set, company_property,
           literal_kind, created_by) VALUES($1,$2,$3,'Organization_Key','guid','test')""",
        uuid.uuid4(), profile_id, entity_set,
    )


# ---------------------------------------------------------------- T1


@pytest.mark.asyncio
async def test_native_profile_is_visible_to_native_only_consumers(tmp_path, machine_env):
    from business_ai_gateway.admin_access import explain_access
    from business_ai_gateway.company_scope import CompanyScopeResolver

    async with _Tx() as conn:
        source_id, company_id, profile_id = await _native_validated(conn, tmp_path)
        assert await conn.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id) == "VALIDATED"
        await _insert_scope_mapping(conn, profile_id)
        meta = await conn.fetchval("SELECT metadata_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1", profile_id)
        mapping = await CompanyScopeResolver(ConnectionDatabase(conn)).mapping(
            source=SimpleNamespace(id=source_id), company=SimpleNamespace(id=company_id),
            entity_set="Document_X", metadata_fingerprint=meta, drift_status="STABLE",
        )
        assert mapping.profile_id == profile_id
        ctx = SimpleNamespace(token=SimpleNamespace(subject="s"), groups=[])
        explained = await explain_access(
            conn, ctx=ctx, kind="subject", principal_id="s", source_id=source_id,
            entity_set="Document_X", limit=50, offset=0,
        )
        assert "mapping_candidate_requires_live_checks" in json.dumps(explained, default=str)
        # a native profile is served as native by the runtime gate, with or without the allow-list
        for registry in (Registry(ConnectionDatabase(conn), production=False), _machine_registry(conn, source_id)):
            served = await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)
            assert served["profile_kind"] == "VALIDATED_NATIVE"
            assert served["audit_detail_code"] is None


_CASE = {"case_id": "c", "status": "PASS", "native_report_ref": "r"}


def _cases(n=10, **extra):
    return [{**_CASE, "case_id": f"c{i}", "native_report_ref": f"r{i}", **extra} for i in range(n)]


SHAPES = {
    "legacy_native": {"native_reconciliation_cases": _cases()},
    "native_labelled": {"native_reconciliation_cases": _cases(evidence_class="NATIVE_UI_REPORT")},
    "empty_case_list": {"native_reconciliation_cases": []},
    "nine_cases": {"native_reconciliation_cases": _cases(9)},
    "evidence_class_null": {"native_reconciliation_cases": _cases(evidence_class=None)},
    "machine_reference_only": {"native_reconciliation_cases": _cases(native_report_ref="machine-artifact:x")},
    "comparison_kind_marker_only": {"native_reconciliation_cases": _cases(comparison_kind="cross_copy_comparison")},
    "mixed_declaration": {"native_reconciliation_cases": _cases(), "evidence_basis": "MIXED"},
    "machine_declaration": {"native_reconciliation_cases": _cases(), "evidence_basis": "MACHINE"},
    "machine_scope_present": {"native_reconciliation_cases": _cases(), "machine_scope": {}},
    "case_not_object": {"native_reconciliation_cases": [*_cases(9), "x"]},
    "cases_not_array": {"native_reconciliation_cases": {"a": 1}},
    "evidence_not_object": [1, 2],
}


# bag.native_reconciliation_evidence_valid (CHECK on VALIDATED rows) requires >= 10 cases, so these shapes can never
# be stored on a VALIDATED profile.  The SQL twin no longer relies on that CHECK for the empty list: it is refused by
# NATIVE_ONLY_SQL itself, exactly like stored_evidence_basis, and the parity test below covers it.
DB_CHECK_UNREACHABLE: set[str] = set()


def _python_native(evidence) -> bool:
    try:
        return stored_evidence_basis(evidence) == BASIS_NATIVE
    except EvidenceBasisError:
        return False


@pytest.mark.asyncio
async def test_native_only_sql_never_admits_what_python_refuses():
    """Safety property: SQL-visible implies Python-native.  Every disagreement is collected, then asserted."""
    async with _Tx() as conn:
        sql_looser = []
        sql_stricter = []
        for name, evidence in SHAPES.items():
            if name in DB_CHECK_UNREACHABLE:
                continue  # covered by test_check_constraint_blocks_validated_rows_with_too_few_cases
            visible = await conn.fetchval(
                f"SELECT EXISTS(SELECT 1 FROM (SELECT $1::jsonb AS validation_evidence_json) p WHERE {NATIVE_ONLY_SQL})",
                json.dumps(evidence),
            )
            py = _python_native(evidence)
            if name == "empty_case_list":
                assert not visible and not py, "the empty case list must be refused by both gates"
            if visible and not py:
                sql_looser.append(name)
            if py and not visible:
                sql_stricter.append(name)
        print("SQL stricter than Python (availability only):", sql_stricter)
        assert sql_looser == [], f"native-only SQL admits evidence the Python gate refuses: {sql_looser}"


# ---------------------------------------------------------------- T2


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Acq:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Acq()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _service(conn):
    from business_ai_gateway.admin_mutations import AdminMutationService

    db = SimpleNamespace(require_pool=lambda: _FakePool(conn))
    return AdminMutationService(db, production=False)


def _actor():
    from business_ai_gateway.admin_mutations import AdminActor

    return AdminActor(subject="functional-admin", client_id="functional")


@pytest.mark.asyncio
async def test_admin_validate_refuses_machine_manifest_and_leaves_draft(tmp_path, machine_env, monkeypatch):
    from business_ai_gateway.admin_mutations import AdminValidationError

    async with _Tx() as conn:
        source_id, company_id, profile_id = await _profile(conn, tmp_path)
        monkeypatch.setenv("BAG_MACHINE_RECONCILED_SOURCES", source_id)
        manifest = json.loads((await _manifest(conn, tmp_path, source_id, company_id, profile_id)).read_text("utf-8"))
        await conn.execute("RESET ROLE")
        with pytest.raises((AdminValidationError, ValueError)):  # the Admin API maps ValueError to 4xx (admin_api.py:835)
            await _service(conn).validate_semantic_profile(
                actor=_actor(), profile_id=profile_id, validation_evidence_data=manifest,
                reason="functional test", request_id=uuid.uuid4(), idempotency_key=uuid.uuid4().hex,
            )
        assert await conn.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id) == "NEEDS_VALIDATION"


@pytest.mark.asyncio
async def test_admin_company_scope_mapping_requires_native_profile(tmp_path, machine_env, monkeypatch):
    from business_ai_gateway.admin_mutations import AdminValidationError

    async with _Tx() as conn:
        (tmp_path / "m").mkdir()
        _s, _c, machine_pid = await _validated(conn, tmp_path / "m", monkeypatch)
        kwargs = dict(  # noqa: C408 - keyword form keeps the call-site readable
            actor=_actor(), entity_set="Document_X", company_property="Organization_Key", literal_kind="guid",
            reason="functional test",
        )
        with pytest.raises(AdminValidationError):
            await _service(conn).create_company_scope_mapping(
                profile_id=machine_pid, request_id=uuid.uuid4(), idempotency_key=uuid.uuid4().hex, **kwargs
            )
        assert await conn.fetchval("SELECT count(*) FROM bag.company_scope_mappings WHERE profile_id=$1", machine_pid) == 0
        (tmp_path / "n").mkdir()
        _s2, _c2, native_pid = await _native_validated(conn, tmp_path / "n")
        created = await _service(conn).create_company_scope_mapping(
            profile_id=native_pid, request_id=uuid.uuid4(), idempotency_key=uuid.uuid4().hex, **kwargs
        )
        assert created["profile_id"] == str(native_pid)
        assert await conn.fetchval("SELECT count(*) FROM bag.company_scope_mappings WHERE profile_id=$1", native_pid) == 1


# ---------------------------------------------------------------- T3


async def _add_mapping_row(conn, profile_id, concept, mapping):
    await conn.execute(
        """INSERT INTO bag.semantic_mappings(mapping_id, profile_id, canonical_concept, mapping_json, evidence_json,
           mapping_status, confidence) VALUES($1,$2,$3,$4::jsonb,'{}'::jsonb,'CONFIRMED','HIGH')""",
        uuid.uuid4(), profile_id, concept, json.dumps(mapping),
    )


@pytest.mark.asyncio
async def test_second_mapping_row_blocks_the_machine_profile(tmp_path, machine_env, monkeypatch):
    from business_ai_gateway.semantic import ACCOUNT_TURNOVERS_FIELDS, ACCOUNT_TURNOVERS_METHOD

    async with _Tx() as conn:
        source_id, company_id, profile_id = await _validated(conn, tmp_path, monkeypatch)
        registry = _machine_registry(conn, source_id)
        other = {
            "entity_set": "AccountingRegister_X", "method": ACCOUNT_TURNOVERS_METHOD,
            "company_scope": {"field": "Organization_Key", "value_type": "guid"},
            "output_fields": {f: f"P{i}" for i, f in enumerate(ACCOUNT_TURNOVERS_FIELDS)},
            "required_register_capabilities": [{"entity_set": "AccountingRegister_X", "method": ACCOUNT_TURNOVERS_METHOD}],
        }
        # 1) through the normal write path a late mapping row invalidates the profile (DB trigger): fail closed.
        await conn.execute("SAVEPOINT late")
        await _add_mapping_row(conn, profile_id, "account.balance_and_turnovers", other)
        assert await conn.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id) == "STALE"
        with pytest.raises(SemanticProfileUnavailable):
            await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)
        await conn.execute("ROLLBACK TO SAVEPOINT late")
        # 2) with triggers bypassed (superuser replica mode) the runtime gate itself must still refuse
        await conn.execute("SET LOCAL session_replication_role = replica")
        await _add_mapping_row(conn, profile_id, "account.balance_and_turnovers", other)
        await conn.execute("SET LOCAL session_replication_role = origin")
        assert await conn.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id) == "VALIDATED"
        with pytest.raises(SemanticProfileUnavailable, match="not enabled for this source or concept"):
            await registry.require_semantic_mapping(source_id, company_id, "account.balance_and_turnovers")
        with pytest.raises(SemanticProfileUnavailable, match="exactly one"):
            await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)


@pytest.mark.asyncio
async def test_duplicate_analytics_mapping_row(tmp_path, machine_env, monkeypatch):
    async with _Tx() as conn:
        source_id, company_id, profile_id = await _validated(conn, tmp_path, monkeypatch)
        mapping = await conn.fetchval("SELECT mapping_json FROM bag.semantic_mappings WHERE profile_id=$1", profile_id)
        mapping = json.loads(mapping) if isinstance(mapping, str) else mapping
        try:
            await conn.execute("SAVEPOINT dup")
            await _add_mapping_row(conn, profile_id, ANALYTICS_BALANCE_CONCEPT, mapping)
        except asyncpg.UniqueViolationError:
            await conn.execute("ROLLBACK TO SAVEPOINT dup")
            return  # the database itself forbids a duplicate concept row: stronger than the runtime check
        with pytest.raises(SemanticProfileUnavailable, match="exactly one"):
            await _machine_registry(conn, source_id).require_semantic_mapping(
                source_id, company_id, ANALYTICS_BALANCE_CONCEPT
            )


# ---------------------------------------------------------------- lifecycle gaps


@pytest.mark.asyncio
async def test_revalidation_is_refused_and_writes_a_single_validated_event(tmp_path, machine_env, monkeypatch):
    async with _Tx() as conn:
        _source_id, _company_id, profile_id = await _validated(conn, tmp_path, monkeypatch)
        fp = await conn.fetchval("SELECT profile_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1", profile_id)
        evidence = tmp_path / "machine-evidence.json"
        with pytest.raises(ValueError, match="only a draft profile"):
            await validate_profile(_validate_args(profile_id, evidence, tmp_path), conn)
        await conn.execute("RESET ROLE")
        events = await conn.fetch(
            "SELECT action FROM bag.semantic_profile_events WHERE profile_id=$1 AND action='VALIDATED'", profile_id
        )
        assert len(events) == 1
        assert await conn.fetchval("SELECT profile_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1", profile_id) == fp


@pytest.mark.asyncio
async def test_failure_after_update_rolls_back_status_evidence_and_event(tmp_path, machine_env, monkeypatch):
    import scripts.semantic_profiles as sp

    async with _Tx() as conn:
        source_id, company_id, profile_id = await _profile(conn, tmp_path)
        monkeypatch.setenv("BAG_MACHINE_RECONCILED_SOURCES", source_id)
        evidence = await _manifest(conn, tmp_path, source_id, company_id, profile_id)
        before = await conn.fetchrow(
            "SELECT status, validation_evidence_json::text AS e, profile_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1",
            profile_id,
        )
        real = sp._record_event

        async def boom(conn_, **kw):
            if kw["action"] == "VALIDATED":
                raise RuntimeError("event store down")
            return await real(conn_, **kw)

        monkeypatch.setattr(sp, "_record_event", boom)
        with pytest.raises(RuntimeError, match="event store down"):
            await validate_profile(_validate_args(profile_id, evidence, tmp_path), conn)
        await conn.execute("RESET ROLE")
        after = await conn.fetchrow(
            "SELECT status, validation_evidence_json::text AS e, profile_fingerprint FROM bag.semantic_profiles WHERE profile_id=$1",
            profile_id,
        )
        assert dict(after) == dict(before)
        assert after["status"] == "NEEDS_VALIDATION"
        assert await conn.fetchval(
            "SELECT count(*) FROM bag.semantic_profile_events WHERE profile_id=$1 AND action='VALIDATED'", profile_id
        ) == 0
        monkeypatch.setattr(sp, "_record_event", real)  # recovery after the fault
        await validate_profile(_validate_args(profile_id, evidence, tmp_path), conn)
        await conn.execute("RESET ROLE")
        assert await conn.fetchval("SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id) == "VALIDATED"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["mapping_amount_field", "extra_account"])
async def test_mapping_changed_after_validation_is_refused(tmp_path, machine_env, monkeypatch, change):
    async with _Tx() as conn:
        source_id, company_id, profile_id = await _validated(conn, tmp_path, monkeypatch)
        registry = _machine_registry(conn, source_id)
        await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)
        mapping = await conn.fetchval("SELECT mapping_json FROM bag.semantic_mappings WHERE profile_id=$1", profile_id)
        mapping = json.loads(mapping) if isinstance(mapping, str) else mapping
        if change == "mapping_amount_field":
            mapping["amount_fields"]["debit"] = "OtherField"
        else:
            mapping["accounts"].append({**mapping["accounts"][0], "code": "521.2"})
        await conn.execute(
            "UPDATE bag.semantic_mappings SET mapping_json=$2::jsonb WHERE profile_id=$1", profile_id, json.dumps(mapping)
        )
        with pytest.raises(SemanticProfileUnavailable):
            await registry.require_semantic_mapping(source_id, company_id, ANALYTICS_BALANCE_CONCEPT)


@pytest.mark.asyncio
async def test_company_isolation_and_evidence_transplant(tmp_path, machine_env, monkeypatch):
    """Evidence copied from company A's profile onto company B's VALIDATED row must not be accepted."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    async with _Tx() as conn:
        sa, ca, pa = await _validated(conn, tmp_path / "a", monkeypatch)
        monkeypatch.setenv("BAG_MACHINE_RECONCILED_SOURCES", "")
        sb, cb, pb = await _validated(conn, tmp_path / "b", monkeypatch)
        registry = Registry(ConnectionDatabase(conn), production=False, machine_reconciled_sources=(sa, sb))
        assert (await registry.require_semantic_mapping(sa, ca, ANALYTICS_BALANCE_CONCEPT))["company_id"] == ca
        assert (await registry.require_semantic_mapping(sb, cb, ANALYTICS_BALANCE_CONCEPT))["company_id"] == cb
        with pytest.raises(SemanticProfileUnavailable):  # company A is not served from source B
            await registry.require_semantic_mapping(sb, ca, ANALYTICS_BALANCE_CONCEPT)
        evidence = await conn.fetchval("SELECT validation_evidence_json::text FROM bag.semantic_profiles WHERE profile_id=$1", pa)
        await conn.execute("UPDATE bag.semantic_profiles SET validation_evidence_json=$2::jsonb WHERE profile_id=$1", pb, evidence)
        with pytest.raises(SemanticProfileUnavailable):
            await registry.require_semantic_mapping(sb, cb, ANALYTICS_BALANCE_CONCEPT)


@pytest.mark.asyncio
async def test_artifact_modified_after_validation_is_not_detected_at_runtime(tmp_path, machine_env, monkeypatch):
    """CHARACTERIZATION: runtime never re-reads artifacts, so post-validation byte drift still serves."""
    async with _Tx() as conn:
        source_id, company_id, _profile_id = await _validated(conn, tmp_path, monkeypatch)
        (tmp_path / "artifacts" / "case-0" / "side_b.json").write_bytes(b"{}")
        served = await _machine_registry(conn, source_id).require_semantic_mapping(
            source_id, company_id, ANALYTICS_BALANCE_CONCEPT
        )
        assert served["profile_kind"] == "VALIDATED_MACHINE_RECONCILED"  # documents the gap; see report


def test_production_refuses_the_allow_list():
    with pytest.raises(ValueError, match="MACHINE_RECONCILED_SOURCES_FORBIDDEN_IN_PRODUCTION"):
        Registry(SimpleNamespace(), production=True, machine_reconciled_sources=("x",))


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["empty_case_list", "nine_cases"])
async def test_check_constraint_blocks_validated_rows_with_too_few_cases(tmp_path, machine_env, shape):
    async with _Tx() as conn:
        _s, _c, profile_id = await _profile(conn, tmp_path)
        await conn.execute("RESET ROLE")
        # the table CHECK is an independent second line of defence for short case lists
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE bag.semantic_profiles SET status='VALIDATED', validated_by='x', validated_at=now(),"
                " validation_evidence_json=$2::jsonb WHERE profile_id=$1",
                profile_id, json.dumps(SHAPES[shape]),
            )
