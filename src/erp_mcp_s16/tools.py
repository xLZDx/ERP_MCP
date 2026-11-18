"""The isolated S16 model-facing tool manifest and safe dispatch adapter.

This module is inert until ``register_s16_tools`` is explicitly called. It does not
add routes to the existing gateway and exposes no approval operation.
"""
from __future__ import annotations

import inspect
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Any, Callable, Mapping, Protocol
from uuid import UUID

from business_ai_gateway.phase2.change.errors import ErrorCode, render
from business_ai_gateway.phase2.change.policy import CALLER_MATRIX, LedgerOperation
from business_ai_gateway.phase2.change.types import CallerClass
from erp_mcp_s15.verifier import VerificationResult

from .contracts import (
    ApplyReceipt,
    AuthenticatedPrincipal,
    DomainReceipt,
    IdSource,
    PreviewSnapshot,
    Result,
    TargetScope,
    TargetVersion,
    VerifyRequest,
)


class _Uuid4IdSource:
    def issue(self) -> UUID:
        return uuid.uuid4()


def _issue_uuid4(source: IdSource) -> str:
    value = source.issue()
    if (type(value) is not UUID or value.version != 4
            or value.variant != "specified in RFC 4122"):
        raise ValueError("ID_SOURCE_INVALID")
    return str(value)

__all__ = ["S16_MODEL_OPERATION_ALLOWLIST", "S16_TOOL_MANIFEST", "S16_TOOL_OPERATION_MAP",
           "ToolSpec", "register_s16_tools"]


class ChangeServicePort(Protocol):
    def propose(self, requester: AuthenticatedPrincipal, raw_request: Mapping[str, object], *,
                now: Any = None) -> Result[PreviewSnapshot, ErrorCode]: ...
    def status(self, requester: AuthenticatedPrincipal, change_id: UUID) -> Result[DomainReceipt, ErrorCode]: ...
    def apply(self, requester: AuthenticatedPrincipal, change_id: UUID, *,
              now: Any = None) -> Result[ApplyReceipt, ErrorCode]: ...
    def verify(self, requester: AuthenticatedPrincipal,
               request: VerifyRequest) -> Result[VerificationResult, ErrorCode]: ...
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

# Keep the user-facing operation surface tied to the policy matrix. `verify` reads
# the scoped ledger state and delegates the evidence check to the S15 verifier port.
# `rollback_propose` is a new proposal, never an implicit reversal.
S16_TOOL_OPERATION_MAP = MappingProxyType({
    "propose": frozenset({LedgerOperation.PROPOSE, LedgerOperation.VALIDATE}),
    "status": frozenset({LedgerOperation.READ_STATUS}),
    "apply": frozenset({LedgerOperation.CLAIM, LedgerOperation.RELEASE_CLAIM,
                         LedgerOperation.BEGIN_APPLY}),
    "verify": frozenset({LedgerOperation.READ_STATUS}),
    "rollback_propose": frozenset({LedgerOperation.PROPOSE, LedgerOperation.VALIDATE}),
})
_APPROVER_ONLY = frozenset({LedgerOperation.APPROVE, LedgerOperation.REJECT})
_REQUESTER_ALLOWED = CALLER_MATRIX[CallerClass.REQUESTER]
S16_MODEL_OPERATION_ALLOWLIST = frozenset().union(
    *(operations & _REQUESTER_ALLOWED for operations in S16_TOOL_OPERATION_MAP.values())
)
if (set(S16_TOOL_OPERATION_MAP) != {spec.name for spec in S16_TOOL_MANIFEST}
        or any(operations & _APPROVER_ONLY for operations in S16_TOOL_OPERATION_MAP.values())
        or any(operations - _REQUESTER_ALLOWED for operations in S16_TOOL_OPERATION_MAP.values())
        or S16_MODEL_OPERATION_ALLOWLIST != _REQUESTER_ALLOWED):
    raise RuntimeError("S16_TOOL_OPERATION_MAP_INVALID")


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
_READ_ERROR_DETAIL = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_VERIFICATION_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_VERIFICATION_CODES = frozenset({
    "MISMATCH", "EMPTY", "NOT_RESOLVING", "DELETION_MARKED", "INCOMPLETE",
    "EXPECTED_MISSING", "READ_ERROR", "TYPING_DIVERGENCE",
})
_VERIFICATION_FIELD_CLASSES = frozenset({
    "number", "identity_text", "date", "enumeration", "reference", "flag",
    "rows", "marker", "read", "unknown",
})


