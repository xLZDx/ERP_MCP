"""ADR-0008 route selection, COM binding and the public tool (fakes with call counters, no DB)."""
from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from business_ai_gateway.adapters.onec.com_contract import (
    ComBalanceClient,
    ComBalanceRequest,
    ComBalanceResponse,
)
from business_ai_gateway.analytics_balance import (
    ComBinding,
    ComBindingInvalid,
    ComRouteUnsupported,
    RouteUnknown,
    classify_odata_capability,
    configuration_fingerprint,
    find_binding,
    load_com_bindings,
    select_route,
    validate_binding,
)
from business_ai_gateway.compatibility import CapabilityUnsupported
from business_ai_gateway.server import build_mcp
from business_ai_gateway.settings import Settings
from tests.test_analytics_balance_mapping import (
    COMPANY,
    KEY1,
    OTHER_COMPANY,
    REGISTER,
    com_row,
    good_mapping,
    odata_row,
)
from tests.test_server_audit import RecordingAudit, TestRegistry

META = "a" * 64
OTHER_META = "b" * 64
SOURCE = SimpleNamespace(
    id="source-1", base_url="http://1c.example.invalid/base/odata/standard.odata",
    username_secret_ref="reader-user-ref",
)
ABSENT = "metadata-function-import-absent-or-not-read-only"


def register_profile(state: str, *, fingerprint: str = META, source_id: str = "source-1") -> dict:
    if state == "AVAILABLE":
        method = {"available": True, "evidence": {"kind": "metadata-get-function-import",
                                                  "metadata_fingerprint": fingerprint}}
    elif state == "UNSUPPORTED":
        method = {"available": False, "evidence": {"kind": ABSENT, "metadata_fingerprint": fingerprint}}
    else:
        method = None
    methods = {} if method is None else {"balance": method}
    return {"schema_version": 1, "source_id": source_id, "evidence_source": "live-metadata",
            "metadata_fingerprint": fingerprint,
            "registers": [{"entity_set": REGISTER, "methods": methods}]}


def make_caps(state: str, *, fingerprint: str = META) -> SimpleNamespace:
    return SimpleNamespace(
        source_id="source-1", platform_version="8.3.24", metadata_fingerprint=fingerprint,
        adapter_profile=SimpleNamespace(value="ODATA_JSON_V3"),
        register_capabilities=register_profile(state, fingerprint=fingerprint),
    )


def make_binding(**over) -> ComBinding:
    values = {
        "source_id": "source-1", "binding_id": "bind-1", "version": 3, "clone_identity": "clone-A",
        "configuration_fingerprint": configuration_fingerprint(make_caps("UNSUPPORTED")),
        "metadata_fingerprint": META,
        "source_base_url_sha256": hashlib.sha256(SOURCE.base_url.encode()).hexdigest(),
        "credential_identity": "reader-user-ref", "allowed_company_refs": (COMPANY,),
        "status": "APPROVED", "approved_at": datetime(2026, 10, 7, tzinfo=UTC),
    }
    values.update(over)
    return ComBinding(**values)


# ------------------------------------------------------------------ classification table

@pytest.mark.parametrize("profile,expected", [
    (register_profile("AVAILABLE"), "AVAILABLE"),
    (register_profile("UNSUPPORTED"), "UNSUPPORTED"),
    (register_profile("UNKNOWN"), "UNKNOWN"),
    (register_profile("AVAILABLE", fingerprint=OTHER_META), "UNKNOWN"),
    (register_profile("UNSUPPORTED", fingerprint=OTHER_META), "UNKNOWN"),
    (register_profile("AVAILABLE", source_id="other"), "UNKNOWN"),
    ({**register_profile("AVAILABLE"), "evidence_source": "synthetic"}, "UNKNOWN"),
    ({**register_profile("AVAILABLE"), "status": "discovery-failed:X"}, "UNKNOWN"),
    ({**register_profile("AVAILABLE"), "registers": []}, "UNKNOWN"),
    (None, "UNKNOWN"), ({}, "UNKNOWN"),
])
def test_classification_table(profile, expected):
    assert classify_odata_capability(
        profile, source_id="source-1", metadata_fingerprint=META, entity_set=REGISTER) == expected


