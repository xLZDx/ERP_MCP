"""Phase 2 bounded capture permit (R2-US-024, REQ15/26). Unwired from Release 1.

Pure in-memory logic: no I/O, no wall clock of its own (an injected ``clock`` returns an aware
datetime), no caller input echoed in results (only fixed machine-readable codes).

Rules:
* A permit is issued by a HUMAN data owner for ONE (tenant, source) scope, a mode, an environment, a
  half-open window ``[not_before, not_after)``, a parameter digest (64 lowercase hex) and an optional
  ``max_uses`` (positive int, default None = unlimited).
* Issuer authority: the store is built with ``owners`` = {(tenant, source): HUMAN owner ids}. Only a
  registered owner of that exact (tenant, source) may issue (``ISSUER_NOT_OWNER`` otherwise) or revoke.
  The default registry is empty: nobody can issue (fail closed).
* The issuer must be HUMAN (LLM/AUTOMATION never) and must differ from the requester after identity
  normalisation (``_identity.clean_identity``: NFKC + casefold, zero-width/format chars are invalid).
* PROD is default OFF: refused at issue with ``PROD_DISABLED`` unless the store has ``prod_enabled``,
  and checked again at every ``admit`` (a flag turned off later denies already issued PROD permits).
* Window must be non-empty and at most ``max_window`` long (default 24h).
* Idempotency per (tenant, key): same key + same request replays the first result and creates
  nothing; same key + different request is ``IDEMPOTENCY_CONFLICT`` (HTTP 409 equivalent) and the
  store is unchanged. Only ISSUED results are remembered; refusals are not. A replay is refused
  (``PERMIT_REVOKED`` / ``PROD_DISABLED``) instead of presenting a dead permit as live.
* ``permit_id`` is a RANDOM handle (``id_source``, default ``secrets.token_hex(16)``), not derived from
  any input, and not a secret credential: ``admit`` is the only gate.
* ``admit(permit_id, tenant_id, source_id, mode, params_digest, requester)`` checks, first failure
  wins: scope FIRST -> mode -> params digest -> requester -> environment flag -> window -> uses.
  Unknown permit, wrong tenant/source and revoked permit all return the ONE code
  ``PERMIT_NOT_ADMITTABLE`` so no existence/revocation state leaks to a caller outside the scope.
  Later codes are only reachable by a caller that already proved the scope. A successful admit
  consumes one use. The time comes from the injected clock only. Wrong types never raise.
* ``revoke(permit_id, tenant_id, by)``: unknown permit, wrong tenant, non-issuer and non-owner all
  return the single code ``REVOKE_DENIED``.
* Audit: an append-only in-store log of PROD-flag changes and issue/admit/revoke outcomes (fixed codes
  and normalised ids only, ids truncated to 128 chars). It keeps at most ``max_audit`` entries (the
  oldest are dropped) and ``audit()`` returns a tuple copy taken under the lock.
* ``Environment`` here is this module's own enum; an ``Environment`` from another module (for example
  ``side_effect_boundary``) is rejected by design (``ENVIRONMENT_INVALID``), never coerced.

KNOWN GAPS: ``Issuer.kind`` and ids are asserted by the caller (no authenticated principal binding
here); the store is process-local and not persisted; an already-expired window can still be issued
(it is simply denied at use); the digest is not verified against real capture parameters; the audit
is in memory only and bounded (it is not tamper-proof storage).
"""
from __future__ import annotations

import secrets
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ._identity import clean_identity, exact_text, stable_key

__all__ = [
    "AdmitResult", "AuditEntry", "CaptureMode", "CapturePermit", "Environment", "IssueResult",
    "IssueStatus", "Issuer", "IssuerKind", "PermitRequest", "PermitStore", "RevokeResult",
]

_HEX = frozenset("0123456789abcdef")
_MAX_ID_LEN = 128
_ID_ATTEMPTS = 8


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
    max_uses: int | None = None


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
    max_uses: int | None = None


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


@dataclass(frozen=True, slots=True)
class AuditEntry:
    kind: str  # PROD_FLAG | ISSUE | ADMIT | REVOKE
    actor: str  # normalised actor id ('' when unusable)
    subject: str  # permit id of a known permit, else ''
    value: str  # 'True'/'False' for PROD_FLAG, else the fixed result code
    at: datetime | None  # UTC time from the injected clock, None if the clock was unusable


def _refused(code: str) -> IssueResult:
    return IssueResult(IssueStatus.REFUSED, None, code)


