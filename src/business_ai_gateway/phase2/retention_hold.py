"""Phase 2 sprint S9 (R2-US-046, TC138): retention and legal hold only DECIDE, they never delete.

Offline, unwired, in-memory, no I/O, no wall clock (an injected ``clock``), no randomness (an injected id
source), no Release 1 import, no ``threading`` import (atomicity comes only from the per-tenant
``TenantBoundedMap`` / ``TenantSlotCounter`` of ``ops_types``). There is NO delete function anywhere in this
module: the only positive answer is ``DeletionDecision`` - a plan whose ``executed`` is the constant ``False``.
Actual deletion is a separate, operator-authorized, unrecoverable-action gate outside this package.

Public names: ``RetentionPolicy``, ``HoldLevel``, ``HoldReason``, ``Hold``, ``DeletionApproval``,
``ApprovalRequest``, ``ReleaseRequest``, ``DeletionRequest``, ``HoldReleaseAudit``, ``HoldReleaseReceipt``,
``DeletionDecision``, ``RetentionLedger`` (``add_policy``, ``register_object``, ``place_hold``,
``request_release``, ``confirm_release``, ``request_approval``, ``confirm_approval``, ``decide_deletion``) and the
module function ``decide_deletion(scope, request, ledger)``.

Every ledger method takes the acting ``OpsScope`` first and runs the fixed order: structure -> entitlement ->
ownership of EVERY referenced object -> per-tenant quota -> only then the ledger is read. Foreign and unknown
objects give one identical refusal and the identical port-call pattern. All storage is per tenant and
append-only: policies (versioned), registered objects (the retention start is the LEDGER's own stamp, never a
caller-supplied age), holds, release records, approvals; nothing is evicted or removed implicitly and overflow is
an explicit ``QUOTA_EXCEEDED`` for that tenant only.

``decide_deletion`` returns ``DeletionDecision`` only when ALL hold: every object is owned by the scope; every
object is registered and its retention (the largest ``min_age`` ever recorded for its class) has elapsed on the
RAW injected clock (a regressed clock can only lengthen retention); NO active hold (a hold on the object, on its
source or on the whole tenant; a release still in flight counts as active); an approval exists, was raised by
the deciding actor and approved by a DIFFERENT person who still holds the platform authority, is unexpired
(judged on the clock floored by the newest recorded stamp, so a regressed clock cannot move before it), is bound to the
digest of the exact object list and class versions, and was not made stale by a hold placed after it was approved
(even a hold released since). Each missing condition is its own fixed refusal: ``HOLD_ACTIVE``,
``RETENTION_NOT_ELAPSED`` (also: unregistered object or class without a policy), ``APPROVAL_MISSING``
(also: wrong requester, lost authority, invalidated by a later hold), ``APPROVAL_EXPIRED``,
``APPROVAL_DIGEST_MISMATCH``, ``SELF_APPROVAL``, ``OBJECT_NOT_OWNED``.

Four-eyes is a TWO-PHASE process (naming an approver is not approval). The initiator records a request
(``request_approval`` / ``request_release``, naming the approver); the named, DIFFERENT approver then acts under
his OWN ``OpsScope`` (``confirm_approval`` / ``confirm_release``): entitlement, ownership and the platform right
are checked on THAT call's ``scope.actor_id``. Only the confirm call creates the stored ``DeletionApproval`` /
applies the release; a named approver who never acts leaves ``APPROVAL_MISSING`` and nothing applied; the
initiator confirming his own request is ``SELF_APPROVAL``. The release is audited through the injected
``audit_fn(HoldReleaseAudit) -> True`` (naming the real requester and the real confirming actor) and applied only
after the audit returned exactly ``True``; any other answer or exception leaves the hold active
(``AUDIT_UNAVAILABLE``). The claim on a release is one atomic per-tenant slot, so two concurrent confirmations
cannot both be audited.

A ``Hold`` stores its company: a hold of another company and an unknown hold id give the identical ``NOT_FOUND``
and port-call pattern (the entitlement gate runs first; the hold's own object/source reference is then owned-checked
for the actor's company). TENANT-level holds are platform-wide: placing and releasing one needs the separate
platform rights ``ACTION_PLACE_TENANT_HOLD`` / ``ACTION_RELEASE_TENANT_HOLD`` through the authority port, and
every company has its own hold quota inside the tenant cap. The retention class of an object is fixed at its first
registration; a class whose longest min_age is below the configured platform floor (``min_age_floor``) can be
registered only by an actor holding ``ACTION_REGISTER_LOW_RETENTION``.

Honest limits: a decision is a point-in-time plan; this package cannot make it atomic with the external
deletion executor, which must re-decide immediately before acting. Placing a hold needs no second approver
(it is the protective direction). A release whose process died between claim and apply stays pending and is
treated as an active hold (fail closed) until an operator intervenes. Stamps are monotone only relative to the
records already visible; the injected clock is trusted to be monotone at its source. Authority is
``EVALUATION_ONLY``.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from ._identity import same_person
from .comparison_snapshot import canonical_digest
from .ops_types import (
    AUTHORITY,
    OpsReason,
    OpsRefusal,
    OpsScope,
    TenantBoundedMap,
    TenantSlotCounter,
    check_scope_order,
    is_aware_datetime,
    is_digest,
    is_exact_int,
    is_identity_text,
    ops_refusal,
)
from .workbench_types import OWNERSHIP_KINDS

__all__ = [
    "ACTION_APPROVE_DELETION", "ACTION_PLACE_TENANT_HOLD", "ACTION_REGISTER_LOW_RETENTION", "ACTION_RELEASE_HOLD",
    "ACTION_RELEASE_TENANT_HOLD", "ACTION_SET_POLICY", "ApprovalRequest", "DeletionApproval", "DeletionDecision",
    "DeletionRequest", "Hold", "HoldLevel", "HoldReason", "HoldReleaseAudit", "HoldReleaseReceipt",
    "ReleaseRequest", "RetentionLedger", "RetentionPolicy", "decide_deletion",
]

ACTION_SET_POLICY: Final = "retention.policy.set"
ACTION_RELEASE_HOLD: Final = "retention.hold.release"
ACTION_APPROVE_DELETION: Final = "retention.deletion.approve"
ACTION_PLACE_TENANT_HOLD: Final = "retention.hold.place_tenant"
ACTION_RELEASE_TENANT_HOLD: Final = "retention.hold.release_tenant"
ACTION_REGISTER_LOW_RETENTION: Final = "retention.object.register_low_class"
MAX_OBJECTS: Final = 64
MAX_ID_CHARS: Final = 200
MAX_APPROVAL_TTL: Final = timedelta(days=30)
MAX_MIN_AGE: Final = timedelta(days=36_500)
MAX_VERSION: Final = 1_000_000
DEFAULT_CAP: Final = 1_000
DEFAULT_MIN_AGE_FLOOR: Final = timedelta(days=1)


class HoldLevel(StrEnum):
    OBJECT = "OBJECT"
    SOURCE = "SOURCE"
    TENANT = "TENANT"


class HoldReason(StrEnum):
    """Closed, text-free reason set for a hold."""

    LEGAL = "LEGAL"
    REGULATORY = "REGULATORY"
    AUDIT = "AUDIT"
    DISPUTE = "DISPUTE"


def _short(value: object) -> bool:
    return is_identity_text(value) and len(value) <= MAX_ID_CHARS  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    retention_class: str
    version: int
    min_age: timedelta

    def __post_init__(self) -> None:
        if (not _short(self.retention_class) or "@" in self.retention_class or not is_exact_int(self.version, 1, MAX_VERSION)
                or type(self.min_age) is not timedelta or not timedelta(0) <= self.min_age <= MAX_MIN_AGE):
            raise ValueError("RETENTION_POLICY_INVALID")

    def __repr__(self) -> str:
        return "RetentionPolicy(<redacted>)"


@dataclass(frozen=True, slots=True)
class Hold:
    hold_id: str
    level: HoldLevel
    object_kind: str
    target: str
    reason: HoldReason
    placed_by: str
    placed_at: datetime
    company_id: str = ""

    def __repr__(self) -> str:
        return "Hold(<redacted>)"


@dataclass(frozen=True, slots=True)
class DeletionApproval:
    approval_id: str
    object_digest: str
    requester: str
    approver: str
    approved_at: datetime
    expires_at: datetime
    company_id: str = ""

    def __repr__(self) -> str:
        return "DeletionApproval(<redacted>)"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Phase 1 of four-eyes: a recorded request naming an approver. It is NOT an approval."""

    approval_id: str
    company_id: str
    object_digest: str
    requester: str
    approver: str
    requested_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        return "ApprovalRequest(<redacted>)"