def test_unsupported_requires_the_absent_evidence_kind():
    profile = register_profile("UNSUPPORTED")
    profile["registers"][0]["methods"]["balance"]["evidence"]["kind"] = "something-else"
    assert classify_odata_capability(
        profile, source_id="source-1", metadata_fingerprint=META, entity_set=REGISTER) == "UNKNOWN"


def test_available_evidence_must_carry_current_fingerprint():
    profile = register_profile("AVAILABLE")
    profile["registers"][0]["methods"]["balance"]["evidence"]["metadata_fingerprint"] = OTHER_META
    assert classify_odata_capability(
        profile, source_id="source-1", metadata_fingerprint=META, entity_set=REGISTER) == "UNKNOWN"


# ------------------------------------------------------------------ select_route

def boom():
    raise AssertionError("bindings must not be consulted")


def test_available_routes_odata_and_never_consults_bindings():
    decision = select_route(make_caps("AVAILABLE"), good_mapping(), boom,
                            source=SOURCE, company_external_ref=COMPANY)
    assert (decision.route, decision.binding) == ("odata", None)


def test_com_route_refuses_a_mapping_the_bridge_does_not_query():
    mapping = good_mapping()
    mapping["company_scope"]["field"] = "Company_Key"
    with pytest.raises(ComRouteUnsupported) as err:
        select_route(make_caps("UNSUPPORTED"), mapping, (make_binding(),),
                     source=SOURCE, company_external_ref=COMPANY)
    assert err.value.reason == "com_mapping_not_served_by_bridge"
    # OData is unaffected by the bridge's fixed shape
    assert select_route(make_caps("AVAILABLE"), mapping, boom,
                        source=SOURCE, company_external_ref=COMPANY).route == "odata"


@pytest.mark.parametrize("as_of", ["0001-01-01T00:00:00+00:00", "1899-12-31T23:59:59+00:00",
                                   "2101-01-01T00:00:00+00:00"])
async def test_out_of_range_as_of_rejected_before_any_call(as_of):
    mcp, audit, onec, com, company = build("UNSUPPORTED", binding=make_binding())
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company, as_of=as_of)
    onec.register_read.assert_not_awaited()
    assert com.calls == [] and audit.events[-1]["outcome"] == "error"


async def test_uppercase_external_ref_is_canonicalised_for_the_bridge():
    mcp, _a, _o, com, company = build("UNSUPPORTED", ext_ref=COMPANY.upper(), binding=make_binding(),
                                      com=FakeCom(ComBalanceResponse(
                                          binding_id="bind-1", binding_version=3, source_id="source-1",
                                          clone_identity="clone-A", metadata_fingerprint=META,
                                          rows=(com_row(),), truncated=False)))
    await call(mcp, company)
    assert com.calls[0].company_external_ref == COMPANY


def test_unsupported_with_matching_binding_routes_com():
    binding = make_binding()
    decision = select_route(make_caps("UNSUPPORTED"), good_mapping(), (binding,),
                            source=SOURCE, company_external_ref=COMPANY)
    assert decision.route == "com" and decision.binding == binding


def test_unsupported_without_binding_is_capability_unsupported():
    with pytest.raises(CapabilityUnsupported) as err:
        select_route(make_caps("UNSUPPORTED"), good_mapping(), (),
                     source=SOURCE, company_external_ref=COMPANY)
    assert err.value.code == "CAPABILITY_UNSUPPORTED"


def test_unknown_fails_closed_even_with_valid_binding():
    with pytest.raises(RouteUnknown) as err:
        select_route(make_caps("UNKNOWN"), good_mapping(), (make_binding(),),
                     source=SOURCE, company_external_ref=COMPANY)
    assert err.value.code == "ROUTE_CAPABILITY_UNKNOWN"


@pytest.mark.parametrize("change,code", [
    ({"source_id": "other"}, "no_binding"),
    ({"status": "REVOKED"}, "com_binding_not_approved"),
    ({"source_base_url_sha256": "c" * 64}, "com_binding_base_url_changed"),
    ({"credential_identity": "someone-else"}, "com_binding_credential_changed"),
    ({"metadata_fingerprint": OTHER_META}, "com_binding_metadata_changed"),
    ({"configuration_fingerprint": "d" * 64}, "com_binding_configuration_changed"),
])
def test_mismatching_binding_is_rejected_as_unsupported(change, code):
    with pytest.raises(ComRouteUnsupported) as err:
        select_route(make_caps("UNSUPPORTED"), good_mapping(), (make_binding(**change),),
                     source=SOURCE, company_external_ref=COMPANY)
    assert err.value.reason == code and err.value.code == "CAPABILITY_UNSUPPORTED"


