"""Safe, structured MCP tool failures.

The MCP SDK hides the text of any exception that is not a ``ToolError``: the client only sees
``Error executing tool <name>``. That made every anticipated refusal (no validated semantic
profile, invalid ``as_of``, source outage, ...) indistinguishable from a crash. This module maps
an exception to a small, safe JSON payload that the model can act on, while the full detail stays
in the server log and the audit trail under the same ``correlation_id``.

Only exception classes whose message is authored by this code base may contribute text, and even
that text is redacted and bounded. Transport, audit and unknown errors never leak their message.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.shared.exceptions import MCPError

from .audit import AuditUnavailable, current_request_correlation_id
from .compatibility import CapabilityUnsupported, MetadataDriftUnacknowledged
from .semantic import SemanticProfileUnavailable

logger = logging.getLogger(__name__)

_MAX_SAFE_TEXT = 240
_REDACTIONS = (
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
    (re.compile(r"(?i)(password|passwd|secret|token|apikey|api_key)\s*[=:]\s*\S+"), r"\1=<redacted>"),
    (re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+"), "<url>"),
    (re.compile(r"\b[A-Za-z]:[\\/][^\s\"']*"), "<path>"),
    (re.compile(r"(?<![\w-])/(?:[\w.-]+/)+[\w.-]*"), "<path>"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "<hex>"),
)


@dataclass(frozen=True)
class ToolFailure:
    code: str
    category: str
    retryable: bool
    safe_message: str


def redact(text: str) -> str:
    """Remove credentials, URLs, filesystem paths and long hex strings; bound the length."""
    cleaned = " ".join(str(text).split())
    for pattern, replacement in _REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    if len(cleaned) > _MAX_SAFE_TEXT:
        cleaned = cleaned[: _MAX_SAFE_TEXT - 1] + "…"
    return cleaned


def classify(exc: BaseException) -> ToolFailure:
    """Map an exception to a safe failure description (never raises, never echoes unknown text)."""
    if isinstance(exc, SemanticProfileUnavailable):
        return ToolFailure(
            getattr(exc, "code", "SEMANTIC_PROFILE_UNVALIDATED"), "capability", False,
            redact(exc) if str(exc) else "No validated semantic profile exists for this source/company.",
        )
    if isinstance(exc, MetadataDriftUnacknowledged):
        return ToolFailure(
            "METADATA_DRIFT_UNACKNOWLEDGED", "capability", False,
            "The source metadata changed and an administrator has not acknowledged it yet.",
        )
    if isinstance(exc, CapabilityUnsupported):
        return ToolFailure(
            getattr(exc, "code", "CAPABILITY_UNSUPPORTED"), "capability", False,
            redact(exc) if str(exc) else "The source does not support this operation.",
        )
    if isinstance(exc, PermissionError):
        # Deliberately text-free: the reason (unknown source vs. no grant vs. other company) must not leak.
        return ToolFailure("ACCESS_DENIED", "authorization", False,
                           "The caller is not authorized for this source, company or operation.")
    if isinstance(exc, AuditUnavailable):
        return ToolFailure("AUDIT_UNAVAILABLE", "dependency", True,
                           "The audit trail is temporarily unavailable; the call was refused.")
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ToolFailure("SOURCE_TIMEOUT", "dependency", True,
                           "The 1C source did not answer in time. Retry, or narrow the period.")
    if type(exc).__name__ in {"OneCTransportError", "ODataSidecarError", "RSVBridgeUnavailable",
                              "ComBridgeError", "ConnectError", "ReadTimeout", "ConnectTimeout"}:
        return ToolFailure("SOURCE_UNAVAILABLE", "dependency", True,
                           "The 1C source could not be reached or returned an error.")
    if isinstance(exc, ValueError):
        return ToolFailure("INVALID_ARGUMENT", "validation", False, redact(exc) or "Invalid argument.")
    return ToolFailure("INTERNAL_ERROR", "internal", False,
                       "The operation failed unexpectedly. Quote the correlation_id to the operator.")


def build_payload(tool: str, arguments: dict[str, Any] | None, failure: ToolFailure) -> dict[str, Any]:
    source_id = (arguments or {}).get("source_id")
    correlation = current_request_correlation_id()
    return {
        "error": {
            **asdict(failure),
            "tool": tool,
            "source_id": source_id if isinstance(source_id, str) and len(source_id) <= 128 else None,
            "operation": tool,
            "correlation_id": str(correlation) if correlation else None,
        }
    }


class StructuredToolError(UnexpectedToolError):
    """A crash or refusal whose client-visible text is the safe structured JSON payload.

    It subclasses ``UnexpectedToolError`` on purpose: callers and tests that already treat a failed
    semantic call as ``UnexpectedToolError`` keep working, while the SDK returns ``str(exc)`` (the
    JSON payload) as the tool result text instead of the opaque ``Error executing tool <name>``.
    """


def to_tool_error(tool: str, arguments: dict[str, Any] | None, exc: BaseException) -> ToolError:
    """Build the client-visible error and log the detail server-side."""
    original = exc.__cause__ if isinstance(exc.__cause__, Exception) else exc
    failure = classify(original)
    payload = build_payload(tool, arguments, failure)
    log = logger.error if failure.category == "internal" else logger.info
    log(
        "tool %s failed code=%s category=%s correlation_id=%s",
        tool, failure.code, failure.category, payload["error"]["correlation_id"],
        exc_info=(type(original), original, original.__traceback__) if failure.category == "internal" else None,
    )
    return StructuredToolError(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


class StructuredErrorMCPServer(MCPServer):
    """MCPServer whose tool failures reach the client as safe structured payloads."""

    async def call_tool(self, name, arguments, context=None):  # type: ignore[override]
        try:
            return await super().call_tool(name, arguments, context)
        except MCPError:
            raise
        except UnexpectedToolError as exc:
            # Only crashes are re-mapped. SDK refusals (unknown tool, schema validation) and a
            # deliberately raised ToolError already carry a safe message and pass through untouched.
            if not isinstance(exc.__cause__, Exception):
                raise
            raise to_tool_error(name, arguments, exc) from exc.__cause__
