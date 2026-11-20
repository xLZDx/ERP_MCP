from __future__ import annotations

import asyncio
import json
import logging
import uuid
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from business_ai_gateway.audit import AuditCorrelationMiddleware, current_request_correlation_id
from business_ai_gateway.observability import (
    HTTPMetrics,
    OperationalMetrics,
    metrics_response,
    trace_span,
)


@pytest.mark.asyncio
async def test_http_metrics_use_bounded_labels_and_record_status_latency():
    async def application(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    metrics = HTTPMetrics().bind(application)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=metrics), base_url="http://gateway"
    ) as client:
        response = await client.get("/sources/customer-private-id")

    body = metrics.render()
    assert response.status_code == 201
    assert 'method="GET",route="other",status="201"' in body
    assert 'route="other"} 0' in body
    assert "customer-private-id" not in body
    bucket_lines = [
        line
        for line in body.splitlines()
        if "erp_mcp_http_request_duration_seconds_bucket" in line
        and 'route="other"' in line
        and 'method="GET"' in line
    ]
    assert len(bucket_lines) == len(HTTPMetrics.BUCKETS) + 1
    assert all(line.endswith(" 1") for line in bucket_lines)


@pytest.mark.asyncio
async def test_structured_http_log_shares_correlation_id_and_never_logs_query_data(caplog):
    observed_ids = []

    async def application(_scope, _receive, send):
        observed_ids.append(current_request_correlation_id())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = HTTPMetrics().bind(application)
    with caplog.at_level(logging.INFO, logger="business_ai_gateway.http"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.get("/mcp?filter=SECRET-ACCOUNT-9012")

    event = json.loads(caplog.records[-1].message)
    assert response.status_code == 200
    assert event["event"] == "http_request"
    assert event["route"] == "/mcp"
    assert event["outcome"] == "success"
    assert uuid.UUID(event["request_id"]) == observed_ids[0]
    assert "SECRET-ACCOUNT-9012" not in caplog.records[-1].message
    assert "path" not in event and "query" not in event and "headers" not in event


def test_metrics_endpoint_is_hidden_without_token_and_constant_time_guarded():
    metrics = HTTPMetrics()
    assert metrics_response(metrics, None, "").status_code == 404
    assert metrics_response(metrics, SecretStr("a" * 32), "Bearer wrong").status_code == 401
    assert metrics_response(metrics, SecretStr("é" * 32), "Bearer invalid").status_code == 401

    allowed = metrics_response(metrics, SecretStr("a" * 32), f"Bearer {'a' * 32}")
    assert allowed.status_code == 200
    assert allowed.headers["cache-control"] == "no-store"
    assert "text/plain" in allowed.headers["content-type"]


def test_operational_metrics_have_bounded_labels():
    metrics = HTTPMetrics()
    metrics.record_operation("source_health", "success")
    metrics.record_operation("secret=DO_NOT_LABEL", "success")
    metrics.record_dependency("redis", "error", 0.02)
    body = metrics.render()
    assert 'tool="source_health",outcome="success"' in body
    assert 'tool="other",outcome="success"' in body
    assert 'dependency="redis",outcome="error"' in body
    assert "DO_NOT_LABEL" not in body


def test_operation_duration_uses_fixed_tool_labels_and_bounded_aggregates():
    metrics = OperationalMetrics()
    for _ in range(25):
        metrics.record_operation_duration("purchase_documents_filtered", 0.25)
    metrics.record_operation_duration("unregistered-private-tool", 0.5)
    metrics.record_operation_duration("source_health", 7200.0)
    metrics.record_operation_duration("source_health", float("inf"))

    body = metrics.render()
    assert (
        'erp_mcp_operation_duration_seconds_sum{tool="purchase_documents_filtered"} 6.250000000'
        in body
    )
    assert (
        'erp_mcp_operation_duration_seconds_count{tool="purchase_documents_filtered"} 25'
        in body
    )
    assert 'erp_mcp_operation_duration_seconds_sum{tool="other"} 0.500000000' in body
    assert 'erp_mcp_operation_duration_seconds_count{tool="other"} 1' in body
    assert 'erp_mcp_operation_duration_seconds_sum{tool="source_health"} 3600.000000000' in body
    assert 'erp_mcp_operation_duration_seconds_count{tool="source_health"} 2' in body
    assert "unregistered-private-tool" not in body
    assert len(metrics._operation_duration) == 3
    assert all(isinstance(value, tuple) and len(value) == 2 for value in metrics._operation_duration.values())


@pytest.mark.asyncio
async def test_tool_call_middleware_records_one_duration_and_preserves_result(monkeypatch):
    from business_ai_gateway import audit as audit_module

    clock = iter((10.0, 10.25))
    monkeypatch.setattr(audit_module.time, "perf_counter", lambda: next(clock))
    metrics = OperationalMetrics()
    middleware = AuditCorrelationMiddleware(metrics)
    ctx = SimpleNamespace(
        method="tools/call",
        params={"name": "purchase_documents_filtered", "arguments": {"source_id": "private"}},
    )
    observed_correlation = []
    expected_result = object()

    async def call_next(_ctx):
        observed_correlation.append(current_request_correlation_id())
        return expected_result

    assert await middleware(ctx, call_next) is expected_result
    body = metrics.render()
    assert observed_correlation[0] is not None
    assert (
        'erp_mcp_operation_duration_seconds_sum{tool="purchase_documents_filtered"} 0.250000000'
        in body
    )
    assert 'erp_mcp_operation_duration_seconds_count{tool="purchase_documents_filtered"} 1' in body
    assert "erp_mcp_operations_total{" not in body
    assert current_request_correlation_id() is None


@pytest.mark.asyncio
async def test_tool_call_middleware_records_duration_when_handler_raises(monkeypatch):
    from business_ai_gateway import audit as audit_module

    clock = iter((20.0, 20.5))
    monkeypatch.setattr(audit_module.time, "perf_counter", lambda: next(clock))
    metrics = OperationalMetrics()
    middleware = AuditCorrelationMiddleware(metrics)
    ctx = SimpleNamespace(method="tools/call", params={"name": "source_health"})

    async def fail(_ctx):
        raise RuntimeError("PRIVATE-RESULT-MUST-NOT-BE-LOGGED")

    with pytest.raises(RuntimeError, match="PRIVATE-RESULT-MUST-NOT-BE-LOGGED"):
        await middleware(ctx, fail)

    body = metrics.render()
    assert 'erp_mcp_operation_duration_seconds_sum{tool="source_health"} 0.500000000' in body
    assert 'erp_mcp_operation_duration_seconds_count{tool="source_health"} 1' in body
    assert "PRIVATE-RESULT-MUST-NOT-BE-LOGGED" not in body
    assert current_request_correlation_id() is None


@pytest.mark.asyncio
async def test_tool_call_middleware_records_duration_and_propagates_cancellation(monkeypatch):
    from business_ai_gateway import audit as audit_module

    clock = iter((30.0, 30.75))
    monkeypatch.setattr(audit_module.time, "perf_counter", lambda: next(clock))
    metrics = OperationalMetrics()
    middleware = AuditCorrelationMiddleware(metrics)
    ctx = SimpleNamespace(method="tools/call", params={"name": "source_health"})

    async def cancel(_ctx):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await middleware(ctx, cancel)

    body = metrics.render()
    assert 'erp_mcp_operation_duration_seconds_sum{tool="source_health"} 0.750000000' in body
    assert 'erp_mcp_operation_duration_seconds_count{tool="source_health"} 1' in body
    assert current_request_correlation_id() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["success", "exception", "cancelled"])
