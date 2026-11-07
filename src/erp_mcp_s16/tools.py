"""The isolated S16 model-facing tool manifest and safe dispatch adapter.

This module is inert until ``register_s16_tools`` is explicitly called. It does not
add routes to the existing gateway and exposes no approval operation.
"""
from __future__ import annotations

import inspect
import re
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

from business_ai_gateway.phase2.change.errors import ErrorCode, render

from .contracts import (
    ApplyReceipt,
    AuthenticatedPrincipal,
    DomainReceipt,
    PreviewSnapshot,
    Result,
    VerifyRequest,
)

__all__ = ["S16_TOOL_MANIFEST", "ToolSpec", "register_s16_tools"]


class ChangeServicePort(Protocol):
    def propose(self, requester: AuthenticatedPrincipal, raw_request: Mapping[str, object], *,
                now: Any = None) -> Result[PreviewSnapshot, ErrorCode]: ...
    def status(self, requester: AuthenticatedPrincipal, change_id: UUID) -> Result[DomainReceipt, ErrorCode]: ...
    def apply(self, requester: AuthenticatedPrincipal, change_id: UUID, *,
              now: Any = None) -> Result[ApplyReceipt, ErrorCode]: ...
    def verify(self, requester: AuthenticatedPrincipal,
               request: VerifyRequest) -> Result[Any, ErrorCode]: ...
    def rollback_propose(self, requester: AuthenticatedPrincipal, change_id: UUID, *,
                         now: Any = None) -> Result[PreviewSnapshot, ErrorCode]: ...


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, object]
    annotations: Mapping[str, bool]


_CHANGE_ID = {"type": "string", "format": "uuid"}
_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "change_id": _CHANGE_ID,
        "document_ref": {"type": "string", "minLength": 1, "maxLength": 512},
        "expected": {
            "type": "object",
            "properties": {
                "values": {"type": "object", "additionalProperties": {"type": "string"}},
                "document_day": {"type": "string", "maxLength": 32},
                "change_id": {"type": "string", "maxLength": 64},
                "manifest_hash": {"type": "string", "maxLength": 128},
                "includes_vat": {"type": "boolean"},
            },
            "required": ["values", "document_day", "change_id", "manifest_hash", "includes_vat"],
            "additionalProperties": False,
        },
        "shape": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "maxLength": 32},
                "document_kind": {"type": "string", "maxLength": 32},
                "line_count": {"type": "integer", "minimum": 0, "maximum": 10000},
            },
            "required": ["operation", "document_kind", "line_count"],
            "additionalProperties": False,
        },
    },
    "required": ["change_id", "document_ref", "expected", "shape"],
    "additionalProperties": False,
}


S16_TOOL_MANIFEST: tuple[ToolSpec, ...] = (
    ToolSpec("propose", "Create a change proposal for the authenticated scope.", {
        "type": "object", "properties": {"request": {"type": "object"}},
        "required": ["request"], "additionalProperties": False,
    }, {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}),
    ToolSpec("status", "Read the current status of a change in the authenticated scope.", {
        "type": "object", "properties": {"change_id": _CHANGE_ID},
        "required": ["change_id"], "additionalProperties": False,
    }, {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}),
    ToolSpec("apply", "Apply a currently approved change after core revalidation.", {
        "type": "object", "properties": {"change_id": _CHANGE_ID},
        "required": ["change_id"], "additionalProperties": False,
    }, {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}),
    ToolSpec("verify", "Verify a change using the configured S15 verification port.", _VERIFY_SCHEMA,
             {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}),
    ToolSpec("rollback_propose", "Create a separate rollback proposal; this does not approve or apply it.", {
        "type": "object", "properties": {"change_id": _CHANGE_ID},
        "required": ["change_id"], "additionalProperties": False,
    }, {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}),
)


def _freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if type(value) is list:
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if type(value) is tuple:
        return [_thaw(child) for child in value]
    return value


S16_TOOL_MANIFEST = tuple(
    ToolSpec(spec.name, spec.description, _freeze(spec.input_schema), _freeze(spec.annotations))
    for spec in S16_TOOL_MANIFEST
)

