from __future__ import annotations

import json
import logging
import uuid

import httpx
import pytest
from pydantic import SecretStr

from business_ai_gateway.audit import current_request_correlation_id
from business_ai_gateway.observability import HTTPMetrics, metrics_response


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

