"""Phase 2 (S7/E4) Drive auth-health state machine, alert record and notification-hint intake.

Pure stdlib, in-memory, no I/O, no Release 1 / httpx / requests / socket import. Reference module over
the read-only ``DrivePort`` (drive_port.py); nothing here is wired into a runtime.

Auth results are three DISTINCT things (``AuthCause`` / refresh path):
- expired-but-refreshable access token: refreshed through the consent seam, the call continues, no
  state change and no alert;
- ``INVALID_GRANT`` (refresh failed or the provider said so): ``AUTH_REQUIRED``;
- revoked consent (or a missing token / moved scope epoch): ``AUTH_REQUIRED``.

``AUTH_REQUIRED`` is fail-closed: the connection is paused through ``SourceStateMachine`` (only if it
was ACTIVE), exactly one deduplicated ``AuthAlert`` per transition goes to the alert sink (fixed
codes and ids only: no token, no provider text), and EVERY guarded port call raises
``DrivePortError(AUTH_REQUIRED)`` before the inner port is touched (zero calls). The cursor is never
read-modified here: this module has no cursor write path at all. Recovery needs ``reconsent(new_epoch)``:
a strictly newer scope epoch, a granted consent, a fresh scope check from the seam; the old epoch, old
grants and old hint channels are never resurrected.

Hints (``HintIntake``): a watch/notification message is accepted only for a registered channel whose
channel id, resource id and token all match (constant-time), and only schedules ONE idempotent poll job.
The message payload is never read, stored or exposed, a hint can neither advance a cursor nor create
evidence, and polling (``run_poll``) is complete with zero hints and with watch unsupported.

Adapters over the real components (the seams above are the only contract this module depends on):
``ConsentManagerSeam`` adapts ``drive_oauth.ConsentManager`` (two different ``ConsentState`` enums, fail
closed on anything unknown) and ``StoreCursorReader`` adapts the async ``DriveCursorStore.load`` to the
read-only cursor view (duck-typed: this module never imports ``drive_cursor``).

Conventions (Release 2): exact types, fixed outward codes, nothing echoed. Constructors validate
configuration and raise ``ValueError`` with a fixed code; runtime entry points never raise on hostile
input (they return a fixed code or raise only ``DrivePortError`` with a fixed code).
"""
from __future__ import annotations

import hmac
import inspect
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Protocol

from .drive_oauth import ConsentManager as _ConsentManager
from .drive_oauth import ConsentState as _OauthConsentState
from .drive_port import (
    ChangesPage,
    DriveErrorCode,
    DrivePort,
    DrivePortError,
    DrivePortIdentity,
    FileMeta,
    RevisionMeta,
    StartToken,
    is_valid_opaque_id,
    is_valid_scope_epoch,
)
from .scheduler import SourceState, SourceStateMachine

__all__ = [
    "AlertSink",
    "AsyncCursorView",
    "AuthAlert",
    "AuthCause",
    "AuthGuardedDrivePort",
    "AuthState",
    "ConsentManagerSeam",
    "ConsentSeam",
    "ConsentState",
    "CursorView",
    "DriveAuthHealth",
    "FakeAlertSink",
    "FakeAuthSeam",
    "FakeCursorView",
    "HintIntake",
    "HintResult",
    "PollJob",
    "PollReason",
    "PollResult",
    "PollStatus",
    "ReconsentResult",
    "StoreCursorReader",
    "TokenStatus",
    "run_poll",
]

_REASON = "DRIVE_AUTH_REQUIRED"
_RESUME_ACTOR = "drive-reconsent"
MAX_HINT_FIELD_CHARS = 512
MAX_CHANNELS = 64


class AuthState(StrEnum):
    HEALTHY = "HEALTHY"
    AUTH_REQUIRED = "AUTH_REQUIRED"


class AuthCause(StrEnum):
    INVALID_GRANT = "INVALID_GRANT"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    ACCESS_REJECTED = "ACCESS_REJECTED"