def _validate_tree(value: object) -> bool:
    nodes = 0
    input_bytes = 0

    def reserve(size: int) -> bool:
        nonlocal input_bytes
        input_bytes += size
        return input_bytes <= _MAX_ARGUMENT_BYTES

    def walk(item: object, depth: int) -> bool:
        nonlocal nodes
        nodes += 1
        if depth > _MAX_DEPTH or nodes > _MAX_NODES:
            return False
        if item is None or type(item) is bool:
            return reserve(len(repr(item)))
        if type(item) is str:
            if len(item) > 8192:
                return False
            try:
                item.encode("utf-8", errors="strict")
                return reserve(len(repr(item).encode("utf-8", errors="strict")))
            except UnicodeError:
                return False
        if type(item) is int:
            digit_bound = max(1, (item.bit_length() * 30103) // 100000 + 1) + (1 if item < 0 else 0)
            if input_bytes + digit_bound > _MAX_ARGUMENT_BYTES:
                return False
            try:
                return reserve(len(repr(item)))
            except (ValueError, OverflowError):
                return False
        if type(item) is float:
            return math.isfinite(item) and reserve(len(repr(item)))
        if type(item) is list:
            if len(item) > 2048 or not reserve(2):
                return False
            for index, child in enumerate(item):
                if (index and not reserve(2)) or not walk(child, depth + 1):
                    return False
            return True
        if type(item) is dict:
            if len(item) > 512 or not reserve(2):
                return False
            for index, (key, child) in enumerate(item.items()):
                normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold()) if type(key) is str else ""
                if (type(key) is not str or len(key) > 128 or key.casefold() in _FORBIDDEN_KEYS
                        or normalized_key in _FORBIDDEN_NORMALIZED_KEYS):
                    return False
                try:
                    key.encode("utf-8", errors="strict")
                    if ((index and not reserve(2))
                            or not reserve(len(repr(key).encode("utf-8", errors="strict")) + 2)):
                        return False
                except UnicodeError:
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


def _change_uuid(value: object) -> UUID:
    if type(value) is not str:
        raise ValueError("CHANGE_ID_INVALID")
    return UUID(value)


def _wire_text(value: object, *, limit: int) -> str:
    if type(value) is not str or not value or len(value) > limit:
        raise RuntimeError("S16_RESPONSE_INVALID")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise RuntimeError("S16_RESPONSE_INVALID") from exc
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RuntimeError("S16_RESPONSE_INVALID")
    return value


def _scope(scope: Any) -> dict[str, object]:
    if type(scope) is not TargetScope:
        raise RuntimeError("S16_RESPONSE_INVALID")
    return {
        "tenant": _wire_text(scope.tenant, limit=128),
        "company": _wire_text(scope.company, limit=128),
        "organization": _wire_text(scope.organization, limit=128),
        "target_class": _wire_text(scope.target_class, limit=32),
    }


def _target_version(version: Any) -> str:
    if type(version) is not TargetVersion:
        raise RuntimeError("S16_RESPONSE_INVALID")
    return _wire_text(version.value, limit=128)


def _preview(snapshot: PreviewSnapshot) -> dict[str, object]:
    if (type(snapshot) is not PreviewSnapshot or type(snapshot.change_id) is not UUID
            or type(snapshot.version) is not int or snapshot.version < 1
            or type(snapshot.preview_digest) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", snapshot.preview_digest)
            or type(snapshot.expires_at) is not datetime
            or snapshot.expires_at.utcoffset() is None):
        raise RuntimeError("S16_RESPONSE_INVALID")
    return {
        "change_id": str(snapshot.change_id), "version": snapshot.version,
        "scope": _scope(snapshot.scope), "target_version": _target_version(snapshot.target_version),
        "preview_digest": snapshot.preview_digest, "expires_at": snapshot.expires_at.isoformat(),
    }


def _receipt(receipt: DomainReceipt) -> dict[str, object]:
    if (type(receipt) is not DomainReceipt or type(receipt.change_id) is not UUID
            or type(receipt.version) is not int or receipt.version < 1):
        raise RuntimeError("S16_RESPONSE_INVALID")
    return {
        "change_id": str(receipt.change_id), "status": _wire_text(receipt.status, limit=64),
        "version": receipt.version, "scope": _scope(receipt.scope),
        "target_version": _target_version(receipt.target_version),
    }


def _apply_receipt(receipt: ApplyReceipt) -> dict[str, object]:
    if type(receipt) is not ApplyReceipt or type(receipt.change_id) is not UUID:
        raise RuntimeError("S16_RESPONSE_INVALID")
    document_ref = receipt.document_ref
    if document_ref is not None:
        document_ref = _wire_text(document_ref, limit=512)
    return {
        "change_id": str(receipt.change_id),
        "status": _wire_text(receipt.status, limit=64),
        "correlation_id": _wire_text(receipt.correlation_id, limit=128),
        "document_ref": document_ref,
    }


