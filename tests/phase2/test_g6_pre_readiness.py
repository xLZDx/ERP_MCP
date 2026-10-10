"""S9 E5: the G6-pre readiness checklist can never express a passed gate. Offline."""
from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from business_ai_gateway.phase2.g6_pre_readiness import (
    OperatorEvidenceRef,
    ReadinessReport,
    SlotKind,
    SlotStatus,
    build_readiness,
)
from business_ai_gateway.phase2.ops_types import FakeCorrelationSource, OpsReason, OpsRefusal

HEAD = "a" * 40
DIGEST = "b" * 64


def ref(slot=SlotKind.REPEATABLE_RESTORE_REHEARSAL, head=HEAD, ref_id="REF-1", env="staging-1"):
    return OperatorEvidenceRef(slot, ref_id, DIGEST, env, head)


def test_every_slot_is_not_run_without_evidence():
    report = build_readiness((), HEAD)
    assert type(report) is ReadinessReport
    assert [r.status for r in report.slots] == [SlotStatus.NOT_RUN] * len(SlotKind)
    assert set(report.not_run) == set(SlotKind)
    for kind in SlotKind:
        assert kind.value in report.statement
    assert "NOT PASSED" in report.statement


def test_none_is_the_same_as_no_evidence():
    assert build_readiness(None, HEAD).not_run == build_readiness((), HEAD).not_run


def test_a_well_formed_reference_only_changes_its_own_slot_to_unverified():
    report = build_readiness([ref()], HEAD)
    by_slot = {r.slot: r.status for r in report.slots}
    assert by_slot[SlotKind.REPEATABLE_RESTORE_REHEARSAL] is SlotStatus.EVIDENCE_RECEIVED_UNVERIFIED
    assert SlotKind.REPEATABLE_RESTORE_REHEARSAL not in report.not_run
    assert len(report.not_run) == len(SlotKind) - 1


def test_all_slots_with_evidence_is_still_not_a_passed_gate():
    refs = [ref(slot=k, ref_id=f"R-{i}") for i, k in enumerate(SlotKind)]
    report = build_readiness(refs, HEAD)
    assert report.not_run == ()
    assert "NOT PASSED" in report.statement and "UNVERIFIED" in report.statement


def test_a_reference_for_another_head_leaves_the_slot_not_run():
    report = build_readiness([ref(head="c" * 40)], HEAD)
    assert set(report.not_run) == set(SlotKind)


@pytest.mark.parametrize("bad", [None, "x", 3, object(), (SlotKind.REPEATABLE_RESTORE_REHEARSAL,)])
def test_junk_items_are_ignored_and_never_raise(bad):
    report = build_readiness([bad, ref()], HEAD)
    assert type(report) is ReadinessReport
    assert SlotKind.REPEATABLE_RESTORE_REHEARSAL not in report.not_run


def test_a_forged_reference_is_not_evidence():
    forged = object.__new__(OperatorEvidenceRef)
    report = build_readiness([forged], HEAD)
    assert set(report.not_run) == set(SlotKind)


def test_a_subclass_reference_is_not_evidence():
    @dataclasses.dataclass(frozen=True)
    class Sub(OperatorEvidenceRef):
        pass

    try:
        sub = Sub(SlotKind.REPEATABLE_RESTORE_REHEARSAL, "R", DIGEST, "env", HEAD)
    except Exception:  # noqa: BLE001 - slots dataclass subclassing may be refused outright
        return
    assert set(build_readiness([sub], HEAD).not_run) == set(SlotKind)


@pytest.mark.parametrize("fields", [
    ("REPEATABLE_RESTORE_REHEARSAL", "R", DIGEST, "env", HEAD),
    (SlotKind.REPEATABLE_RESTORE_REHEARSAL, "", DIGEST, "env", HEAD),
    (SlotKind.REPEATABLE_RESTORE_REHEARSAL, "R", "short", "env", HEAD),
    (SlotKind.REPEATABLE_RESTORE_REHEARSAL, "R", DIGEST, "", HEAD),
    (SlotKind.REPEATABLE_RESTORE_REHEARSAL, "R", DIGEST, "env", "NOT-HEX"),
    (SlotKind.REPEATABLE_RESTORE_REHEARSAL, "R\x00", DIGEST, "env", HEAD),
    (SlotKind.REPEATABLE_RESTORE_REHEARSAL, True, DIGEST, "env", HEAD),
])
def test_malformed_references_are_refused_at_construction(fields):
    with pytest.raises(ValueError, match="EVIDENCE_REF_INVALID"):
        OperatorEvidenceRef(*fields)


@pytest.mark.parametrize("head", [None, "", "XYZ", 5, "a" * 6, "A" * 40])
def test_a_bad_head_is_a_fixed_refusal(head):
    out = build_readiness((), head, FakeCorrelationSource())
    assert type(out) is OpsRefusal and out.reason is OpsReason.INPUT_INVALID


@pytest.mark.parametrize("bad", ["abc", 7, {"a": 1}, object()])
def test_a_non_sequence_container_is_a_fixed_refusal(bad):
    out = build_readiness(bad, HEAD, FakeCorrelationSource())
    assert type(out) is OpsRefusal and out.reason is OpsReason.INPUT_INVALID


def test_the_report_has_no_passed_field_and_is_evaluation_only():
    names = {f.name for f in dataclasses.fields(ReadinessReport)}
    assert not any("pass" in n or "proven" in n or "ok" == n for n in names)
    assert not any(a.startswith(("passed", "is_passed", "g6_pre_passed")) for a in dir(ReadinessReport))
    assert build_readiness((), HEAD).authority == "EVALUATION_ONLY"


def test_digest_is_stable_and_order_independent():
    a = build_readiness([ref(ref_id="R-1"), ref(slot=SlotKind.MIGRATION_REHEARSAL_ON_COPY, ref_id="R-2")], HEAD)
    b = build_readiness([ref(slot=SlotKind.MIGRATION_REHEARSAL_ON_COPY, ref_id="R-2"), ref(ref_id="R-1")], HEAD)
    assert a.report_digest == b.report_digest and a == b
    assert a.report_digest != build_readiness((), HEAD).report_digest


def test_repr_never_contains_input_text():
    report = build_readiness([ref(ref_id="SECRET-REF-TEXT", env="secret-env")], HEAD)
    text = repr(report) + repr(report.slots) + repr(ref(ref_id="SECRET-REF-TEXT"))
    assert "SECRET-REF-TEXT" not in text and "secret-env" not in text
    assert datetime  # keep the import used for hostile-type parametrization below


def test_too_many_references_are_refused():
    out = build_readiness([ref()] * 2000, HEAD, FakeCorrelationSource())
    assert type(out) is OpsRefusal
