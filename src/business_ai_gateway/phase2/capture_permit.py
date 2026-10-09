"""Phase 2 bounded capture permit (R2-US-024, REQ15/26). Unwired from Release 1.

Pure in-memory logic: no I/O, no wall clock of its own (an injected ``clock`` returns an aware
datetime), no caller input echoed in results (only fixed machine-readable codes).

Rules:
* A permit is issued by a HUMAN data owner for ONE (tenant, source) scope, a mode, an environment, a
  half-open window ``[not_before, not_after)`` and a parameter digest (64 lowercase hex).
* The issuer must be HUMAN (LLM/AUTOMATION never) and must differ from the requester after identity
  normalisation (``_identity.clean_identity``: NFKC + casefold, zero-width/format chars are invalid).
* PROD is default OFF: refused at issue with ``PROD_DISABLED`` unless the store has ``prod_enabled``,
  and checked again at every ``admit`` (a flag turned off later denies already issued PROD permits).
* Window must be non-empty and at most ``max_window`` long (default 24h).
* Idempotency per (tenant, key): same key + same request replays the first result and creates
  nothing; same key + different request is ``IDEMPOTENCY_CONFLICT`` (HTTP 409 equivalent) and the
  store is unchanged. Only ISSUED results are remembered; refusals are not.
* ``admit`` checks, first failure wins: unknown -> revoked -> scope (tenant AND source, one code so
  no cross-tenant existence oracle) -> mode -> environment flag -> window. Wrong types never raise.
* ``revoke`` is allowed only for the HUMAN issuer of that permit.

KNOWN GAPS: ``Issuer.kind`` and ids are asserted by the caller (no authenticated principal binding
here); the store is process-local and not persisted; an already-expired window can still be issued
(it is simply denied at use); the digest is not verified against real capture parameters.
"""
from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ._identity import clean_identity, exact_text, stable_key

__all__ = [
    "AdmitResult", "CaptureMode", "CapturePermit", "Environment", "IssueResult", "IssueStatus",
    "Issuer", "IssuerKind", "PermitRequest", "PermitStore", "RevokeResult",
]

_HEX = frozenset("0123456789abcdef")


class CaptureMode(StrEnum):
    READ_SNAPSHOT = "READ_SNAPSHOT"
    READ_INCREMENTAL = "READ_INCREMENTAL"


class Environment(StrEnum):
    NON_PROD = "NON_PROD"
    PROD = "PROD"


class IssuerKind(StrEnum):
    HUMAN = "HUMAN"
    LLM = "LLM"
    AUTOMATION = "AUTOMATION"


class IssueStatus(StrEnum):
    ISSUED = "ISSUED"
    REPLAYED = "REPLAYED"
    REFUSED = "REFUSED"


@dataclass(frozen=True, slots=True)
class Issuer:
    kind: IssuerKind
    issuer_id: str


@dataclass(frozen=True, slots=True)
class PermitRequest:
    tenant_id: str
    source_id: str
    mode: CaptureMode
    environment: Environment
    not_before: datetime
    not_after: datetime
    params_digest: str
    requester: str


@dataclass(frozen=True, slots=True)
class CapturePermit:
    permit_id: str
    tenant_id: str  # normalised
    source_id: str  # normalised
    mode: CaptureMode
    environment: Environment
    not_before: datetime  # UTC
    not_after: datetime  # UTC
    params_digest: str
    issuer: str  # normalised
    requester: str  # normalised


@dataclass(frozen=True, slots=True)
class IssueResult:
    status: IssueStatus
    permit: CapturePermit | None
    code: str


@dataclass(frozen=True, slots=True)
class AdmitResult:
    allowed: bool
    code: str


@dataclass(frozen=True, slots=True)
class RevokeResult:
    revoked: bool
    code: str


def _refused(code: str) -> IssueResult:
    return IssueResult(IssueStatus.REFUSED, None, code)


def _aware(value: object) -> datetime | None:
    """UTC-converted copy of an aware datetime, None for anything else (naive, wrong type)."""
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def _digest_ok(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in _HEX for ch in value)


