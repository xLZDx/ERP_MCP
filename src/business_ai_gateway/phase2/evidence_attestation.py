"""Phase 2 independent-accountant evidence attestation (R2-US-028, REQ16/21). Unwired from Release 1.

Pure in-memory logic: no I/O, no wall clock of its own (an injected ``clock`` returns an aware
datetime), no caller input echoed in results (only fixed machine-readable codes).

Rules:
* An attestation binds ONE exact revision digest (64 lowercase hex) AND the exact policy version
  (visible text) plus policy digest (64 lowercase hex) it was judged under, inside one tenant.
* Signer authority: only a HUMAN ``Signer`` that is registered as an accountant of that tenant
  (``accountants`` registry; the default is empty, so nobody can sign: fail closed) may sign. The signer
  must be independent: ``_identity.same_person`` against the proposer AND the requester (strict
  identity cleaning, so ``al\\u200bice`` or a Cyrillic lookalike does not pass as someone else).
* Only ``AttestationDecision.PASS`` (the real enum member) is signable. A string, a look-alike object, a
  FAIL decision or a non-request object is denied and NOTHING is recorded (no attestation, no id).
* ``check_current`` is the only gating entry: it takes NO caller time and uses the injected clock only.
  ``check_as_of`` is a point-in-time historical query (audits, replay): its success code is
  ``VALID_HISTORICAL``, never ``VALID``, so a gate that tests for ``VALID`` cannot be satisfied by a
  caller-chosen time. Tenant scope is checked FIRST and unknown id / wrong tenant both
  return ``ATTESTATION_NOT_VALID`` so existence does not leak. Then revision digest -> policy version ->
  policy digest -> time. A signature over a different revision or policy is not evidence.
* ``revoke`` ends CURRENT validity at the revocation instant: valid while ``signed_at <= at <
  revoked_at``, invalid at and after ``revoked_at``. ``revoked_at`` is clamped to ``>= signed_at`` so
  a backwards clock cannot create a revocation that predates the signature. History is never deleted: ``history`` lists every
  attestation (revoked ones with ``historical=True`` and their ``revoked_at``). Only the original
  signer may revoke; any other case returns the single code ``REVOKE_DENIED``.
* Audit: append-only in-store log (fixed codes and normalised ids truncated to 128 chars), bounded to
  ``max_audit`` entries; ``audit()`` returns a tuple copy taken under the lock.

KNOWN GAPS: an attestation is not bound to an evaluation ``result_digest`` (evaluation_runner output);
that binding is a wiring item. The ``params_digest`` of an evaluation is caller-asserted and not part
of this module. Signer kind and ids are asserted by the caller (no authenticated principal binding);
the store is process-local and not persisted; digests are not verified against real revision or policy
bytes; the audit is in memory only and bounded (not tamper-proof); a revocation uses the injected clock
value and does not enforce clock monotonicity.
"""
from __future__ import annotations

import secrets
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from ._identity import clean_identity, exact_text, same_person

__all__ = [
    "Attestation", "AttestationDecision", "AttestationRequest", "AttestationStore", "AuditEntry",
    "CheckResult", "RevokeResult", "SignResult", "Signer", "SignerKind",
]

_HEX = frozenset("0123456789abcdef")
_MAX_ID_LEN = 128
_ID_ATTEMPTS = 8


class SignerKind(StrEnum):
    HUMAN = "HUMAN"
    LLM = "LLM"
    AUTOMATION = "AUTOMATION"


class AttestationDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class Signer:
    kind: SignerKind
    signer_id: str


@dataclass(frozen=True, slots=True)
class AttestationRequest:
    tenant_id: str
    revision_digest: str
    policy_version: str
    policy_digest: str
    proposer: str
    requester: str
    decision: AttestationDecision


@dataclass(frozen=True, slots=True)
class Attestation:
    attestation_id: str
    tenant_id: str  # normalised
    revision_digest: str
    policy_version: str
    policy_digest: str
    signer: str  # normalised
    proposer: str  # normalised
    requester: str  # normalised
    signed_at: datetime  # UTC
    revoked_at: datetime | None = None  # UTC

    @property
    def historical(self) -> bool:
        """True once revoked: still readable, no longer current evidence."""
        return self.revoked_at is not None


@dataclass(frozen=True, slots=True)
class SignResult:
    signed: bool
    attestation: Attestation | None
    code: str


@dataclass(frozen=True, slots=True)
class CheckResult:
    valid: bool
    code: str


@dataclass(frozen=True, slots=True)
class RevokeResult:
    revoked: bool
    code: str


@dataclass(frozen=True, slots=True)
class AuditEntry:
    kind: str  # SIGN | CHECK | CHECK_AS_OF | REVOKE
    actor: str  # normalised actor id ('' when unusable)
    subject: str  # attestation id of a known attestation, else ''
    value: str  # fixed result code
    at: datetime | None  # UTC time from the injected clock, None if the clock was unusable


