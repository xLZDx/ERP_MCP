from __future__ import annotations

import hmac
import json
import logging
import math
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

from pydantic import SecretStr
from starlette.responses import JSONResponse, PlainTextResponse, Response

from .audit import (
    begin_request_correlation_id,
    current_request_correlation_id,
    end_request_correlation_id,
)

_access_logger = logging.getLogger("business_ai_gateway.http")
_trace_logger = logging.getLogger("business_ai_gateway.trace")


class OperationalMetrics:
    """Bounded operation/dependency metrics; never accepts user values as labels."""

    OUTCOMES = frozenset({"success", "denied", "error"})
    TOOLS = frozenset({
        "system_status", "sources_list", "source_health", "rsv_metadata", "companies_list",
        "onec_capabilities", "onec_metadata_summary", "onec_find_entities",
        "accounting_balance_and_turnovers", "inventory_balance", "inventory_movements",
        "accounting_posting_rows", "cash_movements", "bank_balance", "receivable_balance",
        "payable_balance", "receivable_aging", "payable_aging", "sales_documents", "purchase_documents", "onec_read", "audit",
        "external_evidence_manifest",
    })  # fixed registered MCP names plus the reserved internal audit-append operation
    DEPENDENCIES = frozenset(
        {"database", "redis", "jwks", "odata_sidecar", "rsv_bridge", "secrets", "audit"}
    )

    def __init__(self) -> None:
        self._operations: dict[tuple[str, str], int] = defaultdict(int)
        self._dependencies: dict[tuple[str, str], int] = defaultdict(int)
        self._dependency_duration: dict[tuple[str, str], tuple[int, float]] = defaultdict(
            lambda: (0, 0.0)
        )

    def record_operation(self, tool: str, outcome: str) -> None:
        safe_tool = tool if isinstance(tool, str) and tool in self.TOOLS else "other"
        safe_outcome = outcome if isinstance(outcome, str) and outcome in self.OUTCOMES else "error"
        self._operations[(safe_tool, safe_outcome)] += 1

    def record_dependency(self, dependency: str, outcome: str, elapsed_seconds: float = 0.0) -> None:
        safe_dependency = dependency if isinstance(dependency, str) and dependency in self.DEPENDENCIES else "other"
        safe_outcome = outcome if isinstance(outcome, str) and outcome in self.OUTCOMES else "error"
        self._dependencies[(safe_dependency, safe_outcome)] += 1
        count, total = self._dependency_duration[(safe_dependency, safe_outcome)]
        self._dependency_duration[(safe_dependency, safe_outcome)] = (
            count + 1,
            total + (min(3600.0, max(0.0, elapsed_seconds)) if type(elapsed_seconds) in (int, float)
                     and math.isfinite(elapsed_seconds) else 0.0),
        )

    def render(self) -> str:
        lines = [
            "# HELP erp_mcp_operations_total MCP operations by bounded tool and outcome.",
            "# TYPE erp_mcp_operations_total counter",
        ]
        for (tool, outcome), count in sorted(self._operations.items()):
            lines.append(
                f'erp_mcp_operations_total{{tool="{tool}",outcome="{outcome}"}} {count}'
            )
        lines.extend(
            [
                "# HELP erp_mcp_dependency_requests_total Dependency calls by bounded dependency and outcome.",
                "# TYPE erp_mcp_dependency_requests_total counter",
            ]
        )
        for (dependency, outcome), count in sorted(self._dependencies.items()):
            lines.append(
                f'erp_mcp_dependency_requests_total{{dependency="{dependency}",outcome="{outcome}"}} {count}'
            )
        lines.extend([
            "# HELP erp_mcp_dependency_duration_seconds Dependency request duration.",
            "# TYPE erp_mcp_dependency_duration_seconds summary",
        ])
        for (dependency, outcome), (count, total) in sorted(self._dependency_duration.items()):
            labels = f'dependency="{dependency}",outcome="{outcome}"'
            lines.append(f'erp_mcp_dependency_duration_seconds_sum{{{labels}}} {total:.9f}')
            lines.append(f'erp_mcp_dependency_duration_seconds_count{{{labels}}} {count}')
        return "\n".join(lines) + "\n"


@asynccontextmanager
async def trace_span(name: str, **attributes: str):
    """Privacy-safe internal span; attributes are fixed semantic values only."""
    started = time.perf_counter()
    correlation_id = current_request_correlation_id()
    allowed_spans = {"mcp.request", "auth.verify", "acl.resolve", "rate.check", "capability.route",
                     "secret.resolve", "adapter.call", "upstream.1c", "semantic.transform",
                     "evidence.resolve", "dad.rule.evaluate", "audit.append"}
    safe_name = name if isinstance(name, str) and name in allowed_spans else "other"
    allowed_values = {"tool": OperationalMetrics.TOOLS,
                      "dependency": OperationalMetrics.DEPENDENCIES,
                      "adapter": frozenset({"odata", "odata_sidecar", "rsv_bridge"}),
                      "outcome": OperationalMetrics.OUTCOMES}
    safe_attributes = {key: value if isinstance(value, str) and value in allowed_values[key] else "other"
                       for key, value in attributes.items() if key in allowed_values}
    try:
        yield
    except Exception as exc:
        safe_attributes["outcome"] = "error"
        _trace_logger.info(
            json.dumps(
                {
                    "event": "trace_span",
                    "name": safe_name,
                    "request_id": str(correlation_id) if correlation_id else None,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error_type": type(exc).__name__,
                    **safe_attributes,
                },
                separators=(",", ":"),
            )
        )
        raise
    else:
        safe_attributes.setdefault("outcome", "success")
        _trace_logger.info(
            json.dumps(
                {
                    "event": "trace_span",
                    "name": safe_name,
                    "request_id": str(correlation_id) if correlation_id else None,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    **safe_attributes,
                },
                separators=(",", ":"),
            )
        )


def metrics_response(
    metrics: HTTPMetrics, token: SecretStr | None, authorization: str
) -> Response:
    if token is None:
        return JSONResponse({"status": "not-found"}, status_code=404)
    expected = f"Bearer {token.get_secret_value()}"
    if not hmac.compare_digest(authorization.encode("utf-8"), expected.encode("utf-8")):
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
        self.operational = OperationalMetrics()

    def record_operation(self, tool: str, outcome: str) -> None:
        self.operational.record_operation(tool, outcome)

    def record_dependency(self, dependency: str, outcome: str, elapsed_seconds: float = 0.0) -> None:
        self.operational.record_dependency(dependency, outcome, elapsed_seconds)

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
        correlation_token, request_id = begin_request_correlation_id()
        self._active[route] += 1

        async def observed_send(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                candidate = message.get("status")
                status = candidate if type(candidate) is int and 100 <= candidate <= 599 else 500
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
            _access_logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": str(request_id),
                        "method": method,
                        "route": route,
                        "status_code": status,
                        "duration_ms": round(elapsed * 1000, 3),
                        "outcome": (
                            "success" if status < 400 else "client_error" if status < 500 else "server_error"
                        ),
                    },
                    separators=(",", ":"),
                )
            )
            end_request_correlation_id(correlation_token)

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
        return "\n".join(lines) + "\n" + self.operational.render()