def _verification(value: Any) -> dict[str, object]:
    from erp_mcp_s15.verifier import Finding, VerificationResult, VerificationStatus

    if (type(value) is not VerificationResult or type(value.status) is not VerificationStatus
            or type(value.oracle_version) is not str or not 1 <= len(value.oracle_version) <= 128
            or not value.oracle_version.isascii() or any(ord(char) < 32 for char in value.oracle_version)
            or type(value.label) is not str or not 1 <= len(value.label) <= 128
            or not value.label.isascii() or any(ord(char) < 32 for char in value.label)
            or type(value.findings) is not tuple or len(value.findings) > 512
            or type(value.unverified_paths) is not tuple or len(value.unverified_paths) > 512
            or type(value.typing_checked) is not bool):
        raise RuntimeError("S15_VERIFY_RESULT_INVALID")
    findings = []
    for item in value.findings:
        if (type(item) is not Finding
                or type(item.path) is not str or not 1 <= len(item.path) <= 256
                or not _VERIFICATION_PATH.fullmatch(item.path)
                or type(item.field_class) is not str
                or item.field_class not in _VERIFICATION_FIELD_CLASSES
                or type(item.code) is not str or item.code not in _VERIFICATION_CODES):
            raise RuntimeError("S15_VERIFY_RESULT_INVALID")
        detail = item.detail
        if (type(detail) is not str or
                (item.code == "READ_ERROR" and not _READ_ERROR_DETAIL.fullmatch(detail)) or
                (item.code != "READ_ERROR" and detail != "")):
            # S15 detail is an exception class name only for READ_ERROR; never serialize
            # arbitrary verifier or adapter text into the model-facing response.
            raise RuntimeError("S15_VERIFY_RESULT_INVALID")
        findings.append({"path": item.path, "field_class": item.field_class,
                         "code": item.code, "detail": detail})
    if any(type(path) is not str or not 1 <= len(path) <= 256
           or not _VERIFICATION_PATH.fullmatch(path) for path in value.unverified_paths):
        raise RuntimeError("S15_VERIFY_RESULT_INVALID")
    return {
        "status": value.status.value,
        "oracle_version": value.oracle_version,
        "label": value.label,
        "findings": findings,
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
                       error_renderer: Callable[[ErrorCode], object] | None = None,
                       *, correlation_id_source: IdSource | None = None) -> None:
    """Register the immutable five-tool surface on an explicitly supplied server.

    The resolver receives server transport context, never model arguments. The server must
    provide ``register_tool(name, handler, schema, annotations)`` so the
    manifest schema is published verbatim. Signature-derived adapters are rejected because
    they cannot preserve the exact schema or guarantee rejection of undeclared arguments.
    """
    id_source = correlation_id_source or _Uuid4IdSource()

    async def dispatch(name: str, arguments: object, context: object = None) -> dict[str, object]:
        try:
            correlation_id = _issue_uuid4(id_source)
        except Exception:
            return _safe_error(ErrorCode.AUDIT_UNAVAILABLE, str(uuid.uuid4()))
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
                result = await _call(service.status, principal, _change_uuid(arguments["change_id"]))
                serializer = _receipt
            elif name == "apply":
                if set(arguments) != {"change_id"}:
                    return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
                result = await _call(service.apply, principal, _change_uuid(arguments["change_id"]))
                serializer = _apply_receipt
            elif name == "rollback_propose":
                if set(arguments) != {"change_id"}:
                    return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
                result = await _call(service.rollback_propose, principal, _change_uuid(arguments["change_id"]))
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
                request = VerifyRequest(_change_uuid(arguments["change_id"]), arguments["document_ref"],
                                        expected_value, shape_value)
                result = await _call(service.verify, principal, request)
                serializer = _verification
            if type(result) is not Result:
                return _safe_error(ErrorCode.AUDIT_UNAVAILABLE, correlation_id)
            if result.error is not None:
                safe_error = result.error if type(result.error) is ErrorCode else ErrorCode.AUDIT_UNAVAILABLE
                # The shared registry is authoritative. A supplied renderer can format only the
                # normalized safe ErrorCode; it never receives an arbitrary service value.
                if error_renderer is not None:
                    try:
                        error_renderer(safe_error)
                    except Exception:
                        pass
                return _safe_error(safe_error, correlation_id)
            if result.value is None:
                return _safe_error(ErrorCode.AUDIT_UNAVAILABLE, correlation_id)
            return {"isError": False, "result": serializer(result.value)}
        except (ValueError, TypeError, KeyError, PermissionError):
            return _safe_error(ErrorCode.SCHEMA_INVALID, correlation_id)
        except Exception:
            return _safe_error(ErrorCode.AUDIT_UNAVAILABLE, correlation_id)

    register_tool = getattr(server, "register_tool", None)
    if not callable(register_tool):
        raise TypeError("UNSUPPORTED_TOOL_SERVER")

    for spec in S16_TOOL_MANIFEST:
        async def handler(arguments: object, context: object = None,
                          *, _name: str = spec.name) -> dict[str, object]:
            return await dispatch(_name, arguments, context)
        handler.__name__ = f"s16_{spec.name}"
        register_tool(spec.name, handler, _thaw(spec.input_schema), _thaw(spec.annotations))