class ConsentState(StrEnum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    NONE = "NONE"


class TokenStatus(StrEnum):
    VALID = "VALID"
    EXPIRED_REFRESHABLE = "EXPIRED_REFRESHABLE"
    MISSING = "MISSING"


class ReconsentResult(StrEnum):
    RECOVERED = "RECOVERED"
    NOT_REQUIRED = "NOT_REQUIRED"
    EPOCH_NOT_NEW = "EPOCH_NOT_NEW"
    NO_CONSENT = "NO_CONSENT"
    EPOCH_MISMATCH = "EPOCH_MISMATCH"
    SCOPE_CHECK_FAILED = "SCOPE_CHECK_FAILED"
    QUARANTINED = "QUARANTINED"
    SEAM_FAULT = "SEAM_FAULT"


class HintResult(StrEnum):
    ACCEPTED_NEW_JOB = "ACCEPTED_NEW_JOB"
    ACCEPTED_COLLAPSED = "ACCEPTED_COLLAPSED"
    REJECTED_INVALID = "REJECTED_INVALID"
    REJECTED_FOREIGN = "REJECTED_FOREIGN"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_PAUSED = "REJECTED_PAUSED"


class PollStatus(StrEnum):
    COMPLETE = "COMPLETE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    NO_CURSOR = "NO_CURSOR"
    PAGE_LIMIT = "PAGE_LIMIT"
    COMMIT_FAILED = "COMMIT_FAILED"
    PORT_ERROR = "PORT_ERROR"
    PAGE_INVALID = "PAGE_INVALID"


class PollReason(StrEnum):
    """Fixed detail code for a non-complete poll (never provider text)."""

    PAGE_TYPE_INVALID = "PAGE_TYPE_INVALID"
    PAGE_SHAPE_INVALID = "PAGE_SHAPE_INVALID"
    TOKEN_REPEATED = "TOKEN_REPEATED"
    TOKEN_REGRESSED = "TOKEN_REGRESSED"
    START_TOKEN_ORDER = "START_TOKEN_ORDER"
    COMMIT_RAISED = "COMMIT_RAISED"
    COMMIT_REJECTED = "COMMIT_REJECTED"
    CONFIG_INVALID = "CONFIG_INVALID"
    INTERNAL = "INTERNAL"


# --- seams (the oauth/consent and cursor modules are written elsewhere; these are the only contract) ---


class ConsentSeam(Protocol):
    """What the auth-health machine needs from the consent / token store. All synchronous."""

    def consent_state(self, identity: DrivePortIdentity) -> ConsentState: ...

    def token_status(self, identity: DrivePortIdentity) -> TokenStatus: ...

    def refresh_access_token(self, identity: DrivePortIdentity) -> bool:
        """True when a new access token is now stored; False when the grant is dead (invalid_grant)."""
        ...

    def scope_epoch(self, identity: DrivePortIdentity) -> int: ...

    def scope_check_ok(self, identity: DrivePortIdentity, scope_epoch: int) -> bool:
        """A FRESH scope evaluation for that epoch (never a cached pre-revoke result)."""
        ...


class CursorView(Protocol):
    """Read-only view of the committed cursor of one connection. This module never writes a cursor."""

    def committed_token(self, identity: DrivePortIdentity) -> str | None: ...


class AsyncCursorView(Protocol):
    """Async twin of ``CursorView`` (``StoreCursorReader``): ``run_poll`` accepts either."""

    async def committed_token(self, identity: DrivePortIdentity) -> str | None: ...


class AlertSink(Protocol):
    def emit(self, alert: AuthAlert) -> None: ...


@dataclass(frozen=True, slots=True)
class AuthAlert:
    """One alert record per AUTH_REQUIRED transition. Fixed codes and ids only."""

    tenant: str
    connection_id: str
    cause: AuthCause
    scope_epoch: int
    transition_no: int
    # unique per DriveAuthHealth instance (random, not derived from any secret); excluded from equality so
    # the content of an alert still compares by its fixed fields
    incident_id: str = field(default="", compare=False)

    @property
    def dedup_key(self) -> tuple[str, str, int, int, str]:
        """Unique per incident: two health objects of one identity (or two epochs) never collide, while a
        re-delivery of the same alert keeps its key."""
        return (self.tenant, self.connection_id, self.scope_epoch, self.transition_no, self.incident_id)


_SEAM_METHODS = ("consent_state", "token_status", "refresh_access_token", "scope_epoch", "scope_check_ok")


def _has_methods(obj: object, names: tuple[str, ...]) -> bool:
    try:
        return obj is not None and all(callable(getattr(obj, name, None)) for name in names)
    except Exception:  # noqa: BLE001 - a hostile attribute access is a refusal, not a crash
        return False


# --- adapters over the real components ------------------------------------------------------------


class ConsentManagerSeam:
    """``ConsentSeam`` over a real ``drive_oauth.ConsentManager``.

    The manager has its own ``ConsentState`` (NEW / CONSENT_PENDING / GRANTED / REVOKED / AUTH_REQUIRED);
    this module's is GRANTED / REVOKED / NONE. Mapping is fail closed: only GRANTED is GRANTED, a lost
    grant is REVOKED, everything else (not yet consented, pending, unknown value) is NONE. The fake token
    store has no expiry and no refresh path, so a stored token is VALID and ``refresh_access_token`` is
    always False (it is only reached for EXPIRED_REFRESHABLE, which this adapter never reports). An unknown
    connection has no epoch: ``scope_epoch`` raises ``LookupError`` (read as a seam fault -> TRANSIENT).
    """

    _MAP: ClassVar[dict] = {
        _OauthConsentState.GRANTED: ConsentState.GRANTED,
        _OauthConsentState.REVOKED: ConsentState.REVOKED,
        _OauthConsentState.AUTH_REQUIRED: ConsentState.REVOKED,
        _OauthConsentState.NEW: ConsentState.NONE,
        _OauthConsentState.CONSENT_PENDING: ConsentState.NONE,
    }

    def __init__(self, manager: _ConsentManager) -> None:
        if type(manager) is not _ConsentManager:
            raise ValueError("CONSENT_ADAPTER_CONFIG_INVALID")
        self._manager = manager

    def consent_state(self, identity: DrivePortIdentity) -> ConsentState:
        return self._MAP.get(self._manager.state_of(identity), ConsentState.NONE)

    def token_status(self, identity: DrivePortIdentity) -> TokenStatus:
        snap = self._manager.snapshot(identity)
        if snap is not None and snap.state is _OauthConsentState.GRANTED and self._manager.store.has_tokens(
            identity
        ):
            return TokenStatus.VALID
        return TokenStatus.MISSING

    def refresh_access_token(self, identity: DrivePortIdentity) -> bool:
        return False

    def scope_epoch(self, identity: DrivePortIdentity) -> int:
        epoch = self._manager.scope_epoch(identity)
        if epoch is None:
            raise LookupError("CONSENT_UNKNOWN")
        return epoch

    def scope_check_ok(self, identity: DrivePortIdentity, scope_epoch: int) -> bool:
        snap = self._manager.snapshot(identity)
        return (
            snap is not None
            and snap.claim is not None
            and self._manager.is_authorized(identity, scope_epoch)
        )


class StoreCursorReader:
    """``AsyncCursorView`` over a ``DriveCursorStore``-shaped object (``await load(identity, corpus,
    drive_epoch, lease)``). Duck-typed: ``drive_cursor`` is not imported here.

    Only a usable CATCHING_UP / LIVE record yields a token (a BASELINING token is a baseline token, not a
    changes cursor); everything else - missing, corrupt, blocked, wrong epoch, a failing store - is None
    (``run_poll`` then reports NO_CURSOR). ``drive_epoch`` is a callable so a reconsent moves it.
    """

    _POLLABLE: ClassVar[frozenset] = frozenset({"CATCHING_UP", "LIVE"})

    def __init__(self, store: object, corpus: object, lease: object, drive_epoch: Callable[[], int]) -> None:
        if not _has_methods(store, ("load",)) or corpus is None or lease is None or not callable(drive_epoch):
            raise ValueError("CURSOR_READER_CONFIG_INVALID")
        self._store = store
        self._corpus = corpus
        self._lease = lease
        self._epoch = drive_epoch

    async def committed_token(self, identity: DrivePortIdentity) -> str | None:
        try:
            if type(identity) is not DrivePortIdentity:
                return None
            epoch = self._epoch()
            if not is_valid_scope_epoch(epoch):
                return None
            load = await self._store.load(identity, self._corpus, epoch, self._lease)  # type: ignore[attr-defined]
            if getattr(load, "usable", None) is not True:
                return None
            record = getattr(load, "record", None)
            state = getattr(getattr(record, "state", None), "value", None)
            if state not in self._POLLABLE:
                return None
            token = getattr(record, "token", None)
            return token if is_valid_opaque_id(token) else None
        except Exception:  # noqa: BLE001 - a broken store is "no cursor", text dropped
            return None


# --- health machine ------------------------------------------------------------------------------


class DriveAuthHealth:
    """Auth health of ONE connection (identity + scope epoch)."""

    def __init__(
        self,
        identity: DrivePortIdentity,
        scope_epoch: int,
        consent: ConsentSeam,
        machine: SourceStateMachine,
        sink: AlertSink,
    ) -> None:
        if type(identity) is not DrivePortIdentity:
            raise ValueError("AUTH_HEALTH_IDENTITY_INVALID")
        if not is_valid_scope_epoch(scope_epoch):
            raise ValueError("AUTH_HEALTH_EPOCH_INVALID")
        if not isinstance(machine, SourceStateMachine):
            raise ValueError("AUTH_HEALTH_MACHINE_INVALID")  # noqa: TRY004 - fixed-code config error
        if not _has_methods(consent, _SEAM_METHODS) or not _has_methods(sink, ("emit",)):
            raise ValueError("AUTH_HEALTH_SEAM_INVALID")
        self._identity = identity
        self._epoch = scope_epoch
        self._consent = consent
        self._machine = machine
        self._sink = sink
        self._state = AuthState.HEALTHY
        self._cause: AuthCause | None = None
        self._transitions = 0
        self._paused_by_us = False
        self._alerts: list[AuthAlert] = []
        self._unacked: list[AuthAlert] = []
        self._incident = secrets.token_hex(8)
        self._alert_failures = 0
        self._refreshes = 0
        self._rederive()

    def _rederive(self) -> None:
        """A health object built over a seam that is already revoked / moved starts AUTH_REQUIRED (a restart
        during an outage must not forget it). Only definitive seam answers count; a faulty seam stays quiet."""
        consent = self._read(lambda: self._consent.consent_state(self._identity), ConsentState)
        epoch = self._read_epoch()
        if (consent is not None and consent is not ConsentState.GRANTED) or (
            epoch is not None and epoch != self._epoch
        ):
            self.record_failure(AuthCause.CONSENT_REVOKED)

    # --- observation ---
    @property
    def identity(self) -> DrivePortIdentity:
        return self._identity

    @property
    def scope_epoch(self) -> int:
        return self._epoch

    @property
    def state(self) -> AuthState:
        return self._state

    @property
    def cause(self) -> AuthCause | None:
        return self._cause

    @property
    def alerts(self) -> tuple[AuthAlert, ...]:
        return tuple(self._alerts)

    @property
    def alert_failures(self) -> int:
        return self._alert_failures

    @property
    def refresh_count(self) -> int:
        return self._refreshes

    # --- seam reads (a faulty or hostile seam answer is a fail-closed TRANSIENT, never an exception) ---
    def _read(self, fn: Callable[[], object], expected: type) -> object | None:
        try:
            value = fn()
        except Exception:  # noqa: BLE001 - seam faults are data; text is never kept
            return None
        return value if type(value) is expected else None

    def _read_epoch(self) -> int | None:
        try:
            value = self._consent.scope_epoch(self._identity)
        except Exception:  # noqa: BLE001
            return None
        return value if is_valid_scope_epoch(value) else None

    # --- transitions ---
    def record_failure(self, cause: AuthCause) -> None:
        """Enter AUTH_REQUIRED (idempotent: a second failure while AUTH_REQUIRED emits nothing)."""
        if self._state is AuthState.AUTH_REQUIRED or type(cause) is not AuthCause:
            return
        self._state = AuthState.AUTH_REQUIRED
        self._cause = cause
        self._transitions += 1
        try:
            if self._machine.state is SourceState.ACTIVE:
                self._machine.pause(_REASON)
                self._paused_by_us = True
        except Exception:  # noqa: BLE001 - the gate is this object's state, not the machine's
            self._paused_by_us = False
        alert = AuthAlert(
            self._identity.tenant, self._identity.connection_id, cause, self._epoch, self._transitions,
            self._incident,
        )
        self._alerts.append(alert)
        self._unacked.append(alert)
        self.flush_alerts()

    def flush_alerts(self) -> int:
        """Deliver alerts the sink has not accepted yet, oldest first; stops at the first failure (the
        record is kept and retried on the next call). Returns the number delivered. Never raises."""
        delivered = 0
        for alert in tuple(self._unacked):
            try:
                self._sink.emit(alert)
            except Exception:  # noqa: BLE001 - the connection stays closed; the record is kept
                self._alert_failures += 1
                break
            delivered += 1
        self._unacked = self._unacked[delivered:]
        return delivered

    def notify_revoked(self) -> None:
        """The consent module reports a revoke: AUTH_REQUIRED(CONSENT_REVOKED). Never raises."""
        self.record_failure(AuthCause.CONSENT_REVOKED)

    def ensure_healthy(self) -> None:
        """Re-read consent/epoch from the seam; raises ``DrivePortError`` (fixed code) when not usable."""
        if self._state is AuthState.AUTH_REQUIRED:
            if self._unacked:
                self.flush_alerts()
            raise DrivePortError(DriveErrorCode.AUTH_REQUIRED)
        consent = self._read(lambda: self._consent.consent_state(self._identity), ConsentState)
        epoch = self._read_epoch()
        if consent is None or epoch is None:
            raise DrivePortError(DriveErrorCode.TRANSIENT)
        if consent is not ConsentState.GRANTED or epoch != self._epoch:
            self.record_failure(AuthCause.CONSENT_REVOKED)
            raise DrivePortError(DriveErrorCode.AUTH_REQUIRED)

    def preflight(self) -> None:
        """Before a port call: consent/epoch check, then token status (refresh when refreshable)."""
        self.ensure_healthy()
        status = self._read(lambda: self._consent.token_status(self._identity), TokenStatus)
        if status is None:
            raise DrivePortError(DriveErrorCode.TRANSIENT)
        if status is TokenStatus.MISSING:
            self.record_failure(AuthCause.CONSENT_REVOKED)
            raise DrivePortError(DriveErrorCode.AUTH_REQUIRED)
        if status is TokenStatus.EXPIRED_REFRESHABLE:
            outcome = self._refresh()
            if outcome is None:
                raise DrivePortError(DriveErrorCode.TRANSIENT)
            if not outcome:
                self.record_failure(AuthCause.INVALID_GRANT)
                raise DrivePortError(DriveErrorCode.AUTH_REQUIRED)

    def _refresh(self) -> bool | None:
        try:
            ok = self._consent.refresh_access_token(self._identity)
        except Exception:  # noqa: BLE001
            return None
        if type(ok) is not bool:
            return None
        if ok:
            self._refreshes += 1
        return ok

    def refresh_after_rejection(self) -> bool | None:
        """After a provider 401: True when the token was refreshable and is refreshed now, False when it is
        not refreshable or the refresh was refused, None when the seam could not answer (unknown: the
        caller must not escalate to AUTH_REQUIRED on it)."""
        status = self._read(lambda: self._consent.token_status(self._identity), TokenStatus)
        if status is None:
            return None
        if status is not TokenStatus.EXPIRED_REFRESHABLE:
            return False
        return self._refresh()

    # --- recovery ---
    def reconsent(self, new_scope_epoch: object) -> ReconsentResult:
        """Leave AUTH_REQUIRED only with a strictly newer epoch, granted consent and a fresh scope check."""
        if self._state is not AuthState.AUTH_REQUIRED:
            return ReconsentResult.NOT_REQUIRED
        if not is_valid_scope_epoch(new_scope_epoch) or new_scope_epoch <= self._epoch:  # type: ignore[operator]
            return ReconsentResult.EPOCH_NOT_NEW
        consent = self._read(lambda: self._consent.consent_state(self._identity), ConsentState)
        status = self._read(lambda: self._consent.token_status(self._identity), TokenStatus)
        seam_epoch = self._read_epoch()
        if consent is None or status is None or seam_epoch is None:
            return ReconsentResult.SEAM_FAULT
        if consent is not ConsentState.GRANTED or status is TokenStatus.MISSING:
            return ReconsentResult.NO_CONSENT
        if seam_epoch != new_scope_epoch:
            return ReconsentResult.EPOCH_MISMATCH
        try:
            scope_ok = self._consent.scope_check_ok(self._identity, new_scope_epoch)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return ReconsentResult.SEAM_FAULT
        if scope_ok is not True:
            return ReconsentResult.SCOPE_CHECK_FAILED
        try:
            if self._machine.state is SourceState.QUARANTINED:
                return ReconsentResult.QUARANTINED
            if self._paused_by_us and self._machine.state is SourceState.PAUSED:
                self._machine.resume(_RESUME_ACTOR)
        except Exception:  # noqa: BLE001 - fail closed: not recovered
            return ReconsentResult.QUARANTINED
        self._paused_by_us = False
        self._epoch = new_scope_epoch  # type: ignore[assignment]
        self._state = AuthState.HEALTHY
        self._cause = None
        return ReconsentResult.RECOVERED


# --- guarded port --------------------------------------------------------------------------------


class AuthGuardedDrivePort:
    """``DrivePort`` wrapper: fail-closed auth gate in front of an inner port (read-only, 4 methods)."""

    def __init__(self, health: DriveAuthHealth, port: DrivePort) -> None:
        if type(health) is not DriveAuthHealth or port is None:
            raise ValueError("AUTH_GUARD_CONFIG_INVALID")
        self._health = health
        self._port = port

    async def _call(self, method: str, identity: object, scope_epoch: object, *args: object):
        h = self._health
        if type(identity) is not DrivePortIdentity or identity != h.identity:
            raise DrivePortError(DriveErrorCode.AUTH_REQUIRED)
        if not is_valid_scope_epoch(scope_epoch) or scope_epoch != h.scope_epoch:
            raise DrivePortError(DriveErrorCode.SCOPE_EPOCH_STALE)
        h.preflight()
        for attempt in (0, 1):
            try:
                fn = getattr(self._port, method)
                result = await fn(identity, scope_epoch, *args)
            except DrivePortError as exc:
                code = exc.code
                if code is DriveErrorCode.INVALID_GRANT:
                    h.record_failure(AuthCause.INVALID_GRANT)
                    raise DrivePortError(DriveErrorCode.AUTH_REQUIRED) from None
                if code is DriveErrorCode.AUTH_REQUIRED:
                    if attempt == 0:
                        refreshed = h.refresh_after_rejection()
                        if refreshed is True:
                            continue
                        if refreshed is None:  # the seam could not answer: unknown is not a verdict
                            raise DrivePortError(DriveErrorCode.TRANSIENT) from None
                    h.record_failure(AuthCause.ACCESS_REJECTED)
                    raise DrivePortError(DriveErrorCode.AUTH_REQUIRED) from None
                raise DrivePortError(code) from None
            except Exception:  # noqa: BLE001 - never echo provider/transport text
                raise DrivePortError(DriveErrorCode.TRANSIENT) from None
            h.ensure_healthy()  # revoke/expiry race: a result obtained across a revoke is discarded
            return result
        raise DrivePortError(DriveErrorCode.AUTH_REQUIRED)  # pragma: no cover - loop always returns/raises

    async def get_start_page_token(self, identity: DrivePortIdentity, scope_epoch: int) -> StartToken:
        return await self._call("get_start_page_token", identity, scope_epoch)

    async def list_changes(
        self, identity: DrivePortIdentity, scope_epoch: int, page_token: str
    ) -> ChangesPage:
        return await self._call("list_changes", identity, scope_epoch, page_token)

    async def get_file_meta(
        self, identity: DrivePortIdentity, scope_epoch: int, file_id: str
    ) -> FileMeta:
        return await self._call("get_file_meta", identity, scope_epoch, file_id)

    async def list_revisions(
        self, identity: DrivePortIdentity, scope_epoch: int, file_id: str
    ) -> tuple[RevisionMeta, ...]:
        return await self._call("list_revisions", identity, scope_epoch, file_id)


# --- polling (the only completeness path) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PollResult:
    status: PollStatus
    pages_committed: int = 0
    final_token: str | None = None
    error_code: DriveErrorCode | None = None
    reason: PollReason | None = None
    # fixed reason code of a rejected commit (e.g. a store ``CursorReason`` value); never free text
    commit_reason: str | None = None


PageCommit = Callable[[str, ChangesPage, int], Awaitable[object] | object]


def _is_code(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 64
        and all(ch.isascii() and (ch.isupper() or ch.isdigit() or ch == "_") for ch in value)
    )


def _commit_verdict(outcome: object) -> tuple[bool, str | None]:
    """(accepted, reason code). Only ``None`` or an object whose ``ok`` is exactly True is a success."""
    if outcome is None:
        return True, None
    try:
        if getattr(outcome, "ok", None) is True:
            return True, None
        reason = getattr(outcome, "reason", None)
        code = reason.value if isinstance(reason, StrEnum) else None
        return False, (code if _is_code(code) else None)
    except Exception:  # noqa: BLE001
        return False, None


def _page_shape_ok(page: ChangesPage) -> bool:
    nxt, new = page.next_page_token, page.new_start_page_token
    return (
        type(page.changes) is tuple
        and (nxt is None) != (new is None)
        and (nxt is None or is_valid_opaque_id(nxt))
        and (new is None or is_valid_opaque_id(new))
    )


async def run_poll(
    health: DriveAuthHealth,
    guarded: AuthGuardedDrivePort,
    cursor: CursorView | AsyncCursorView,
    commit: PageCommit,
    *,
    max_pages: int = 1000,
) -> PollResult:
    """One poll chain from the committed cursor. Hints are irrelevant to it.

    ``commit(page_token, page, scope_epoch)`` is the caller's durable page+cursor commit; this function
    never writes a cursor. Its result must be ``None`` or an object with ``ok is True`` (e.g. a store
    commit result), sync or awaited; anything else is ``COMMIT_FAILED`` (the store's fixed reason code is
    surfaced in ``commit_reason``). Auth is re-checked immediately before each commit, so a page fetched
    across a revoke is not committed and the chain stops. A forged page, a repeated or regressed page
    token, or a terminal start token that is not newer than the chain so far stops the chain WITHOUT
    committing the offending page (``PAGE_INVALID``). Never raises.
    """
    try:
        return await _run_poll(health, guarded, cursor, commit, max_pages)
    except Exception:  # noqa: BLE001 - hostile/forged collaborators: fixed code, nothing echoed
        return PollResult(PollStatus.PORT_ERROR, reason=PollReason.INTERNAL)


async def _run_poll(
    health: DriveAuthHealth,
    guarded: AuthGuardedDrivePort,
    cursor: CursorView | AsyncCursorView,
    commit: PageCommit,
    max_pages: object,
) -> PollResult:
    if type(max_pages) is not int or max_pages < 1 or not callable(commit):
        return PollResult(PollStatus.PORT_ERROR, reason=PollReason.CONFIG_INVALID)
    identity, epoch = health.identity, health.scope_epoch
    try:
        token = cursor.committed_token(identity)
        if inspect.isawaitable(token):
            token = await token
    except Exception:  # noqa: BLE001
        return PollResult(PollStatus.NO_CURSOR)
    if not is_valid_opaque_id(token):
        return PollResult(PollStatus.NO_CURSOR)
    committed = 0
    seen = {token}
    while committed < max_pages:
        try:
            page = await guarded.list_changes(identity, epoch, token)  # type: ignore[arg-type]
            health.ensure_healthy()
        except DrivePortError as exc:
            if exc.code is DriveErrorCode.AUTH_REQUIRED:
                return PollResult(PollStatus.AUTH_REQUIRED, committed, None, exc.code)
            return PollResult(PollStatus.PORT_ERROR, committed, None, exc.code)
        if type(page) is not ChangesPage:
            return PollResult(PollStatus.PAGE_INVALID, committed, reason=PollReason.PAGE_TYPE_INVALID)
        if not _page_shape_ok(page):
            return PollResult(PollStatus.PAGE_INVALID, committed, reason=PollReason.PAGE_SHAPE_INVALID)
        nxt, new = page.next_page_token, page.new_start_page_token
        if nxt is not None:
            if nxt == token:
                return PollResult(PollStatus.PAGE_INVALID, committed, reason=PollReason.TOKEN_REPEATED)
            if nxt in seen:
                return PollResult(PollStatus.PAGE_INVALID, committed, reason=PollReason.TOKEN_REGRESSED)
        elif new in seen:  # equal to or older than the committed cursor / this chain: not newer
            return PollResult(PollStatus.PAGE_INVALID, committed, reason=PollReason.START_TOKEN_ORDER)
        try:
            outcome = commit(token, page, epoch)
            if inspect.isawaitable(outcome):
                outcome = await outcome
        except Exception:  # noqa: BLE001
            return PollResult(PollStatus.COMMIT_FAILED, committed, reason=PollReason.COMMIT_RAISED)
        accepted, code = _commit_verdict(outcome)
        if not accepted:
            return PollResult(
                PollStatus.COMMIT_FAILED, committed, reason=PollReason.COMMIT_REJECTED, commit_reason=code
            )
        committed += 1
        if nxt is None:
            return PollResult(PollStatus.COMPLETE, committed, new)
        seen.add(nxt)
        token = nxt
    return PollResult(PollStatus.PAGE_LIMIT, committed)


# --- hints ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PollJob:
    """A request to poll one connection. Carries no hint data."""

    tenant: str
    connection_id: str
    scope_epoch: int


class _Channel:
    __slots__ = ("epoch", "resource_id", "token")

    def __init__(self, resource_id: bytes, token: bytes, epoch: int) -> None:
        self.resource_id = resource_id
        self.token = token
        self.epoch = epoch


def _field(value: object) -> bytes | None:
    if not is_valid_opaque_id(value) or len(value) > MAX_HINT_FIELD_CHARS:  # type: ignore[arg-type]
        return None
    return value.encode("utf-8")  # type: ignore[union-attr]


class HintIntake:
    """Hint intake of ONE connection: validates a notification and keeps at most one pending poll job."""

    def __init__(self, health: DriveAuthHealth) -> None:
        if type(health) is not DriveAuthHealth:
            raise ValueError("HINT_INTAKE_CONFIG_INVALID")
        self._health = health
        self._channels: dict[bytes, _Channel] = {}
        self._pending = False
        self._accepted = 0
        self._collapsed = 0

    @property
    def pending_jobs(self) -> int:
        return 1 if self._pending else 0

    @property
    def accepted_count(self) -> int:
        return self._accepted

    @property
    def collapsed_count(self) -> int:
        return self._collapsed

    def register_channel(self, channel_id: object, resource_id: object, token: object) -> bool:
        """Remember a watch channel opened for THIS connection at the current epoch. Never raises."""
        cid, rid, tok = _field(channel_id), _field(resource_id), _field(token)
        if cid is None or rid is None or tok is None:
            return False
        if cid not in self._channels and len(self._channels) >= MAX_CHANNELS:
            current = self._health.scope_epoch
            for old in [k for k, chan in self._channels.items() if chan.epoch != current]:
                del self._channels[old]  # channels of older epochs are dead anyway (REJECTED_STALE)
            if len(self._channels) >= MAX_CHANNELS:
                return False
        self._channels[cid] = _Channel(rid, tok, self._health.scope_epoch)
        return True

    def accept_hint(
        self,
        channel_id: object,
        resource_id: object,
        token: object,
        message_number: object = None,
        payload: object = None,
    ) -> HintResult:
        """Validate a notification; ``message_number`` and ``payload`` are ignored on purpose (a hint is
        order-independent and carries no data). Never raises, never echoes an input."""
        del message_number, payload
        cid, rid, tok = _field(channel_id), _field(resource_id), _field(token)
        if cid is None or rid is None or tok is None:
            return HintResult.REJECTED_INVALID
        chan = self._channels.get(cid)
        # always compare all three, even for an unknown channel, so the answer is one fixed code
        known_rid = chan.resource_id if chan is not None else b"\x00"
        known_tok = chan.token if chan is not None else b"\x00"
        ok_rid = hmac.compare_digest(rid, known_rid)
        ok_tok = hmac.compare_digest(tok, known_tok)
        if chan is None or not (ok_rid and ok_tok):
            return HintResult.REJECTED_FOREIGN
        if chan.epoch != self._health.scope_epoch:
            return HintResult.REJECTED_STALE
        if self._health.state is not AuthState.HEALTHY:
            return HintResult.REJECTED_PAUSED
        if self._pending:
            self._collapsed += 1
            return HintResult.ACCEPTED_COLLAPSED
        self._pending = True
        self._accepted += 1
        return HintResult.ACCEPTED_NEW_JOB

    def take_poll_job(self) -> PollJob | None:
        """Pop the single pending poll job (None when nothing is pending)."""
        if not self._pending:
            return None
        self._pending = False
        h = self._health
        return PollJob(h.identity.tenant, h.identity.connection_id, h.scope_epoch)


# --- test support (scripted, like drive_fake.py) ---------------------------------------------------


class FakeAlertSink:
    """Collects alerts, deduplicated by ``AuthAlert.dedup_key``."""

    def __init__(self) -> None:
        self._alerts: list[AuthAlert] = []
        self._keys: set[tuple[str, str, int, int, str]] = set()
        self.fail = False

    @property
    def alerts(self) -> tuple[AuthAlert, ...]:
        return tuple(self._alerts)

    def emit(self, alert: AuthAlert) -> None:
        if self.fail:
            raise RuntimeError("SINK_DOWN")
        if type(alert) is not AuthAlert or alert.dedup_key in self._keys:
            return
        self._keys.add(alert.dedup_key)
        self._alerts.append(alert)


class FakeAuthSeam:
    """Scripted ``ConsentSeam``: tokens are fake strings that never leave it."""

    def __init__(self, *, scope_epoch: int = 0) -> None:
        self.consent = ConsentState.GRANTED
        self.token = TokenStatus.VALID
        self.refresh_ok = True
        self.epoch = scope_epoch
        self.scope_ok = True
        self.fault = False
        self.refresh_calls = 0
        self.scope_checks = 0

    def revoke(self) -> None:
        self.consent = ConsentState.REVOKED
        self.token = TokenStatus.MISSING

    def expire_token(self, *, refreshable: bool = True) -> None:
        self.token = TokenStatus.EXPIRED_REFRESHABLE
        self.refresh_ok = refreshable

    def regrant(self, scope_epoch: int, *, scope_ok: bool = True) -> None:
        self.consent = ConsentState.GRANTED
        self.token = TokenStatus.VALID
        self.refresh_ok = True
        self.epoch = scope_epoch
        self.scope_ok = scope_ok

    def _maybe_fault(self) -> None:
        if self.fault:
            raise RuntimeError("SEAM_DOWN https://example.invalid/?token=SECRET")

    def consent_state(self, identity: DrivePortIdentity) -> ConsentState:
        self._maybe_fault()
        return self.consent

    def token_status(self, identity: DrivePortIdentity) -> TokenStatus:
        self._maybe_fault()
        return self.token

    def refresh_access_token(self, identity: DrivePortIdentity) -> bool:
        self._maybe_fault()
        self.refresh_calls += 1
        if self.token is TokenStatus.EXPIRED_REFRESHABLE and self.refresh_ok:
            self.token = TokenStatus.VALID
            return True
        return False

    def scope_epoch(self, identity: DrivePortIdentity) -> int:
        self._maybe_fault()
        return self.epoch

    def scope_check_ok(self, identity: DrivePortIdentity, scope_epoch: int) -> bool:
        self._maybe_fault()
        self.scope_checks += 1
        return self.scope_ok


class FakeCursorView:
    """In-memory committed cursor; ``commit_for_test`` stands in for the durable CAS commit."""

    def __init__(self, token: str | None = "START-1") -> None:
        self.token = token
        self.commits = 0

    def committed_token(self, identity: DrivePortIdentity) -> str | None:
        return self.token

    def commit_for_test(self, token: str | None) -> None:
        self.token = token
        self.commits += 1
