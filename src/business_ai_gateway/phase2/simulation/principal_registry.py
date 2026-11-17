"""Offline TEST-lane principal and approval ledger for S12-03 scenarios.

This model is deliberately in-memory. It cannot authenticate a real person, persist to a database,
or dispatch to 1C. Every operation requires an explicit TEST lane marker.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from threading import RLock
from typing import Final

__all__ = [
    "LANE",
    "ApprovalRecord",
    "DispatchPermit",
    "OfflinePrincipalRegistry",
    "Principal",
    "PrincipalRegistryError",
    "SimulatedEffect",
]

LANE: Final = "TEST"
_IDENT: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_CAPABILITIES: Final = frozenset({"requester", "approver"})


class PrincipalRegistryError(ValueError):
    """Stable fail-closed refusal from the synthetic principal/approval ledger."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Principal:
    account_id: str
    person_id: str
    capabilities: frozenset[str]
    active: bool
    epoch: int
    lane: str = LANE
    synthetic: bool = True


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    approval_id: str
    change_id: str
    approval_digest: str
    requester_account_id: str
    requester_person_id: str
    requester_epoch: int
    approver_account_id: str
    approver_person_id: str
    approver_epoch: int
    lane: str = LANE
    synthetic: bool = True


@dataclass(frozen=True, slots=True)
class DispatchPermit:
    approval_id: str
    change_id: str
    approval_digest: str
    requester_account_id: str
    approver_account_id: str
    requester_epoch: int
    approver_epoch: int
    lane: str = LANE


@dataclass(frozen=True, slots=True)
class SimulatedEffect:
    change_id: str
    approval_digest: str
    approval_id: str
    lane: str = LANE
    synthetic: bool = True


