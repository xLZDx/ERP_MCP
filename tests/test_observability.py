from __future__ import annotations

import json
import logging
import uuid

import httpx
import pytest
from pydantic import SecretStr

from business_ai_gateway.audit import current_request_correlation_id
from business_ai_gateway.observability import HTTPMetrics, metrics_response, trace_span


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