_FORBIDDEN_KEYS = frozenset({
    "principal", "principal_id", "person", "person_id", "role", "roles", "token",
    "token_class", "session", "session_id", "scope", "tenant", "company",
    "organization", "base_fingerprint", "target_fingerprint", "target_version",
    "approval", "approved", "approval_digest", "preview_digest", "approval_nonce",
    "nonce", "csrf", "decision", "decision_ref", "authorize", "authority",
    "effects", "url", "host", "hostname", "redirect", "proxy",
})
_FORBIDDEN_NORMALIZED_KEYS = frozenset({
    "principal", "principalid", "person", "personid", "role", "roles", "token",
    "tokenclass", "session", "sessionid", "scope", "tenant", "tenantid", "company",
    "companyid", "organization", "organizationid", "basefingerprint", "targetfingerprint",
    "targetversion", "targetref", "approval", "approved", "approvalstatus", "approvaldigest",
    "previewdigest", "approver", "approverid", "approvalnonce", "nonce", "csrf", "decision",
    "decisionref", "authorize", "authorized", "authorization", "authority", "effects", "url",
    "host", "hostname", "redirect", "proxy",
})
_MAX_ARGUMENT_BYTES = 64 * 1024
_MAX_DEPTH = 12
_MAX_NODES = 4096


def _validate_tree(value: object) -> bool:
    nodes = 0

    def walk(item: object, depth: int) -> bool:
        nonlocal nodes
        nodes += 1
        if depth > _MAX_DEPTH or nodes > _MAX_NODES:
            return False
        if item is None or type(item) in (str, int, float, bool):
            return not (type(item) is str and len(item) > 8192)
        if type(item) is list:
            return len(item) <= 2048 and all(walk(child, depth + 1) for child in item)
        if type(item) is dict:
            if len(item) > 512:
                return False
            for key, child in item.items():
                normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold()) if type(key) is str else ""
                if (type(key) is not str or len(key) > 128 or key.casefold() in _FORBIDDEN_KEYS
                        or normalized_key in _FORBIDDEN_NORMALIZED_KEYS):
                    return False
                if not walk(child, depth + 1):
                    return False
            return True
        return False

    return walk(value, 0)


def _safe_error(code: object, correlation_id: str) -> dict[str, object]:
    safe_code = code if type(code) is ErrorCode else ErrorCode.SCHEMA_INVALID
    info = render(safe_code)
    return {
        "isError": True,
        "error": {
            "code": safe_code.value,
            "message": info.message,
            "next_action": info.next_action.value,
            "correlation_id": correlation_id,
        },
    }


def _scope(scope: Any) -> dict[str, object]:
    return {
        "tenant": scope.tenant,
        "company": scope.company,
        "organization": scope.organization,
        "target_class": scope.target_class,
    }


def _preview(snapshot: PreviewSnapshot) -> dict[str, object]:
    return {
        "change_id": str(snapshot.change_id), "version": snapshot.version,
        "scope": _scope(snapshot.scope), "target_version": snapshot.target_version.value,
        "preview_digest": snapshot.preview_digest, "expires_at": snapshot.expires_at.isoformat(),
    }


def _receipt(receipt: DomainReceipt) -> dict[str, object]:
    return {
        "change_id": str(receipt.change_id), "status": receipt.status,
        "version": receipt.version, "scope": _scope(receipt.scope),
        "target_version": receipt.target_version.value,
    }


def _verification(value: Any) -> dict[str, object]:
    return {
        "status": value.status.value,
        "oracle_version": value.oracle_version,
        "label": value.label,
        "findings": [{"path": item.path, "field_class": item.field_class, "code": item.code}
                     for item in value.findings],
        "unverified_paths": list(value.unverified_paths),
        "typing_checked": value.typing_checked,
    }