async def test_tool_call_middleware_duration_metric_failure_preserves_call_outcome(monkeypatch, failure):
    metrics = OperationalMetrics()

    def fail_recording(*_args):
        raise RuntimeError("METRIC-BACKEND-FAILURE")

    monkeypatch.setattr(metrics, "record_operation_duration", fail_recording)
    middleware = AuditCorrelationMiddleware(metrics)
    ctx = SimpleNamespace(method="tools/call", params={"name": "source_health"})
    observed = []
    expected_result = object()
    expected_error = ValueError("APPLICATION-FAILURE")

    async def call_next(_ctx):
        observed.append(current_request_correlation_id())
        if failure == "exception":
            raise expected_error
        if failure == "cancelled":
            raise asyncio.CancelledError
        return expected_result

    if failure == "exception":
        with pytest.raises(ValueError) as raised:
            await middleware(ctx, call_next)
        assert raised.value is expected_error
    elif failure == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await middleware(ctx, call_next)
    else:
        assert await middleware(ctx, call_next) is expected_result

    assert len(observed) == 1 and observed[0] is not None
    assert current_request_correlation_id() is None
    assert "METRIC-BACKEND-FAILURE" not in metrics.render()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["metadata", "timing", "correlation_start"])
async def test_tool_call_middleware_pre_dispatch_fault_still_calls_application(monkeypatch, fault):
    from business_ai_gateway import audit as audit_module

    metrics = OperationalMetrics()
    middleware = AuditCorrelationMiddleware(metrics)
    calls = []

    class BrokenMetadata:
        method = "tools/call"

        @property
        def params(self):
            raise RuntimeError("PRIVATE-METADATA-FAILURE")

    ctx = BrokenMetadata() if fault == "metadata" else SimpleNamespace(
        method="tools/call", params={"name": "source_health"}
    )

    if fault == "timing":
        monkeypatch.setattr(
            audit_module.time,
            "perf_counter",
            lambda: (_ for _ in ()).throw(RuntimeError("CLOCK-FAILURE")),
        )
    elif fault == "correlation_start":
        monkeypatch.setattr(
            audit_module,
            "begin_request_correlation_id",
            lambda: (_ for _ in ()).throw(RuntimeError("CORRELATION-START-FAILURE")),
        )

    async def call_next(_ctx):
        calls.append(current_request_correlation_id())
        return "application-result"

    assert await middleware(ctx, call_next) == "application-result"
    assert len(calls) == 1
    if fault in {"metadata", "timing"}:
        assert calls[0] is not None
    else:
        assert calls[0] is None
    assert current_request_correlation_id() is None
    rendered = metrics.render()
    assert "PRIVATE-METADATA-FAILURE" not in rendered
    assert "CLOCK-FAILURE" not in rendered
    assert "CORRELATION-START-FAILURE" not in rendered


@pytest.mark.asyncio
async def test_non_tool_mcp_message_does_not_record_tool_duration(monkeypatch):
    from business_ai_gateway import audit as audit_module

    monkeypatch.setattr(audit_module.time, "perf_counter", lambda: 40.0)
    metrics = OperationalMetrics()
    middleware = AuditCorrelationMiddleware(metrics)
    ctx = SimpleNamespace(method="tools/list", params={})

    async def call_next(_ctx):
        return {"tools": []}

    await middleware(ctx, call_next)
    assert "erp_mcp_operation_duration_seconds_sum" not in metrics.render()


@pytest.mark.asyncio
async def test_trace_span_logs_only_fixed_attributes(caplog):
    with caplog.at_level(logging.INFO, logger="business_ai_gateway.trace"):
        async with trace_span(
            "adapter.call",
            tool="source_health",
            adapter="odata",
            secret="MUST_NOT_LOG",
        ):
            pass
    event = json.loads(caplog.records[-1].message)
    assert event["event"] == "trace_span"
    assert event["name"] == "adapter.call"
    assert event["tool"] == "source_health"
    assert "secret" not in event
    assert "MUST_NOT_LOG" not in caplog.records[-1].message

