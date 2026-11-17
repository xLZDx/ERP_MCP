"""Bounded offline intake of caller-supplied native baseline bytes (S5 R2-US-021).

This is an adapter contract, not 1C authentication, native-origin proof, or a
completeness detector. Authentication is delegated to an injected authorizer;
the in-memory vault remains test-only and process-local.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from .artifact_vault import ArtifactRef, ArtifactScope, ArtifactVault, Principal, PutStatus

__all__ = [
    "BaselineCompleteness", "BaselineIntake", "BaselineIntakeStatus", "BaselineManifestClaims",
    "BaselineRead", "BaselineResult", "TrustedCaptureContext",
]

_MAX_ID = 256
_MAX_TEXT = 4096
_MAX_PAIRS = 128
_MAX_COLUMNS = 256
_MAX_TOTAL_TEXT = 100_000
_MAX_REQUESTS = 10_000
_MEDIA_TYPES = frozenset({"text/csv", "application/pdf"})


class BaselineIntakeStatus(StrEnum):
    UNATTESTED = "UNATTESTED"


class BaselineCompleteness(StrEnum):
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True, slots=True)
class TrustedCaptureContext:
    """Exact scope supplied by an authenticated adapter, never from the manifest."""

    tenant_id: str
    source_id: str
    database_id: str
    company_id: str
    caller_namespace: str
    report_object: str
    variant: str


@dataclass(frozen=True, slots=True)
class BaselineManifestClaims:
    """Structured uploader claims; values are retained as claims, not verified facts."""

    tenant_id: str
    source_id: str
    database_id: str
    company_id: str
    report_object: str
    variant: str
    period: str
    filters: tuple[tuple[str, str], ...]
    columns: tuple[str, ...]
    totals: tuple[tuple[str, str], ...]
    row_limit_reached: bool | None
    partial: bool
    known_truncated: bool


@dataclass(frozen=True, slots=True)
class BaselineResult:
    baseline_id: str
    request_id: str
    tenant_id: str
    source_id: str
    database_id: str
    company_id: str
    report_object: str
    variant: str
    period: str
    filters: tuple[tuple[str, str], ...]
    columns: tuple[str, ...]
    totals: tuple[tuple[str, str], ...]
    media_type: str
    size: int
    sha256: str
    attestation: BaselineIntakeStatus = BaselineIntakeStatus.UNATTESTED
    completeness: BaselineCompleteness = BaselineCompleteness.UNVERIFIED


@dataclass(frozen=True, slots=True)
class BaselineRead:
    result: BaselineResult | None
    content: bytes | None
    code: str


@dataclass(frozen=True, slots=True)
class _Binding:
    context: TrustedCaptureContext
    principal_id: str
    request_id: str
    claims: BaselineManifestClaims
    media_type: str
    size: int
    digest: str


@dataclass(frozen=True, slots=True)
class _Published:
    binding: _Binding
    result: BaselineResult
    ref: ArtifactRef


def _bounded_text(value: object, limit: int, *, empty: bool = False) -> bool:
    return (type(value) is str and (empty or bool(value)) and len(value) <= limit
            and value == value.strip() and "\x00" not in value)


def _valid_pairs(value: object) -> bool:
    if type(value) is not tuple or len(value) > _MAX_PAIRS:
        return False
    prior: str | None = None
    for pair in value:
        if type(pair) is not tuple or len(pair) != 2:
            return False
        key, item = pair
        if not _bounded_text(key, _MAX_TEXT) or not _bounded_text(item, _MAX_TEXT, empty=True):
            return False
        if prior is not None and key <= prior:
            return False
        prior = key
    return True


def _valid_context(context: object) -> bool:
    return (type(context) is TrustedCaptureContext and all(
        _bounded_text(getattr(context, field), _MAX_ID)
        for field in ("tenant_id", "source_id", "database_id", "company_id", "caller_namespace", "report_object", "variant")
    ))


def _valid_claims(claims: object, context: TrustedCaptureContext) -> bool:
    if type(claims) is not BaselineManifestClaims:
        return False
    ids = (claims.tenant_id, claims.source_id, claims.database_id, claims.company_id)
    if not all(_bounded_text(v, _MAX_ID) for v in ids):
        return False
    if ids != (context.tenant_id, context.source_id, context.database_id, context.company_id):
        return False
    if not all(_bounded_text(v, _MAX_TEXT) for v in (
        claims.report_object, claims.variant, claims.period,
    )):
        return False
    if (claims.report_object, claims.variant) != (context.report_object, context.variant):
        return False
    if (not _valid_pairs(claims.filters) or not _valid_pairs(claims.totals) or not claims.totals
            or type(claims.columns) is not tuple
            or not 1 <= len(claims.columns) <= _MAX_COLUMNS
            or any(not _bounded_text(v, _MAX_TEXT) for v in claims.columns)
            or len(set(claims.columns)) != len(claims.columns)):
        return False
    if type(claims.row_limit_reached) is not bool or claims.row_limit_reached:
        return False
    if type(claims.partial) is not bool or claims.partial:
        return False
    if type(claims.known_truncated) is not bool or claims.known_truncated:
        return False
    total = sum(map(len, ids + (claims.report_object, claims.variant, claims.period)))
    total += sum(len(k) + len(v) for k, v in claims.filters + claims.totals)
    total += sum(map(len, claims.columns))
    return total <= _MAX_TOTAL_TEXT


class BaselineIntake:
    """Process-local immutable intake with caller authorization on every access.

    The authorizer must consult the real authenticated identity and exact scope;
    it is not a boolean supplied by the uploading caller. ``ArtifactVault`` ACL
    grants must separately permit ``vault_principal`` in the tenant/source scope.
    """

    def __init__(self, vault: ArtifactVault, vault_principal: Principal,
                 authorize: Callable[[TrustedCaptureContext, Principal], bool], *,
                 authorize_request: Callable[[TrustedCaptureContext, Principal, str], bool],
                 id_source: Callable[[], str] = lambda: secrets.token_urlsafe(24),
                 max_bytes: int = 5_000_000, max_requests: int = _MAX_REQUESTS) -> None:
        if type(vault) is not ArtifactVault or type(vault_principal) is not Principal:
            raise TypeError("invalid intake dependency")
        if not all(callable(dependency) for dependency in (authorize, authorize_request, id_source)):
            raise TypeError("authorization and ID dependencies must be callable")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if type(max_requests) is not int or max_requests <= 0:
            raise ValueError("max_requests must be positive")
        self._vault = vault
        self._vault_principal = vault_principal
        self._authorize = authorize
        self._authorize_request = authorize_request
        self._id_source = id_source
        self._max_bytes = min(max_bytes, 5_000_000)
        self._max_requests = min(max_requests, _MAX_REQUESTS)
        self._lock = threading.RLock()
        self._by_request: dict[tuple[str, str], _Published] = {}
        self._by_baseline: dict[str, _Published] = {}

    def _authorized(self, context: object, principal: object) -> bool:
        if (not _valid_context(context) or type(principal) is not Principal
                or not _bounded_text(principal.principal_id, _MAX_ID)):
            return False
        try:
            return self._authorize(context, principal) is True
        except Exception:  # authorization failure always denies without leaking details
            return False

    def _request_authorized(self, context: TrustedCaptureContext, principal: Principal,
                            request_id: str) -> bool:
        """Require the trusted intake workflow to bind this ID to the caller and scope."""
        if not _bounded_text(request_id, _MAX_ID) or not self._authorized(context, principal):
            return False
        try:
            return self._authorize_request(context, principal, request_id) is True
        except Exception:
            return False

    @staticmethod
    def _request_key(binding: _Binding) -> tuple[str, str]:
        return binding.context.caller_namespace, binding.request_id

    @staticmethod
    def _same_binding(left: _Binding, right: _Binding) -> bool:
        # Exact value equality over validated immutable built-ins only.
        return left == right

    @staticmethod
    def _publication_allowed(authorize: Callable[[], bool] | None) -> bool:
        if authorize is None:
            return True
        try:
            return authorize() is True
        except Exception:
            return False

    def _verified_read(self, published: _Published, context: TrustedCaptureContext,
                       principal: Principal) -> bytes | None:
        if (not self._authorized(context, principal)
                or published.binding.context != context
                or published.binding.principal_id != principal.principal_id):
            return None
        scope = ArtifactScope(context.tenant_id, context.source_id)
        try:
            read = self._vault.read(published.ref, self._vault_principal)
        except Exception:
            return None
        if not read.allowed or type(read.content) is not bytes or read.media_type != published.result.media_type:
            return None
        data = read.content
        if (len(data) != published.result.size
                or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), published.result.sha256)
                or published.ref.scope != scope or published.ref.size != len(data)
                or published.ref.digest != published.result.sha256):
            return None
        return data

    def intake(self, *, context: TrustedCaptureContext, principal: Principal, request_id: str,
               claims: BaselineManifestClaims, content: bytes, media_type: str,
               publication_authorized: Callable[[], bool] | None = None) -> tuple[BaselineResult | None, str]:
        """Validate, write, verify read-back, then atomically publish/replay."""
        if (not self._request_authorized(context, principal, request_id)
                or not self._publication_allowed(publication_authorized)):
            return None, "INTAKE_REFUSED"
        if (type(content) is not bytes or not content
                or len(content) > self._max_bytes or type(media_type) is not str
                or media_type not in _MEDIA_TYPES or not _valid_claims(claims, context)):
            return None, "INTAKE_REFUSED"
        digest = hashlib.sha256(content).hexdigest()
        binding = _Binding(context, principal.principal_id, request_id, claims,
                           media_type, len(content), digest)
        key = self._request_key(binding)

        with self._lock:
            existing = self._by_request.get(key)
            if existing is not None:
                if (not self._request_authorized(context, principal, request_id)
                        or not self._same_binding(existing.binding, binding)):
                    return None, "INTAKE_REFUSED"
                verified = self._verified_read(existing, context, principal)
                if verified is None or not self._publication_allowed(publication_authorized):
                    return None, "INTAKE_REFUSED"
                return existing.result, "OK"

        try:
            put = self._vault.put(ArtifactScope(context.tenant_id, context.source_id),
                                  content, self._vault_principal, media_type)
            if put.status not in (PutStatus.STORED, PutStatus.DUPLICATE) or type(put.ref) is not ArtifactRef:
                return None, "INTAKE_REFUSED"
            ref = put.ref
            read = self._vault.read(ref, self._vault_principal)
        except Exception:  # store failures are a fixed refusal
            return None, "INTAKE_REFUSED"
        if (not read.allowed or type(read.content) is not bytes or read.content != content
                or read.media_type != media_type or ref.scope != ArtifactScope(context.tenant_id, context.source_id)
                or ref.size != len(content) or ref.digest != digest
                or not hmac.compare_digest(hashlib.sha256(read.content).hexdigest(), digest)):
            return None, "INTAKE_REFUSED"

        with self._lock:
            # Authorization is checked again at the publication boundary; a
            # revocation during vault I/O must not publish a successful result.
            if (not self._request_authorized(context, principal, request_id)
                    or not self._publication_allowed(publication_authorized)):
                return None, "INTAKE_REFUSED"
            existing = self._by_request.get(key)
            if existing is not None:
                if not self._same_binding(existing.binding, binding):
                    return None, "INTAKE_REFUSED"
                verified = self._verified_read(existing, context, principal)
                if verified is None or not self._publication_allowed(publication_authorized):
                    return None, "INTAKE_REFUSED"
                return existing.result, "OK"
            if len(self._by_request) >= self._max_requests:
                return None, "INTAKE_REFUSED"
            try:
                baseline_id = self._id_source()
            except Exception:
                return None, "INTAKE_REFUSED"
            if (not _bounded_text(baseline_id, _MAX_ID) or baseline_id in self._by_baseline):
                return None, "INTAKE_REFUSED"
            result = BaselineResult(
                baseline_id, request_id, context.tenant_id, context.source_id,
                context.database_id, context.company_id, claims.report_object,
                claims.variant, claims.period, claims.filters, claims.columns,
                claims.totals, media_type, len(content), digest,
            )
            published = _Published(binding, result, ref)
            if (not self._request_authorized(context, principal, request_id)
                    or not self._publication_allowed(publication_authorized)):
                return None, "INTAKE_REFUSED"
            try:
                self._by_baseline[baseline_id] = published
                self._by_request[key] = published
            except Exception:
                self._by_baseline.pop(baseline_id, None)
                return None, "INTAKE_REFUSED"
            return result, "OK"

    def recover(self, *, context: TrustedCaptureContext, principal: Principal,
                request_id: str) -> tuple[BaselineResult | None, str]:
        """Recover an exact published request only after fresh full-scope authorization."""
        if not self._request_authorized(context, principal, request_id):
            return None, "INTAKE_REFUSED"
        with self._lock:
            published = self._by_request.get((context.caller_namespace, request_id))
            if published is None or not self._request_authorized(context, principal, request_id):
                return None, "INTAKE_REFUSED"
            if self._verified_read(published, context, principal) is None:
                return None, "INTAKE_REFUSED"
            return published.result, "OK"

    def read(self, *, context: TrustedCaptureContext, principal: Principal,
             baseline_id: str) -> BaselineRead:
        """Read private original bytes by opaque ID after rechecking exact authorization."""
        if not self._authorized(context, principal) or not _bounded_text(baseline_id, _MAX_ID):
            return BaselineRead(None, None, "INTAKE_REFUSED")
        with self._lock:
            published = self._by_baseline.get(baseline_id)
            if published is None:
                return BaselineRead(None, None, "INTAKE_REFUSED")
            content = self._verified_read(published, context, principal)
            if content is None:
                return BaselineRead(None, None, "INTAKE_REFUSED")
            return BaselineRead(published.result, content, "OK")