def _denied(code: str) -> SignResult:
    return SignResult(False, None, code)


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


class AttestationStore:
    def __init__(
        self,
        clock: Callable[[], datetime],
        *,
        accountants: Mapping[str, frozenset[str] | set[str] | list[str] | tuple[str, ...]] | None = None,
        id_source: Callable[[], str] | None = None,
        max_audit: int = 1000,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if id_source is not None and not callable(id_source):
            raise TypeError("id_source must be callable")
        if type(max_audit) is not int or max_audit <= 0:
            raise ValueError("max_audit must be a positive int")
        registry: dict[str, frozenset[str]] = {}
        for tenant_raw, ids in (accountants or {}).items():
            if type(ids) not in (set, frozenset, list, tuple) or any(type(x) is not str for x in ids):
                raise ValueError("accountants values must be a set/frozenset/list/tuple of str ids")
            tenant = clean_identity(tenant_raw)
            if not tenant:
                raise ValueError("accountants keys must be valid tenant ids")
            clean = frozenset(i for i in (clean_identity(x) for x in ids) if i)
            registry[tenant] = registry.get(tenant, frozenset()) | clean
        self._accountants = registry
        self._clock = clock
        self._id_source = id_source or _default_ids
        self._lock = threading.Lock()
        self._items: dict[str, Attestation] = {}
        self._order: list[str] = []
        self._audit: deque[AuditEntry] = deque(maxlen=max_audit)

    def _now(self) -> datetime | None:
        try:
            return _aware(self._clock())
        except Exception:  # noqa: BLE001 - a broken clock must fail closed, never leak text
            return None

    def _append_locked(self, kind: str, actor: str, subject: str, value: str,
                       at: datetime | None) -> None:
        self._audit.append(AuditEntry(kind, actor, subject, value, at))

    def audit(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._audit)

    def count(self) -> int:
        """Number of recorded attestations including revoked ones (a method: empty is not falsy)."""
        with self._lock:
            return len(self._items)

    # ------------------------------------------------------------------ sign
    def sign(self, request: AttestationRequest, signer: Signer) -> SignResult:
        actor = _ident(signer.signer_id) if type(signer) is Signer else ""
        result = self._sign(request, signer, actor)
        if result.attestation is None:  # stateless refusal; successful signs are audited in-lock
            with self._lock:
                self._append_locked("SIGN", actor, "", result.code, self._now())
        return result

    def _validate(self, request: AttestationRequest, signer: Signer) -> SignResult | None:
        if type(request) is not AttestationRequest:
            return _denied("REQUEST_INVALID")
        if type(request.decision) is not AttestationDecision:
            return _denied("DECISION_INVALID")
        if request.decision is not AttestationDecision.PASS:
            return _denied("DECISION_NOT_PASS")
        if type(signer) is not Signer or type(signer.kind) is not SignerKind:
            return _denied("SIGNER_INVALID")
        if signer.kind is not SignerKind.HUMAN:
            return _denied("SIGNER_NOT_HUMAN")
        signer_id = clean_identity(signer.signer_id)
        tenant = clean_identity(request.tenant_id)
        proposer = clean_identity(request.proposer)
        requester = clean_identity(request.requester)
        if not signer_id:
            return _denied("SIGNER_INVALID")
        if not tenant:
            return _denied("SCOPE_INVALID")
        if not proposer or not requester:
            return _denied("PARTY_INVALID")
        if not _digest_ok(request.revision_digest):
            return _denied("REVISION_DIGEST_INVALID")
        if not exact_text(request.policy_version):
            return _denied("POLICY_VERSION_INVALID")
        if not _digest_ok(request.policy_digest):
            return _denied("POLICY_DIGEST_INVALID")
        if same_person(signer.signer_id, request.proposer):
            return _denied("SIGNER_IS_PROPOSER")
        if same_person(signer.signer_id, request.requester):
            return _denied("SIGNER_IS_REQUESTER")
        if signer_id not in self._accountants.get(tenant, frozenset()):
            return _denied("SIGNER_NOT_ACCOUNTANT")
        return None

    def _sign(self, request: AttestationRequest, signer: Signer, actor: str) -> SignResult:
        early = self._validate(request, signer)
        if early is not None:
            return early
        tenant = clean_identity(request.tenant_id)
        policy_version = exact_text(request.policy_version)
        candidate = ""
        for _ in range(_ID_ATTEMPTS + 1):
            with self._lock:
                now = self._now()
                if now is None:
                    self._append_locked("SIGN", actor, "", "TIME_INVALID", None)
                    return _denied("TIME_INVALID")
                if candidate and candidate not in self._items:
                    att = Attestation(
                        attestation_id=candidate, tenant_id=tenant,
                        revision_digest=request.revision_digest, policy_version=policy_version,
                        policy_digest=request.policy_digest, signer=clean_identity(signer.signer_id),
                        proposer=clean_identity(request.proposer),
                        requester=clean_identity(request.requester), signed_at=now,
                    )
                    self._items[candidate] = att
                    self._order.append(candidate)
                    self._append_locked("SIGN", actor, candidate, "SIGNED", now)
                    return SignResult(True, att, "SIGNED")
            try:
                got = self._id_source()
            except Exception:  # noqa: BLE001 - a broken id source fails closed
                break
            candidate = got if type(got) is str and got else ""
        with self._lock:
            self._append_locked("SIGN", actor, "", "ID_UNAVAILABLE", self._now())
        return _denied("ID_UNAVAILABLE")

    # ----------------------------------------------------------------- check
    def check_current(
        self,
        attestation_id: str,
        tenant_id: str,
        revision_digest: str,
        policy_version: str,
        policy_digest: str,
    ) -> CheckResult:
        """Is the attestation CURRENT evidence for exactly this revision and policy NOW (injected clock)?

        The only gating entry; success code ``VALID``. Accepts no caller-supplied time.
        """
        with self._lock:
            now = self._now()
            result, subject = self._check(attestation_id, tenant_id, revision_digest,
                                          policy_version, policy_digest, now, "VALID")
            self._append_locked("CHECK", "", subject, result.code, now)
        return result

    def check_as_of(
        self,
        attestation_id: str,
        tenant_id: str,
        revision_digest: str,
        policy_version: str,
        policy_digest: str,
        at: datetime,
    ) -> CheckResult:
        """Point-in-time historical query at an aware ``at`` (else ``TIME_INVALID``).

        NOT a gate: success is ``VALID_HISTORICAL`` (valid=True at that instant only), never ``VALID``.
        """
        with self._lock:
            now = self._now()
            result, subject = self._check(attestation_id, tenant_id, revision_digest,
                                          policy_version, policy_digest, _aware(at), "VALID_HISTORICAL")
            self._append_locked("CHECK_AS_OF", "", subject, result.code, now)
        return result

    def _check(self, attestation_id: str, tenant_id: str, revision_digest: str, policy_version: str,
               policy_digest: str, when: datetime | None, ok_code: str) -> tuple[CheckResult, str]:
        """Caller holds ``self._lock``."""
        att = self._items.get(attestation_id) if type(attestation_id) is str else None
        tenant = clean_identity(tenant_id)
        if att is None or not tenant or tenant != att.tenant_id:
            return CheckResult(False, "ATTESTATION_NOT_VALID"), ""
        sid = att.attestation_id
        if type(revision_digest) is not str or revision_digest != att.revision_digest:
            return CheckResult(False, "REVISION_MISMATCH"), sid
        if type(policy_version) is not str or exact_text(policy_version) != att.policy_version:
            return CheckResult(False, "POLICY_VERSION_MISMATCH"), sid
        if type(policy_digest) is not str or policy_digest != att.policy_digest:
            return CheckResult(False, "POLICY_DIGEST_MISMATCH"), sid
        if when is None:
            return CheckResult(False, "TIME_INVALID"), sid
        if when < att.signed_at:
            return CheckResult(False, "NOT_YET_VALID"), sid
        if att.revoked_at is not None and when >= att.revoked_at:
            return CheckResult(False, "REVOKED"), sid
        return CheckResult(True, ok_code), sid

    # ---------------------------------------------------------------- revoke
    def revoke(self, attestation_id: str, tenant_id: str, by: Signer) -> RevokeResult:
        actor = _ident(by.signer_id) if type(by) is Signer else ""
        with self._lock:
            now = self._now()
            result, subject = self._revoke(attestation_id, tenant_id, by, now)
            self._append_locked("REVOKE", actor, subject, result.code, now)
        return result

    def _revoke(self, attestation_id: str, tenant_id: str, by: Signer,
                now: datetime | None) -> tuple[RevokeResult, str]:
        """Caller holds ``self._lock``."""
        denied = (RevokeResult(False, "REVOKE_DENIED"), "")
        if type(attestation_id) is not str or type(by) is not Signer or by.kind is not SignerKind.HUMAN:
            return denied
        who = clean_identity(by.signer_id)
        tenant = clean_identity(tenant_id)
        att = self._items.get(attestation_id)
        if (att is None or not who or who != att.signer or not tenant or tenant != att.tenant_id
                or att.revoked_at is not None or now is None):
            return denied
        self._items[attestation_id] = replace(att, revoked_at=max(now, att.signed_at))
        return RevokeResult(True, "REVOKED"), attestation_id

    # --------------------------------------------------------------- history
    def history(self, tenant_id: str, revision_digest: str | None = None) -> tuple[Attestation, ...]:
        """Every attestation of the tenant in signing order, revoked ones included (``historical``).

        An unknown or invalid tenant yields an empty tuple, never another tenant's records.
        """
        tenant = clean_identity(tenant_id)
        if not tenant:
            return ()
        with self._lock:
            return tuple(
                self._items[i] for i in self._order
                if self._items[i].tenant_id == tenant
                and (revision_digest is None or self._items[i].revision_digest == revision_digest)
            )
