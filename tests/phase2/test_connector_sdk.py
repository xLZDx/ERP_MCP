"""Behavioral tests for the snapshot-only connector SDK envelopes (fail-closed)."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta, timezone

import pytest

from business_ai_gateway.phase2.connector_sdk import (
    CaptureMode,
    CaptureRequest,
    CaptureResponse,
    Completeness,
    ConnectorContract,
    HealthState,
    Provenance,
    ValidationError,
    checked_capture_page,
    parse_request,
    parse_response,
    validate_exchange,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
DIGEST = "c" * 64


def req_map(**over):
    base = {"source_id": "src-1", "tenant_id": "tenant-1", "scope_epoch": 3,
            "capture_mode": "SNAPSHOT_ONLY"}
    base.update(over)
    return base


def prov_map(**over):
    base = {"connector_id": "onec-odata", "connector_version": "1.2.0",
            "observed_at": NOW, "content_digest": DIGEST}
    base.update(over)
    return base


def resp_map(prov=None, **over):
    base = {"source_id": "src-1", "tenant_id": "tenant-1", "scope_epoch": 3,
            "capture_mode": "SNAPSHOT_ONLY", "completeness": "COMPLETE",
            "provenance": prov if prov is not None else prov_map()}
    base.update(over)
    return base


def reasons_of(fn, *args):
    with pytest.raises(ValidationError) as info:
        fn(*args)
    return info.value.reasons


def make_request(**over):
    return CaptureRequest(**{"source_id": "src-1", "tenant_id": "tenant-1", "scope_epoch": 3, **over})


def make_response(**over):
    base = {"source_id": "src-1", "tenant_id": "tenant-1", "scope_epoch": 3,
            "capture_mode": CaptureMode.SNAPSHOT_ONLY, "completeness": Completeness.COMPLETE,
            "provenance": Provenance("onec-odata", "1.2.0", NOW, DIGEST)}
    base.update(over)
    return CaptureResponse(**base)


# ---- happy path ----------------------------------------------------------------

def test_valid_request_and_response_round_trip():
    request = parse_request(req_map(page_cursor="cur_1=="))
    assert request.capture_mode is CaptureMode.SNAPSHOT_ONLY
    assert request.page_cursor == "cur_1=="
    response = parse_response(resp_map(prov_map(
        observed_at="2026-10-09T12:00:00Z", page_cursor="cur_1==", next_cursor="cur_2")))
    assert response.completeness is Completeness.COMPLETE
    assert response.provenance.observed_at == NOW
    assert validate_exchange(request, response) is response


def test_envelopes_are_frozen():
    with pytest.raises(AttributeError):
        make_request().scope_epoch = 9  # type: ignore[misc]
    with pytest.raises(AttributeError):
        make_response().tenant_id = "x"  # type: ignore[misc]


def test_capture_mode_only_snapshot_exists():
    assert [m.value for m in CaptureMode] == ["SNAPSHOT_ONLY"]


# ---- identity / scope guards ---------------------------------------------------

@pytest.mark.parametrize("field", ["source_id", "tenant_id"])
@pytest.mark.parametrize("value,code", [
    ("", "BLANK"), ("   ", "BLANK"), (None, "NOT_A_STRING"), (5, "NOT_A_STRING"),
    (" pad", "INVALID_FORMAT"), ("a b", "INVALID_FORMAT"), ("x" * 129, "INVALID_FORMAT"),
])
def test_blank_or_malformed_ids_rejected(field, value, code):
    assert f"{field}:{code}" in reasons_of(parse_request, req_map(**{field: value}))


@pytest.mark.parametrize("missing", ["source_id", "tenant_id", "scope_epoch", "capture_mode"])
def test_missing_request_fields_rejected(missing):
    data = req_map()
    del data[missing]
    assert f"{missing}:MISSING" in reasons_of(parse_request, data)


@pytest.mark.parametrize("value,code", [
    (-1, "NEGATIVE"), (True, "NOT_AN_INTEGER"), ("3", "NOT_AN_INTEGER"), (1.0, "NOT_AN_INTEGER"),
    (None, "NOT_AN_INTEGER"),
])
def test_scope_epoch_guard(value, code):
    assert f"scope_epoch:{code}" in reasons_of(parse_request, req_map(scope_epoch=value))


def test_zero_scope_epoch_allowed():
    assert parse_request(req_map(scope_epoch=0)).scope_epoch == 0


@pytest.mark.parametrize("mode", ["STREAMING", "snapshot_only", "CDC", "", None, 3])
def test_unknown_capture_mode_rejected(mode):
    assert "capture_mode:UNKNOWN_VALUE" in reasons_of(parse_request, req_map(capture_mode=mode))


def test_dataclass_rejects_non_enum_capture_mode_directly():
    assert "capture_mode:UNKNOWN_MODE" in reasons_of(lambda: make_request(capture_mode="CDC"))


def test_multiple_reasons_are_all_reported():
    reasons = reasons_of(lambda: make_request(source_id="", tenant_id=" ", scope_epoch=-4))
    assert {"source_id:BLANK", "tenant_id:BLANK", "scope_epoch:NEGATIVE"} <= set(reasons)


# ---- timestamps ----------------------------------------------------------------

def test_naive_timestamp_rejected():
    r = reasons_of(parse_response, resp_map(prov_map(observed_at=datetime(2026, 10, 9, 12, 0))))  # noqa: DTZ001 - naive on purpose
    assert "provenance.observed_at:NAIVE_TIMESTAMP" in r


def test_non_utc_timestamp_rejected():
    plus3 = timezone(timedelta(hours=3))
    r = reasons_of(parse_response, resp_map(prov_map(observed_at=datetime(2026, 10, 9, 15, tzinfo=plus3))))
    assert "provenance.observed_at:NON_UTC_TIMESTAMP" in r


def test_iso_string_with_offset_rejected_and_garbage_rejected():
    assert "provenance.observed_at:NON_UTC_TIMESTAMP" in reasons_of(
        parse_response, resp_map(prov_map(observed_at="2026-10-09T15:00:00+03:00")))
    assert "provenance.observed_at:NOT_A_DATETIME" in reasons_of(
        parse_response, resp_map(prov_map(observed_at="yesterday")))


# ---- digest / provenance / completeness ----------------------------------------

@pytest.mark.parametrize("digest,code", [
    ("", "BLANK"), ("A" * 64, "INVALID_FORMAT"), ("c" * 63, "INVALID_FORMAT"), (None, "NOT_A_STRING"),
])
def test_content_digest_guard(digest, code):
    assert f"provenance.content_digest:{code}" in reasons_of(
        parse_response, resp_map(prov_map(content_digest=digest)))


@pytest.mark.parametrize("field,value,code", [
    ("connector_id", "", "BLANK"), ("connector_version", " ", "BLANK"),
    ("connector_version", "v 1", "INVALID_FORMAT"), ("page_cursor", "a b", "INVALID_FORMAT"),
    ("next_cursor", "", "BLANK"),
])
def test_provenance_field_guards(field, value, code):
    assert f"provenance.{field}:{code}" in reasons_of(
        parse_response, resp_map(prov_map(**{field: value})))


@pytest.mark.parametrize("value", ["FULL", "", None, "complete"])
def test_unknown_completeness_rejected(value):
    assert "completeness:UNKNOWN_VALUE" in reasons_of(parse_response, resp_map(completeness=value))


@pytest.mark.parametrize("value", ["COMPLETE", "PARTIAL", "UNKNOWN"])
def test_each_completeness_value_accepted(value):
    assert parse_response(resp_map(completeness=value)).completeness is Completeness(value)


def test_provenance_must_be_mapping_and_complete():
    assert "provenance:NOT_A_MAPPING" in reasons_of(parse_response, resp_map(prov=None, provenance="x"))
    assert "provenance.content_digest:MISSING" in reasons_of(
        parse_response, resp_map({"connector_id": "a", "connector_version": "1", "observed_at": NOW}))


def test_non_mapping_input_rejected():
    assert reasons_of(parse_request, "oops") == ("request:NOT_A_MAPPING",)
    assert reasons_of(parse_response, ["x"]) == ("response:NOT_A_MAPPING",)


def test_envelope_and_provenance_errors_reported_together():
    r = reasons_of(parse_response, resp_map(prov_map(content_digest="z"), scope_epoch=-1))
    assert "provenance.content_digest:INVALID_FORMAT" in r
    assert "scope_epoch:NEGATIVE" in r


# ---- forbidden keys / values / unknown fields ----------------------------------

FORBIDDEN_KEYS = [
    "password", "token", "secret", "authorization", "connection_string", "url", "sql", "query",
    "api_key", "Bearer", "dsn", "cookie", "endpoint_url", "access_token", "private-key", "uri",
]


@pytest.mark.parametrize("key", FORBIDDEN_KEYS)
def test_credential_url_sql_keys_rejected_in_request(key):
    assert f"{key}:FORBIDDEN_FIELD" in reasons_of(parse_request, req_map(**{key: "anything"}))


@pytest.mark.parametrize("key", FORBIDDEN_KEYS)
def test_credential_url_sql_keys_rejected_in_response_and_provenance(key):
    assert f"{key}:FORBIDDEN_FIELD" in reasons_of(parse_response, resp_map(**{key: "x"}))
    assert f"provenance.{key}:FORBIDDEN_FIELD" in reasons_of(
        parse_response, resp_map(prov_map(**{key: "x"})))


def test_unknown_non_secret_fields_rejected_everywhere():
    assert "extra:UNKNOWN_FIELD" in reasons_of(parse_request, req_map(extra=1))
    assert "extra:UNKNOWN_FIELD" in reasons_of(parse_response, resp_map(extra=1))
    assert "provenance.extra:UNKNOWN_FIELD" in reasons_of(
        parse_response, resp_map(prov_map(extra=1)))


@pytest.mark.parametrize("value,code", [
    ("https://evil.example/odata", "URL_VALUE"),
    ("jdbc://host/db", "URL_VALUE"),
    ("www.example.com", "URL_VALUE"),
    ("SELECT * FROM users", "SQL_VALUE"),
    ("a; DROP TABLE x", "SQL_VALUE"),
    ("x'; --", "SQL_VALUE"),
    ("password=hunter2", "CREDENTIAL_VALUE"),
    ("Bearer abc123", "CREDENTIAL_VALUE"),
])
@pytest.mark.parametrize("where", ["source_id", "tenant_id", "page_cursor"])
def test_url_sql_credential_values_rejected_in_request_fields(where, value, code):
    assert f"{where}:{code}" in reasons_of(parse_request, req_map(**{where: value}))


@pytest.mark.parametrize("field", ["connector_id", "connector_version", "page_cursor", "next_cursor"])
@pytest.mark.parametrize("value,code", [
    ("http://x/y", "URL_VALUE"), ("select a from b", "SQL_VALUE"), ("secret: x", "CREDENTIAL_VALUE"),
])
def test_url_sql_credential_values_rejected_in_provenance(field, value, code):
    assert f"provenance.{field}:{code}" in reasons_of(
        parse_response, resp_map(prov_map(**{field: value})))


def test_direct_construction_is_also_fail_closed():
    with pytest.raises(ValidationError):
        make_request(source_id="https://x")
    with pytest.raises(ValidationError):
        Provenance("c", "1", NOW, DIGEST, next_cursor="DROP TABLE t")
    with pytest.raises(ValidationError):
        make_response(provenance="not-provenance")
    with pytest.raises(ValidationError):
        make_response(completeness="COMPLETE")


# ---- request/response consistency ----------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant-2"), ("source_id", "src-2"), ("scope_epoch", 4),
])
def test_response_scope_mismatch_rejected(field, value):
    assert f"{field}:RESPONSE_MISMATCH" in reasons_of(
        validate_exchange, make_request(), make_response(**{field: value}))


def test_response_cursor_mismatch_rejected():
    request = make_request(page_cursor="cur1")
    response = make_response(provenance=Provenance("c", "1", NOW, DIGEST, page_cursor="other"))
    assert "page_cursor:RESPONSE_MISMATCH" in reasons_of(validate_exchange, request, response)


def test_exchange_wrong_types_rejected():
    assert reasons_of(validate_exchange, req_map(), make_response()) == ("exchange:WRONG_TYPES",)


def test_mismatch_reports_every_differing_field():
    r = reasons_of(validate_exchange, make_request(),
                   make_response(tenant_id="t2", source_id="s2", scope_epoch=9))
    assert {"tenant_id:RESPONSE_MISMATCH", "source_id:RESPONSE_MISMATCH",
            "scope_epoch:RESPONSE_MISMATCH"} <= set(r)


class _Fake:
    connector_id = "fake"
    connector_version = "1"

    def __init__(self, response):
        self._response = response

    def capture_page(self, request):
        return self._response

    def health(self, *, source_id, tenant_id):
        return HealthState.OK


def test_checked_capture_page_passes_matching_and_blocks_foreign_response():
    request = make_request()
    good = make_response()
    assert checked_capture_page(_Fake(good), request) is good
    with pytest.raises(ValidationError):
        checked_capture_page(_Fake(make_response(tenant_id="other")), request)


def test_protocol_is_structural_and_rejects_incomplete_connectors():
    assert isinstance(_Fake(make_response()), ConnectorContract)
    assert not isinstance(object(), ConnectorContract)


def test_parsers_do_not_mutate_input():
    data = resp_map()
    snapshot = copy.deepcopy(data)
    parse_response(data)
    assert data == snapshot