@dataclass(frozen=True, slots=True)
class ReleaseRequest:
    """Phase 1 of a hold release: a recorded request naming an approver. It releases nothing."""

    hold_id: str
    company_id: str
    requester: str
    approver: str
    requested_at: datetime

    def __repr__(self) -> str:
        return "ReleaseRequest(<redacted>)"


@dataclass(frozen=True, slots=True)
class DeletionRequest:
    """Which objects (one ownership ``object_kind``) and which approval; nothing free-form."""

    object_kind: str
    object_ids: tuple[str, ...]
    approval_id: str

    def __post_init__(self) -> None:
        if (type(self.object_kind) is not str or self.object_kind not in OWNERSHIP_KINDS
                or type(self.object_ids) is not tuple or not 1 <= len(self.object_ids) <= MAX_OBJECTS
                or not all(_short(i) for i in self.object_ids) or len(set(self.object_ids)) != len(self.object_ids)
                or not _short(self.approval_id)):
            raise ValueError("DELETION_REQUEST_INVALID")

    def __repr__(self) -> str:
        return "DeletionRequest(<redacted>)"


@dataclass(frozen=True, slots=True)
class HoldReleaseAudit:
    """The record handed to the injected ``audit_fn`` (no free text)."""

    action: str
    tenant_id: str
    company_id: str
    requester: str
    approver: str
    hold_id: str
    at: datetime

    def __repr__(self) -> str:
        return "HoldReleaseAudit(<redacted>)"