async def _call(callable_: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = callable_(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def _resolve_principal(resolver: Callable[..., Any], context: object) -> AuthenticatedPrincipal:
    principal = await _call(resolver, context)
    if type(principal) is not AuthenticatedPrincipal:
        raise PermissionError("AUTHENTICATION_REQUIRED")
    return principal


def register_s16_tools(server: object, service: ChangeServicePort,
                       principal_resolver: Callable[..., Any],
                       error_renderer: Callable[[ErrorCode], object] | None = None) -> None:
    """Register the immutable five-tool surface on an explicitly supplied server.

    The resolver receives server transport context, never model arguments. Supported server
    adapters are ``register_tool(name, handler, schema, annotations)`` and FastMCP's
    ``tool(...)`` decorator; no gateway is imported or modified here.
    """
    async def dispatch(name: str, arguments: object, context: object = None) -> dict[str, object]:
        correlation_id = str(uuid.uuid4())
        try:
            spec = next((candidate for candidate in S16_TOOL_MANIFEST if candidate.name == name), None)
            if spec is None or type(arguments) is not dict or not _validate_tree(arguments):
                return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
            principal = await _resolve_principal(principal_resolver, context)
            if len(repr(arguments).encode("utf-8")) > _MAX_ARGUMENT_BYTES:
                return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
            if name == "propose":
                if set(arguments) != {"request"} or type(arguments["request"]) is not dict:
                    return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
                result = await _call(service.propose, principal, arguments["request"])
                serializer = _preview
            elif name == "status":
                if set(arguments) != {"change_id"}:
                    return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
                result = await _call(service.status, principal, UUID(arguments["change_id"]))
                serializer = _receipt
            elif name == "apply":
                if set(arguments) != {"change_id"}:
                    return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
                result = await _call(service.apply, principal, UUID(arguments["change_id"]))
                serializer = lambda receipt: {"change_id": str(receipt.change_id),
                                              "status": receipt.status,
                                              "correlation_id": receipt.correlation_id}
            elif name == "rollback_propose":
                if set(arguments) != {"change_id"}:
                    return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
                result = await _call(service.rollback_propose, principal, UUID(arguments["change_id"]))
                serializer = _preview
            else:
                if set(arguments) != {"change_id", "document_ref", "expected", "shape"}:
                    return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
                from erp_mcp_s15.verifier import ExpectedReceipt, OperationShape
                expected = arguments["expected"]
                shape = arguments["shape"]
                if type(expected) is not dict or type(shape) is not dict:
                    return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
                expected_value = ExpectedReceipt(**expected)
                shape_value = OperationShape(**shape)
                request = VerifyRequest(UUID(arguments["change_id"]), arguments["document_ref"],
                                        expected_value, shape_value)
                result = await _call(service.verify, principal, request)
                serializer = _verification
            if type(result) is not Result:
                return _safe_error(ErrorCode.AUDIT_UNAVAILABLE, correlation_id)
            if result.error is not None:
                # The shared registry is authoritative. A supplied renderer can format only the
                # same safe ErrorCode; it cannot add details from the failed operation.
                if error_renderer is not None:
                    try:
                        error_renderer(result.error)
                    except Exception:
                        pass
                return _safe_error(result.error, correlation_id)
            if result.value is None:
                return _safe_error(ErrorCode.AUDIT_UNAVAILABLE, correlation_id)
            return {"isError": False, "result": serializer(result.value)}
        except (ValueError, TypeError, KeyError, PermissionError):
            return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
        except Exception:
            return _safe_error(ErrorCode.AUDIT_UNAVAILABLE, correlation_id)

    for spec in S16_TOOL_MANIFEST:
        async def handler(arguments: object, context: object = None, *, _name: str = spec.name) -> dict[str, object]:
            return await dispatch(_name, arguments, context)
        handler.__name__ = f"s16_{spec.name}"
        if hasattr(server, "register_tool"):
            server.register_tool(spec.name, handler, _thaw(spec.input_schema), _thaw(spec.annotations))
        elif callable(getattr(server, "tool", None)):
            decorator = server.tool(name=spec.name, description=spec.description,
                                    annotations=_thaw(spec.annotations))
            decorator(handler)
        else:
            raise TypeError("UNSUPPORTED_TOOL_SERVER")

