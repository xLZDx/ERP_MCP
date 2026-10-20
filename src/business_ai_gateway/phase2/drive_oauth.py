"""Phase 2 (S7/E1) ERP_MCP-owned Drive OAuth/consent state machine over an in-memory FAKE token store.

Offline reference logic only: no network, no Google call, no real client or token. Nothing here reads,
copies, refreshes or compares a PDCC / Release 1 token or right; the only token store is the
``FakeTokenStore`` defined here, keyed by the ERP_MCP identity.

Per (namespace, tenant, connection) the consent state is ``NEW`` -> ``CONSENT_PENDING`` -> ``GRANTED``,
and ``GRANTED`` -> ``REVOKED`` or ``AUTH_REQUIRED`` (``invalid_grant`` observed); a revoked or
auth-required connection re-consents through ``begin_consent`` under a NEW scope epoch.

Consent ``state`` values
- come from an injected generator (default ``secrets.token_urlsafe``), are validated, never reused: the
  digest of every issued value is kept in a never-evicted bounded set (``max_issued_states``; CAPACITY when
  full), so a value that repeats after its record was evicted is skipped (``STATE_SOURCE_INVALID`` if the
  generator keeps repeating) and an old callback can never authorize a re-issued state;
- are single use: any completion attempt that reaches the verifier check burns the state; a second
  use is ``STATE_REPLAYED``; past ``pending_ttl`` on the injected clock it is ``STATE_EXPIRED``;
- a callback from another (tenant, connection) is ``STATE_UNKNOWN`` (same code as a never-issued
  value so nothing leaks) and does NOT burn the state;
- are bound to a PKCE-style verifier: only the SHA-256 challenge is stored, the verifier is compared
  in constant time.

Tokens (``FAKE-`` prefix mandatory) are minted by the store itself from an injected source and are
refused otherwise; they cannot be injected from outside (no public method accepts a token), are never
part of ``repr``/``str``/results/errors/digests, and are deleted on revoke / auth failure, which also
bumps the scope epoch so cursors/ports bound to the old epoch fail closed.

Identities are reconstructed as plain validated ``str`` tuples (``_key``) before any lookup; a forged
identity is ``IDENTITY_INVALID``.

Every public method returns a ``ConsentResult`` with a fixed ``ConsentCode`` and never raises on bad
input (wrong type, subclass, NUL, huge, None, recursive). Configuration errors in constructors raise.

KNOWN GAPS: process-local, not persisted; used/expired states are retained for replay detection only
until a capacity bound is reached (``max_states`` overall, ``max_states_per_identity`` per connection):
then they are evicted (a late replay of an evicted state is ``STATE_UNKNOWN``, still refused) and only
live pending states can cause ``CAPACITY``, so one tenant cannot exhaust the table for another; no authenticated principal binding of the caller; no real
refresh/expiry of access tokens (E4 owns auth-health); the scope allow-list lives in ``drive_scope``.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ._identity import canonical_guid, stable_key
from .drive_port import DrivePortIdentity, is_valid_opaque_id, is_valid_scope_epoch
from .drive_scope import Isolation, ScopeClaim, evaluate_scopes

__all__ = [
    "FAKE_CODE_PREFIX",
    "FAKE_TOKEN_PREFIX",
    "ConsentCode",
    "ConsentManager",
    "ConsentResult",
    "ConsentSnapshot",
    "ConsentState",
    "FakeTokenStore",
]

FAKE_TOKEN_PREFIX = "FAKE-"
FAKE_CODE_PREFIX = "FAKE-CODE-"
_MAX_EPOCH = 2**63 - 1
_VERIFIER_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_STATE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
_MAX_TOKEN_CHARS = 512
_STATE_ATTEMPTS = 4


class ConsentState(StrEnum):
    NEW = "NEW"
    CONSENT_PENDING = "CONSENT_PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    AUTH_REQUIRED = "AUTH_REQUIRED"


class ConsentCode(StrEnum):
    OK = "OK"
    INPUT_INVALID = "INPUT_INVALID"
    IDENTITY_INVALID = "IDENTITY_INVALID"
    SCOPE_REFUSED = "SCOPE_REFUSED"
    GRANT_NOT_SUBSET = "GRANT_NOT_SUBSET"
    VERIFIER_INVALID = "VERIFIER_INVALID"
    VERIFIER_MISMATCH = "VERIFIER_MISMATCH"
    CODE_INVALID = "CODE_INVALID"
    STATE_INVALID = "STATE_INVALID"
    STATE_UNKNOWN = "STATE_UNKNOWN"
    STATE_REPLAYED = "STATE_REPLAYED"
    STATE_EXPIRED = "STATE_EXPIRED"
    STATE_SOURCE_INVALID = "STATE_SOURCE_INVALID"
    TOKEN_INVALID = "TOKEN_INVALID"
    ALREADY_GRANTED = "ALREADY_GRANTED"
    NOT_GRANTED = "NOT_GRANTED"
    CLOCK_INVALID = "CLOCK_INVALID"
    EPOCH_EXHAUSTED = "EPOCH_EXHAUSTED"
    CAPACITY = "CAPACITY"


@dataclass(frozen=True, slots=True)
class ConsentResult:
    ok: bool
    code: ConsentCode
    state: ConsentState | None = None
    scope_epoch: int | None = None
    # opaque single-use redirect handle: returned by begin_consent only, hidden from repr
    state_value: str | None = None
    claim: ScopeClaim | None = None
    isolation: Isolation | None = None

    def __repr__(self) -> str:
        return (
            f"ConsentResult(ok={self.ok!r}, code={self.code.value}, "
            f"state={self.state.value if self.state else None})"
        )


@dataclass(frozen=True, slots=True)
class ConsentSnapshot:
    state: ConsentState
    scope_epoch: int
    scopes: tuple[str, ...]
    claim: ScopeClaim | None
    isolation: Isolation | None
    broad_accepted: bool


def _refuse(code: ConsentCode, state: ConsentState | None = None, epoch: int | None = None):
    return ConsentResult(False, code, state, epoch)


def _default_state() -> str:
    return secrets.token_urlsafe(32)


def _default_token() -> str:
    return FAKE_TOKEN_PREFIX + secrets.token_hex(16)


def _redacted_reduce(self: object):
    raise TypeError("NOT_PICKLABLE")


class FakeTokenStore:
    """In-memory store of FAKE tokens keyed by ERP_MCP identity. No public method accepts or returns a
    token: minting is internal to this module (``ConsentManager``), so a token held by another system
    is unreachable by construction."""

    __slots__ = ("_lock", "_source", "_tokens")

    def __init__(self, token_source: Callable[[], str] | None = None) -> None:
        if token_source is not None and not callable(token_source):
            raise TypeError("token_source must be callable")
        self._source = token_source or _default_token
        self._tokens: dict[tuple[str, str, str], tuple[str, str]] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "FakeTokenStore(<redacted>)"

    __str__ = __repr__
    __reduce__ = _redacted_reduce

    def has_tokens(self, identity: object) -> bool:
        key = _key(identity)
        if key is None:
            return False
        with self._lock:
            return key in self._tokens

    def count(self) -> int:
        with self._lock:
            return len(self._tokens)

    def _pull(self) -> str | None:
        try:
            value = self._source()
        except Exception:  # noqa: BLE001 - a broken source fails closed, text dropped
            return None
        if (
            type(value) is not str
            or not value.startswith(FAKE_TOKEN_PREFIX)
            or not len(FAKE_TOKEN_PREFIX) < len(value) <= _MAX_TOKEN_CHARS
            or not is_valid_opaque_id(value)
        ):
            return None
        return value

    def _pull_pair(self) -> tuple[str, str] | None:
        """Pull an access/refresh pair from the source. Takes NO lock of the consent manager."""
        access = self._pull()
        refresh = self._pull()
        if access is None or refresh is None or access == refresh:
            return None
        return (access, refresh)

    def _put(self, key: tuple[str, str, str], pair: tuple[str, str]) -> None:
        with self._lock:
            self._tokens[key] = pair

    def _mint(self, key: tuple[str, str, str]) -> bool:
        pair = self._pull_pair()
        if pair is None:
            return False
        self._put(key, pair)
        return True

    def _delete(self, key: tuple[str, str, str]) -> None:
        with self._lock:
            self._tokens.pop(key, None)


def _key(identity: object) -> tuple[str, str, str] | None:
    """Plain, validated ``(namespace, tenant, connection_id)`` copy of an identity, or ``None``.

    Every field is read ONCE and must be an exact ``str`` that is a valid opaque id (``namespace`` with an
    ``account:``/``drive:`` prefix, a GUID-shaped tenant/connection already canonical) BEFORE it is used as a
    dict key, a lookup or a comparison. A forged identity (``object.__new__`` shell, ``str`` subclass with a
    lying ``__eq__``/``__hash__``, unset slot) therefore yields ``None`` and never reaches an authorization
    decision; the returned tuple holds only exact ``str`` objects, so comparing/hashing it cannot be hijacked.
    """
    try:
        if type(identity) is not DrivePortIdentity:
            return None
        ns = identity.namespace
        tenant = identity.tenant
        conn = identity.connection_id
        if not (is_valid_opaque_id(ns) and is_valid_opaque_id(tenant) and is_valid_opaque_id(conn)):
            return None
        if not (ns.startswith("account:") and len(ns) > 8 or ns.startswith("drive:") and len(ns) > 6):
            return None
        for part in (tenant, conn):
            guid = canonical_guid(part)
            if guid is not None and guid != part:
                return None
        return (ns, tenant, conn)
    except Exception:  # noqa: BLE001 - an unset slot / hostile attribute is a refusal
        return None


@dataclass(slots=True)
class _Record:
    state: ConsentState = ConsentState.NEW
    epoch: int = 0
    scopes: tuple[str, ...] = ()
    claim: ScopeClaim | None = None
    isolation: Isolation | None = None
    broad_accepted: bool = False
    pending: str | None = None
    # requested scope names/labels kept while CONSENT_PENDING
    requested: tuple[str, ...] = ()
    # every state value issued for this connection that is still retained (live or used/expired)
    states: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Pending:
    key: tuple[str, str, str]
    challenge: str
    requested: tuple[str, ...]
    broad_accepted: bool
    expires: datetime
    used: bool = False
    # True while a completion is minting tokens outside the manager lock (never evicted/reset then)
    completing: bool = False


def _digest(state: str) -> bytes:
    return hashlib.sha256(state.encode("ascii")).digest()


def _challenge(verifier: str) -> str:
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


def _verifier_ok(value: object) -> bool:
    return (
        type(value) is str
        and 16 <= len(value) <= 128
        and all(ch in _VERIFIER_CHARS for ch in value)
    )


def _state_ok(value: object) -> bool:
    return (
        type(value) is str
        and 16 <= len(value) <= 256
        and all(ch in _STATE_CHARS for ch in value)
    )


class ConsentManager:
    def __init__(
        self,
        clock: Callable[[], datetime],
        *,
        store: FakeTokenStore | None = None,
        state_source: Callable[[], str] | None = None,
        pending_ttl: timedelta = timedelta(minutes=10),
        max_states: int = 10_000,
        max_records: int = 10_000,
        max_states_per_identity: int = 16,
        max_issued_states: int = 100_000,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if store is not None and type(store) is not FakeTokenStore:
            raise TypeError("store must be a FakeTokenStore")
        if state_source is not None and not callable(state_source):
            raise TypeError("state_source must be callable")
        if type(pending_ttl) is not timedelta or not timedelta(0) < pending_ttl <= timedelta(hours=1):
            raise ValueError("pending_ttl must be a timedelta in (0, 1h]")
        if type(max_states) is not int or max_states <= 0 or type(max_records) is not int or max_records <= 0:
            raise ValueError("max_states and max_records must be positive ints")
        if type(max_states_per_identity) is not int or max_states_per_identity <= 0:
            raise ValueError("max_states_per_identity must be a positive int")
        if type(max_issued_states) is not int or max_issued_states <= 0:
            raise ValueError("max_issued_states must be a positive int")
        self._clock = clock
        self._store = store if store is not None else FakeTokenStore()
        self._state_source = state_source or _default_state
        self._ttl = pending_ttl
        self._max_states = max_states
        self._max_records = max_records
        self._max_per_identity = max_states_per_identity
        # SHA-256 digest of EVERY state value ever issued: never evicted (bounded by ``max_issued_states``,
        # fail-closed CAPACITY when full), so non-reuse does not depend on bounded record retention
        self._max_issued = max_issued_states
        self._issued: set[bytes] = set()
        self._lock = threading.Lock()
        self._records: dict[tuple[str, str, str], _Record] = {}
        self._states: dict[str, _Pending] = {}

    def __repr__(self) -> str:
        return "ConsentManager(<redacted>)"

    __str__ = __repr__
    __reduce__ = _redacted_reduce

    @property
    def store(self) -> FakeTokenStore:
        return self._store

    # --- helpers ---------------------------------------------------------------------------------

    def _now(self) -> datetime | None:
        try:
            value = self._clock()
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                return None
            return value.astimezone(UTC)
        except Exception:  # noqa: BLE001 - broken clock fails closed
            return None

    def _expire_locked(self, key: tuple[str, str, str], rec: _Record, now: datetime) -> None:
        if rec.state is ConsentState.CONSENT_PENDING and rec.pending is not None:
            pend = self._states.get(rec.pending)
            if pend is not None and pend.completing:
                return
            if pend is None or pend.used or now >= pend.expires:
                if pend is not None:
                    pend.used = True
                rec.state, rec.pending, rec.requested = ConsentState.NEW, None, ()

    def _bump_locked(self, rec: _Record) -> bool:
        if rec.epoch >= _MAX_EPOCH:
            return False
        rec.epoch += 1
        return True

    def _purge_locked(self, now: datetime, values: list[str] | None = None) -> None:
        """Evict used/expired states (never one that is completing); keep every live pending state."""
        removed: dict[tuple[str, str, str], set[str]] = {}
        for value in tuple(self._states if values is None else values):
            pend = self._states.get(value)
            if pend is None or pend.completing or not (pend.used or now >= pend.expires):
                continue
            del self._states[value]
            removed.setdefault(pend.key, set()).add(value)
        for key, gone in removed.items():
            rec = self._records.get(key)
            if rec is not None:
                rec.states = [v for v in rec.states if v not in gone]

    def _make_room_locked(self, rec: _Record | None, now: datetime) -> bool:
        """Bounded eviction before a new state is issued; False only when live pending states fill it."""
        if rec is not None and len(rec.states) >= self._max_per_identity:
            self._purge_locked(now, rec.states)
            if len(rec.states) >= self._max_per_identity:
                return False
        if len(self._states) >= self._max_states:
            self._purge_locked(now)
            if len(self._states) >= self._max_states:
                return False
        return len(self._issued) < self._max_issued

    def _new_state_locked(self) -> str | None:
        for _ in range(_STATE_ATTEMPTS):
            try:
                value = self._state_source()
            except Exception:  # noqa: BLE001
                return None
            if _state_ok(value) and value not in self._states and _digest(value) not in self._issued:
                return value
        return None

    # --- public ----------------------------------------------------------------------------------

    def begin_consent(
        self,
        identity: object,
        scope_names: object,
        code_verifier: object,
        risk_labels: object = (),
    ) -> ConsentResult:
        """NEW / REVOKED / AUTH_REQUIRED / CONSENT_PENDING -> CONSENT_PENDING; returns the one-time
        ``state_value``. A second begin supersedes (burns) the earlier pending state."""
        try:
            key = _key(identity)
            if key is None:
                return _refuse(ConsentCode.IDENTITY_INVALID)
            if not _verifier_ok(code_verifier):
                return _refuse(ConsentCode.VERIFIER_INVALID)
            evaluation = evaluate_scopes(scope_names, risk_labels)
            if not evaluation.may_proceed or evaluation.claim is None:
                return _refuse(ConsentCode.SCOPE_REFUSED)
            now = self._now()
            if now is None:
                return _refuse(ConsentCode.CLOCK_INVALID)
            try:
                expires = now + self._ttl  # before any mutation: an overflow must not burn a state
            except (OverflowError, ValueError):
                return _refuse(ConsentCode.CLOCK_INVALID)
            broad = evaluation.claim is not ScopeClaim.NARROW_FILE_SCOPE
            with self._lock:
                rec = self._records.get(key)
                if rec is None:
                    if len(self._records) >= self._max_records:
                        return _refuse(ConsentCode.CAPACITY)
                else:
                    self._expire_locked(key, rec, now)
                    if rec.state is ConsentState.GRANTED:
                        return _refuse(ConsentCode.ALREADY_GRANTED, rec.state, rec.epoch)
                known = (rec.state, rec.epoch) if rec is not None else (None, None)
                if not self._make_room_locked(rec, now):
                    return _refuse(ConsentCode.CAPACITY, *known)
                value = self._new_state_locked()
                if value is None:
                    return _refuse(ConsentCode.STATE_SOURCE_INVALID, *known)
                self._issued.add(_digest(value))
                if rec is None:  # allocated only after every early refusal
                    rec = _Record()
                    self._records[key] = rec
                if rec.pending is not None and rec.pending in self._states:
                    self._states[rec.pending].used = True
                self._states[value] = _Pending(
                    key, _challenge(code_verifier), evaluation.scopes, broad, expires  # type: ignore[arg-type]
                )
                rec.states.append(value)
                rec.state, rec.pending, rec.requested = (
                    ConsentState.CONSENT_PENDING, value, evaluation.scopes,
                )
                rec.broad_accepted = broad
                return ConsentResult(
                    True, ConsentCode.OK, rec.state, rec.epoch, value,
                    evaluation.claim, evaluation.isolation,
                )
        except Exception:  # noqa: BLE001 - never raise on hostile input
            return _refuse(ConsentCode.INPUT_INVALID)

    def complete_consent(
        self,
        identity: object,
        state: object,
        code_verifier: object,
        authorization_code: object,
        granted_scopes: object = None,
    ) -> ConsentResult:
        """The fake provider callback. CONSENT_PENDING -> GRANTED, tokens minted into the store."""
        try:
            key = _key(identity)
            if key is None:
                return _refuse(ConsentCode.IDENTITY_INVALID)
            if not _state_ok(state):
                return _refuse(ConsentCode.STATE_INVALID)
            if not _verifier_ok(code_verifier):
                return _refuse(ConsentCode.VERIFIER_INVALID)
            if not (
                type(authorization_code) is str
                and authorization_code.startswith(FAKE_CODE_PREFIX)
                and len(FAKE_CODE_PREFIX) < len(authorization_code) <= _MAX_TOKEN_CHARS
                and is_valid_opaque_id(authorization_code)
            ):
                return _refuse(ConsentCode.CODE_INVALID)
            now = self._now()
            if now is None:
                return _refuse(ConsentCode.CLOCK_INVALID)
            with self._lock:
                pend = self._states.get(state)  # type: ignore[arg-type]
                if pend is None or pend.key != key:
                    return _refuse(ConsentCode.STATE_UNKNOWN)
                rec = self._records.get(key)
                if rec is None:
                    return _refuse(ConsentCode.STATE_UNKNOWN)
                if pend.used:
                    return _refuse(ConsentCode.STATE_REPLAYED, rec.state, rec.epoch)
                # Possession checks (expiry, verifier) come BEFORE any scope evaluation, so a state holder
                # without the verifier learns nothing about the scopes; both burn the state.
                if now >= pend.expires:
                    pend.used = True
                    self._reset_pending_locked(rec, str(state))
                    return _refuse(ConsentCode.STATE_EXPIRED, rec.state, rec.epoch)
                if not hmac.compare_digest(pend.challenge, _challenge(code_verifier)):  # type: ignore[arg-type]
                    pend.used = True
                    self._reset_pending_locked(rec, str(state))
                    return _refuse(ConsentCode.VERIFIER_MISMATCH, rec.state, rec.epoch)
                final = pend.requested
                broad = pend.broad_accepted
                if granted_scopes is not None:
                    labels = (_BROAD_LABEL,) if broad else ()
                    chosen = evaluate_scopes(granted_scopes, labels)
                    if not chosen.may_proceed or chosen.claim is None:
                        return _refuse(ConsentCode.SCOPE_REFUSED, rec.state, rec.epoch)
                    if not set(chosen.scopes) <= set(pend.requested):
                        return _refuse(ConsentCode.GRANT_NOT_SUBSET, rec.state, rec.epoch)
                    final = chosen.scopes
                pend.used = True  # single use from here on, whatever the outcome
                final_eval = evaluate_scopes(final, (_BROAD_LABEL,) if broad else ())
                if rec.pending != state or final_eval.claim is None:
                    self._reset_pending_locked(rec, str(state))
                    return _refuse(ConsentCode.TOKEN_INVALID, rec.state, rec.epoch)
                pend.completing = True
            # the token source is user code: it runs OUTSIDE the manager lock
            try:
                pair = self._store._pull_pair()
            except Exception:  # noqa: BLE001
                pair = None
            with self._lock:
                pend.completing = False
                rec = self._records.get(key)
                if pair is None or rec is None or rec.pending != state:
                    if rec is not None:
                        self._reset_pending_locked(rec, str(state))
                    return _refuse(ConsentCode.TOKEN_INVALID, rec.state if rec else None,
                                   rec.epoch if rec else None)
                self._store._put(key, pair)
                rec.state, rec.pending, rec.requested = ConsentState.GRANTED, None, ()
                rec.scopes = final_eval.scopes
                rec.claim, rec.isolation = final_eval.claim, final_eval.isolation
                rec.broad_accepted = broad
                return ConsentResult(
                    True, ConsentCode.OK, rec.state, rec.epoch, None, rec.claim, rec.isolation
                )
        except Exception:  # noqa: BLE001
            return _refuse(ConsentCode.INPUT_INVALID)

    def _reset_pending_locked(self, rec: _Record, state: str) -> None:
        if rec.pending == state:
            rec.state, rec.pending, rec.requested = ConsentState.NEW, None, ()

    def revoke(self, identity: object) -> ConsentResult:
        """GRANTED / AUTH_REQUIRED -> REVOKED: delete tokens, bump the scope epoch, clear the grant."""
        return self._lose_grant(identity, ConsentState.REVOKED)

    def mark_auth_required(self, identity: object) -> ConsentResult:
        """``invalid_grant`` observed: GRANTED -> AUTH_REQUIRED, tokens deleted, scope epoch bumped."""
        return self._lose_grant(identity, ConsentState.AUTH_REQUIRED)

    def _lose_grant(self, identity: object, target: ConsentState) -> ConsentResult:
        try:
            key = _key(identity)
            if key is None:
                return _refuse(ConsentCode.IDENTITY_INVALID)
            with self._lock:
                rec = self._records.get(key)
                allowed = (ConsentState.GRANTED,) if target is ConsentState.AUTH_REQUIRED else (
                    ConsentState.GRANTED, ConsentState.AUTH_REQUIRED,
                )
                if rec is None or rec.state not in allowed:
                    return _refuse(ConsentCode.NOT_GRANTED, rec.state if rec else None,
                                   rec.epoch if rec else None)
                self._store._delete(key)
                if not self._bump_locked(rec):
                    return _refuse(ConsentCode.EPOCH_EXHAUSTED, rec.state, rec.epoch)
                rec.state = target
                rec.scopes, rec.claim, rec.isolation, rec.broad_accepted = (), None, None, False
                return ConsentResult(True, ConsentCode.OK, rec.state, rec.epoch)
        except Exception:  # noqa: BLE001
            return _refuse(ConsentCode.INPUT_INVALID)

    def snapshot(self, identity: object) -> ConsentSnapshot | None:
        """Never raises: any internal failure reads as "no record" (fail closed)."""
        try:
            key = _key(identity)
            if key is None:
                return None
            now = self._now()
            with self._lock:
                rec = self._records.get(key)
                if rec is None:
                    return None
                if now is not None:
                    self._expire_locked(key, rec, now)
                return ConsentSnapshot(
                    rec.state, rec.epoch, rec.scopes, rec.claim, rec.isolation, rec.broad_accepted
                )
        except Exception:  # noqa: BLE001
            return None

    def state_of(self, identity: object) -> ConsentState:
        snap = self.snapshot(identity)
        return ConsentState.NEW if snap is None else snap.state

    def scope_epoch(self, identity: object) -> int | None:
        snap = self.snapshot(identity)
        return None if snap is None else snap.scope_epoch

    def is_authorized(self, identity: object, scope_epoch: object) -> bool:
        """GRANTED, tokens present and the epoch exactly current. False for anything else."""
        try:
            if not is_valid_scope_epoch(scope_epoch):
                return False
            snap = self.snapshot(identity)
            return (
                snap is not None
                and snap.state is ConsentState.GRANTED
                and snap.scope_epoch == scope_epoch
                and self._store.has_tokens(identity)
            )
        except Exception:  # noqa: BLE001
            return False

    def consent_digest(self, identity: object) -> str | None:
        """Stable digest of the consent record. The preimage never contains a token or a state value."""
        try:
            snap = self.snapshot(identity)
            key = _key(identity)
            if snap is None or key is None:
                return None
            preimage = stable_key(
                "drive-consent-v1", *key, snap.state.value, str(snap.scope_epoch), *snap.scopes
            )
            return hashlib.sha256(preimage.encode("utf-8")).hexdigest()
        except Exception:  # noqa: BLE001
            return None


_BROAD_LABEL = "BROAD_ACCEPTED"
