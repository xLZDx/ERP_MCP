"""Phase 2 sprint S9 E3 (R2-US-045, REQ25, TC134/TC135): rollback DECISION that never resurrects rights.

Offline, unwired, in-memory, PLATFORM level. No I/O, no wall clock, no randomness, no Release 1 import and
no deletion/execution code: ``decide_rollback`` only DECIDES (``executed`` is the constant ``False``) and
returns a plan digest; applying a plan is operator-owned. Public functions never raise. A tenant actor can
never invoke it: authorization is an injected platform-level ``OperatorAuthorityPort`` and the check runs
right after the structure check, before anything about the release is revealed.

Fixed check order of ``decide_rollback`` (first failure wins, every failure is an ``OpsRefusal``)
1. structure (``INPUT_INVALID``)            4. classification of EVERY plan step via ``classify_step``:
2. operator authority (``NOT_AUTHORIZED``)     any ``DESTRUCTIVE``/``UNCLASSIFIED`` step ->
3. one clock read (``DEPENDENCY_FAILED``)      ``ROLLBACK_DESTRUCTIVE_DENIED`` (never a name list)
5. live head format newer than the old version can read -> ``ROLLBACK_HEAD_INCOMPATIBLE`` (blocked, not forced)
6. CONTRACT steps: window not yet elapsed on the injected clock -> ``ROLLBACK_WINDOW_OPEN`` (a separate
   approval cannot shorten it; a clock regression only keeps it open longer, never shortens it); elapsed but
   without the separate contract approval -> ``CONTRACT_NOT_ALLOWED``
7. effective grants computed from CURRENT state (see below); a failing dependency -> ``DEPENDENCY_FAILED``.

Rights and evidence are never resurrected (decision 15): ``effective_after_rollback`` reads the CURRENT
``GrantRegistry`` view (one atomic read, high-water clock inside the registry) and
``AttestationStore.check_current`` (never ``check_as_of``). A grant is effective only if it is not revoked,
its credential has not expired (a regressed clock never revives an expired credential: expiry is sticky
and judged against the registry high-water) and its attestation, if bound, is CURRENT. A switch-time
snapshot may only be used to REPORT what differs (``RESURRECTION_BLOCKED`` entries with typed ids); an id
that is absent from the current registry is only counted, never listed.

Typed ids only: ``GrantId`` and ``AttestationBinding`` hold opaque pattern-checked identifiers and digests;
no business or tenant payload exists in any type here. Outputs are frozen, derived, ``EVALUATION_ONLY``.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol

from .comparison_snapshot import canonical_digest
from .evidence_attestation import CheckResult
from .ops_types import (
    AUTHORITY,
    OpsReason,
    OpsRefusal,
    is_aware_datetime,
    is_digest,
    is_exact_int,
    is_identity_text,
    ops_refusal,
)
from .release_migration import MigrationStep, StepClass, classify_step

__all__ = [
    "ACTION_CONTRACT_APPROVE",
    "ACTION_ROLLBACK",
    "MAX_GRANTS",
    "AttestationBinding",
    "BlockCause",
    "EffectiveGrants",
    "FakeGrantRegistry",
    "GrantEntry",
    "GrantId",
    "GrantRecord",
    "GrantRegistry",
    "RegistryView",
    "ReleaseState",
    "ResurrectionEntry",
    "RollbackDecision",
    "RollbackPlan",
    "SwitchSnapshot",
    "decide_rollback",
    "effective_after_rollback",
]

ACTION_ROLLBACK: Final = "release.rollback.decide"
ACTION_CONTRACT_APPROVE: Final = "release.contract.approve"
MAX_GRANTS: Final = 10_000
_MAX_PLAN_STEPS: Final = 256
_MAX_WINDOW_SECONDS: Final = 10 * 366 * 24 * 3600
_MAX_FORMAT: Final = 1_000_000
_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")


def _id_ok(value: object) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


# --------------------------------------------------------------------------------------------------
# typed ids and registry records

@dataclass(frozen=True, slots=True)
class GrantId:
    value: str

    def __post_init__(self) -> None:
        if not _id_ok(self.value):
            raise ValueError("GRANT_ID_INVALID")

    def __repr__(self) -> str:
        return "GrantId(<id>)"


@dataclass(frozen=True, slots=True)
class AttestationBinding:
    """Opaque identifiers needed to ask ``AttestationStore.check_current``; no evidence content."""

    attestation_id: str
    tenant_id: str
    revision_digest: str
    policy_version: str
    policy_digest: str

    def __post_init__(self) -> None:
        if not (is_identity_text(self.attestation_id) and len(self.attestation_id) <= 128
                and is_identity_text(self.tenant_id) and len(self.tenant_id) <= 128
                and is_digest(self.revision_digest) and is_identity_text(self.policy_version)
                and len(self.policy_version) <= 128 and is_digest(self.policy_digest)):
            raise ValueError("ATTESTATION_BINDING_INVALID")

    def __repr__(self) -> str:
        return "AttestationBinding(<ids>)"


@dataclass(frozen=True, slots=True)
class GrantRecord:
    grant_id: GrantId
    credential_expires_at: datetime
    evidence: AttestationBinding | None = None

    def __post_init__(self) -> None:
        if (type(self.grant_id) is not GrantId or not is_aware_datetime(self.credential_expires_at)
                or (self.evidence is not None and type(self.evidence) is not AttestationBinding)):
            raise ValueError("GRANT_RECORD_INVALID")

    def __repr__(self) -> str:
        return "GrantRecord(<typed>)"


@dataclass(frozen=True, slots=True)
class GrantEntry:
    record: GrantRecord
    revoked: bool
    expired: bool

    def __repr__(self) -> str:
        return "GrantEntry(<typed>)"


@dataclass(frozen=True, slots=True)
class RegistryView:
    """One atomic read of the registry: every entry plus the high-water clock used to judge expiry."""

    entries: tuple[GrantEntry, ...]
    effective_now: datetime

    def __repr__(self) -> str:
        return "RegistryView(<typed>)"


class GrantRegistry(Protocol):
    def view(self, now: datetime) -> RegistryView | None: ...


class FakeGrantRegistry:
    """In-memory grant registry. Revocation and expiry are STICKY; check-then-act is one lock section.

    ``issue`` adds a new grant (a grant id is never reused or replaced), ``revoke`` marks it revoked
    forever, ``view(now)`` advances a monotonic high-water clock (a regressed ``now`` changes nothing),
    marks credentials whose expiry is at or before the high-water as expired for good and returns an
    immutable snapshot, all inside one critical section.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, GrantRecord] = {}
        self._revoked: set[str] = set()
        self._expired: set[str] = set()
        self._high_water: datetime | None = None

    def __repr__(self) -> str:
        return "FakeGrantRegistry(<redacted>)"

    def issue(self, record: object) -> bool:
        if type(record) is not GrantRecord:
            return False
        try:
            key = record.grant_id.value
            if not _id_ok(key) or not is_aware_datetime(record.credential_expires_at):
                return False
        except Exception:  # noqa: BLE001 - forged instance
            return False
        with self._lock:
            if key in self._records or len(self._records) >= MAX_GRANTS:
                return False
            self._records[key] = record
            return True

    def revoke(self, grant_id: object) -> bool:
        """Revoke for good; ``True`` when the grant is known (also when it was already revoked)."""
        if type(grant_id) is not GrantId:
            return False
        try:
            key = grant_id.value
        except Exception:  # noqa: BLE001
            return False
        with self._lock:
            if key not in self._records:
                return False
            self._revoked.add(key)
            return True

    def view(self, now: object) -> RegistryView | None:
        if not is_aware_datetime(now):
            return None
        try:
            stamp = now.astimezone(UTC)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - OverflowError near the datetime limits
            return None
        with self._lock:
            if self._high_water is None or stamp > self._high_water:
                self._high_water = stamp
            high = self._high_water
            entries: list[GrantEntry] = []
            for key, rec in self._records.items():
                if key not in self._expired and rec.credential_expires_at <= high:
                    self._expired.add(key)
                entries.append(GrantEntry(rec, key in self._revoked, key in self._expired))
            return RegistryView(tuple(entries), high)