@dataclass(frozen=True, slots=True)
class HoldReleaseReceipt:
    hold_id: str
    released_at: datetime
    authority: str = AUTHORITY

    def __repr__(self) -> str:
        return "HoldReleaseReceipt(<redacted>)"


@dataclass(frozen=True, slots=True)
class DeletionDecision:
    """The ONLY positive answer: a plan. It never deletes; ``executed`` is the constant ``False``."""

    object_digest: str
    approval_id: str
    decided_at: datetime
    plan_digest: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        if (not is_digest(self.object_digest) or not _short(self.approval_id) or not is_aware_datetime(self.decided_at)
                or not is_digest(self.plan_digest) or type(self.authority) is not str or self.authority != AUTHORITY
                or self.plan_digest != _plan_digest(self.object_digest, self.approval_id, self.decided_at)):
            raise ValueError("DELETION_DECISION_INVALID")

    @property
    def reason(self) -> OpsReason:
        return OpsReason.DELETION_ALLOWED_PLAN

    @property
    def executed(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "DeletionDecision(<redacted>)"


def _object_key(company_id: str, kind: str, object_id: str) -> str:
    """Registered-object key; the length prefix keeps (company, kind, id) unambiguous."""
    return f"{len(company_id)}:{company_id}:{kind}:{object_id}"


def _plan_digest(object_digest: str, approval_id: str, at: datetime) -> str:
    return canonical_digest({"v": 1, "o": object_digest, "a": approval_id, "t": at})


@dataclass(frozen=True, slots=True)
class _Object:
    kind: str
    object_id: str
    source_id: str
    retention_class: str
    retained_from: datetime

    def __repr__(self) -> str:
        return "RetainedObject(<redacted>)"


# --------------------------------------------------------------------------------------------------

def _guarded(fn: Callable[..., object]) -> Callable[..., object]:
    """Public ledger methods never raise: an unexpected error becomes the fixed ``INTERNAL_REFUSED``."""

    @functools.wraps(fn)
    def wrapper(self: RetentionLedger, *args: object, **kwargs: object) -> object:
        try:
            return fn(self, *args, **kwargs)
        except Exception:  # noqa: BLE001
            return ops_refusal(OpsReason.INTERNAL_REFUSED, self._ids)
    return wrapper


class RetentionLedger:
    """Append-only per-tenant ledger with injected ports; see the module docstring."""

    def __init__(self, ids: object, ownership: object, entitlement: object, authority: object, clock: object,
                 audit_fn: object = None, per_tenant_cap: int = DEFAULT_CAP, per_company_hold_cap: object = None,
                 min_age_floor: object = DEFAULT_MIN_AGE_FLOOR) -> None:
        if not callable(clock) or (audit_fn is not None and not callable(audit_fn)):
            raise ValueError("RETENTION_LEDGER_INVALID")
        if type(min_age_floor) is not timedelta or not timedelta(0) <= min_age_floor <= MAX_MIN_AGE:
            raise ValueError("RETENTION_LEDGER_INVALID")
        if per_company_hold_cap is None:  # a company may use at most half of the tenant's hold room by default
            per_company_hold_cap = max(1, per_tenant_cap // 2) if is_exact_int(per_tenant_cap, 1) else 1
        if not is_exact_int(per_company_hold_cap, 1, per_tenant_cap if is_exact_int(per_tenant_cap) else 1):
            raise ValueError("RETENTION_LEDGER_INVALID")
        self._floor_age: timedelta = min_age_floor
        self._ids, self._ownership, self._entitlement = ids, ownership, entitlement
        self._authority, self._clock, self._audit = authority, clock, audit_fn
        self._policies = TenantBoundedMap(per_tenant_cap, ids)
        self._objects = TenantBoundedMap(per_tenant_cap, ids)
        self._holds = TenantBoundedMap(per_tenant_cap, ids)
        self._releases = TenantBoundedMap(per_tenant_cap, ids)
        self._approvals = TenantBoundedMap(per_tenant_cap, ids)
        self._approval_requests = TenantBoundedMap(per_tenant_cap, ids)
        self._release_requests = TenantBoundedMap(per_tenant_cap, ids)
        self._company_holds = TenantSlotCounter(per_company_hold_cap)  # keyed (tenant, company); holds never expire
        self._claims = TenantSlotCounter(1)

    def __repr__(self) -> str:
        return "RetentionLedger(<redacted>)"

    # ---- helpers ----------------------------------------------------------------------------
    def _refuse(self, reason: OpsReason) -> OpsRefusal:
        return ops_refusal(reason, self._ids)

    def _gate(self, scope: object, refs: tuple[tuple[str, str], ...]) -> OpsRefusal | None:
        return check_scope_order(scope, refs, self._ownership, self._entitlement, self._ids)

    def _raw_now(self) -> datetime | None:
        try:
            now = self._clock()  # type: ignore[operator]
        except Exception:  # noqa: BLE001
            return None
        return now if is_aware_datetime(now) else None

    def _floor(self, tenant: str) -> datetime | None:
        stamps = [h.placed_at for _, h in self._holds.items(tenant)]  # type: ignore[attr-defined]
        stamps += [a.approved_at for _, a in self._approvals.items(tenant)]  # type: ignore[attr-defined]
        stamps += [r.requested_at for _, r in self._approval_requests.items(tenant)]  # type: ignore[attr-defined]
        stamps += [r.requested_at for _, r in self._release_requests.items(tenant)]  # type: ignore[attr-defined]
        stamps += [o.retained_from for _, o in self._objects.items(tenant)]  # type: ignore[attr-defined]
        return max(stamps) if stamps else None

    def _stamp(self, tenant: str, raw: datetime) -> datetime:
        floor = self._floor(tenant)
        return raw if floor is None or raw >= floor else floor

    def _authorized(self, actor: str, action: str) -> bool | None:
        try:
            return self._authority.authorized(actor, action) is True  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None

    def _new_id(self) -> str | None:
        try:
            value = self._ids.next_id()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None
        return value if _short(value) else None

    def _policy_state(self, tenant: str) -> dict[str, tuple[int, timedelta]]:
        """class -> (highest version, largest min_age ever recorded)."""
        out: dict[str, tuple[int, timedelta]] = {}
        for _, pol in self._policies.items(tenant):  # type: ignore[attr-defined]
            version, age = out.get(pol.retention_class, (0, timedelta(0)))
            out[pol.retention_class] = (max(version, pol.version), max(age, pol.min_age))
        return out

    @staticmethod
    def _covers(hold: Hold, kind: str, ids: frozenset[str], sources: frozenset[str]) -> bool:
        if hold.level is HoldLevel.TENANT:
            return True
        if hold.level is HoldLevel.SOURCE:
            return hold.target in sources
        return hold.object_kind == kind and hold.target in ids

    def _digest(self, scope: OpsScope, kind: str, objects: list[_Object], state: dict[str, tuple[int, timedelta]]) -> str:
        rows = sorted([o.object_id, o.retention_class, state[o.retention_class][0], o.source_id] for o in objects)
        return canonical_digest({"v": 1, "t": scope.tenant_id, "c": scope.company_id, "k": kind, "o": rows})

    # ---- policies and objects -----------------------------------------------------------------
    @_guarded
    def add_policy(self, scope: object, policy: object) -> RetentionPolicy | OpsRefusal:
        if type(policy) is not RetentionPolicy:
            return self._refuse(OpsReason.INPUT_INVALID)
        refusal = self._gate(scope, ())
        if refusal is not None:
            return refusal
        cls, version, age = policy.retention_class, policy.version, policy.min_age
        tenant, actor = scope.tenant_id, scope.actor_id  # type: ignore[attr-defined]
        allowed = self._authorized(actor, ACTION_SET_POLICY)
        if allowed is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        if not allowed:
            return self._refuse(OpsReason.NOT_AUTHORIZED)
        known = self._policy_state(tenant).get(cls)
        if known is not None and age < known[1]:  # a new version may never shorten retention
            return self._refuse(OpsReason.INPUT_INVALID)
        refused = self._policies.insert(tenant, f"{cls}@{version}", policy)
        return policy if refused is None else refused

    @_guarded
    def register_object(self, scope: object, kind: object, object_id: object, source_id: object,
                        retention_class: object) -> _Object | OpsRefusal:
        if (type(kind) is not str or kind not in OWNERSHIP_KINDS or not _short(object_id) or not _short(source_id)
                or not _short(retention_class)):
            return self._refuse(OpsReason.INPUT_INVALID)
        refusal = self._gate(scope, ((kind, object_id), ("source_id", source_id)))  # type: ignore[arg-type]
        if refusal is not None:
            return refusal
        tenant = scope.tenant_id  # type: ignore[attr-defined]
        raw = self._raw_now()
        if raw is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        state = self._policy_state(tenant)
        if retention_class not in state:
            return self._refuse(OpsReason.NOT_FOUND)
        key = _object_key(scope.company_id, kind, object_id)  # type: ignore[attr-defined]
        if self._objects.get(tenant, key) is not None:  # the class of a known object is fixed
            return self._refuse(OpsReason.DUPLICATE_SUPPRESSED)
        if state[retention_class][1] < self._floor_age:  # an almost-instant class is a platform decision
            allowed = self._authorized(scope.actor_id, ACTION_REGISTER_LOW_RETENTION)  # type: ignore[attr-defined]
            if allowed is None:
                return self._refuse(OpsReason.DEPENDENCY_FAILED)
            if not allowed:
                return self._refuse(OpsReason.NOT_AUTHORIZED)
        record = _Object(kind, object_id, source_id, retention_class, self._stamp(tenant, raw))  # type: ignore[arg-type]
        refused = self._objects.insert(tenant, key, record)
        return record if refused is None else refused

    # ---- holds --------------------------------------------------------------------------------
    @_guarded
    def place_hold(self, scope: object, level: object, reason: object, target_kind: object = None,
                   target_id: object = None) -> Hold | OpsRefusal:
        if type(level) is not HoldLevel or type(reason) is not HoldReason:
            return self._refuse(OpsReason.INPUT_INVALID)
        if level is HoldLevel.OBJECT:
            if type(target_kind) is not str or target_kind not in OWNERSHIP_KINDS or not _short(target_id):
                return self._refuse(OpsReason.INPUT_INVALID)
            refs, kind, target = ((target_kind, target_id),), target_kind, target_id
        elif level is HoldLevel.SOURCE:
            if target_kind is not None or not _short(target_id):
                return self._refuse(OpsReason.INPUT_INVALID)
            refs, kind, target = (("source_id", target_id),), "", target_id
        else:
            if target_kind is not None or target_id is not None:
                return self._refuse(OpsReason.INPUT_INVALID)
            refs, kind, target = (), "", ""
        refusal = self._gate(scope, refs)  # type: ignore[arg-type]
        if refusal is not None:
            return refusal
        tenant, company, actor = scope.tenant_id, scope.company_id, scope.actor_id  # type: ignore[attr-defined]
        if level is HoldLevel.TENANT:  # blocks every company of the tenant: a platform-level right
            allowed = self._authorized(actor, ACTION_PLACE_TENANT_HOLD)
            if allowed is None:
                return self._refuse(OpsReason.DEPENDENCY_FAILED)
            if not allowed:
                return self._refuse(OpsReason.NOT_AUTHORIZED)
        raw = self._raw_now()
        hold_id = self._new_id()
        if raw is None or hold_id is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        if not self._company_holds.try_acquire(tenant, company):  # type: ignore[arg-type]
            return self._refuse(OpsReason.QUOTA_EXCEEDED)  # this company's share of the tenant's hold room
        hold = Hold(hold_id, level, kind, target, reason, actor, self._stamp(tenant, raw), company)  # type: ignore[arg-type]
        refused = self._holds.insert(tenant, hold_id, hold)
        if refused is not None:
            self._company_holds.release(tenant, company)  # type: ignore[arg-type]
            return self._refuse(OpsReason.INTERNAL_REFUSED) if refused.reason is OpsReason.DUPLICATE_SUPPRESSED else refused
        return hold

    def _own_hold(self, scope: OpsScope, hold_id: str) -> Hold | OpsRefusal:
        """The hold of THIS company, after the ownership gate on the hold's own reference.

        Entitlement is asked first (by the caller). A hold of another company and an unknown id are one identical
        ``NOT_FOUND`` with the identical port calls (none beyond the entitlement). TENANT holds need the platform right.
        """
        hold = self._holds.get(scope.tenant_id, hold_id)
        if type(hold) is not Hold or hold.company_id != scope.company_id:
            return self._refuse(OpsReason.NOT_FOUND)
        refs: tuple[tuple[str, str], ...]
        if hold.level is HoldLevel.OBJECT:
            refs = ((hold.object_kind, hold.target),)
        elif hold.level is HoldLevel.SOURCE:
            refs = (("source_id", hold.target),)
        else:
            refs = ()
        refusal = self._gate(scope, refs)
        if refusal is not None:
            return refusal
        if hold.level is HoldLevel.TENANT:
            allowed = self._authorized(scope.actor_id, ACTION_RELEASE_TENANT_HOLD)
            if allowed is None:
                return self._refuse(OpsReason.DEPENDENCY_FAILED)
            if not allowed:
                return self._refuse(OpsReason.NOT_AUTHORIZED)
        return hold

    @_guarded
    def request_release(self, scope: object, hold_id: object, approver_id: object) -> ReleaseRequest | OpsRefusal:
        """Phase 1: record that ``scope.actor_id`` wants ``hold_id`` released and names the approver. Releases nothing."""
        if not _short(hold_id) or not _short(approver_id):
            return self._refuse(OpsReason.INPUT_INVALID)
        refusal = self._gate(scope, ())
        if refusal is not None:
            return refusal
        tenant, company, actor = scope.tenant_id, scope.company_id, scope.actor_id  # type: ignore[attr-defined]
        hold = self._own_hold(scope, hold_id)  # type: ignore[arg-type]
        if type(hold) is not Hold:
            return hold  # type: ignore[return-value]
        if approver_id == actor or same_person(approver_id, actor):
            return self._refuse(OpsReason.SELF_APPROVAL)
        allowed = self._authorized(approver_id, ACTION_RELEASE_HOLD)  # type: ignore[arg-type]
        if allowed is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        if not allowed:
            return self._refuse(OpsReason.NOT_AUTHORIZED)
        if self._releases.get(tenant, hold_id) is not None:
            return self._refuse(OpsReason.DUPLICATE_SUPPRESSED)
        raw = self._raw_now()
        if raw is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        request = ReleaseRequest(hold_id, company, actor, approver_id, self._stamp(tenant, raw))  # type: ignore[arg-type]
        refused = self._release_requests.insert(tenant, hold_id, request)  # type: ignore[arg-type]
        if refused is not None and refused.reason is OpsReason.DUPLICATE_SUPPRESSED:  # a newer request supersedes
            refused = self._release_requests.replace(tenant, hold_id, request)  # type: ignore[arg-type]
        return request if refused is None else refused

    @_guarded
    def confirm_release(self, scope: object, hold_id: object) -> HoldReleaseReceipt | OpsRefusal:
        """Phase 2: the NAMED, different approver acts under his own scope; only this call applies the release."""
        if not _short(hold_id):
            return self._refuse(OpsReason.INPUT_INVALID)
        refusal = self._gate(scope, ())
        if refusal is not None:
            return refusal
        tenant, company, actor = scope.tenant_id, scope.company_id, scope.actor_id  # type: ignore[attr-defined]
        hold = self._own_hold(scope, hold_id)  # type: ignore[arg-type]
        if type(hold) is not Hold:
            return hold  # type: ignore[return-value]
        if self._releases.get(tenant, hold_id) is not None:
            return self._refuse(OpsReason.DUPLICATE_SUPPRESSED)
        request = self._release_requests.get(tenant, hold_id)  # type: ignore[arg-type]
        if type(request) is not ReleaseRequest or request.company_id != company:
            return self._refuse(OpsReason.APPROVAL_MISSING)
        if request.requester == actor or same_person(request.requester, actor):
            return self._refuse(OpsReason.SELF_APPROVAL)
        allowed = self._authorized(actor, ACTION_RELEASE_HOLD)
        if allowed is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        if not allowed:
            return self._refuse(OpsReason.NOT_AUTHORIZED)
        if request.approver != actor:  # somebody else was named: this actor was not asked
            return self._refuse(OpsReason.APPROVAL_MISSING)
        if self._audit is None:
            return self._refuse(OpsReason.AUDIT_UNAVAILABLE)
        raw = self._raw_now()
        if raw is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        at = self._stamp(tenant, raw)
        if not self._claims.try_acquire(tenant, hold_id):  # type: ignore[arg-type]
            return self._refuse(OpsReason.DUPLICATE_SUPPRESSED)
        applied = False
        try:
            record = HoldReleaseAudit("HOLD_RELEASED", tenant, company, request.requester, actor, hold_id, at)  # type: ignore[arg-type]
            try:
                audited = self._audit(record)  # type: ignore[operator]
            except Exception:  # noqa: BLE001
                audited = None
            if audited is not True:
                return self._refuse(OpsReason.AUDIT_UNAVAILABLE)
            refused = self._releases.insert(tenant, hold_id, at)  # type: ignore[arg-type]
            if refused is not None:
                return refused
            applied = True
            return HoldReleaseReceipt(hold_id, at)  # type: ignore[arg-type]
        finally:
            if not applied:
                self._claims.release(tenant, hold_id)  # type: ignore[arg-type]

    # ---- approvals and the decision ------------------------------------------------------------
    def _load(self, scope: OpsScope, request: DeletionRequest) -> tuple[list[_Object] | None, frozenset[str]]:
        records = [self._objects.get(scope.tenant_id, _object_key(scope.company_id, request.object_kind, i))
                   for i in request.object_ids]
        found = [r for r in records if r is not None]
        sources = frozenset(r.source_id for r in found)
        return (found if len(found) == len(records) else None), sources

    @_guarded
    def request_approval(self, scope: object, request: object, approver_id: object,
                         expires_at: object) -> ApprovalRequest | OpsRefusal:
        """Phase 1: record a deletion-approval request naming the approver. It is NOT an approval."""
        if (type(request) is not DeletionRequest or not _short(approver_id) or not is_aware_datetime(expires_at)):
            return self._refuse(OpsReason.INPUT_INVALID)
        refusal = self._gate(scope, tuple((request.object_kind, i) for i in request.object_ids))
        if refusal is not None:
            return self._refuse(OpsReason.OBJECT_NOT_OWNED) if refusal.reason is OpsReason.NOT_FOUND else refusal
        tenant, company, actor = scope.tenant_id, scope.company_id, scope.actor_id  # type: ignore[attr-defined]
        if approver_id == actor or same_person(approver_id, actor):
            return self._refuse(OpsReason.SELF_APPROVAL)
        allowed = self._authorized(approver_id, ACTION_APPROVE_DELETION)  # type: ignore[arg-type]
        if allowed is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        if not allowed:
            return self._refuse(OpsReason.NOT_AUTHORIZED)
        raw = self._raw_now()
        if raw is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        now = self._stamp(tenant, raw)
        if not now < expires_at <= now + MAX_APPROVAL_TTL:  # type: ignore[operator]
            return self._refuse(OpsReason.INPUT_INVALID)
        objects, _sources = self._load(scope, request)  # type: ignore[arg-type]
        if objects is None:
            return self._refuse(OpsReason.NOT_FOUND)
        digest = self._digest(scope, request.object_kind, objects, self._policy_state(tenant))  # type: ignore[arg-type]
        approval_id = self._new_id()
        if approval_id is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        pending = ApprovalRequest(approval_id, company, digest, actor, approver_id, now, expires_at)  # type: ignore[arg-type]
        refused = self._approval_requests.insert(tenant, approval_id, pending)
        return pending if refused is None else refused

    @_guarded
    def confirm_approval(self, scope: object, request: object) -> DeletionApproval | OpsRefusal:
        """Phase 2: the NAMED, different approver acts under his OWN scope (``request.approval_id`` is the pending id).

        Entitlement, ownership of every object and the platform right are checked for ``scope.actor_id`` of THIS call;
        only this call stores the ``DeletionApproval`` (approver = the real acting person).
        """
        if type(request) is not DeletionRequest:
            return self._refuse(OpsReason.INPUT_INVALID)
        refusal = self._gate(scope, tuple((request.object_kind, i) for i in request.object_ids))
        if refusal is not None:
            return self._refuse(OpsReason.OBJECT_NOT_OWNED) if refusal.reason is OpsReason.NOT_FOUND else refusal
        tenant, company, actor = scope.tenant_id, scope.company_id, scope.actor_id  # type: ignore[attr-defined]
        pending = self._approval_requests.get(tenant, request.approval_id)
        if type(pending) is not ApprovalRequest or pending.company_id != company:  # unknown == another company's
            return self._refuse(OpsReason.APPROVAL_MISSING)
        if pending.requester == actor or same_person(pending.requester, actor):
            return self._refuse(OpsReason.SELF_APPROVAL)
        allowed = self._authorized(actor, ACTION_APPROVE_DELETION)
        if allowed is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        if not allowed:
            return self._refuse(OpsReason.NOT_AUTHORIZED)
        if pending.approver != actor:  # somebody else was named: this actor was not asked
            return self._refuse(OpsReason.APPROVAL_MISSING)
        raw = self._raw_now()
        if raw is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        now = self._stamp(tenant, raw)
        if now >= pending.expires_at:
            return self._refuse(OpsReason.APPROVAL_EXPIRED)
        objects, _sources = self._load(scope, request)  # type: ignore[arg-type]
        if objects is None:
            return self._refuse(OpsReason.NOT_FOUND)
        digest = self._digest(scope, request.object_kind, objects, self._policy_state(tenant))  # type: ignore[arg-type]
        if digest != pending.object_digest:
            return self._refuse(OpsReason.APPROVAL_DIGEST_MISMATCH)
        approval = DeletionApproval(pending.approval_id, digest, pending.requester, actor, now, pending.expires_at,
                                    company)
        refused = self._approvals.insert(tenant, pending.approval_id, approval)
        return approval if refused is None else refused

    @_guarded
    def decide_deletion(self, scope: object, request: object) -> DeletionDecision | OpsRefusal:
        if type(request) is not DeletionRequest:
            return self._refuse(OpsReason.INPUT_INVALID)
        refusal = self._gate(scope, tuple((request.object_kind, i) for i in request.object_ids))
        if refusal is not None:  # foreign and unknown objects read identically
            return self._refuse(OpsReason.OBJECT_NOT_OWNED) if refusal.reason is OpsReason.NOT_FOUND else refusal
        tenant, actor = scope.tenant_id, scope.actor_id  # type: ignore[attr-defined]
        raw = self._raw_now()
        if raw is None:
            return self._refuse(OpsReason.DEPENDENCY_FAILED)
        floored = self._stamp(tenant, raw)
        kind, ids = request.object_kind, frozenset(request.object_ids)
        objects, sources = self._load(scope, request)  # type: ignore[arg-type]
        released = {k for k, _ in self._releases.items(tenant)}  # type: ignore[attr-defined]
        holds = [h for _, h in self._holds.items(tenant)  # type: ignore[attr-defined]
                 if h.level is HoldLevel.TENANT or h.company_id == scope.company_id]  # tenant holds stay tenant-wide
        if any(h.hold_id not in released and self._covers(h, kind, ids, sources) for h in holds):
            return self._refuse(OpsReason.HOLD_ACTIVE)
        state = self._policy_state(tenant)
        if objects is None or any(
                o.retention_class not in state or raw - o.retained_from < state[o.retention_class][1] for o in objects):
            return self._refuse(OpsReason.RETENTION_NOT_ELAPSED)
        approval = self._approvals.get(tenant, request.approval_id)
        if type(approval) is not DeletionApproval:
            return self._refuse(OpsReason.APPROVAL_MISSING)
        if approval.company_id != scope.company_id:  # type: ignore[attr-defined]
            return self._refuse(OpsReason.APPROVAL_MISSING)  # foreign == unknown, before any person comparison
        if approval.approver == actor or same_person(approval.approver, actor):
            return self._refuse(OpsReason.SELF_APPROVAL)
        if (approval.requester != actor
                or self._authorized(approval.approver, ACTION_APPROVE_DELETION) is not True):
            return self._refuse(OpsReason.APPROVAL_MISSING)
        if any(h.placed_at >= approval.approved_at and self._covers(h, kind, ids, sources) for h in holds):
            return self._refuse(OpsReason.APPROVAL_MISSING)
        if floored >= approval.expires_at:
            return self._refuse(OpsReason.APPROVAL_EXPIRED)
        if approval.object_digest != self._digest(scope, kind, objects, state):  # type: ignore[arg-type]
            return self._refuse(OpsReason.APPROVAL_DIGEST_MISMATCH)
        return DeletionDecision(approval.object_digest, approval.approval_id, raw,
                                _plan_digest(approval.object_digest, approval.approval_id, raw))


def decide_deletion(scope: object, request: object, ledger: object) -> DeletionDecision | OpsRefusal:
    """Module-level entry: ``ledger.decide_deletion(scope, request)``; never raises."""
    if type(ledger) is not RetentionLedger:
        return ops_refusal(OpsReason.INPUT_INVALID, None)
    return ledger.decide_deletion(scope, request)  # type: ignore[return-value]