def _aware(value: object) -> datetime | None:
    """UTC-converted copy of an aware datetime, None for anything else (naive, wrong type)."""
    try:
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(UTC)
    except Exception:  # noqa: BLE001 - OverflowError near min/max, hostile tzinfo: fail closed
        return None


def _digest_ok(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in _HEX for ch in value)


def _ident(value: object) -> str:
    return clean_identity(value)[:_MAX_ID_LEN]


def _default_ids() -> str:
    return secrets.token_hex(16)


class PermitStore:
    def __init__(
        self,
        clock: Callable[[], datetime],
        *,
        prod_enabled: bool = False,
        max_window: timedelta = timedelta(hours=24),
        owners: Mapping[tuple[str, str], frozenset[str]] | None = None,
        id_source: Callable[[], str] | None = None,
        max_audit: int = 1000,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if type(prod_enabled) is not bool:
            raise TypeError("prod_enabled must be bool")
        if type(max_window) is not timedelta or max_window <= timedelta(0):
            raise ValueError("max_window must be a positive timedelta")
        if id_source is not None and not callable(id_source):
            raise TypeError("id_source must be callable")
        if type(max_audit) is not int or max_audit <= 0:
            raise ValueError("max_audit must be a positive int")
        registry: dict[tuple[str, str], frozenset[str]] = {}
        for scope, ids in (owners or {}).items():
            tenant, source = (clean_identity(part) for part in scope)
            clean = frozenset(i for i in (clean_identity(x) for x in ids) if i)
            if not tenant or not source:
                raise ValueError("owners keys must be valid (tenant, source) pairs")
            registry[(tenant, source)] = registry.get((tenant, source), frozenset()) | clean
        self._owners = registry
        self._id_source = id_source or _default_ids
        self._clock = clock
        self._prod_enabled = prod_enabled
        self._max_window = max_window
        self._lock = threading.Lock()
        self._permits: dict[str, CapturePermit] = {}
        self._revoked: set[str] = set()
        self._uses: dict[str, int] = {}
        # (tenant, idem key) -> (fingerprint, permit)
        self._by_key: dict[str, tuple[str, CapturePermit]] = {}
        self._audit: deque[AuditEntry] = deque(maxlen=max_audit)

    def _now(self) -> datetime | None:
        try:
            return _aware(self._clock())
        except Exception:  # noqa: BLE001 - a broken clock must fail closed, never leak text
            return None

    def _record(self, kind: str, actor: str, subject: str, value: str, at: datetime | None) -> None:
        with self._lock:
            self._audit.append(AuditEntry(kind, actor, subject, value, at))

    def audit(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._audit)

    def set_prod_enabled(self, enabled: bool, actor: str = "") -> bool:
        """Policy toggle; returns False (unchanged, not audited) for a non-bool value."""
        if type(enabled) is not bool:
            return False
        at = self._now()
        with self._lock:
            self._prod_enabled = enabled
            self._audit.append(AuditEntry("PROD_FLAG", _ident(actor), "", str(enabled), at))
        return True

    def count(self) -> int:
        """Number of issued permits (a method, so an empty store is not falsy)."""
        with self._lock:
            return len(self._permits)

    def issue(self, idempotency_key: str, request: PermitRequest, issuer: Issuer) -> IssueResult:
        at = self._now()
        result = self._issue(idempotency_key, request, issuer)
        actor = _ident(issuer.issuer_id) if type(issuer) is Issuer else ""
        subject = result.permit.permit_id if result.permit is not None else ""
        self._record("ISSUE", actor, subject, result.code, at)
        return result

    def _issue(self, idempotency_key: str, request: PermitRequest, issuer: Issuer) -> IssueResult:
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
        max_uses = request.max_uses
        if max_uses is not None and (type(max_uses) is not int or max_uses <= 0):
            return _refused("MAX_USES_INVALID")
        if issuer_id == requester:
            return _refused("ISSUER_IS_REQUESTER")
        if not_after <= not_before or not_after - not_before > self._max_window:
            return _refused("WINDOW_INVALID")
        if issuer_id not in self._owners.get((tenant, source), frozenset()):
            return _refused("ISSUER_NOT_OWNER")

        fingerprint = stable_key(
            tenant, source, request.mode.value, request.environment.value,
            not_before.isoformat(), not_after.isoformat(), request.params_digest,
            requester, issuer_id, str(max_uses),
        )
        idem_scope = stable_key(tenant, key)
        with self._lock:
            known = self._by_key.get(idem_scope)
            if known is not None:
                if known[0] == fingerprint:
                    if known[1].permit_id in self._revoked:
                        return _refused("PERMIT_REVOKED")
                    if known[1].environment is Environment.PROD and not self._prod_enabled:
                        return _refused("PROD_DISABLED")
                    return IssueResult(IssueStatus.REPLAYED, known[1], "REPLAYED")
                return _refused("IDEMPOTENCY_CONFLICT")
            if request.environment is Environment.PROD and not self._prod_enabled:
                return _refused("PROD_DISABLED")
            permit_id = ""
            for _ in range(_ID_ATTEMPTS):
                try:
                    candidate = self._id_source()
                except Exception:  # noqa: BLE001 - a broken id source fails closed
                    break
                if type(candidate) is str and candidate and candidate not in self._permits:
                    permit_id = candidate
                    break
            if not permit_id:
                return _refused("ID_UNAVAILABLE")
            permit = CapturePermit(
                permit_id=permit_id,
                tenant_id=tenant, source_id=source, mode=request.mode,
                environment=request.environment, not_before=not_before, not_after=not_after,
                params_digest=request.params_digest, issuer=issuer_id, requester=requester,
                max_uses=max_uses,
            )
            self._permits[permit_id] = permit
            self._by_key[idem_scope] = (fingerprint, permit)
            return IssueResult(IssueStatus.ISSUED, permit, "ISSUED")

    def admit(
        self,
        permit_id: str,
        tenant_id: str,
        source_id: str,
        mode: CaptureMode,
        params_digest: str,
        requester: str,
    ) -> AdmitResult:
        """Decide using the injected clock only; a success consumes one use."""
        at = self._now()
        result, subject = self._admit(permit_id, tenant_id, source_id, mode, params_digest,
                                      requester, at)
        self._record("ADMIT", _ident(requester), subject, result.code, at)
        return result

    def _admit(
        self, permit_id: str, tenant_id: str, source_id: str, mode: CaptureMode,
        params_digest: str, requester: str, now: datetime | None,
    ) -> tuple[AdmitResult, str]:
        not_admittable = AdmitResult(False, "PERMIT_NOT_ADMITTABLE")
        tenant = clean_identity(tenant_id)
        source = clean_identity(source_id)
        with self._lock:
            permit = self._permits.get(permit_id) if type(permit_id) is str else None
            if (permit is None or not tenant or not source or tenant != permit.tenant_id
                    or source != permit.source_id or permit.permit_id in self._revoked):
                return not_admittable, ""
            sid = permit.permit_id
            if type(mode) is not CaptureMode or mode is not permit.mode:
                return AdmitResult(False, "MODE_MISMATCH"), sid
            if type(params_digest) is not str or params_digest != permit.params_digest:
                return AdmitResult(False, "PARAMS_MISMATCH"), sid
            who = clean_identity(requester)
            if not who or who != permit.requester:
                return AdmitResult(False, "REQUESTER_MISMATCH"), sid
            if permit.environment is Environment.PROD and not self._prod_enabled:
                return AdmitResult(False, "PROD_DISABLED"), sid
            if now is None:
                return AdmitResult(False, "TIME_INVALID"), sid
            if now < permit.not_before:
                return AdmitResult(False, "NOT_YET_VALID"), sid
            if now >= permit.not_after:
                return AdmitResult(False, "EXPIRED"), sid
            used = self._uses.get(sid, 0)
            if permit.max_uses is not None and used >= permit.max_uses:
                return AdmitResult(False, "USES_EXHAUSTED"), sid
            self._uses[sid] = used + 1
            return AdmitResult(True, "ADMITTED"), sid

    def revoke(self, permit_id: str, tenant_id: str, by: Issuer) -> RevokeResult:
        at = self._now()
        result, subject = self._revoke(permit_id, tenant_id, by)
        actor = _ident(by.issuer_id) if type(by) is Issuer else ""
        self._record("REVOKE", actor, subject, result.code, at)
        return result

    def _revoke(self, permit_id: str, tenant_id: str, by: Issuer) -> tuple[RevokeResult, str]:
        denied = (RevokeResult(False, "REVOKE_DENIED"), "")
        if type(permit_id) is not str or type(by) is not Issuer or by.kind is not IssuerKind.HUMAN:
            return denied
        who = clean_identity(by.issuer_id)
        tenant = clean_identity(tenant_id)
        with self._lock:
            permit = self._permits.get(permit_id)
            if (permit is None or not who or who != permit.issuer
                    or not tenant or tenant != permit.tenant_id
                    or who not in self._owners.get((permit.tenant_id, permit.source_id), frozenset())):
                return denied
            self._revoked.add(permit_id)
            return RevokeResult(True, "REVOKED"), permit_id