# --------------------------------------------------------------------------------------------------
# effective grants after rollback

class BlockCause(StrEnum):
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    EVIDENCE_NOT_CURRENT = "EVIDENCE_NOT_CURRENT"


@dataclass(frozen=True, slots=True)
class SwitchSnapshot:
    """Grant ids that were effective at switch time. REPORT-ONLY input: it can never restore anything."""

    grant_ids: tuple[GrantId, ...]

    def __repr__(self) -> str:
        return "SwitchSnapshot(<ids>)"


@dataclass(frozen=True, slots=True)
class ResurrectionEntry:
    grant_id: GrantId
    cause: BlockCause

    def __post_init__(self) -> None:
        if type(self.grant_id) is not GrantId or type(self.cause) is not BlockCause:
            raise ValueError("RESURRECTION_ENTRY_INVALID")

    @property
    def reason(self) -> OpsReason:
        return OpsReason.RESURRECTION_BLOCKED

    def __repr__(self) -> str:
        return "ResurrectionEntry(<typed>)"


@dataclass(frozen=True, slots=True)
class EffectiveGrants:
    effective: tuple[GrantId, ...]
    blocked: tuple[ResurrectionEntry, ...]
    snapshot_absent_count: int
    digest: str = field(init=False)
    authority: str = field(init=False, default=AUTHORITY)

    def __post_init__(self) -> None:
        if (type(self.effective) is not tuple or type(self.blocked) is not tuple
                or any(type(g) is not GrantId for g in self.effective)
                or any(type(b) is not ResurrectionEntry for b in self.blocked)
                or not is_exact_int(self.snapshot_absent_count, 0, MAX_GRANTS)
                or len(self.effective) > MAX_GRANTS or len(self.blocked) > MAX_GRANTS):
            raise ValueError("EFFECTIVE_GRANTS_INVALID")
        object.__setattr__(self, "digest", canonical_digest({
            "kind": "effective", "effective": [g.value for g in self.effective],
            "blocked": [[b.grant_id.value, b.cause.value] for b in self.blocked],
            "absent": self.snapshot_absent_count}))

    def __repr__(self) -> str:
        return "EffectiveGrants(<derived>)"