class OfflinePrincipalRegistry:
    """In-memory registry with immutable approvals and pre-dispatch epoch revalidation."""

    def __init__(self) -> None:
        self._principals: dict[str, Principal] = {}
        self._approvals: dict[str, ApprovalRecord] = {}
        self._effects: list[SimulatedEffect] = []
        self._approval_sequence = 0
        self._lock = RLock()

    @staticmethod
    def _require_lane(lane: object) -> None:
        if lane != LANE:
            raise PrincipalRegistryError("TEST_LANE_REQUIRED")

    @staticmethod
    def _ident(value: object) -> str:
        if type(value) is not str or _IDENT.fullmatch(value) is None:
            raise PrincipalRegistryError("IDENTITY_INVALID")
        return value

    @classmethod
    def _digest(cls, value: object) -> str:
        if type(value) is not str or _DIGEST.fullmatch(value) is None:
            raise PrincipalRegistryError("APPROVAL_DIGEST_INVALID")
        return value

    @staticmethod
    def _capabilities(values: object) -> frozenset[str]:
        if isinstance(values, (str, bytes)):
            raise PrincipalRegistryError("CAPABILITIES_INVALID")
        try:
            result = frozenset(values)  # type: ignore[arg-type]
        except TypeError:
            raise PrincipalRegistryError("CAPABILITIES_INVALID") from None
        if (not result or any(type(value) is not str or value not in _CAPABILITIES for value in result)):
            raise PrincipalRegistryError("CAPABILITIES_INVALID")
        return result

    def register_principal(self, account_id: str, person_id: str, capabilities: object, *,
                           active: bool = True, lane: str) -> Principal:
        """Create or revise one synthetic account binding; every revision advances its epoch."""
        self._require_lane(lane)
        account = self._ident(account_id)
        person = self._ident(person_id)
        allowed = self._capabilities(capabilities)
        if type(active) is not bool:
            raise PrincipalRegistryError("PRINCIPAL_STATE_INVALID")
        with self._lock:
            current = self._principals.get(account)
            if current is not None and (current.person_id, current.capabilities, current.active) == (
                person, allowed, active
            ):
                return current
            epoch = 1 if current is None else current.epoch + 1
            principal = Principal(account, person, allowed, active, epoch)
            self._principals[account] = principal
            return principal

    def read_principal(self, account_id: str, *, lane: str) -> Principal:
        self._require_lane(lane)
        account = self._ident(account_id)
        with self._lock:
            principal = self._principals.get(account)
            if principal is None:
                raise PrincipalRegistryError("PRINCIPAL_UNKNOWN")
            return principal

    def record_approval(self, *, change_id: str, approval_digest: str, requester_account_id: str,
                        approver_account_id: str, lane: str) -> ApprovalRecord:
        """Append a TEST approval bound to one change/digest and two distinct synthetic persons."""
        self._require_lane(lane)
        change = self._ident(change_id)
        digest = self._digest(approval_digest)
        requester_account = self._ident(requester_account_id)
        approver_account = self._ident(approver_account_id)
        with self._lock:
            requester = self._require_active(requester_account, "requester")
            approver = self._require_active(approver_account, "approver")
            if requester.person_id == approver.person_id:
                raise PrincipalRegistryError("APPROVER_NOT_INDEPENDENT")
            self._approval_sequence += 1
            approval_id = f"TEST-APPROVAL-{self._approval_sequence:08d}"
            approval = ApprovalRecord(
                approval_id=approval_id,
                change_id=change,
                approval_digest=digest,
                requester_account_id=requester.account_id,
                requester_person_id=requester.person_id,
                requester_epoch=requester.epoch,
                approver_account_id=approver.account_id,
                approver_person_id=approver.person_id,
                approver_epoch=approver.epoch,
            )
            self._approvals[approval_id] = approval
            return approval

    def dequeue(self, *, approval_id: str, change_id: str, approval_digest: str, lane: str) -> DispatchPermit:
        """Revalidate approval binding, independence, activity and epochs at dequeue."""
        self._require_lane(lane)
        approval_key = self._ident(approval_id)
        change = self._ident(change_id)
        digest = self._digest(approval_digest)
        with self._lock:
            approval = self._require_approval(approval_key, change, digest)
            requester, approver = self._require_approval_principals(approval)
            return DispatchPermit(
                approval_id=approval.approval_id,
                change_id=approval.change_id,
                approval_digest=approval.approval_digest,
                requester_account_id=requester.account_id,
                approver_account_id=approver.account_id,
                requester_epoch=requester.epoch,
                approver_epoch=approver.epoch,
            )

    def apply_simulated(self, permit: DispatchPermit, *, lane: str) -> SimulatedEffect:
        """Revalidate immediately before recording an in-memory effect; refusals have no effect."""
        self._require_lane(lane)
        if type(permit) is not DispatchPermit or permit.lane != LANE:
            raise PrincipalRegistryError("DISPATCH_PERMIT_INVALID")
        with self._lock:
            approval = self._require_approval(permit.approval_id, permit.change_id, permit.approval_digest)
            requester, approver = self._require_approval_principals(approval)
            if ((requester.epoch, approver.epoch) != (permit.requester_epoch, permit.approver_epoch)
                    or requester.epoch != approval.requester_epoch
                    or approver.epoch != approval.approver_epoch):
                raise PrincipalRegistryError("PRINCIPAL_EPOCH_CHANGED")
            effect = SimulatedEffect(approval.change_id, approval.approval_digest, approval.approval_id)
            self._effects.append(effect)
            return effect

    def approvals(self, *, lane: str) -> tuple[ApprovalRecord, ...]:
        self._require_lane(lane)
        with self._lock:
            return tuple(self._approvals.values())

    def effects(self, *, lane: str) -> tuple[SimulatedEffect, ...]:
        self._require_lane(lane)
        with self._lock:
            return tuple(self._effects)

    def _require_active(self, account_id: str, capability: str) -> Principal:
        principal = self._principals.get(account_id)
        if principal is None:
            raise PrincipalRegistryError("PRINCIPAL_UNKNOWN")
        if not principal.active:
            raise PrincipalRegistryError("PRINCIPAL_INACTIVE")
        if capability not in principal.capabilities:
            raise PrincipalRegistryError("CAPABILITY_REQUIRED")
        return principal

    def _require_approval(self, approval_id: str, change_id: str, digest: str) -> ApprovalRecord:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise PrincipalRegistryError("APPROVAL_UNKNOWN")
        if (approval.change_id, approval.approval_digest) != (change_id, digest):
            raise PrincipalRegistryError("APPROVAL_BINDING_MISMATCH")
        return approval

    def _require_approval_principals(self, approval: ApprovalRecord) -> tuple[Principal, Principal]:
        requester = self._require_active(approval.requester_account_id, "requester")
        approver = self._require_active(approval.approver_account_id, "approver")
        if requester.person_id == approver.person_id:
            raise PrincipalRegistryError("APPROVER_NOT_INDEPENDENT")
        if ((requester.person_id, approver.person_id) !=
                (approval.requester_person_id, approval.approver_person_id)):
            raise PrincipalRegistryError("PRINCIPAL_EPOCH_CHANGED")
        if (requester.epoch, approver.epoch) != (approval.requester_epoch, approval.approver_epoch):
            raise PrincipalRegistryError("PRINCIPAL_EPOCH_CHANGED")
        return requester, approver
