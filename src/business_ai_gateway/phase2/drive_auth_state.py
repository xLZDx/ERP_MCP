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

Conventions (Release 2): exact types, fixed outward codes, nothing echoed. Constructors validate
configuration and raise ``ValueError`` with a fixed code; runtime entry points never raise on hostile
input (they return a fixed code or raise only ``DrivePortError`` with a fixed code).
"""
from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

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
from .scheduler import IllegalTransition, SourceState, SourceStateMachine

__all__ = [
    "AlertSink",
    "AuthAlert",
    "AuthCause",
    "AuthGuardedDrivePort",
    "AuthState",
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
    "PollResult",
    "PollStatus",
    "ReconsentResult",
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

    @property
    def dedup_key(self) -> tuple[str, str, int]:
        return (self.tenant, self.connection_id, self.transition_no)


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
        if consent is None or sink is None:
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
        self._alert_failures = 0
        self._refreshes = 0

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
        if self._machine.state is SourceState.ACTIVE:
            try:
                self._machine.pause(_REASON)
                self._paused_by_us = True
            except IllegalTransition:
                self._paused_by_us = False
        alert = AuthAlert(
            self._identity.tenant, self._identity.connection_id, cause, self._epoch, self._transitions
        )
        self._alerts.append(alert)
        try:
            self._sink.emit(alert)
        except Exception:  # noqa: BLE001 - the connection stays closed; the record is kept in alerts
            self._alert_failures += 1

    def notify_revoked(self) -> None:
        """The consent module reports a revoke: AUTH_REQUIRED(CONSENT_REVOKED). Never raises."""
        self.record_failure(AuthCause.CONSENT_REVOKED)

    def ensure_healthy(self) -> None:
        """Re-read consent/epoch from the seam; raises ``DrivePortError`` (fixed code) when not usable."""
        if self._state is AuthState.AUTH_REQUIRED:
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

    def refresh_after_rejection(self) -> bool:
        """After a provider 401: True only when the token was refreshable and is refreshed now."""
        status = self._read(lambda: self._consent.token_status(self._identity), TokenStatus)
        return status is TokenStatus.EXPIRED_REFRESHABLE and self._refresh() is True

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
        if self._machine.state is SourceState.QUARANTINED:
            return ReconsentResult.QUARANTINED
        if self._paused_by_us and self._machine.state is SourceState.PAUSED:
            try:
                self._machine.resume(_RESUME_ACTOR)
            except IllegalTransition:
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
        fn = getattr(self._port, method)
        for attempt in (0, 1):
            try:
                result = await fn(identity, scope_epoch, *args)
            except DrivePortError as exc:
                code = exc.code
                if code is DriveErrorCode.INVALID_GRANT:
                    h.record_failure(AuthCause.INVALID_GRANT)
                    raise DrivePortError(DriveErrorCode.AUTH_REQUIRED) from None
                if code is DriveErrorCode.AUTH_REQUIRED:
                    if attempt == 0 and h.refresh_after_rejection():
                        continue
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


PageCommit = Callable[[str, ChangesPage, int], Awaitable[None] | None]


async def run_poll(
    health: DriveAuthHealth,
    guarded: AuthGuardedDrivePort,
    cursor: CursorView,
    commit: PageCommit,
    *,
    max_pages: int = 1000,
) -> PollResult:
    """One poll chain from the committed cursor. Hints are irrelevant to it.

    ``commit(page_token, page, scope_epoch)`` is the caller's durable page+cursor commit; this function
    never writes a cursor. Auth is re-checked immediately before each commit, so a page fetched across a
    revoke is not committed and the chain stops. Never raises on seam/port failures.
    """
    if type(max_pages) is not int or max_pages < 1 or not callable(commit):
        return PollResult(PollStatus.PORT_ERROR)
    identity, epoch = health.identity, health.scope_epoch
    try:
        token = cursor.committed_token(identity)
    except Exception:  # noqa: BLE001
        return PollResult(PollStatus.NO_CURSOR)
    if not is_valid_opaque_id(token):
        return PollResult(PollStatus.NO_CURSOR)
    committed = 0
    while committed < max_pages:
        try:
            page = await guarded.list_changes(identity, epoch, token)  # type: ignore[arg-type]
            health.ensure_healthy()
        except DrivePortError as exc:
            if exc.code is DriveErrorCode.AUTH_REQUIRED:
                return PollResult(PollStatus.AUTH_REQUIRED, committed, None, exc.code)
            return PollResult(PollStatus.PORT_ERROR, committed, None, exc.code)
        try:
            outcome = commit(token, page, epoch)
            if outcome is not None:
                await outcome
        except Exception:  # noqa: BLE001
            return PollResult(PollStatus.COMMIT_FAILED, committed)
        committed += 1
        if page.next_page_token is None:
            return PollResult(PollStatus.COMPLETE, committed, page.new_start_page_token)
        token = page.next_page_token
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
        self._keys: set[tuple[str, str, int]] = set()
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