def test_company_not_in_binding_is_denied():
    with pytest.raises(ComBindingInvalid) as err:
        select_route(make_caps("UNSUPPORTED"), good_mapping(),
                     (make_binding(allowed_company_refs=(OTHER_COMPANY,)),),
                     source=SOURCE, company_external_ref=COMPANY)
    assert err.value.code == "COM_COMPANY_NOT_ALLOWED"


def test_company_ref_guid_case_insensitive():
    validate_binding(make_binding(allowed_company_refs=(COMPANY.upper(),)), source=SOURCE,
                     capabilities=make_caps("UNSUPPORTED"), company_external_ref=COMPANY)


def test_configuration_not_derivable_fails_closed():
    caps = make_caps("UNSUPPORTED")
    caps.platform_version = None
    with pytest.raises(ComBindingInvalid):
        validate_binding(make_binding(), source=SOURCE, capabilities=caps, company_external_ref=COMPANY)


def test_find_binding_ambiguous():
    with pytest.raises(ComBindingInvalid):
        find_binding((make_binding(), make_binding(binding_id="bind-2")), "source-1")


# ------------------------------------------------------------------ pinned loader

def _record(**over):
    record = {
        "source_id": "source-1", "binding_id": "bind-1", "version": 1, "clone_identity": "clone-A",
        "configuration_fingerprint": "e" * 64, "metadata_fingerprint": META,
        "source_base_url_sha256": "f" * 64, "credential_identity": "reader-user-ref",
        "allowed_company_refs": [COMPANY], "status": "APPROVED", "approved_at": "2026-10-07T10:00:00Z",
    }
    record.update(over)
    return record


def _write(tmp_path, document, *, raw=None):
    from business_ai_gateway.evidence_store import PrivateEvidenceStore, _write_new
    data = raw if raw is not None else json.dumps(document).encode()
    path = PrivateEvidenceStore.create(tmp_path)._root / "bindings.json"
    _write_new(path, data)
    return path, hashlib.sha256(data).hexdigest()


def test_loader_roundtrip_and_pin(tmp_path):
    path, digest = _write(tmp_path, {"schema_version": 1, "bindings": [_record()]})
    (binding,) = load_com_bindings(path, digest)
    assert binding.version == 1 and binding.allowed_company_refs == (COMPANY,)
    with pytest.raises(ComBindingInvalid) as err:
        load_com_bindings(path, "0" * 64)
    assert err.value.code == "COM_BINDINGS_STALE"


@pytest.mark.parametrize("mutation", [
    {"unknown": 1}, {"version": True}, {"version": 0}, {"status": "PENDING"},
    {"metadata_fingerprint": "xyz"}, {"allowed_company_refs": []}, {"approved_at": "2026-10-07"},
    {"binding_id": "bad id!"},
])
def test_loader_rejects_invalid_entries(tmp_path, mutation):
    path, digest = _write(tmp_path, {"schema_version": 1, "bindings": [_record(**mutation)]})
    with pytest.raises(ComBindingInvalid) as err:
        load_com_bindings(path, digest)
    assert err.value.code == "COM_BINDINGS_INVALID"


def test_loader_rejects_duplicate_keys_duplicate_sources_and_bad_pin(tmp_path):
    raw = b'{"schema_version":1,"schema_version":1,"bindings":[]}'
    path, digest = _write(tmp_path, None, raw=raw)
    with pytest.raises(ComBindingInvalid):
        load_com_bindings(path, digest)
    dup = tmp_path / "d"
    dup.mkdir()
    path, digest = _write(dup, {"schema_version": 1, "bindings": [_record(), _record(binding_id="b2")]})
    with pytest.raises(ComBindingInvalid):
        load_com_bindings(path, digest)
    with pytest.raises(ComBindingInvalid):
        load_com_bindings(path, "not-a-hash")


# ------------------------------------------------------------------ public tool

class FakeCom:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.factory_calls = 0
        self.bindings_calls = 0
        self.response = response
        self.error = error

    async def balance_by_analytics(self, request: ComBalanceRequest) -> ComBalanceResponse:
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.response or ComBalanceResponse(
            binding_id="bind-1", binding_version=3, source_id="source-1", clone_identity="clone-A",
            metadata_fingerprint=META, rows=(com_row(),), truncated=False)