def _snapshot_ids(snapshot: object) -> tuple[str, ...] | None:
    if type(snapshot) is not SwitchSnapshot:
        return None
    try:
        raw = snapshot.grant_ids  # one read
        if type(raw) not in (tuple, list) or len(raw) > MAX_GRANTS:
            return None
        items = tuple(raw)
        if any(type(g) is not GrantId for g in items):
            return None
        return tuple(g.value for g in items)
    except Exception:  # noqa: BLE001
        return None


def _read_clock(clock: object) -> datetime | None:
    if not callable(clock):
        return None
    try:
        now = clock()
        if not is_aware_datetime(now):
            return None
        return now.astimezone(UTC)
    except Exception:  # noqa: BLE001 - a broken clock fails closed
        return None


def _evidence_current(attestations: object, binding: AttestationBinding) -> bool:
    try:
        res = attestations.check_current(  # type: ignore[attr-defined]
            binding.attestation_id, binding.tenant_id, binding.revision_digest,
            binding.policy_version, binding.policy_digest)
        return type(res) is CheckResult and res.valid is True and res.code == "VALID"
    except Exception:  # noqa: BLE001 - a store that cannot answer is not evidence
        return False


def effective_after_rollback(grants: object, attestations: object, clock: object, ids: object,
                             switch_snapshot: object = None) -> EffectiveGrants | OpsRefusal:
    """The grants that are effective after a rollback, from CURRENT state only. Never raises.

    ``INPUT_INVALID`` for a bad snapshot, ``DEPENDENCY_FAILED`` for a clock/registry that cannot answer.
    The snapshot (if any) only adds ``RESURRECTION_BLOCKED`` report entries for grants that exist in the
    current registry and are not effective; it never adds an effective grant.
    """
    snap_ids: tuple[str, ...] | None = None
    if switch_snapshot is not None:
        snap_ids = _snapshot_ids(switch_snapshot)
        if snap_ids is None:
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
    now = _read_clock(clock)
    if now is None:
        return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
    return _effective(grants, attestations, now, ids, snap_ids)


