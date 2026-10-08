"""Phase 2 connector SDK contract: snapshot-only request/response envelopes.

Pure and offline. A connector never receives or returns an arbitrary URL, SQL text or
credential material: the server resolves endpoints and secrets from its own source
registry. Every envelope is validated fail-closed and a failure raises
ValidationError listing every reason found (not only the first).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_OPAQUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.=-]{0,511}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")

# Substrings of a normalized key (lowercase, only [a-z0-9]) that mark forbidden material.
_FORBIDDEN_KEY_PARTS = (
    "password", "passwd", "pwd", "secret", "token", "authorization", "bearer",
    "apikey", "credential", "connectionstring", "connstr", "dsn", "cookie",
    "privatekey", "url", "uri", "sql", "query",
)
_URL_VALUE = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]*://|\bwww\.|\bfile:)")
_SQL_VALUE = re.compile(
    r"(?is)\b(?:select\b.+\bfrom|insert\s+into|update\b.+\bset|delete\s+from|"
    r"drop\s+(?:table|database)|union\s+select|exec(?:ute)?\s+\w+)\b|;\s*--|/\*")
_SECRET_VALUE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]|\bbearer\s+\S|\bbasic\s+[A-Za-z0-9+/=]{8,}")


class CaptureMode(StrEnum):
    SNAPSHOT_ONLY = "SNAPSHOT_ONLY"


class Completeness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class HealthState(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


class ValidationError(ValueError):
    """Typed fail-closed rejection carrying every reason code found."""

    def __init__(self, reasons: list[str] | tuple[str, ...]) -> None:
        self.reasons: tuple[str, ...] = tuple(reasons)
        super().__init__("; ".join(self.reasons))


def _normalize_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def forbidden_key(key: object) -> bool:
    norm = _normalize_key(key)
    return any(part in norm for part in _FORBIDDEN_KEY_PARTS)


def _forbidden_value(value: str) -> str | None:
    if _URL_VALUE.search(value):
        return "URL_VALUE"
    if _SQL_VALUE.search(value):
        return "SQL_VALUE"
    if _SECRET_VALUE.search(value):
        return "CREDENTIAL_VALUE"
    return None


def _check_text(name: str, value: object, pattern: re.Pattern[str], reasons: list[str],
                *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str):
        reasons.append(f"{name}:NOT_A_STRING")
        return
    if not value.strip():
        reasons.append(f"{name}:BLANK")
        return
    bad = _forbidden_value(value)
    if bad:
        reasons.append(f"{name}:{bad}")
        return
    if not pattern.fullmatch(value):
        reasons.append(f"{name}:INVALID_FORMAT")


def _check_timestamp(name: str, value: object, reasons: list[str]) -> None:
    if not isinstance(value, datetime):
        reasons.append(f"{name}:NOT_A_DATETIME")
    elif value.tzinfo is None or value.utcoffset() is None:
        reasons.append(f"{name}:NAIVE_TIMESTAMP")
    elif value.utcoffset() != timedelta(0):
        reasons.append(f"{name}:NON_UTC_TIMESTAMP")


def _check_scope(source_id: object, tenant_id: object, scope_epoch: object,
                 capture_mode: object, reasons: list[str]) -> None:
    _check_text("source_id", source_id, _ID, reasons)
    _check_text("tenant_id", tenant_id, _ID, reasons)
    if type(scope_epoch) is not int:
        reasons.append("scope_epoch:NOT_AN_INTEGER")
    elif scope_epoch < 0:
        reasons.append("scope_epoch:NEGATIVE")
    if not isinstance(capture_mode, CaptureMode):
        reasons.append("capture_mode:UNKNOWN_MODE")


@dataclass(frozen=True, slots=True)
class CaptureRequest:
    source_id: str
    tenant_id: str
    scope_epoch: int
    capture_mode: CaptureMode = CaptureMode.SNAPSHOT_ONLY
    page_cursor: str | None = None  # opaque cursor issued by a previous response

    def __post_init__(self) -> None:
        reasons: list[str] = []
        _check_scope(self.source_id, self.tenant_id, self.scope_epoch, self.capture_mode, reasons)
        _check_text("page_cursor", self.page_cursor, _OPAQUE, reasons, optional=True)
        if reasons:
            raise ValidationError(reasons)


@dataclass(frozen=True, slots=True)
class Provenance:
    connector_id: str
    connector_version: str
    observed_at: datetime
    content_digest: str
    page_cursor: str | None = None  # cursor of this page (None for the first page)
    next_cursor: str | None = None  # cursor for the next page (None when no more pages)

    def __post_init__(self) -> None:
        reasons: list[str] = []
        _check_text("connector_id", self.connector_id, _ID, reasons)
        _check_text("connector_version", self.connector_version, _VERSION, reasons)
        _check_timestamp("observed_at", self.observed_at, reasons)
        _check_text("content_digest", self.content_digest, _DIGEST, reasons)
        _check_text("page_cursor", self.page_cursor, _OPAQUE, reasons, optional=True)
        _check_text("next_cursor", self.next_cursor, _OPAQUE, reasons, optional=True)
        if reasons:
            raise ValidationError(reasons)


@dataclass(frozen=True, slots=True)
class CaptureResponse:
    source_id: str
    tenant_id: str
    scope_epoch: int
    capture_mode: CaptureMode
    completeness: Completeness
    provenance: Provenance

    def __post_init__(self) -> None:
        reasons: list[str] = []
        _check_scope(self.source_id, self.tenant_id, self.scope_epoch, self.capture_mode, reasons)
        if not isinstance(self.completeness, Completeness):
            reasons.append("completeness:UNKNOWN_VALUE")
        if not isinstance(self.provenance, Provenance):
            reasons.append("provenance:NOT_PROVENANCE")
        if reasons:
            raise ValidationError(reasons)


@runtime_checkable
class ConnectorContract(Protocol):
    """Minimal read-only connector surface. Implementations must be snapshot-only."""

    connector_id: str
    connector_version: str

    def capture_page(self, request: CaptureRequest) -> CaptureResponse: ...

    def health(self, *, source_id: str, tenant_id: str) -> HealthState: ...


_REQUEST_FIELDS = frozenset({"source_id", "tenant_id", "scope_epoch", "capture_mode", "page_cursor"})
_RESPONSE_FIELDS = frozenset({
    "source_id", "tenant_id", "scope_epoch", "capture_mode", "completeness", "provenance"})
_PROVENANCE_FIELDS = frozenset({
    "connector_id", "connector_version", "observed_at", "content_digest",
    "page_cursor", "next_cursor"})


def _scan_keys(data: Mapping[str, Any], allowed: frozenset[str], prefix: str,
               reasons: list[str]) -> None:
    for key in data:
        label = f"{prefix}{key}"
        if forbidden_key(key):
            reasons.append(f"{label}:FORBIDDEN_FIELD")
        elif key not in allowed:
            reasons.append(f"{label}:UNKNOWN_FIELD")


def _enum(enum_cls: type[StrEnum], value: object, name: str, reasons: list[str]) -> Any:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError:
        reasons.append(f"{name}:UNKNOWN_VALUE")
        return None


def _utc_datetime(value: object) -> object:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _require_mapping(data: object, reasons_name: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise ValidationError([f"{reasons_name}:NOT_A_MAPPING"])
    return data


def parse_request(data: object) -> CaptureRequest:
    mapping = _require_mapping(data, "request")
    reasons: list[str] = []
    _scan_keys(mapping, _REQUEST_FIELDS, "", reasons)
    for required in ("source_id", "tenant_id", "scope_epoch", "capture_mode"):
        if required not in mapping:
            reasons.append(f"{required}:MISSING")
    if reasons:
        raise ValidationError(reasons)
    mode = _enum(CaptureMode, mapping["capture_mode"], "capture_mode", reasons)
    if reasons:
        raise ValidationError(reasons)
    return CaptureRequest(
        source_id=mapping["source_id"], tenant_id=mapping["tenant_id"],
        scope_epoch=mapping["scope_epoch"], capture_mode=mode,
        page_cursor=mapping.get("page_cursor"))


def parse_response(data: object) -> CaptureResponse:
    mapping = _require_mapping(data, "response")
    reasons: list[str] = []
    _scan_keys(mapping, _RESPONSE_FIELDS, "", reasons)
    for required in _RESPONSE_FIELDS:
        if required not in mapping:
            reasons.append(f"{required}:MISSING")
    prov_raw = mapping.get("provenance")
    if "provenance" in mapping and not isinstance(prov_raw, Mapping):
        reasons.append("provenance:NOT_A_MAPPING")
    elif isinstance(prov_raw, Mapping):
        _scan_keys(prov_raw, _PROVENANCE_FIELDS, "provenance.", reasons)
        for required in ("connector_id", "connector_version", "observed_at", "content_digest"):
            if required not in prov_raw:
                reasons.append(f"provenance.{required}:MISSING")
    if reasons:
        raise ValidationError(reasons)
    mode = _enum(CaptureMode, mapping["capture_mode"], "capture_mode", reasons)
    completeness = _enum(Completeness, mapping["completeness"], "completeness", reasons)
    if reasons:
        raise ValidationError(reasons)
    try:
        provenance = Provenance(
            connector_id=prov_raw["connector_id"],
            connector_version=prov_raw["connector_version"],
            observed_at=_utc_datetime(prov_raw["observed_at"]),
            content_digest=prov_raw["content_digest"],
            page_cursor=prov_raw.get("page_cursor"),
            next_cursor=prov_raw.get("next_cursor"))
    except ValidationError as exc:
        # Keep collecting: report envelope-level problems together with provenance ones.
        reasons.extend(f"provenance.{r}" for r in exc.reasons)
        provenance = None
    if provenance is None:
        try:
            CaptureResponse(
                source_id=mapping["source_id"], tenant_id=mapping["tenant_id"],
                scope_epoch=mapping["scope_epoch"], capture_mode=mode,
                completeness=completeness, provenance=_PLACEHOLDER)
        except ValidationError as exc:
            reasons.extend(exc.reasons)
        raise ValidationError(reasons)
    return CaptureResponse(
        source_id=mapping["source_id"], tenant_id=mapping["tenant_id"],
        scope_epoch=mapping["scope_epoch"], capture_mode=mode,
        completeness=completeness, provenance=provenance)


_PLACEHOLDER = Provenance("placeholder", "0", datetime(1970, 1, 1, tzinfo=UTC), "0" * 64)


def validate_exchange(request: CaptureRequest, response: CaptureResponse) -> CaptureResponse:
    """Reject a response that does not belong to the request (scope confusion)."""
    if not isinstance(request, CaptureRequest) or not isinstance(response, CaptureResponse):
        raise ValidationError(["exchange:WRONG_TYPES"])
    reasons = [
        f"{field}:RESPONSE_MISMATCH"
        for field in ("tenant_id", "source_id", "scope_epoch", "capture_mode")
        if getattr(request, field) != getattr(response, field)
    ]
    if request.page_cursor != response.provenance.page_cursor:
        reasons.append("page_cursor:RESPONSE_MISMATCH")
    if reasons:
        raise ValidationError(reasons)
    return response


def checked_capture_page(connector: ConnectorContract, request: CaptureRequest) -> CaptureResponse:
    """Call a connector and fail closed on a malformed or foreign response."""
    response = connector.capture_page(request)
    return validate_exchange(request, response)