def build(state="AVAILABLE", *, binding=None, com=None, odata_result=None, odata_error=None,
          drift="STABLE", fingerprint=META, mapping=None, source_denied=False,
          internal_id=COMPANY, ext_ref=COMPANY):
    company = UUID(internal_id)
    registry = TestRegistry()
    registry.require_company = AsyncMock(return_value=SimpleNamespace(external_ref=ext_ref))
    registry.save_capabilities = AsyncMock(return_value={"drift_status": drift})
    registry.require_semantic_mapping = AsyncMock(return_value={
        "mapping": mapping or good_mapping(), "profile_kind": "VALIDATED_NATIVE",
        "profile_fingerprint": "sha256:profile", "audit_detail_code": None})

    async def require_source_for_company(_p, _s, _c):
        if source_denied:
            raise PermissionError("denied")
        return SOURCE

    registry.require_source_for_company = require_source_for_company
    audit = RecordingAudit()
    page_result = odata_result if odata_result is not None else {
        "value": [odata_row()], "page": {"returned": 1, "has_more": False, "truncated": False}}
    register_read = AsyncMock(side_effect=odata_error) if odata_error else AsyncMock(return_value=page_result)
    onec = SimpleNamespace(
        capabilities=AsyncMock(return_value=make_caps(state, fingerprint=fingerprint)),
        register_read=register_read)
    com_client = com or FakeCom()

    async def factory():
        com_client.factory_calls += 1
        return com_client

    def bindings():
        com_client.bindings_calls += 1
        return (binding,) if binding else ()

    runtime = SimpleNamespace(
        audit=audit, registry=registry, rate_limit=SimpleNamespace(check=AsyncMock()), onec=onec,
        com_bindings=bindings, com_client=factory)
    return build_mcp(Settings(), runtime), audit, onec, com_client, company


async def call(mcp, company, **over):
    args = {"source_id": "source-1", "company_id": str(company), "as_of": "2026-04-30T00:00:00+00:00"}
    args.update(over)
    return await mcp.call_tool("accounting_balance_by_analytics", args)


def payload(result):
    return json.loads(result.content[0].text)


async def test_available_uses_odata_and_reports_route():
    mcp, audit, onec, com, company = build("AVAILABLE", binding=make_binding())
    body = payload(await call(mcp, company))
    assert body["route"] == "odata" and body["route_reason"] == "capability_available"
    assert body["row_count"] == 1 and body["truncated"] is False
    assert body["rows"][0]["account"] == "521.1"
    assert body["concept"] == "account.balance_by_analytics" and body["profile_fingerprint"]
    kwargs = onec.register_read.await_args.kwargs
    assert kwargs["method"] == "balance" and kwargs["top"] == Settings().max_rows
    assert set(kwargs["arguments"]) == {"Period", "Condition", "AccountCondition"}
    assert com.calls == [] and com.factory_calls == 0 and com.bindings_calls == 0
    assert audit.events[-1]["outcome"] == "success"
    assert audit.events[-1]["detail_code"] == "route=odata;reason=capability_available"


async def test_odata_truncated_flag_follows_has_more():
    result = {"value": [odata_row()], "page": {"has_more": True}}
    mcp, _a, _o, _c, company = build("AVAILABLE", odata_result=result)
    assert payload(await call(mcp, company))["truncated"] is True


@pytest.mark.parametrize("result", [
    {"value": [odata_row()]}, {"value": [odata_row()], "page": None},
    {"value": [odata_row()], "page": {"has_more": "no"}}, {"value": "x", "page": {"has_more": False}},
])
async def test_missing_or_bad_page_info_fails_closed(result):
    mcp, audit, _o, com, company = build("AVAILABLE", odata_result=result, binding=make_binding())
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert audit.events[-1]["outcome"] == "error" and com.calls == []


@pytest.mark.parametrize("error", [
    ConnectionError("503 Service Unavailable"), PermissionError("401"), TimeoutError("t"),
    RuntimeError("OData sidecar returned HTTP 503"),
])
async def test_odata_error_never_falls_back_to_com(error):
    mcp, audit, onec, com, company = build("AVAILABLE", binding=make_binding(), odata_error=error)
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    onec.register_read.assert_awaited_once()
    assert com.calls == [] and com.factory_calls == 0 and com.bindings_calls == 0
    last = audit.events[-1]
    assert last["outcome"] in {"error", "denied"} and "route=odata" in last["detail_code"]