def _effective(grants: object, attestations: object, now: datetime, ids: object,
               snap_ids: tuple[str, ...] | None) -> EffectiveGrants | OpsRefusal:
    try:
        view = grants.view(now)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
    if (type(view) is not RegistryView or type(view.entries) is not tuple
            or len(view.entries) > MAX_GRANTS or not is_aware_datetime(view.effective_now)
            or any(type(e) is not GrantEntry for e in view.entries)):
        return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
    high = view.effective_now
    effective: list[GrantId] = []
    causes: dict[str, BlockCause] = {}
    try:
        for entry in view.entries:
            rec = entry.record
            gid = rec.grant_id
            if entry.revoked is not False:
                causes[gid.value] = BlockCause.REVOKED
            elif entry.expired is not False or rec.credential_expires_at <= high:
                causes[gid.value] = BlockCause.EXPIRED
            elif rec.evidence is not None and not _evidence_current(attestations, rec.evidence):
                causes[gid.value] = BlockCause.EVIDENCE_NOT_CURRENT
            else:
                effective.append(gid)
        known = {e.record.grant_id.value for e in view.entries}
    except Exception:  # noqa: BLE001 - a forged entry/record: fail closed
        return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
    effective.sort(key=lambda g: g.value)
    blocked: list[ResurrectionEntry] = []
    absent = 0
    if snap_ids is not None:
        for value in sorted(set(snap_ids)):
            if value not in known:
                absent += 1
            elif value in causes:
                blocked.append(ResurrectionEntry(GrantId(value), causes[value]))
    return EffectiveGrants(tuple(effective), tuple(blocked), absent)


# --------------------------------------------------------------------------------------------------
# rollback decision

@dataclass(frozen=True, slots=True)
class ReleaseState:
    """Platform facts about the live release: when it switched, its window and the live head format."""

    release_id: str
    switched_at: datetime
    rollback_window_seconds: int
    live_head_format: int

    def __post_init__(self) -> None:
        if not (_id_ok(self.release_id) and is_aware_datetime(self.switched_at)
                and is_exact_int(self.rollback_window_seconds, 0, _MAX_WINDOW_SECONDS)
                and is_exact_int(self.live_head_format, 0, _MAX_FORMAT)):
            raise ValueError("RELEASE_STATE_INVALID")

    def __repr__(self) -> str:
        return "ReleaseState(<typed>)"


@dataclass(frozen=True, slots=True)
class RollbackPlan:
    """What a rollback would do: typed steps, the target version and the newest head format it can read."""

    target_version: str
    max_readable_head_format: int
    steps: tuple[MigrationStep, ...]

    def __repr__(self) -> str:
        return "RollbackPlan(<typed>)"


def _read_state(state: object) -> tuple[str, datetime, int, int] | None:
    if type(state) is not ReleaseState:
        return None
    try:
        row = (state.release_id, state.switched_at, state.rollback_window_seconds,
               state.live_head_format)  # one read each
        if not (_id_ok(row[0]) and is_aware_datetime(row[1])
                and is_exact_int(row[2], 0, _MAX_WINDOW_SECONDS)
                and is_exact_int(row[3], 0, _MAX_FORMAT)):
            return None
        return row[0], row[1].astimezone(UTC), row[2], row[3]
    except Exception:  # noqa: BLE001 - forged instance / overflow
        return None


def _read_plan(plan: object) -> tuple[str, int, tuple[object, ...]] | None:
    if type(plan) is not RollbackPlan:
        return None
    try:
        target, max_head, steps_raw = (
            plan.target_version, plan.max_readable_head_format, plan.steps)  # one read each
        if (not _id_ok(target) or not is_exact_int(max_head, 0, _MAX_FORMAT)
                or type(steps_raw) not in (tuple, list) or not 1 <= len(steps_raw) <= _MAX_PLAN_STEPS):
            return None
        return target, max_head, tuple(steps_raw)
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True, slots=True)
class RollbackDecision:
    refusal: OpsRefusal | None
    plan_digest: str | None
    effective_grants: tuple[GrantId, ...] = ()
    blocked: tuple[ResurrectionEntry, ...] = ()
    allowed: bool = field(init=False)
    authority: str = field(init=False, default=AUTHORITY)

    def __post_init__(self) -> None:
        ok = self.refusal is None
        if ok != is_digest(self.plan_digest) or (not ok and type(self.refusal) is not OpsRefusal):
            raise ValueError("ROLLBACK_DECISION_INVALID")
        if (type(self.effective_grants) is not tuple or type(self.blocked) is not tuple
                or any(type(g) is not GrantId for g in self.effective_grants)
                or any(type(b) is not ResurrectionEntry for b in self.blocked)
                or (not ok and (self.effective_grants or self.blocked))):
            raise ValueError("ROLLBACK_DECISION_INVALID")
        object.__setattr__(self, "allowed", ok)

    @property
    def reason(self) -> OpsReason | None:
        return None if self.refusal is None else self.refusal.reason

    @property
    def executed(self) -> bool:
        """Rollback never executes anything; applying a plan is operator-owned."""
        return False

    def __repr__(self) -> str:
        return "RollbackDecision(<derived>)"


