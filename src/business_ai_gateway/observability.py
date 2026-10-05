from __future__ import annotations

import hmac
import time
from collections import defaultdict
from typing import Any

from pydantic import SecretStr
from starlette.responses import JSONResponse, PlainTextResponse, Response


def metrics_response(
    metrics: HTTPMetrics, token: SecretStr | None, authorization: str
) -> Response:
    if token is None:
        return JSONResponse({"status": "not-found"}, status_code=404)
    expected = f"Bearer {token.get_secret_value()}"
    if not hmac.compare_digest(authorization, expected):
        return JSONResponse(
            {"status": "unauthorized"},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )
    return PlainTextResponse(
        metrics.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )

class HTTPMetrics:
    """Small bounded-cardinality HTTP metrics collector; never labels user data."""

    BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    ROUTES = frozenset({"/mcp", "/healthz", "/readyz", "/metrics"})
    METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

    def __init__(self) -> None:
        self._requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self._active: dict[str, int] = defaultdict(int)
        self._duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self._duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)

    @classmethod
    def _route(cls, path: str) -> str:
        return path if path in cls.ROUTES else "other"

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        route = self._route(scope.get("path", ""))
        method = scope.get("method", "OTHER")
        if method not in self.METHODS:
            method = "OTHER"
        started = time.perf_counter()
        status = 500
        self._active[route] += 1

        async def observed_send(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            elapsed = max(0.0, time.perf_counter() - started)
            self._active[route] -= 1
            self._requests[(method, route, status)] += 1
            self._duration_count[(method, route)] += 1
            self._duration_sum[(method, route)] += elapsed
            for bound in self.BUCKETS:
                if elapsed <= bound:
                    self._duration_buckets[(method, route, bound)] += 1
                    break

    def bind(self, app) -> HTTPMetrics:
        self.app = app
        return self

    def render(self) -> str:
        lines = [
            "# HELP erp_mcp_http_requests_total Completed HTTP requests.",
            "# TYPE erp_mcp_http_requests_total counter",
        ]
        for (method, route, status), count in sorted(self._requests.items()):
            lines.append(
                f'erp_mcp_http_requests_total{{method="{method}",route="{route}",'
                f'status="{status}"}} {count}'
            )

        lines.extend(
            [
                "# HELP erp_mcp_http_requests_active Active HTTP requests.",
                "# TYPE erp_mcp_http_requests_active gauge",
            ]
        )
        for route, count in sorted(self._active.items()):
            lines.append(f'erp_mcp_http_requests_active{{route="{route}"}} {count}')

        lines.extend(
            [
                "# HELP erp_mcp_http_request_duration_seconds HTTP request latency.",
                "# TYPE erp_mcp_http_request_duration_seconds histogram",
            ]
        )
        for method, route in sorted(self._duration_count):
            labels = f'method="{method}",route="{route}"'
            cumulative = 0
            for bound in self.BUCKETS:
                cumulative += self._duration_buckets[(method, route, bound)]
                lines.append(
                    f'erp_mcp_http_request_duration_seconds_bucket{{{labels},le="{bound:g}"}} '
                    f"{cumulative}"
                )
            count = self._duration_count[(method, route)]
            lines.append(
                f'erp_mcp_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}'
            )
            lines.append(
                f"erp_mcp_http_request_duration_seconds_sum{{{labels}}} "
                f"{self._duration_sum[(method, route)]:.9f}"
            )
            lines.append(f'erp_mcp_http_request_duration_seconds_count{{{labels}}} {count}')
        return "\n".join(lines) + "\n"
