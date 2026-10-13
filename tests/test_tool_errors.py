"""Safe structured tool failures: no semantic-tool refusal may collapse into an opaque error."""
from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from business_ai_gateway.audit import (
    AuditCorrelationMiddleware,
    AuditUnavailable,
    begin_request_correlation_id,
    end_request_correlation_id,
)
from business_ai_gateway.compatibility import CapabilityUnsupported, MetadataDriftUnacknowledged
from business_ai_gateway.semantic import SemanticProfileUnavailable
from business_ai_gateway.tool_errors import (
    StructuredErrorMCPServer,
    StructuredToolError,
    classify,
    redact,
)

SECRET_TEXT = (
    "password=hunter2 Bearer eyJhbGciOiJSUzI1NiJ9.payload.signature "
    "http://user:pw@10.0.0.5:8080/odata D:\\secret\\conn.ini /etc/erp/secret.key "
    + "a" * 40
)


class OneCTransportError(RuntimeError):  # same class name the adapter raises
    pass


def make_server(exc_factory):
    server = StructuredErrorMCPServer("test")

    @server.tool()
    async def boom(source_id: str = "src-1", as_of: str = "2026-08-31") -> dict:
        raise exc_factory()

    @server.tool()
    async def ok(source_id: str = "src-1") -> dict:
        return {"value": 1}

    @server.tool()
    async def deliberate(source_id: str = "src-1") -> dict:
        raise ToolError("a deliberate, already safe message")

    return server


async def failure(exc_factory, **arguments) -> tuple[dict, BaseException]:
    server = make_server(exc_factory)
    with pytest.raises(UnexpectedToolError) as raised:
        await server.call_tool("boom", arguments)
    return json.loads(str(raised.value))["error"], raised.value


@pytest.mark.parametrize(
    ("exc_factory", "code", "category", "retryable"),
    [
        (lambda: SemanticProfileUnavailable("no validated payable.balance profile exists for this exact "
                                            "source/company"), "SEMANTIC_PROFILE_UNVALIDATED", "capability", False),
        (lambda: MetadataDriftUnacknowledged("drift"), "METADATA_DRIFT_UNACKNOWLEDGED", "capability", False),
        (lambda: CapabilityUnsupported("balance function import absent"), "CAPABILITY_UNSUPPORTED",
         "capability", False),
        (lambda: PermissionError("company 3e31 is not granted"), "ACCESS_DENIED", "authorization", False),
        (lambda: AuditUnavailable("AUDIT_UNAVAILABLE"), "AUDIT_UNAVAILABLE", "dependency", True),
        (lambda: TimeoutError(), "SOURCE_TIMEOUT", "dependency", True),
        (lambda: OneCTransportError("GET http://1c.internal/odata failed"), "SOURCE_UNAVAILABLE",
         "dependency", True),
        (lambda: ValueError("as_of must include an explicit timezone"), "INVALID_ARGUMENT",
         "validation", False),
        (lambda: KeyError("unexpected"), "INTERNAL_ERROR", "internal", False),
    ],
)
async def test_each_failure_class_becomes_a_structured_payload(exc_factory, code, category, retryable):
    error, raised = await failure(exc_factory, source_id="onec-818ha-reference")

    assert isinstance(raised, StructuredToolError)  # still an UnexpectedToolError for existing callers
    assert (error["code"], error["category"], error["retryable"]) == (code, category, retryable)
    assert error["tool"] == error["operation"] == "boom"
    assert error["source_id"] == "onec-818ha-reference"
    assert error["safe_message"] and "Error executing tool" not in error["safe_message"]
    assert set(error) == {"code", "category", "retryable", "safe_message", "tool", "source_id",
                          "operation", "correlation_id"}


async def test_real_1c_refusal_message_reaches_the_client():
    """The exact refusal observed on onec-818ha-reference was invisible before this change."""
    error, _ = await failure(lambda: SemanticProfileUnavailable(
        "no validated payable.balance profile exists for this exact source/company"))

    assert "payable.balance" in error["safe_message"]
    assert error["code"] == "SEMANTIC_PROFILE_UNVALIDATED"


async def test_as_of_without_timezone_is_reported_as_invalid_argument():
    error, _ = await failure(lambda: ValueError("as_of must include an explicit timezone"))

    assert error["code"] == "INVALID_ARGUMENT"
    assert "timezone" in error["safe_message"]


@pytest.mark.parametrize("exc_factory", [
    lambda: RuntimeError(SECRET_TEXT),
    lambda: OneCTransportError(SECRET_TEXT),
    lambda: PermissionError(SECRET_TEXT),
    lambda: AuditUnavailable(SECRET_TEXT),
    lambda: KeyError(SECRET_TEXT),
])
async def test_unsafe_exception_text_never_reaches_the_client(exc_factory):
    _, raised = await failure(exc_factory)

    text = str(raised)
    for leaked in ("hunter2", "eyJhbGci", "10.0.0.5", "D:\\secret", "/etc/erp", "a" * 40, "user:pw"):
        assert leaked not in text


async def test_text_from_classes_allowed_to_speak_is_redacted_and_bounded():
    error, _ = await failure(lambda: ValueError(SECRET_TEXT * 5))

    for leaked in ("hunter2", "eyJhbGci", "10.0.0.5", "D:\\secret", "/etc/erp", "user:pw"):
        assert leaked not in error["safe_message"]
    assert len(error["safe_message"]) <= 240


def test_redact_is_idempotent_and_keeps_plain_text():
    assert redact("as_of must include an explicit timezone") == "as_of must include an explicit timezone"
    assert redact(redact(SECRET_TEXT)) == redact(SECRET_TEXT)


async def test_correlation_id_matches_the_request_scope():
    token, correlation = begin_request_correlation_id()
    try:
        error, _ = await failure(lambda: ValueError("bad"))
    finally:
        end_request_correlation_id(token)

    assert error["correlation_id"] == str(correlation)


async def test_correlation_id_is_none_outside_a_request():
    error, _ = await failure(lambda: ValueError("bad"))

    assert error["correlation_id"] is None


async def test_successful_call_is_untouched():
    server = make_server(lambda: ValueError("unused"))

    result = await server.call_tool("ok", {})

    assert not result.is_error


async def test_deliberate_tool_error_passes_through_unchanged():
    server = make_server(lambda: ValueError("unused"))

    with pytest.raises(ToolError) as raised:
        await server.call_tool("deliberate", {})

    assert not isinstance(raised.value, StructuredToolError)
    assert "a deliberate, already safe message" in str(raised.value)


async def test_unknown_tool_and_schema_failures_keep_the_sdk_message():
    server = make_server(lambda: ValueError("unused"))

    with pytest.raises(ToolError) as unknown:
        await server.call_tool("does_not_exist", {})
    with pytest.raises(ToolError) as bad_args:
        await server.call_tool("ok", {"source_id": {"not": "a string"}})

    assert not isinstance(unknown.value, StructuredToolError)
    assert not isinstance(bad_args.value, StructuredToolError)


async def test_non_string_or_oversized_source_id_is_not_echoed():
    error, _ = await failure(lambda: ValueError("x"), source_id="s" * 500)

    assert error["source_id"] is None


def test_classify_never_raises_for_odd_exceptions():
    class Weird(Exception):
        def __str__(self):  # a broken __str__ must not break error reporting
            raise RuntimeError("no str")

    assert classify(Weird()).code == "INTERNAL_ERROR"


def test_middleware_class_is_still_a_valid_server_middleware():
    assert callable(AuditCorrelationMiddleware().__call__)