def _deny(reason: OpsReason, ids: object) -> RollbackDecision:
    return RollbackDecision(ops_refusal(reason, ids), None)


def _authorized(authority: object, actor_id: str, action: str) -> bool | None:
    """``True``/``False`` for the port's answer, ``None`` when the port failed."""
    try:
        return authority.authorized(actor_id, action) is True  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return None


def decide_rollback(actor_id: object, plan: object, release_state: object, *, grants: object,
                    attestations: object, authority: object, clock: Callable[[], datetime] | object,
                    ids: object, switch_snapshot: object = None) -> RollbackDecision:
    """Decide (never execute) a rollback; see the module docstring for the fixed check order.

    Allowed: ``allowed=True``, ``plan_digest`` set, ``executed=False`` and the effective grants computed
    from CURRENT state. Denied: ``refusal`` carries the fixed code and no grant list is produced.
    """
    state = _read_state(release_state)
    parsed = _read_plan(plan)
    snap_ids: tuple[str, ...] | None = None
    if switch_snapshot is not None:
        snap_ids = _snapshot_ids(switch_snapshot)
        if snap_ids is None:
            return _deny(OpsReason.INPUT_INVALID, ids)
    if not is_identity_text(actor_id) or state is None or parsed is None:
        return _deny(OpsReason.INPUT_INVALID, ids)
    answer = _authorized(authority, actor_id, ACTION_ROLLBACK)  # type: ignore[arg-type]
    if answer is None:
        return _deny(OpsReason.DEPENDENCY_FAILED, ids)
    if not answer:
        return _deny(OpsReason.NOT_AUTHORIZED, ids)
    now = _read_clock(clock)
    if now is None:
        return _deny(OpsReason.DEPENDENCY_FAILED, ids)
    release_id, switched_at, window_seconds, live_head = state
    target, max_head, steps = parsed
    classes = [classify_step(s) for s in steps]
    if any(c in (StepClass.DESTRUCTIVE, StepClass.UNCLASSIFIED) for c in classes):
        return _deny(OpsReason.ROLLBACK_DESTRUCTIVE_DENIED, ids)
    if live_head > max_head:
        return _deny(OpsReason.ROLLBACK_HEAD_INCOMPATIBLE, ids)
    if StepClass.CONTRACT in classes:
        try:
            window_open = now < switched_at + timedelta(seconds=window_seconds)
        except OverflowError:
            window_open = True  # an unrepresentable end is never "elapsed"
        if window_open:
            return _deny(OpsReason.ROLLBACK_WINDOW_OPEN, ids)
        approved = _authorized(authority, actor_id, ACTION_CONTRACT_APPROVE)  # type: ignore[arg-type]
        if approved is None:
            return _deny(OpsReason.DEPENDENCY_FAILED, ids)
        if not approved:
            return _deny(OpsReason.CONTRACT_NOT_ALLOWED, ids)
    effective = _effective(grants, attestations, now, ids, snap_ids)
    if type(effective) is not EffectiveGrants:
        return RollbackDecision(effective if type(effective) is OpsRefusal
                                else ops_refusal(OpsReason.DEPENDENCY_FAILED, ids), None)
    digest = canonical_digest({
        "kind": "rollback", "release": release_id, "switched_at": switched_at.isoformat(),
        "window": window_seconds, "live_head": live_head, "target": target, "max_head": max_head,
        "steps": [[s.phase.value, s.kind.value, s.schema.value, s.object_class.value]  # type: ignore[attr-defined]
                  for s in steps],
        "effective": [g.value for g in effective.effective]})
    return RollbackDecision(None, digest, effective.effective, effective.blocked)
