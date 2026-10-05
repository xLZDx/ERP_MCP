from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

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


def test_metrics_endpoint_is_hidden_without_token_and_constant_time_guarded():
    metrics = HTTPMetrics()
    assert metrics_response(metrics, None, "").status_code == 404
    assert metrics_response(metrics, SecretStr("a" * 32), "Bearer wrong").status_code == 401

    allowed = metrics_response(metrics, SecretStr("a" * 32), f"Bearer {'a' * 32}")
    assert allowed.status_code == 200
    assert allowed.headers["cache-control"] == "no-store"
    assert "text/plain" in allowed.headers["content-type"]