async def test_odata_capability_unsupported_error_does_not_switch_route():
    mcp, _a, _o, com, company = build(
        "AVAILABLE", binding=make_binding(), odata_error=CapabilityUnsupported("CAPABILITY_UNSUPPORTED"))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert com.calls == []


async def test_metadata_drift_stops_before_any_data_call():
    mcp, audit, onec, com, company = build("AVAILABLE", binding=make_binding(), drift="DRIFTED")
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    onec.register_read.assert_not_awaited()
    assert com.calls == [] and audit.events[-1]["outcome"] == "denied"


async def test_drift_on_unsupported_route_stops_before_binding_and_com():
    mcp, audit, onec, com, company = build("UNSUPPORTED", binding=make_binding(), drift="DRIFTED")
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    onec.register_read.assert_not_awaited()
    assert com.calls == [] and com.factory_calls == 0 and com.bindings_calls == 0
    assert audit.events[-1]["outcome"] == "denied"
    assert "MetadataDriftUnacknowledged" in audit.events[-1]["detail_code"]


@pytest.mark.parametrize("state,route", [("AVAILABLE", "odata"), ("UNSUPPORTED", "com")])
async def test_acknowledged_drift_proceeds(state, route):
    mcp, _a, _o, _c, company = build(state, binding=make_binding(), drift="ACKNOWLEDGED")
    assert payload(await call(mcp, company))["route"] == route


async def test_company_external_ref_not_internal_id_reaches_both_routes():
    internal, ext = "99999999-9999-4999-8999-999999999999", COMPANY
    result = {"value": [odata_row()], "page": {"has_more": False}}
    mcp, _a, onec, _c, company = build("AVAILABLE", internal_id=internal, ext_ref=ext, odata_result=result)
    await call(mcp, company)
    condition = onec.register_read.await_args.kwargs["arguments"]["Condition"]
    assert ext in condition and internal not in condition
    mcp, _a, _o, com, company = build(
        "UNSUPPORTED", internal_id=internal, ext_ref=ext, binding=make_binding())
    await call(mcp, company)
    assert com.calls[0].company_external_ref == ext


async def test_foreign_company_row_fails_closed_through_the_tool():
    result = {"value": [odata_row(Организация_Key=OTHER_COMPANY)], "page": {"has_more": False}}
    mcp, audit, _o, com, company = build("AVAILABLE", odata_result=result, binding=make_binding())
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert audit.events[-1]["outcome"] == "error"
    assert "COMPANY_SCOPE_MISMATCH" in audit.events[-1]["detail_code"]
    assert com.calls == []
    bad = ComBalanceResponse(binding_id="bind-1", binding_version=3, source_id="source-1",
                             clone_identity="clone-A", metadata_fingerprint=META,
                             rows=(com_row(company_ref=OTHER_COMPANY),), truncated=False)
    mcp, audit, *_rest, company = build("UNSUPPORTED", binding=make_binding(), com=FakeCom(bad))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert audit.events[-1]["outcome"] == "error"
    assert "COMPANY_SCOPE_MISMATCH" in audit.events[-1]["detail_code"]


async def test_full_page_is_never_reported_complete():
    cap = Settings().max_rows
    result = {"value": [odata_row()] * cap, "page": {"has_more": False}}
    mcp, _a, _o, _c, company = build("AVAILABLE", odata_result=result)
    assert payload(await call(mcp, company))["truncated"] is True
    full = ComBalanceResponse(binding_id="bind-1", binding_version=3, source_id="source-1",
                              clone_identity="clone-A", metadata_fingerprint=META,
                              rows=(com_row(),) * min(cap, 5000), truncated=False)
    mcp, _a, _o, _c, company = build("UNSUPPORTED", binding=make_binding(), com=FakeCom(full))
    assert payload(await call(mcp, company))["truncated"] is True


async def test_unknown_capability_fails_closed():
    mcp, audit, onec, com, company = build("UNKNOWN", binding=make_binding())
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    onec.register_read.assert_not_awaited()
    assert com.calls == []
    assert audit.events[-1]["outcome"] == "denied"
    assert audit.events[-1]["detail_code"] == "ROUTE_CAPABILITY_UNKNOWN"


