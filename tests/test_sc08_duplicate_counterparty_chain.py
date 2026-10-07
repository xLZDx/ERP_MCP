"""SC08: duplicate-counterparty candidates through the public MCP tool (synthetic L1, never native).

Chain under test: MCP tool -> registry/semantic profile (PostgreSQL) -> real adapter -> fake sidecar
-> Fake1C. The Fake1C and sidecar apps are wrapped by a request recorder so the tests can prove what
actually reached the upstream (read-only, nothing at all on a denied or fail-closed call).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.adapters.onec.client import OneCTransportError
from business_ai_gateway.audit import query_fingerprint
from business_ai_gateway.business_policy import CAPABILITY_KEYS, CapabilityPolicy
from business_ai_gateway.semantic import canonical_fingerprint
from business_ai_gateway.server import BUSINESS_CAPABILITY_BY_TOOL, build_mcp
from business_ai_gateway.settings import Settings
from business_ai_gateway.testbed.fake1c import SEED
from scripts import synthetic_fixture_profiles as fixture_gen
from tests.sc_stack import ORG_ONE, ORG_TWO, ServerThread, needs_pg
from tests.test_synthetic_fixture_profiles import _stack

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
TOOL = "counterparty_duplicate_candidates"
CONCEPT = "counterparty.duplicate_candidates"
ACTIVITY = "AccumulationRegister_SettlementItems"
CATALOG = "Catalog_Counterparties"

_PARTIES = {row["Code"]: row for row in SEED["counterparties"]}
DUP_A, DUP_B = _PARTIES["C001"], _PARTIES["C001D"]
DUP_REFS = {DUP_A["Ref_Key"], DUP_B["Ref_Key"]}
OTHERS = [_PARTIES[code] for code in ("S001", "C004", "C005")]
ORG_ONE_ACTIVITY_ROWS = sum(
    1 for row in SEED["settlement_items"] if row["Организация_Key"] == ORG_ONE
)
SIDECAR_PATHS = {"/v1/read", "/v1/capabilities/registers"}


def _recorded(app, log):
    async def wrapper(scope, receive, send):
        if scope["type"] == "http":
            log.append((scope["method"], scope["path"]))
        await app(scope, receive, send)

    return wrapper


@pytest.fixture(scope="module")
def rec_fake1c():
    from testbed.fake1c.app import create_app

    log: list = []
    with ServerThread(_recorded(create_app("json"), log)) as server:
        yield f"http://127.0.0.1:{server.port}", log


@pytest.fixture(scope="module")
def rec_sidecar():
    from business_ai_gateway.testbed.fake_sidecar import create_sidecar_app

    log: list = []
    with ServerThread(_recorded(create_sidecar_app("t" * 40), log)) as server:
        yield f"http://127.0.0.1:{server.port}", log


async def _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch):
    stack = await _stack(rec_fake1c[0], rec_sidecar[0], tmp_path, monkeypatch)
    stack.fake_log, stack.sidecar_log = rec_fake1c[1], rec_sidecar[1]
    stack.reads = []
    stack.read_calls = []  # full keyword arguments of every onec.read, in order
    stack.override = None  # optional async (original, source, kwargs) -> result
    original = stack.runtime.onec.read

    async def spy(source, **kwargs):
        stack.reads.append(kwargs["entity_set"])
        stack.read_calls.append(dict(kwargs))
        if stack.override is not None:
            return await stack.override(original, source, kwargs)
        return await original(source, **kwargs)

    stack.runtime.onec.read = spy
    return stack


def _args(stack, org=ORG_ONE, **extra):
    return {"source_id": stack.source_id, "company_id": str(stack.companies[org]), **extra}


async def _ok(stack, org=ORG_ONE, **extra):
    result = await stack.call(TOOL, **_args(stack, org, **extra))
    assert not result.is_error
    return stack.payload(result)


async def _full_audit(stack):
    rows = await stack.db.require_pool().fetch(
        "SELECT * FROM bag.audit_events WHERE tool_name=$1 AND source_id=$2 "
        "ORDER BY occurred_at, event_id", TOOL, stack.source_id)
    return [dict(row) for row in rows]


def _assert_read_only(*logs):
    fake, sidecar = logs
    assert all(method in ("GET", "HEAD") for method, _ in fake), fake
    assert all(method == "POST" and path in SIDECAR_PATHS for method, path in sidecar), sidecar


def _all_text(body) -> str:
    return json.dumps(body, ensure_ascii=False)


# ------------------------------------------------------------------ 1. positive


@needs_pg
@pytest.mark.asyncio
async def test_positive_company_one_finding_with_provenance_and_clean_audit(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        body = await _ok(stack)
        assert body["status"] == "FINDING" and body["reason"] == "DUPLICATE_CANDIDATES_FOUND"
        assert body["candidate_count"] == 2 and body["group_count"] == 1
        assert body["merge_count"] == 0 and type(body["merge_count"]) is int
        assert body["truncated"] is False and body["human_review_required"] is True
        assert body["native_approval_inferred"] is False
        assert body["match_rule"] == "normalized_name_v1" and body["concept"] == CONCEPT
        (group,) = body["groups"]
        assert {m["counterparty_id"] for m in group["members"]} == DUP_REFS
        assert {m["code"] for m in group["members"]} == {"C001", "C001D"}
        assert {m["name"] for m in group["members"]} == {"Synthetic customer"}
        assert group["match_basis"] == "NORMALIZED_NAME"
        text = _all_text(body)
        for other in OTHERS:
            assert other["Description"] not in text and other["Code"] not in text
        assert body["profile_kind"] == "SYNTHETIC_FIXTURE" and body["evidence_level"] == "L1"
        assert body["native_reconciliation"] == "NOT_RUN"
        assert "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE" in body["warnings"]
        # activity read first, then the catalog read; nothing else
        assert stack.reads == [ACTIVITY, CATALOG]

        audit = await _full_audit(stack)
        assert [r["detail_code"] for r in audit] == ["ACCESS_AUTHORIZED", "SYNTHETIC_FIXTURE_PROFILE"]
        assert [r["outcome"] for r in audit] == ["success", "success"]
        assert audit[1]["returned_items"] == 1
        serialized = json.dumps([{k: str(v) for k, v in r.items()} for r in audit], ensure_ascii=False)
        for party in SEED["counterparties"]:
            assert party["Description"] not in serialized and party["Code"] not in serialized
        _assert_read_only(stack.fake_log, stack.sidecar_log)
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 2. isolation


@needs_pg
@pytest.mark.asyncio
async def test_other_company_sees_no_duplicates_and_unknown_company_is_denied(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        body = await _ok(stack, ORG_TWO)
        assert body["status"] == "PASS" and body["reason"] == "NO_DUPLICATE_CANDIDATES"
        assert body["groups"] == [] and body["candidate_count"] == 0 and body["group_count"] == 0
        text = _all_text(body)
        assert not any(ref in text for ref in DUP_REFS) and "Synthetic customer" not in text
        assert all(p["Description"] not in text for p in OTHERS)
        completion = (await _full_audit(stack))[-1]
        assert completion["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE"
        assert completion["outcome"] == "success" and completion["returned_items"] == 0

        before = len(stack.reads)
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, source_id=stack.source_id, company_id=str(uuid.uuid4()))
        assert len(stack.reads) == before
        assert (await _full_audit(stack))[-1]["outcome"] == "denied"
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 3. truncation


@needs_pg
@pytest.mark.asyncio
async def test_activity_truncation_is_inconclusive_and_never_reads_the_catalog(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        assert ORG_ONE_ACTIVITY_ROWS > 3
        body = await _ok(stack, top=3)
        assert body["status"] == "INCONCLUSIVE" and body["reason"] == "COUNTERPARTY_ROWS_TRUNCATED"
        assert body["groups"] == [] and body["candidate_count"] == 0 and body["group_count"] == 0
        assert body["truncated"] is True and body["merge_count"] == 0
        assert stack.reads == [ACTIVITY]
        audit = await _full_audit(stack)
        assert audit[-1]["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE:COUNTERPARTY_ROWS_TRUNCATED"
        assert audit[-1]["outcome"] == "error"
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_activity_limit_boundary_exactly_at_limit_is_truncated_one_above_is_complete(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        at_limit = await _ok(stack, top=ORG_ONE_ACTIVITY_ROWS)
        assert at_limit["reason"] == "COUNTERPARTY_ROWS_TRUNCATED" and at_limit["groups"] == []
        above = await _ok(stack, top=ORG_ONE_ACTIVITY_ROWS + 1)
        assert above["status"] == "FINDING" and above["candidate_count"] == 2
        # the seed catalog (5 rows) always fits once the activity read fits, so a catalog-only
        # truncation is unreachable through the seed; it is forced below.
        assert len(SEED["counterparties"]) < ORG_ONE_ACTIVITY_ROWS + 1
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_catalog_truncation_is_inconclusive_with_no_partial_groups(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        inner = stack.runtime.onec.read

        async def truncating(source, **kwargs):
            result = await inner(source, **kwargs)
            if kwargs["entity_set"] == CATALOG:
                rows = result["value"] if isinstance(result, dict) else result
                return {"value": rows, "page": {"truncated": True}}
            return result

        stack.runtime.onec.read = truncating
        body = await _ok(stack)
        assert stack.reads == [ACTIVITY, CATALOG]
        assert body["status"] == "INCONCLUSIVE" and body["reason"] == "COUNTERPARTY_ROWS_TRUNCATED"
        assert body["groups"] == [] and body["candidate_count"] == 0 and body["truncated"] is True
        completion = (await _full_audit(stack))[-1]
        assert completion["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE:COUNTERPARTY_ROWS_TRUNCATED"
        assert completion["outcome"] == "error"
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 4. fail closed


@needs_pg
@pytest.mark.asyncio
async def test_missing_profile_fails_closed_before_any_upstream_read(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        provider = stack.runtime.registry.synthetic_profiles
        for company in stack.companies.values():
            provider._sources[stack.source_id]["companies"][str(company)]["concepts"].pop(CONCEPT)
        stack.runtime.onec.read = AsyncMock()
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, **_args(stack))
        stack.runtime.onec.read.assert_not_awaited()
        audit = await _full_audit(stack)
        assert audit[-1]["detail_code"] == "SEMANTIC_PROFILE_UNVALIDATED"
        assert audit[-1]["outcome"] == "denied"
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_invalid_company_id_and_non_positive_top_are_rejected_without_reads(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        stack.runtime.onec.read = AsyncMock()
        with pytest.raises(Exception) as bad_company:
            await stack.call(TOOL, source_id=stack.source_id, company_id="not-a-uuid")
        assert isinstance(bad_company.value.__cause__, ValueError)
        assert "company_id must be a UUID" in str(bad_company.value.__cause__)
        audit = await _full_audit(stack)
        assert [(r["outcome"], r["detail_code"]) for r in audit] == [("denied", "INVALID_COMPANY_ID")]
        with pytest.raises(Exception) as bad_top:
            await stack.call(TOOL, **_args(stack, top=0))
        assert isinstance(bad_top.value.__cause__, ValueError)
        assert "top must be positive" in str(bad_top.value.__cause__)
        assert len(await _full_audit(stack)) == 1  # rejected before any audit or access
        stack.runtime.onec.read.assert_not_awaited()
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 5. DB profile wins


@needs_pg
@pytest.mark.asyncio
async def test_db_profile_shadows_the_fixture_draft_fails_closed_validated_is_used(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    pool = stack.db.require_pool()
    try:
        baseline = await _ok(stack)  # fixture path records capabilities
        assert baseline["profile_kind"] == "SYNTHETIC_FIXTURE"
        cap = await pool.fetchrow(
            "SELECT metadata_fingerprint, register_capabilities_json FROM bag.source_capabilities "
            "WHERE source_id=$1", stack.source_id)
        caps = cap["register_capabilities_json"]
        caps = json.loads(caps) if isinstance(caps, str) else caps
        mapping = fixture_gen.concept_mappings()[CONCEPT]
        profile_id = uuid.uuid4()
        await pool.execute(
            """INSERT INTO bag.semantic_profiles(profile_id, source_id, company_id, preset_id,
                 profile_name, profile_version, status, metadata_fingerprint,
                 capability_fingerprint, profile_fingerprint, preset_repository,
                 preset_upstream_sha, created_by)
               VALUES($1,$2,$3,'bp30','db-native',1,'DRAFT',$4,$5,'profile-db','r','s','test')""",
            profile_id, stack.source_id, stack.companies[ORG_ONE], cap["metadata_fingerprint"],
            canonical_fingerprint(caps))
        await pool.execute(
            "INSERT INTO bag.semantic_mappings(mapping_id, profile_id, canonical_concept, "
            "mapping_json, mapping_status, confidence) VALUES($1,$2,$3,$4::jsonb,'CONFIRMED','HIGH')",
            uuid.uuid4(), profile_id, CONCEPT, json.dumps(mapping))
        # a non-RETIRED but unvalidated DB row shadows the fixture: fail closed, no upstream read
        stack.reads.clear()
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, **_args(stack))
        assert stack.reads == []
        assert (await _full_audit(stack))[-1]["detail_code"] == "SEMANTIC_PROFILE_UNVALIDATED"
        # once validated the DB profile is the one used, never the fixture
        evidence = {"native_reconciliation_cases": [
            {"case_id": f"c{i}", "status": "PASS", "native_report_ref": f"ref/{i}"}
            for i in range(10)]}
        await pool.execute(
            "UPDATE bag.semantic_profiles SET status='VALIDATED', validated_by='t', "
            "validated_at=now(), validation_evidence_json=$2::jsonb WHERE profile_id=$1",
            profile_id, json.dumps(evidence))
        body = await _ok(stack)
        assert body["profile_kind"] == "VALIDATED_NATIVE"
        assert not body["profile_fingerprint"].startswith("synthetic-fixture:")
        assert "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE" not in body["warnings"]
        assert body["status"] == "FINDING" and body["candidate_count"] == 2
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 6. capability enforcement


@needs_pg
@pytest.mark.asyncio
async def test_capability_enforcement_denies_without_accounting_read_and_allows_with_it(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    pool = stack.db.require_pool()
    try:
        stack.settings.business_capability_enforcement_enabled = True
        stack.runtime.capability_policy = CapabilityPolicy(stack.db, enabled=True)
        fake_before, sidecar_before = len(stack.fake_log), len(stack.sidecar_log)
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, **_args(stack))
        audit = await _full_audit(stack)
        assert [(r["outcome"], r["detail_code"]) for r in audit] == [("denied", "CAPABILITY_DENIED")]
        assert stack.reads == []
        assert (len(stack.fake_log), len(stack.sidecar_log)) == (fake_before, sidecar_before)

        await pool.execute(
            "INSERT INTO bag.capability_overrides(override_id, principal_kind, principal_id, "
            "capability_key, source_id, effect) VALUES($1,'subject','development-local',"
            "'accounting.read',$2,'allow')", uuid.uuid4(), stack.source_id)
        body = await _ok(stack)
        assert body["status"] == "FINDING" and body["candidate_count"] == 2

        # an unmapped tool name is refused for everybody under enforcement
        monkeypatch.delitem(BUSINESS_CAPABILITY_BY_TOOL, TOOL)
        stack.reads.clear()
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, **_args(stack))
        assert stack.reads == []
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 7. no write


@needs_pg
@pytest.mark.asyncio
async def test_every_upstream_request_is_read_only(rec_fake1c, rec_sidecar, tmp_path, monkeypatch):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        await _ok(stack)
        await _ok(stack, ORG_TWO)
        await _ok(stack, top=3)
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, source_id=stack.source_id, company_id=str(uuid.uuid4()))
        assert stack.sidecar_log and stack.fake_log
        _assert_read_only(stack.fake_log, stack.sidecar_log)
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 8. structural pins


@pytest.mark.asyncio
async def test_tool_is_registered_with_exact_input_schema_and_accounting_read_capability():
    tools = {t.name: t for t in await build_mcp(Settings(_env_file=None), SimpleNamespace()).list_tools()}
    assert TOOL in tools
    schema = tools[TOOL].input_schema
    assert set(schema["properties"]) == {"source_id", "company_id", "top"}
    assert set(schema["required"]) == {"source_id", "company_id"}
    assert BUSINESS_CAPABILITY_BY_TOOL[TOOL] == "accounting.read"


# ------------------------------------------------------------------ 9. strengthened evidence
# (added after the test-adequacy review; the product behaviour is unchanged)

MAPPING = fixture_gen.concept_mappings()[CONCEPT]
SCOPE_FIELD = MAPPING["company_activity"]["company_scope"]["field"]
PARTY_FIELD = MAPPING["company_activity"]["counterparty_field"]
FIXTURE_MARKER = "SYNTHETIC_FIXTURE_PROFILE"
SEED_TEXTS = sorted(
    {p[k] for p in SEED["counterparties"] for k in ("Description", "Code", "Ref_Key")}
)


def _rows(result):
    return result["value"] if isinstance(result, dict) else result


def _override(stack, entity, transform):
    """Run the real read, then replace the answer of one entity set with transform(real)."""

    async def override(original, source, kwargs):
        real = await original(source, **kwargs)
        return transform(real) if kwargs["entity_set"] == entity else real

    stack.override = override


def _assert_no_seed_text(*objects):
    blob = json.dumps([str(o) for o in objects], ensure_ascii=False)
    leaked = [text for text in SEED_TEXTS if text in blob]
    assert leaked == []


def _audit_blob(audit) -> str:
    return json.dumps([{k: str(v) for k, v in r.items()} for r in audit], ensure_ascii=False)


@needs_pg
@pytest.mark.asyncio
async def test_exact_upstream_read_kwargs_and_audit_query_shape(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        assert stack.settings.max_rows == 200
        body = await _ok(stack)
        assert body["status"] == "FINDING"
        activity_call, catalog_call = stack.read_calls
        assert activity_call == {
            "entity_set": ACTIVITY, "select": [PARTY_FIELD, SCOPE_FIELD],
            "filter_expr": f"{SCOPE_FIELD} eq guid'{ORG_ONE}'",
            "orderby": f"{PARTY_FIELD} asc", "expand": None, "top": 200, "skip": 0,
        }
        assert catalog_call == {
            "entity_set": CATALOG, "select": ["Ref_Key", "Code", "Description"],
            "filter_expr": None, "orderby": "Ref_Key asc", "expand": None, "top": 200, "skip": 0,
        }
        # the 1C register is filtered by the company's EXTERNAL ref, never the gateway UUID
        gateway_uuid = str(stack.companies[ORG_ONE])
        assert gateway_uuid != ORG_ONE and gateway_uuid not in activity_call["filter_expr"]

        audit = await _full_audit(stack)
        expected = query_fingerprint(
            {"company_id": gateway_uuid, "concept": CONCEPT, "top": 200})
        assert [r["query_fingerprint"] for r in audit] == [expected, expected]
        assert expected != query_fingerprint(
            {"company_id": gateway_uuid, "concept": CONCEPT, "top": 2000})
        # raw queries are never persisted (the audit stores the fingerprint only)
        assert [r["query_json"] for r in audit] == [None, None]
        assert str(audit[-1]["company_id"]) == gateway_uuid
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_requested_top_is_clamped_to_max_rows_and_the_two_thousand_cap(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        await _ok(stack, top=10**6)
        assert [c["top"] for c in stack.read_calls] == [200, 200]  # min(top, max_rows, 2000)
        stack.read_calls.clear()
        await _ok(stack, top=50)
        assert [c["top"] for c in stack.read_calls] == [50, 50]

        stack.settings.max_rows = 5000  # above the tool's own hard cap
        stack.read_calls.clear()

        async def empty(original, source, kwargs):
            return {"value": []}

        stack.override = empty
        body = await _ok(stack, top=10**6)
        assert body["status"] == "PASS"  # empty scans are PASS per contract section 8
        assert [c["top"] for c in stack.read_calls] == [2000, 2000]
        audit = await _full_audit(stack)
        assert audit[-1]["query_fingerprint"] == query_fingerprint(
            {"company_id": str(stack.companies[ORG_ONE]), "concept": CONCEPT, "top": 2000})

        stack.override = None
        stack.read_calls.clear()
        body = await _ok(stack, top=1)
        assert body["reason"] == "COUNTERPARTY_ROWS_TRUNCATED"
        assert [(c["entity_set"], c["top"], c["skip"]) for c in stack.read_calls] == [
            (ACTIVITY, 1, 0)]
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_response_echoes_gateway_ids_and_stored_capability_fingerprint(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        body = await _ok(stack)
        assert body["company_id"] == str(stack.companies[ORG_ONE])
        assert body["company_id"] != ORG_ONE  # the gateway UUID, not the 1C external ref
        assert body["source_id"] == stack.source_id and body["concept"] == CONCEPT
        assert body["profile_fingerprint"].startswith("synthetic-fixture:")
        stored = await stack.db.require_pool().fetchval(
            "SELECT metadata_fingerprint FROM bag.source_capabilities WHERE source_id=$1",
            stack.source_id)
        assert stored and body["metadata_fingerprint"] == stored
        completion = (await _full_audit(stack))[-1]
        assert completion["metadata_fingerprint"] == stored
        assert completion["profile_fingerprint"] == body["profile_fingerprint"]
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_debug_logs_never_carry_counterparty_names_codes_or_refs(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch, caplog
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        caplog.set_level(logging.DEBUG)
        body = await _ok(stack)
        assert body["candidate_count"] == 2
        assert caplog.records, "nothing was logged at DEBUG: the scan would be vacuous"
        leaked = [text for text in SEED_TEXTS if text in caplog.text]
        assert leaked == []
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 10. failure matrix


def _activity_row(party, company=ORG_ONE):
    return {PARTY_FIELD: party, SCOPE_FIELD: company}


FAILURE_CASES = {
    "activity-not-a-list": (ACTIVITY, lambda real: {"value": "nope"},
                            "SOURCE_RESPONSE_INVALID", [ACTIVITY]),
    "activity-bad-guid": (ACTIVITY, lambda real: [_activity_row("not-a-guid")],
                          "COUNTERPARTY_FACT_INVALID", [ACTIVITY, CATALOG]),
    "activity-other-company": (ACTIVITY, lambda real: [_activity_row(DUP_A["Ref_Key"], ORG_TWO)],
                               "COMPANY_SCOPE_MISMATCH", [ACTIVITY, CATALOG]),
    "catalog-not-a-list": (CATALOG, lambda real: {"value": None},
                           "SOURCE_RESPONSE_INVALID", [ACTIVITY, CATALOG]),
    "catalog-non-guid-ref": (
        CATALOG, lambda real: [{**_rows(real)[0], "Ref_Key": "not-a-guid"}],
        "COUNTERPARTY_FACT_INVALID", [ACTIVITY, CATALOG]),
    "catalog-duplicate-ref-different-text": (
        CATALOG, lambda real: _rows(real) + [{**_rows(real)[0], "Ref_Key": "{" + DUP_A["Ref_Key"] + "}"}],
        "COUNTERPARTY_FACT_INVALID", [ACTIVITY, CATALOG]),
    "catalog-lone-surrogate": (
        CATALOG, lambda real: [{**_rows(real)[0], "Description": "Acme\ud800"}],
        "COUNTERPARTY_FACT_INVALID", [ACTIVITY, CATALOG]),
}


@needs_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(FAILURE_CASES))
async def test_untrustworthy_source_answers_are_inconclusive_and_audited_as_error(
    case, rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    entity, transform, reason, expected_reads = FAILURE_CASES[case]
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        _override(stack, entity, transform)
        body = await _ok(stack)
        assert (body["status"], body["reason"]) == ("INCONCLUSIVE", reason)
        assert body["groups"] == [] and body["candidate_count"] == 0 and body["merge_count"] == 0
        assert stack.reads == expected_reads
        audit = await _full_audit(stack)
        assert [r["outcome"] for r in audit] == ["success", "error"]
        assert audit[-1]["detail_code"] == f"{FIXTURE_MARKER}:{reason}"
        assert audit[-1]["returned_items"] == 0
        _assert_no_seed_text(_all_text(body), _audit_blob(audit))
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("failing", [ACTIVITY, CATALOG])
async def test_transport_error_propagates_and_is_audited_by_class_only(
    failing, rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        secret = "upstream said Synthetic customer C001 password=hunter2"

        def explode(real):
            raise OneCTransportError(secret)

        _override(stack, failing, explode)
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, **_args(stack))
        assert stack.reads == ([ACTIVITY] if failing == ACTIVITY else [ACTIVITY, CATALOG])
        audit = await _full_audit(stack)
        assert [r["outcome"] for r in audit] == ["success", "error"]
        assert audit[-1]["detail_code"] == f"{FIXTURE_MARKER}:OneCTransportError"
        assert audit[-1]["returned_items"] is None
        blob = _audit_blob(audit)
        assert "hunter2" not in blob and "upstream said" not in blob
        _assert_no_seed_text(blob)
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 11. scan bounds


@needs_pg
@pytest.mark.asyncio
async def test_page_flag_truncation_with_few_rows_never_reads_the_catalog(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        _override(stack, ACTIVITY, lambda real: {"value": _rows(real)[:2], "page": {"truncated": True}})
        body = await _ok(stack)
        assert (body["status"], body["reason"]) == ("INCONCLUSIVE", "COUNTERPARTY_ROWS_TRUNCATED")
        assert body["truncated"] is True and body["groups"] == []
        assert stack.reads == [ACTIVITY]
        completion = (await _full_audit(stack))[-1]
        assert completion["outcome"] == "error"
        assert completion["detail_code"] == f"{FIXTURE_MARKER}:COUNTERPARTY_ROWS_TRUNCATED"
        assert completion["truncated"] is True
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_exactly_at_limit_activity_never_reads_the_catalog_one_above_reads_both(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        body = await _ok(stack, top=ORG_ONE_ACTIVITY_ROWS)
        assert body["reason"] == "COUNTERPARTY_ROWS_TRUNCATED"
        assert stack.reads == [ACTIVITY]
        stack.reads.clear()
        body = await _ok(stack, top=ORG_ONE_ACTIVITY_ROWS + 1)
        assert body["status"] == "FINDING"
        assert stack.reads == [ACTIVITY, CATALOG]
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 12. deny gates


async def _capability_evidence(stack):
    raw = await stack.db.require_pool().fetchval(
        "SELECT evidence_json FROM bag.source_capabilities WHERE source_id=$1", stack.source_id)
    raw = json.loads(raw) if isinstance(raw, str) else raw
    return list((raw or {}).get("semantic_capabilities", {}).values())


@needs_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["catalog-lacks-description", "register-entity-absent"])
async def test_live_metadata_gate_denies_before_any_read(
    case, rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        await _ok(stack)  # records capabilities and warms the metadata cache
        stack.reads.clear()
        real_metadata = stack.runtime.onec.metadata

        async def altered(source, **kwargs):
            index = await real_metadata(source, **kwargs)
            entities = []
            for entity in index.entities:
                if case == "register-entity-absent" and entity.name == ACTIVITY:
                    continue
                if case == "catalog-lacks-description" and entity.name == CATALOG:
                    entity = dataclasses.replace(
                        entity, properties=tuple(p for p in entity.properties if p != "Description"))
                entities.append(entity)
            return dataclasses.replace(index, entities=tuple(entities))

        monkeypatch.setattr(stack.runtime.onec, "metadata", altered)
        before = len(await _full_audit(stack))
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, **_args(stack))
        assert stack.reads == []
        audit = await _full_audit(stack)
        assert [r["outcome"] for r in audit[before:]] == ["success", "denied"]
        assert audit[-1]["detail_code"] == f"{FIXTURE_MARKER}:CAPABILITY_UNSUPPORTED"
        evidence = await _capability_evidence(stack)
        if case == "catalog-lacks-description":
            hit = [e for e in evidence if e["entity_set"] == CATALOG]
            assert [(e["reason"], e["missing_properties"]) for e in hit] == [
                ("PROPERTY_ABSENT", ["Description"])]
        else:
            hit = [e for e in evidence if e["entity_set"] == ACTIVITY]
            assert [e["reason"] for e in hit] == ["ENTITY_SET_ABSENT"]
        assert all(e["status"] == "UNSUPPORTED" for e in hit)
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("pattern", ["Catalog_Counterparties", "AccumulationRegister_*"])
async def test_source_entity_deny_pattern_on_either_planned_set_denies_before_any_read(
    pattern, rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        await stack.db.require_pool().execute(
            "UPDATE bag.sources SET entity_deny_patterns=ARRAY[$2]::text[] WHERE source_id=$1",
            stack.source_id, pattern)
        data_reads = sum(1 for m, p in rec_sidecar[1] if p == "/v1/read")
        fake_filtered = len(rec_fake1c[1])
        with pytest.raises(UnexpectedToolError) as raised:
            await stack.call(TOOL, **_args(stack))
        assert stack.reads == []
        assert sum(1 for m, p in rec_sidecar[1] if p == "/v1/read") == data_reads
        audit = await _full_audit(stack)
        assert [r["outcome"] for r in audit] == ["success", "denied"]
        assert audit[-1]["detail_code"] == f"{FIXTURE_MARKER}:PermissionError"
        assert audit[-1]["returned_items"] is None
        _assert_no_seed_text(raised.value, _audit_blob(audit))
        assert fake_filtered <= len(rec_fake1c[1])
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_validated_db_profile_with_an_extra_mapping_key_fails_closed_without_reads(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    pool = stack.db.require_pool()
    try:
        await _ok(stack)  # fixture path records the capability fingerprint first
        cap = await pool.fetchrow(
            "SELECT metadata_fingerprint, register_capabilities_json FROM bag.source_capabilities "
            "WHERE source_id=$1", stack.source_id)
        caps = cap["register_capabilities_json"]
        caps = json.loads(caps) if isinstance(caps, str) else caps
        profile_id = uuid.uuid4()
        await pool.execute(
            """INSERT INTO bag.semantic_profiles(profile_id, source_id, company_id, preset_id,
                 profile_name, profile_version, status, metadata_fingerprint,
                 capability_fingerprint, profile_fingerprint, preset_repository,
                 preset_upstream_sha, created_by)
               VALUES($1,$2,$3,'bp30','db-native',1,'DRAFT',$4,$5,'profile-db','r','s','test')""",
            profile_id, stack.source_id, stack.companies[ORG_ONE], cap["metadata_fingerprint"],
            canonical_fingerprint(caps))
        await pool.execute(
            "INSERT INTO bag.semantic_mappings(mapping_id, profile_id, canonical_concept, "
            "mapping_json, mapping_status, confidence) VALUES($1,$2,$3,$4::jsonb,'CONFIRMED','HIGH')",
            uuid.uuid4(), profile_id, CONCEPT, json.dumps({**MAPPING, "unreviewed_extra": 1}))
        evidence = {"native_reconciliation_cases": [
            {"case_id": f"c{i}", "status": "PASS", "native_report_ref": f"ref/{i}"}
            for i in range(10)]}
        await pool.execute(
            "UPDATE bag.semantic_profiles SET status='VALIDATED', validated_by='t', "
            "validated_at=now(), validation_evidence_json=$2::jsonb WHERE profile_id=$1",
            profile_id, json.dumps(evidence))
        stack.reads.clear()
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, **_args(stack))
        assert stack.reads == []
        last = (await _full_audit(stack))[-1]
        assert last["outcome"] == "denied"
        assert last["detail_code"] == "SEMANTIC_MAPPING_UNCONFIRMED"
    finally:
        await stack.db.close()


@needs_pg
@pytest.mark.asyncio
async def test_response_larger_than_the_budget_is_an_audited_error_at_the_exact_boundary(
    rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        await _ok(stack)
        size = (await _full_audit(stack))[-1]["response_bytes"]
        assert size and size > 0
        stack.settings.max_response_bytes = size  # exactly at the budget is allowed
        await _ok(stack)
        stack.settings.max_response_bytes = size - 1
        before = len(await _full_audit(stack))
        with pytest.raises(UnexpectedToolError):
            await stack.call(TOOL, **_args(stack))
        audit = await _full_audit(stack)
        assert [r["outcome"] for r in audit[before:]] == ["success", "error"]
        last = audit[-1]
        assert last["detail_code"] == f"{FIXTURE_MARKER}:RESPONSE_TOO_LARGE"
        assert last["returned_items"] is None and last["response_bytes"] is None
        _assert_no_seed_text(_audit_blob(audit))
    finally:
        await stack.db.close()


# ------------------------------------------------------------------ 13. scoping guard


@needs_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("org", [ORG_ONE, ORG_TWO])
async def test_out_of_scope_namesake_in_the_catalog_is_never_reported(
    org, rec_fake1c, rec_sidecar, tmp_path, monkeypatch
):
    """An extra catalog counterparty with the in-scope name but NO activity in the company."""
    stack = await _chain(rec_fake1c, rec_sidecar, tmp_path, monkeypatch)
    try:
        namesake = {"Ref_Key": str(uuid.uuid4()), "Code": "OOS1", "Description": "SYNTHETIC  customer."}
        _override(stack, CATALOG, lambda real: _rows(real) + [namesake])
        body = await _ok(stack, org)
        text = _all_text(body)
        assert namesake["Ref_Key"] not in text and "OOS1" not in text
        if org == ORG_ONE:
            assert body["status"] == "FINDING" and body["candidate_count"] == 2
            (group,) = body["groups"]
            assert {m["counterparty_id"] for m in group["members"]} == DUP_REFS
        else:
            # company two only has activity for ONE of the two namesakes: no pair, no leak
            assert (body["status"], body["candidate_count"], body["groups"]) == ("PASS", 0, [])
            assert not any(ref in text for ref in DUP_REFS)
        assert stack.reads == [ACTIVITY, CATALOG]
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_every_registered_tool_has_a_valid_business_capability():
    tools = await build_mcp(Settings(_env_file=None), SimpleNamespace()).list_tools()
    names = {t.name for t in tools}
    assert TOOL in names
    missing = sorted(n for n in names if n not in BUSINESS_CAPABILITY_BY_TOOL)
    # Pre-existing unmapped tools (they do not go through resolve_source); a NEW tool that is not
    # mapped would fail closed for everybody under enforcement, so it must show up here and fail.
    assert missing == ["external_evidence_manifest", "sources_list", "system_status"]
    bad = {n: BUSINESS_CAPABILITY_BY_TOOL[n] for n in names - set(missing)
           if BUSINESS_CAPABILITY_BY_TOOL[n] not in CAPABILITY_KEYS}
    assert bad == {}
