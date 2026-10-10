"""Phase 2 sprint S9 E5: the G6-pre readiness checklist (offline, unwired, in-memory).

G6-pre means ACTUAL workload metrics, ACTUAL fault alarms and REPEATABLE recovery. None of them can be produced
offline, so this module is a checklist of MISSING evidence, never a verdict:

* ``SlotKind`` lists the evidence slots; every slot is ``NOT_RUN`` unless a well-formed ``OperatorEvidenceRef``
  (slot, reference id, digest, environment label, head) for exactly the asked head is supplied, in which case
  the slot becomes ``EVIDENCE_RECEIVED_UNVERIFIED``. The artifact itself is never read or validated here.
* ``ReadinessReport`` has no field or method that expresses a passed gate; its text states the NOT_RUN set.
* The facade adds no decision rule of its own. Hostile input (wrong types, subclasses, forged instances) never
  raises; it leaves the slots ``NOT_RUN`` or yields a fixed ``OpsRefusal``.

Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .comparison_snapshot import canonical_digest
from .ops_types import (
    AUTHORITY,
    OpsReason,
    OpsRefusal,
    is_digest,
    is_exact_str,
    is_identity_text,
    ops_refusal,
)

__all__ = [
    "EVIDENCE_PER_SLOT_MAX", "OperatorEvidenceRef", "ReadinessReport", "SlotKind", "SlotResult", "SlotStatus",
    "build_readiness",
]

EVIDENCE_PER_SLOT_MAX: Final = 64
_MAX_REFS: Final = 1024
_HEAD: Final = re.compile(r"[a-f0-9]{7,64}")


class SlotKind(StrEnum):
    WORKLOAD_METRICS_PER_GRID_CELL = "WORKLOAD_METRICS_PER_GRID_CELL"
    FAULT_ALARMS_FIRED_AND_RECOVERED_ON_STAGING = "FAULT_ALARMS_FIRED_AND_RECOVERED_ON_STAGING"
    REPEATABLE_RESTORE_REHEARSAL = "REPEATABLE_RESTORE_REHEARSAL"
    MIGRATION_REHEARSAL_ON_COPY = "MIGRATION_REHEARSAL_ON_COPY"
    R1_SHADOW_REGRESSION_ON_STAGING = "R1_SHADOW_REGRESSION_ON_STAGING"
    RETENTION_AND_HOLD_POLICY_APPROVAL = "RETENTION_AND_HOLD_POLICY_APPROVAL"


class SlotStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    EVIDENCE_RECEIVED_UNVERIFIED = "EVIDENCE_RECEIVED_UNVERIFIED"


assert {s.value for s in SlotStatus} <= {r.value for r in OpsReason}  # the codes live in the closed set


@dataclass(frozen=True, slots=True)
class OperatorEvidenceRef:
    slot: SlotKind
    ref_id: str
    digest: str
    environment: str
    head: str

    def __post_init__(self) -> None:
        if not _ref_ok(self.slot, self.ref_id, self.digest, self.environment, self.head):
            raise ValueError("EVIDENCE_REF_INVALID")

    def __repr__(self) -> str:
        return "OperatorEvidenceRef()"


def _ref_ok(slot: object, ref_id: object, digest: object, environment: object, head: object) -> bool:
    return (type(slot) is SlotKind and is_identity_text(ref_id) and is_digest(digest)
            and is_exact_str(environment, max_len=64) and is_identity_text(environment)
            and type(head) is str and _HEAD.fullmatch(head) is not None)


@dataclass(frozen=True, slots=True)
class SlotResult:
    slot: SlotKind
    status: SlotStatus
    evidence_digest: str | None  # digest of the supplied reference, never of an artifact that was read

    def __repr__(self) -> str:
        return f"SlotResult({self.slot.value}, {self.status.value})"


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    head: str
    slots: tuple[SlotResult, ...]
    not_run: tuple[SlotKind, ...]
    statement: str
    report_digest: str
    authority: str = AUTHORITY

    def __repr__(self) -> str:
        return f"ReadinessReport(not_run={len(self.not_run)})"


def _valid_ref(value: object, head: str) -> OperatorEvidenceRef | None:
    try:
        if type(value) is not OperatorEvidenceRef:
            return None
        slot, ref_id, digest = value.slot, value.ref_id, value.digest
        environment, ref_head = value.environment, value.head
        if not _ref_ok(slot, ref_id, digest, environment, ref_head) or ref_head != head:
            return None
        return OperatorEvidenceRef(slot, ref_id, digest, environment, ref_head)  # rebuilt: no forged instance
    except Exception:  # noqa: BLE001 - hostile/forged instance: simply not evidence
        return None


def build_readiness(evidence_refs: object, head: object, ids: object = None) -> ReadinessReport | OpsRefusal:
    """Checklist for ``head``. Never raises; never expresses a passed gate."""
    try:
        if type(head) is not str or _HEAD.fullmatch(head) is None:
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        if evidence_refs is None:
            refs: tuple[object, ...] = ()
        elif type(evidence_refs) in (tuple, list) and len(evidence_refs) <= _MAX_REFS:
            refs = tuple(evidence_refs)  # one snapshot; the caller's container is never read again
        else:
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        best: dict[SlotKind, str] = {}
        for item in refs:
            ref = _valid_ref(item, head)
            if ref is None:
                continue
            token = canonical_digest({"slot": ref.slot.value, "ref": ref.ref_id, "digest": ref.digest,
                                      "environment": ref.environment, "head": ref.head})
            if ref.slot not in best or token < best[ref.slot]:  # deterministic choice, order independent
                best[ref.slot] = token
        results = tuple(
            SlotResult(kind, SlotStatus.EVIDENCE_RECEIVED_UNVERIFIED, best[kind]) if kind in best
            else SlotResult(kind, SlotStatus.NOT_RUN, None)
            for kind in SlotKind)
        not_run = tuple(r.slot for r in results if r.status is SlotStatus.NOT_RUN)
        statement = ("G6-pre is NOT PASSED and cannot be evaluated offline. NOT_RUN: "
                     + ", ".join(k.value for k in not_run) if not_run else
                     "G6-pre is NOT PASSED: evidence references were received but are UNVERIFIED by this package.")
        digest = canonical_digest({"head": head, "slots": [(r.slot.value, r.status.value, r.evidence_digest)
                                                            for r in results], "authority": AUTHORITY})
        return ReadinessReport(head, results, not_run, statement, digest)
    except Exception:  # noqa: BLE001 - public boundary: fixed refusal
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)