async def test_stale_fingerprint_evidence_is_unknown_not_com():
    mcp, _a, onec, com, company = build("UNSUPPORTED", binding=make_binding())
    onec.capabilities.return_value = replace_caps(make_caps("UNSUPPORTED"), register_profile("UNSUPPORTED", fingerprint=OTHER_META))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert com.calls == [] and onec.register_read.await_count == 0


def replace_caps(caps, profile):
    caps.register_capabilities = profile
    return caps


async def test_unsupported_with_matching_binding_uses_com():
    mcp, audit, onec, com, company = build("UNSUPPORTED", binding=make_binding())
    body = payload(await call(mcp, company))
    assert body["route"] == "com" and body["row_count"] == 1
    assert body["rows"][0] == {
        "account": "521.1", "account_key": KEY1,
        "analytics": [
            {"slot": 1, "role": "counterparty", "ref": "33333333-3333-4333-8333-333333333333",
             "type": "Catalog.Контрагенты"},
            {"slot": 2, "role": "contract", "ref": None, "type": None}],
        "balance_debit": "10.5", "balance_credit": "0", "currency_ref": None}
    onec.register_read.assert_not_awaited()
    (request,) = com.calls
    assert request.binding_id == "bind-1" and request.binding_version == 3
    assert request.company_external_ref == COMPANY and request.as_of.tzinfo is not None
    assert len(request.account_keys) == 2 and request.max_rows == Settings().max_rows
    detail = audit.events[-1]["detail_code"]
    assert detail.startswith("route=com;") and "binding=bind-1@3" in detail
    assert audit.events[-1]["adapter_kind"] == "COM_BRIDGE"


async def test_same_source_with_changed_base_url_rejects_old_binding():
    mcp, audit, onec, com, company = build("UNSUPPORTED", binding=make_binding(
        source_base_url_sha256=hashlib.sha256(b"http://old.example.invalid/").hexdigest()))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert com.calls == [] and onec.register_read.await_count == 0
    assert audit.events[-1]["outcome"] == "denied"
    assert audit.events[-1]["detail_code"].startswith("CAPABILITY_UNSUPPORTED;reason=com_binding_base_url_changed")


async def test_same_source_with_changed_metadata_rejects_old_binding():
    mcp, _a, _o, com, company = build("UNSUPPORTED", fingerprint=OTHER_META, binding=make_binding())
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert com.calls == []


async def test_company_not_in_binding_denied_before_com():
    mcp, audit, _o, com, company = build(
        "UNSUPPORTED", binding=make_binding(allowed_company_refs=(OTHER_COMPANY,)))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert com.calls == []
    assert audit.events[-1]["outcome"] == "denied"
    assert audit.events[-1]["detail_code"] == "COM_COMPANY_NOT_ALLOWED"


async def test_unsupported_without_binding_is_denied():
    mcp, audit, _o, com, company = build("UNSUPPORTED")
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert com.calls == [] and audit.events[-1]["outcome"] == "denied"


async def test_com_response_provenance_mismatch_fails_closed():
    bad = ComBalanceResponse(binding_id="bind-1", binding_version=4, source_id="source-1",
                             clone_identity="clone-A", metadata_fingerprint=META,
                             rows=(com_row(),), truncated=False)
    mcp, audit, _o, com, company = build("UNSUPPORTED", binding=make_binding(), com=FakeCom(bad))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert len(com.calls) == 1 and audit.events[-1]["outcome"] == "error"


@pytest.mark.parametrize("field,value", [
    ("binding_id", "other"), ("source_id", "source-2"),
    ("clone_identity", "clone-B"), ("metadata_fingerprint", OTHER_META),
])
async def test_com_provenance_mismatch_per_field_fails_closed(field, value):
    values = {"binding_id": "bind-1", "binding_version": 3, "source_id": "source-1",
              "clone_identity": "clone-A", "metadata_fingerprint": META,
              "rows": (com_row(),), "truncated": False}
    values[field] = value
    mcp, audit, _o, com, company = build(
        "UNSUPPORTED", binding=make_binding(), com=FakeCom(ComBalanceResponse(**values)))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert len(com.calls) == 1 and audit.events[-1]["outcome"] == "error"
    assert "COM_PROVENANCE_MISMATCH" in audit.events[-1]["detail_code"]


