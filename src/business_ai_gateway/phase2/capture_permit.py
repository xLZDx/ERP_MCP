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
_MAX_USES_CAP = 10**9


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
        prod_admins: frozenset[str] | set[str] | list[str] | tuple[str, ...] = (),
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
        if type(prod_admins) not in (set, frozenset, list, tuple) or any(
                type(x) is not str for x in prod_admins):
            raise ValueError("prod_admins must be a set/frozenset/list/tuple of str ids")
        self._prod_admins = frozenset(i for i in (clean_identity(x) for x in prod_admins) if i)
        registry: dict[tuple[str, str], frozenset[str]] = {}
        for scope, ids in (owners or {}).items():
            # a str/bytes value would be iterated per character: reject it (and any non-collection)
            if type(ids) not in (set, frozenset, list, tuple) or any(type(x) is not str for x in ids):
                raise ValueError("owners values must be a set/frozenset/list/tuple of str ids")
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
        # ADMIT entries (attacker-floodable with unknown ids) live in their own bounded log so they can
        # never evict the security-relevant PROD_FLAG / ISSUE / REVOKE entries. (seq, entry) pairs.
        self._audit: deque[tuple[int, AuditEntry]] = deque(maxlen=max_audit)
        self._audit_admit: deque[tuple[int, AuditEntry]] = deque(maxlen=max_audit)
        self._audit_seq = 0
        self._dropped_admits = 0

    def _now(self) -> datetime | None:
        try:
            return _aware(self._clock())
        except Exception:  # noqa: BLE001 - a broken clock must fail closed, never leak text
            return None

    def _append_locked(self, kind: str, actor: str, subject: str, value: str,
                       at: datetime | None) -> None:
        """Caller holds ``self._lock``."""
        self._audit_seq += 1
        log = self._audit_admit if kind == "ADMIT" else self._audit
        if log is self._audit_admit and len(log) == log.maxlen:
            self._dropped_admits += 1
        log.append((self._audit_seq, AuditEntry(kind, actor, subject, value, at)))

    def _record(self, kind: str, actor: str, subject: str, value: str) -> None:
        """Audit a stateless outcome; the clock is read inside the lock."""
        with self._lock:
            self._append_locked(kind, actor, subject, value, self._now())

    def audit(self) -> tuple[AuditEntry, ...]:
        """Both logs merged in decision order (at most ``2 * max_audit`` entries)."""
        with self._lock:
            return tuple(e for _, e in sorted((*self._audit, *self._audit_admit),
                                              key=lambda pair: pair[0]))

    def dropped_admits(self) -> int:
        """Number of ADMIT audit entries evicted from the bounded admit log."""
        with self._lock:
            return self._dropped_admits

    def set_prod_enabled(self, enabled: bool, by: Issuer | None = None) -> bool:
        """Policy toggle. Only a HUMAN ``Issuer`` that is a ``prod_admins`` member or a registered owner
        of at least one scope may change the flag; anyone else gets False, the flag is unchanged and the
        attempt is audited (``PROD_FLAG_DENIED``). A non-bool value returns False and is not audited."""
        if type(enabled) is not bool:
            return False
        who = _ident(by.issuer_id) if type(by) is Issuer else ""
        with self._lock:
            allowed = (type(by) is Issuer and by.kind is IssuerKind.HUMAN and bool(who) and (
                clean_identity(by.issuer_id) in self._prod_admins
                or any(clean_identity(by.issuer_id) in ids for ids in self._owners.values())))
            if not allowed:
                self._append_locked("PROD_FLAG", who, "", "PROD_FLAG_DENIED", self._now())
                return False
            self._prod_enabled = enabled
            self._append_locked("PROD_FLAG", who, "", str(enabled), self._now())
        return True

    def count(self) -> int:
        """Number of issued permits (a method, so an empty store is not falsy)."""
        with self._lock:
            return len(self._permits)

    def issue(self, idempotency_key: str, request: PermitRequest, issuer: Issuer) -> IssueResult:
        actor = _ident(issuer.issuer_id) if type(issuer) is Issuer else ""
        result, recorded = self._issue(idempotency_key, request, issuer, actor)
        if not recorded:  # stateless refusal: order against other decisions is irrelevant
            self._record("ISSUE", actor, "", result.code)
        return result

    def _issue(self, idempotency_key: str, request: PermitRequest, issuer: Issuer,
               actor: str) -> tuple[IssueResult, bool]:
        """Returns (result, audited). Stateful outcomes are audited under the decision's own lock."""
        early = self._validate(idempotency_key, request, issuer)
        if early is not None:
            return early, False
        key = exact_text(idempotency_key)
        issuer_id = clean_identity(issuer.issuer_id)
        tenant = clean_identity(request.tenant_id)
        source = clean_identity(request.source_id)
        requester = clean_identity(request.requester)
        max_uses = request.max_uses
        not_before = _aware(request.not_before)
        not_after = _aware(request.not_after)
        if not_before is None or not_after is None:  # unreachable after _validate; fail closed anyway
            return _refused("WINDOW_INVALID"), False

        fingerprint = stable_key(
            tenant, source, request.mode.value, request.environment.value,
            not_before.isoformat(), not_after.isoformat(), request.params_digest,
            requester, issuer_id, str(max_uses),
        )
        idem_scope = stable_key(tenant, key)

        def fin(result: IssueResult) -> tuple[IssueResult, bool]:  # caller holds the lock
            subject = result.permit.permit_id if result.permit is not None else ""
            self._append_locked("ISSUE", actor, subject, result.code, self._now())
            return result, True

        # id_source runs OUTSIDE the lock (it may call count()/audit()); the idempotency decision and
        # the collision check are re-made under the lock on every pass.
        candidate = ""
        for _ in range(_ID_ATTEMPTS + 1):
            with self._lock:
                known = self._by_key.get(idem_scope)
                if known is not None:
                    if known[0] == fingerprint:
                        if known[1].permit_id in self._revoked:
                            return fin(_refused("PERMIT_REVOKED"))
                        if known[1].environment is Environment.PROD and not self._prod_enabled:
                            return fin(_refused("PROD_DISABLED"))
                        return fin(IssueResult(IssueStatus.REPLAYED, known[1], "REPLAYED"))
                    return fin(_refused("IDEMPOTENCY_CONFLICT"))
                if request.environment is Environment.PROD and not self._prod_enabled:
                    return fin(_refused("PROD_DISABLED"))
                if candidate and candidate not in self._permits:
                    permit = CapturePermit(
                        permit_id=candidate,
                        tenant_id=tenant, source_id=source, mode=request.mode,
                        environment=request.environment, not_before=not_before,
                        not_after=not_after, params_digest=request.params_digest,
                        issuer=issuer_id, requester=requester, max_uses=max_uses,
                    )
                    self._permits[candidate] = permit
                    self._by_key[idem_scope] = (fingerprint, permit)
                    return fin(IssueResult(IssueStatus.ISSUED, permit, "ISSUED"))
            try:
                got = self._id_source()
            except Exception:  # noqa: BLE001 - a broken id source fails closed
                break
            candidate = got if type(got) is str and got else ""
        with self._lock:
            return fin(_refused("ID_UNAVAILABLE"))

    def _validate(self, idempotency_key: str, request: PermitRequest, issuer: Issuer) -> IssueResult | None:
        """Stateless refusals (None = valid)."""
        if not exact_text(idempotency_key):
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
        # type and magnitude are checked before any str()/formatting of the value (huge ints are costly)
        if max_uses is not None and (type(max_uses) is not int or not 0 < max_uses <= _MAX_USES_CAP):
            return _refused("MAX_USES_INVALID")
        if issuer_id == requester:
            return _refused("ISSUER_IS_REQUESTER")
        if not_after <= not_before or not_after - not_before > self._max_window:
            return _refused("WINDOW_INVALID")
        if issuer_id not in self._owners.get((tenant, source), frozenset()):
            return _refused("ISSUER_NOT_OWNER")
        return None

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
        actor = _ident(requester)
        with self._lock:  # clock read, decision and audit entry share one critical section
            now = self._now()
            result, subject = self._admit(permit_id, tenant_id, source_id, mode, params_digest,
                                          requester, now)
            self._append_locked("ADMIT", actor, subject, result.code, now)
        return result

    def _admit(
        self, permit_id: str, tenant_id: str, source_id: str, mode: CaptureMode,
        params_digest: str, requester: str, now: datetime | None,
    ) -> tuple[AdmitResult, str]:
        """Caller holds ``self._lock``."""
        not_admittable = AdmitResult(False, "PERMIT_NOT_ADMITTABLE")
        tenant = clean_identity(tenant_id)
        source = clean_identity(source_id)
        if True:
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
        actor = _ident(by.issuer_id) if type(by) is Issuer else ""
        with self._lock:
            result, subject = self._revoke(permit_id, tenant_id, by)
            self._append_locked("REVOKE", actor, subject, result.code, self._now())
        return result

    def _revoke(self, permit_id: str, tenant_id: str, by: Issuer) -> tuple[RevokeResult, str]:
        """Caller holds ``self._lock``."""
        denied = (RevokeResult(False, "REVOKE_DENIED"), "")
        if type(permit_id) is not str or type(by) is not Issuer or by.kind is not IssuerKind.HUMAN:
            return denied
        who = clean_identity(by.issuer_id)
        tenant = clean_identity(tenant_id)
        if True:
            permit = self._permits.get(permit_id)
            if (permit is None or not who or who != permit.issuer
                    or not tenant or tenant != permit.tenant_id
                    or who not in self._owners.get((permit.tenant_id, permit.source_id), frozenset())):
                return denied
            self._revoked.add(permit_id)
            return RevokeResult(True, "REVOKED"), permit_id