class PermitStore:
    def __init__(
        self,
        clock: Callable[[], datetime],
        *,
        prod_enabled: bool = False,
        max_window: timedelta = timedelta(hours=24),
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if type(prod_enabled) is not bool:
            raise TypeError("prod_enabled must be bool")
        if type(max_window) is not timedelta or max_window <= timedelta(0):
            raise ValueError("max_window must be a positive timedelta")
        self._clock = clock
        self._prod_enabled = prod_enabled
        self._max_window = max_window
        self._lock = threading.Lock()
        self._permits: dict[str, CapturePermit] = {}
        self._revoked: set[str] = set()
        self._by_key: dict[str, tuple[str, CapturePermit]] = {}  # idem key -> (fingerprint, permit)

    def set_prod_enabled(self, enabled: bool) -> bool:
        """Policy toggle; returns False (unchanged) for a non-bool value."""
        if type(enabled) is not bool:
            return False
        with self._lock:
            self._prod_enabled = enabled
        return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._permits)

    def _now(self) -> datetime | None:
        try:
            return _aware(self._clock())
        except Exception:  # noqa: BLE001 - a broken clock must fail closed, never leak text
            return None

    def issue(self, idempotency_key: str, request: PermitRequest, issuer: Issuer) -> IssueResult:
        key = exact_text(idempotency_key)
        if not key:
            return _refused("IDEMPOTENCY_KEY_INVALID")
        if type(request) is not PermitRequest:
            return _refused("REQUEST_INVALID")
        if type(issuer) is not Issuer or type(issuer.kind) is not IssuerKind:
            return _refused("ISSUER_INVALID")
        if issuer.kind is not IssuerKind.HUMAN:
            return _refused("ISSUER_NOT_HUMAN")
        issuer_id = clean_identity(issuer.issuer_id)
        if not issuer_id:
            return _refused("ISSUER_INVALID")
        tenant = clean_identity(request.tenant_id)
        source = clean_identity(request.source_id)
        requester = clean_identity(request.requester)
        if not tenant or not source:
            return _refused("SCOPE_INVALID")
        if not requester:
            return _refused("REQUESTER_INVALID")
        if type(request.mode) is not CaptureMode:
            return _refused("MODE_INVALID")
        if type(request.environment) is not Environment:
            return _refused("ENVIRONMENT_INVALID")
        not_before = _aware(request.not_before)
        not_after = _aware(request.not_after)
        if not_before is None or not_after is None:
            return _refused("WINDOW_INVALID")
        if not _digest_ok(request.params_digest):
            return _refused("DIGEST_INVALID")
        if issuer_id == requester:
            return _refused("ISSUER_IS_REQUESTER")
        if not_after <= not_before or not_after - not_before > self._max_window:
            return _refused("WINDOW_INVALID")

        fingerprint = stable_key(
            tenant, source, request.mode.value, request.environment.value,
            not_before.isoformat(), not_after.isoformat(), request.params_digest,
            requester, issuer_id,
        )
        idem_scope = stable_key(tenant, key)
        with self._lock:
            known = self._by_key.get(idem_scope)
            if known is not None:
                if known[0] == fingerprint:
                    return IssueResult(IssueStatus.REPLAYED, known[1], "REPLAYED")
                return _refused("IDEMPOTENCY_CONFLICT")
            if request.environment is Environment.PROD and not self._prod_enabled:
                return _refused("PROD_DISABLED")
            permit = CapturePermit(
                permit_id=hashlib.sha256(idem_scope.encode("ascii")).hexdigest()[:32],
                tenant_id=tenant, source_id=source, mode=request.mode,
                environment=request.environment, not_before=not_before, not_after=not_after,
                params_digest=request.params_digest, issuer=issuer_id, requester=requester,
            )
            self._permits[permit.permit_id] = permit
            self._by_key[idem_scope] = (fingerprint, permit)
            return IssueResult(IssueStatus.ISSUED, permit, "ISSUED")

    def admit(
        self,
        permit_id: str,
        tenant_id: str,
        source_id: str,
        mode: CaptureMode,
        at: datetime | None = None,
    ) -> AdmitResult:
        if type(permit_id) is not str:
            return AdmitResult(False, "PERMIT_UNKNOWN")
        with self._lock:
            permit = self._permits.get(permit_id)
            revoked = permit_id in self._revoked
            prod_enabled = self._prod_enabled
        if permit is None:
            return AdmitResult(False, "PERMIT_UNKNOWN")
        if revoked:
            return AdmitResult(False, "PERMIT_REVOKED")
        tenant = clean_identity(tenant_id)
        source = clean_identity(source_id)
        if not tenant or not source or tenant != permit.tenant_id or source != permit.source_id:
            return AdmitResult(False, "SCOPE_MISMATCH")
        if type(mode) is not CaptureMode or mode is not permit.mode:
            return AdmitResult(False, "MODE_MISMATCH")
        if permit.environment is Environment.PROD and not prod_enabled:
            return AdmitResult(False, "PROD_DISABLED")
        now = self._now() if at is None else _aware(at)
        if now is None:
            return AdmitResult(False, "TIME_INVALID")
        if now < permit.not_before:
            return AdmitResult(False, "NOT_YET_VALID")
        if now >= permit.not_after:
            return AdmitResult(False, "EXPIRED")
        return AdmitResult(True, "ADMITTED")

    def revoke(self, permit_id: str, by: Issuer) -> RevokeResult:
        if type(permit_id) is not str:
            return RevokeResult(False, "PERMIT_UNKNOWN")
        if type(by) is not Issuer or by.kind is not IssuerKind.HUMAN:
            return RevokeResult(False, "REVOKER_NOT_ISSUER")
        who = clean_identity(by.issuer_id)
        with self._lock:
            permit = self._permits.get(permit_id)
            if permit is None:
                return RevokeResult(False, "PERMIT_UNKNOWN")
            if not who or who != permit.issuer:
                return RevokeResult(False, "REVOKER_NOT_ISSUER")
            self._revoked.add(permit_id)
            return RevokeResult(True, "REVOKED")