async def test_com_bridge_error_fails_closed_without_odata():
    mcp, audit, onec, _c, company = build(
        "UNSUPPORTED", binding=make_binding(), com=FakeCom(error=ConnectionError("down")))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    onec.register_read.assert_not_awaited()
    assert audit.events[-1]["outcome"] == "error"


async def test_row_outside_account_set_fails_closed_on_both_routes():
    other = "44444444-4444-4444-8444-444444444444"
    result = {"value": [odata_row(Account_Key=other)], "page": {"has_more": False}}
    mcp, audit, *_rest, company = build("AVAILABLE", odata_result=result)
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert audit.events[-1]["outcome"] == "error"
    bad = ComBalanceResponse(binding_id="bind-1", binding_version=3, source_id="source-1",
                             clone_identity="clone-A", metadata_fingerprint=META,
                             rows=(com_row(account_key=other),), truncated=False)
    mcp, audit, _o, com, company = build("UNSUPPORTED", binding=make_binding(), com=FakeCom(bad))
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    assert len(com.calls) == 1 and audit.events[-1]["outcome"] == "error"
    assert "SOURCE_RESPONSE_INVALID" in audit.events[-1]["detail_code"]


async def test_source_acl_denial_is_audited_and_stops_before_capabilities():
    mcp, audit, onec, com, company = build("AVAILABLE", source_denied=True)
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company)
    onec.capabilities.assert_not_awaited()
    assert audit.events[0]["outcome"] == "denied" and com.calls == []


async def test_invalid_company_id_denied():
    mcp, audit, onec, _c, company = build("AVAILABLE")
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company, company_id="not-a-uuid")
    assert audit.events[-1]["detail_code"] == "INVALID_COMPANY_ID"
    onec.capabilities.assert_not_awaited()


@pytest.mark.parametrize("as_of", ["2026-04-30", "2026-04-30T00:00:00"])
async def test_naive_as_of_rejected_before_any_call(as_of):
    mcp, audit, onec, com, company = build("AVAILABLE", binding=make_binding())
    with pytest.raises(UnexpectedToolError):
        await call(mcp, company, as_of=as_of)
    onec.register_read.assert_not_awaited()
    assert com.calls == [] and audit.events[-1]["outcome"] == "error"


# ------------------------------------------------------------------ schema / surface

async def test_tool_schema_has_exactly_three_parameters():
    mcp, *_ = build()
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    schema = tools["accounting_balance_by_analytics"].input_schema
    assert set(schema["properties"]) == {"source_id", "company_id", "as_of"}
    assert set(schema["required"]) == {"source_id", "company_id", "as_of"}
    assert schema.get("additionalProperties") is False


@pytest.mark.parametrize("extra", ["route", "bridge_id", "path", "secret", "binding_id", "query"])
async def test_caller_supplied_route_bridge_path_or_secret_is_rejected(extra):
    mcp, _audit, onec, com, company = build("AVAILABLE", binding=make_binding())
    with pytest.raises(ToolError):
        await call(mcp, company, **{extra: "com"})
    onec.register_read.assert_not_awaited()
    assert com.calls == []


def test_com_client_protocol_has_no_write_capability():
    methods = {name for name, member in inspect.getmembers(ComBalanceClient)
               if not name.startswith("_") and callable(member)}
    assert methods == {"balance_by_analytics"}
    forbidden = ("write", "execute", "post", "update", "delete", "set", "put", "query")
    assert not [name for name in methods if any(word in name for word in forbidden)]


def test_scope_map_and_metrics_register_the_tool():
    from business_ai_gateway.observability import OperationalMetrics
    from business_ai_gateway.server import BUSINESS_CAPABILITY_BY_TOOL
    assert BUSINESS_CAPABILITY_BY_TOOL["accounting_balance_by_analytics"] == "accounting.read"
    assert "accounting_balance_by_analytics" in OperationalMetrics.TOOLS


def test_settings_com_route_is_optional_and_loopback_only():
    assert Settings().com_bindings_file is None and Settings().com_bridge_url is None
    with pytest.raises(ValueError):
        Settings(com_bridge_url="http://127.0.0.1:9", com_bridge_token_secret_ref=None)
    with pytest.raises(ValueError):
        Settings(com_bridge_url="http://10.0.0.5:9", com_bridge_token_secret_ref="ref")
    with pytest.raises(ValueError):
        Settings(com_bindings_file="/x/b.json")
    assert Settings(com_bridge_url="http://127.0.0.1:9", com_bridge_token_secret_ref="ref")
