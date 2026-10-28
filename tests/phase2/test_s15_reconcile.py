"""S15 epic E15-4: bidirectional ledger<->1C check (R-c), triggers, apply gate, no resend.

Delivered against fakes (S12/S13 not accepted); no real ledger or real 1C is exercised here.
"""
from __future__ import annotations

import pytest

from erp_mcp_s15.labels import LABEL_MACHINE_VERIFIED
from erp_mcp_s15.reconcile import (
    ApplyBlockedError,
    ApplyGate,
    LedgerChange,
    LedgerListing,
    OneCDocument,
    OneCListing,
    ReconcileStatus,
    ReconciliationRunner,
    Trigger,
    reconcile,
)

C = ReconcileStatus
APPLIED, UNKNOWN, PENDING = "APPLIED", "UNKNOWN_OUTCOME", "PENDING"


def change(cid: str, status: str = APPLIED, h: str | None = None) -> LedgerChange:
    return LedgerChange(cid, h or f"hash-{cid}", status)


def doc(cid: str | None, ref: str | None = None, *, marker: str | None = "same",
        content: str | None = "same") -> OneCDocument:
    """A 1C document; marker/content default to the ledger hash of the same change id."""
    h = f"hash-{cid}"
    return OneCDocument(ref or f"ref-{cid}", cid, h if marker == "same" else marker,
                        h if content == "same" else content)


class FakeLedger:
    def __init__(self, changes=(), complete=True, error=None, payload=None):
        self.changes = list(changes)
        self.complete = complete
        self.error = error
        self.payload = payload
        self.list_calls = 0

    def list_changes(self):
        self.list_calls += 1
        if self.error:
            raise self.error
        if self.payload is not None:
            return self.payload
        return LedgerListing(self.complete, tuple(self.changes))


class FakeOneC:
    """Read port; every attribute outside the read port is recorded as an unexpected call."""

    def __init__(self, docs=(), complete=True, list_error=None, find_error=None, payload=None):
        self.docs = list(docs)
        self.complete = complete
        self.list_error = list_error
        self.find_error = find_error
        self.payload = payload
        self.list_calls = 0
        self.find_calls: list[str] = []
        self.writes: list[str] = []
        self.unexpected: list[str] = []

    def list_documents(self):
        self.list_calls += 1
        if self.list_error:
            raise self.list_error
        if self.payload is not None:
            return self.payload
        return OneCListing(self.complete, tuple(self.docs))

    def find_by_change_id(self, change_id):
        self.find_calls.append(change_id)
        if self.find_error:
            raise self.find_error
        return next((d for d in self.docs if d.change_id == change_id), None)

    def __getattr__(self, name):  # only reached for attributes that do not exist
        if name.startswith("__"):
            raise AttributeError(name)

        def recorder(*args, **kwargs):
            self.unexpected.append(name)
            self.writes.append(name)
        return recorder


def kinds(report):
    return sorted(f.kind for f in report.findings)


def run_reconcile(ledger, onec, trigger=Trigger.STARTUP):
    return reconcile(trigger, ledger, onec)


# --- clean state and labels ----------------------------------------------------------------------

def test_consistent_ledger_and_1c_is_clean_with_label():
    report = run_reconcile(FakeLedger([change("c1"), change("c2")]),
                           FakeOneC([doc("c1"), doc("c2")]))
    assert report.status is C.CLEAN
    assert report.findings == () and report.unknown_outcomes == ()
    assert report.label == LABEL_MACHINE_VERIFIED


def test_empty_ledger_and_empty_1c_is_clean():
    assert run_reconcile(FakeLedger(), FakeOneC()).status is C.CLEAN


def test_pending_change_without_document_is_not_a_finding():
    report = run_reconcile(FakeLedger([change("c1", PENDING)]), FakeOneC())
    assert report.status is C.CLEAN


# --- assertion 1: ledger -> 1C ---------------------------------------------------------------------

def test_applied_ledger_change_without_document_is_reported():
    report = run_reconcile(FakeLedger([change("c1"), change("c2")]), FakeOneC([doc("c1")]))
    assert report.status is C.DIRTY
    assert [(f.kind, f.change_id) for f in report.findings] == [("LEDGER_MISSING_IN_1C", "c2")]


# --- assertion 2: 1C -> ledger -----------------------------------------------------------------------

def test_document_without_marker_is_reported_as_unmarked():
    report = run_reconcile(FakeLedger([change("c1")]),
                           FakeOneC([doc("c1"), doc(None, "ref-plain", marker=None)]))
    assert report.status is C.DIRTY
    assert [(f.kind, f.document_ref) for f in report.findings] == [
        ("UNMARKED_DOCUMENT", "ref-plain")]


def test_document_with_change_id_but_no_marker_hash_is_unmarked_and_ledger_side_missing():
    report = run_reconcile(FakeLedger([change("c1")]),
                           FakeOneC([doc("c1", marker=None)]))
    assert report.status is C.DIRTY
    assert kinds(report) == ["LEDGER_MISSING_IN_1C", "UNMARKED_DOCUMENT"]


def test_edit_with_unchanged_marker_but_changed_content_hash_is_detected():
    report = run_reconcile(FakeLedger([change("c1")]),
                           FakeOneC([doc("c1", content="tampered")]))
    assert report.status is C.DIRTY
    assert [(f.kind, f.change_id) for f in report.findings] == [("CONTENT_CHANGED", "c1")]


def test_marker_hash_differing_from_the_ledger_is_detected():
    report = run_reconcile(FakeLedger([change("c1")]),
                           FakeOneC([doc("c1", marker="forged", content="forged")]))
    assert report.status is C.DIRTY
    assert kinds(report) == ["MARKER_HASH_MISMATCH"]


def test_marker_of_a_change_the_ledger_does_not_know_is_an_orphan():
    report = run_reconcile(FakeLedger([change("c1")]), FakeOneC([doc("c1"), doc("c7")]))
    assert report.status is C.DIRTY
    assert [(f.kind, f.change_id) for f in report.findings] == [("ORPHAN_MARKER", "c7")]


def test_two_documents_with_one_change_id_are_a_duplicate_marker():
    report = run_reconcile(FakeLedger([change("c1")]),
                           FakeOneC([doc("c1", "ref-a"), doc("c1", "ref-b")]))
    assert report.status is C.DIRTY
    assert kinds(report) == ["DUPLICATE_MARKER"]


def test_drift_is_detected_in_both_directions_in_one_pass():
    report = run_reconcile(FakeLedger([change("c1"), change("c2")]),
                           FakeOneC([doc("c1", content="x"), doc("c9")]))
    assert kinds(report) == ["CONTENT_CHANGED", "LEDGER_MISSING_IN_1C", "ORPHAN_MARKER"]


# --- incomplete or failed reads fail closed -----------------------------------------------------------

@pytest.mark.parametrize("ledger,onec", [
    (FakeLedger([change("c1")], complete=False), FakeOneC([doc("c1")])),
    (FakeLedger([change("c1")]), FakeOneC([doc("c1")], complete=False)),
    (FakeLedger(error=RuntimeError("db")), FakeOneC()),
    (FakeLedger(), FakeOneC(list_error=TimeoutError())),
    (FakeLedger(payload="rows"), FakeOneC()),
    (FakeLedger(), FakeOneC(payload=object())),
], ids=["ledger_partial", "1c_partial", "ledger_error", "1c_error", "ledger_garbage",
        "1c_garbage"])
def test_incomplete_or_failed_listing_is_inconclusive_never_clean(ledger, onec):
    report = run_reconcile(ledger, onec)
    assert report.status is C.INCONCLUSIVE
    assert report.status is not C.CLEAN
    assert report.findings == ()


def test_partial_listing_with_drift_is_inconclusive_not_dirty_or_clean():
    report = run_reconcile(FakeLedger([change("c1")]), FakeOneC([], complete=False))
    assert report.status is C.INCONCLUSIVE


# --- assertion 5: unknown outcome, classified by marker lookup, no resend ---------------------------------

def test_unknown_outcome_with_a_marked_document_is_found_by_marker_and_nothing_is_written():
    onec = FakeOneC([doc("c9")])
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), onec)
    assert report.status is C.CLEAN
    assert report.unknown_outcomes == (("c9", "FOUND_BY_MARKER"),)
    assert onec.find_calls == ["c9"]
    assert onec.writes == [] and onec.unexpected == []


def test_unknown_outcome_without_a_document_is_unresolved_and_nothing_is_resent():
    onec = FakeOneC([])
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), onec)
    assert report.status is C.DIRTY
    assert report.unknown_outcomes == (("c9", "NOT_FOUND_BY_MARKER"),)
    assert [f.kind for f in report.findings] == ["UNRESOLVED_UNKNOWN_OUTCOME"]
    assert onec.find_calls == ["c9"]
    assert onec.writes == [] and onec.unexpected == []


def test_unknown_outcome_lookup_failure_is_inconclusive_and_not_evidence_of_absence():
    onec = FakeOneC([], find_error=RuntimeError("com"))
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), onec)
    assert report.status is C.INCONCLUSIVE
    assert report.unknown_outcomes == (("c9", "LOOKUP_FAILED"),)
    assert report.findings == ()
    assert onec.writes == [] and onec.unexpected == []


def test_dirty_finding_outranks_a_failed_unknown_lookup():
    onec = FakeOneC([doc("c7")], find_error=RuntimeError("com"))
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), onec)
    assert report.status is C.DIRTY
    assert report.unknown_outcomes == (("c9", "LOOKUP_FAILED"),)


def test_unknown_outcome_is_not_also_reported_as_missing_in_1c():
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), FakeOneC([]))
    assert "LEDGER_MISSING_IN_1C" not in kinds(report)


def test_only_unknown_outcome_changes_trigger_a_marker_lookup():
    onec = FakeOneC([doc("c1"), doc("c9")])
    run_reconcile(FakeLedger([change("c1"), change("c9", UNKNOWN), change("c3", PENDING)]),
                  onec)
    assert onec.find_calls == ["c9"]


def test_repeating_the_check_never_writes_and_gives_the_same_report():
    onec = FakeOneC([])
    ledger = FakeLedger([change("c9", UNKNOWN)])
    first = run_reconcile(ledger, onec)
    second = run_reconcile(ledger, onec)
    assert first == second
    assert onec.writes == [] and onec.unexpected == []


# --- assertion 3: three triggers each produce a run ----------------------------------------------------------

def make_runner(ledger, onec, enabled=True, interval=60.0):
    flag = {"on": enabled}
    gate = ApplyGate(lambda: flag["on"])
    return ReconciliationRunner(ledger, onec, gate, interval), gate, flag


def test_startup_trigger_runs_one_check_and_reports_its_trigger():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, _, _ = make_runner(ledger, onec)
    report = runner.run(Trigger.STARTUP)
    assert (ledger.list_calls, onec.list_calls) == (1, 1)
    assert report.trigger is Trigger.STARTUP and report.status is C.CLEAN


def test_after_restore_trigger_runs_one_check_and_reports_its_trigger():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, _, _ = make_runner(ledger, onec)
    report = runner.run(Trigger.AFTER_RESTORE)
    assert (ledger.list_calls, onec.list_calls) == (1, 1)
    assert report.trigger is Trigger.AFTER_RESTORE


def test_periodic_trigger_runs_one_check_and_reports_its_trigger():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, _, _ = make_runner(ledger, onec)
    report = runner.tick(1000.0)
    assert report is not None
    assert (ledger.list_calls, onec.list_calls) == (1, 1)
    assert report.trigger is Trigger.PERIODIC


def test_periodic_tick_runs_only_when_the_interval_has_elapsed():
    ledger, onec = FakeLedger(), FakeOneC()
    runner, _, _ = make_runner(ledger, onec, interval=10.0)
    assert runner.tick(100.0) is not None and ledger.list_calls == 1
    assert runner.tick(105.0) is None and ledger.list_calls == 1
    assert runner.tick(109.999) is None and ledger.list_calls == 1
    assert runner.tick(110.0) is not None and ledger.list_calls == 2
    assert runner.tick(111.0) is None and ledger.list_calls == 2


def test_a_startup_run_with_a_clock_value_defers_the_first_periodic_run():
    ledger, onec = FakeLedger(), FakeOneC()
    runner, _, _ = make_runner(ledger, onec, interval=10.0)
    runner.run(Trigger.STARTUP, now=50.0)
    assert runner.tick(55.0) is None
    assert runner.tick(60.0) is not None
    assert ledger.list_calls == 2


def test_every_trigger_run_reads_both_sides_afresh():
    ledger, onec = FakeLedger(), FakeOneC()
    runner, _, _ = make_runner(ledger, onec, interval=1.0)
    runner.run(Trigger.STARTUP, now=0.0)
    runner.run(Trigger.AFTER_RESTORE, now=0.0)
    runner.tick(5.0)
    assert (ledger.list_calls, onec.list_calls) == (3, 3)


@pytest.mark.parametrize("interval", [0, -1, -0.5, float("nan")])
def test_runner_rejects_a_non_positive_interval(interval):
    with pytest.raises(ValueError, match="RECONCILE_INTERVAL_INVALID"):
        ReconciliationRunner(FakeLedger(), FakeOneC(), ApplyGate(lambda: True), interval)


# --- assertion 4: skew after restore blocks applies until clean ------------------------------------------------

def test_gate_starts_blocked_when_the_writer_is_enabled_and_a_clean_run_unblocks_it():
    runner, gate, _ = make_runner(FakeLedger([change("c1")]), FakeOneC([doc("c1")]))
    assert gate.applies_blocked() is True
    with pytest.raises(ApplyBlockedError, match="RECONCILIATION_NOT_CLEAN"):
        gate.ensure_apply_allowed()
    runner.run(Trigger.STARTUP)
    assert gate.applies_blocked() is False
    gate.ensure_apply_allowed()  # does not raise


def test_ledger_older_than_1c_after_restore_blocks_applies_until_clean():
    ledger = FakeLedger([change("c1")])  # restored: the newer change c2 is gone
    onec = FakeOneC([doc("c1"), doc("c2")])
    runner, gate, _ = make_runner(ledger, onec)
    runner.run(Trigger.STARTUP)  # not clean either
    report = runner.run(Trigger.AFTER_RESTORE)
    assert report.status is C.DIRTY and kinds(report) == ["ORPHAN_MARKER"]
    with pytest.raises(ApplyBlockedError):
        gate.ensure_apply_allowed()
    # Periodic checks keep it blocked while the skew remains.
    assert runner.run(Trigger.PERIODIC).status is C.DIRTY
    assert gate.applies_blocked() is True
    # Heal the ledger (the chain catches up) and the next run unblocks.
    ledger.changes.append(change("c2"))
    assert runner.run(Trigger.PERIODIC).status is C.CLEAN
    assert gate.applies_blocked() is False
    gate.ensure_apply_allowed()


def test_ledger_newer_than_1c_after_restore_blocks_applies_until_clean():
    ledger = FakeLedger([change("c1"), change("c2")])
    onec = FakeOneC([doc("c1")])  # 1C restored to an older state
    runner, gate, _ = make_runner(ledger, onec)
    report = runner.run(Trigger.AFTER_RESTORE)
    assert kinds(report) == ["LEDGER_MISSING_IN_1C"]
    assert gate.applies_blocked() is True
    onec.docs.append(doc("c2"))
    runner.run(Trigger.PERIODIC)
    assert gate.applies_blocked() is False


def test_restore_re_blocks_a_gate_that_was_clean():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, gate, _ = make_runner(ledger, onec)
    runner.run(Trigger.STARTUP)
    assert gate.applies_blocked() is False
    gate.mark_restore()
    assert gate.applies_blocked() is True
    runner.run(Trigger.PERIODIC)
    assert gate.applies_blocked() is False


def test_after_restore_run_that_cannot_complete_keeps_applies_blocked():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, gate, _ = make_runner(ledger, onec)
    runner.run(Trigger.STARTUP)
    assert gate.applies_blocked() is False
    ledger.error = RuntimeError("ledger offline")
    report = runner.run(Trigger.AFTER_RESTORE)
    assert report.status is C.INCONCLUSIVE
    assert gate.applies_blocked() is True


@pytest.mark.parametrize("make_report_state", ["dirty", "inconclusive"])
def test_only_a_clean_report_unblocks(make_report_state):
    ledger = FakeLedger([change("c1")])
    onec = FakeOneC([] if make_report_state == "dirty" else [doc("c1")],
                    complete=make_report_state == "dirty")
    runner, gate, _ = make_runner(ledger, onec)
    report = runner.run(Trigger.STARTUP)
    assert report.status is (C.DIRTY if make_report_state == "dirty" else C.INCONCLUSIVE)
    assert gate.applies_blocked() is True


# --- assertion 6: gate inert while the writer is disabled ---------------------------------------------------------

@pytest.mark.parametrize("trigger", list(Trigger))
def test_dirty_reconciliation_does_not_block_while_the_writer_is_disabled(trigger):
    ledger = FakeLedger([change("c1")])  # applied, but 1C has nothing: DIRTY
    runner, gate, _ = make_runner(ledger, FakeOneC([]), enabled=False)
    report = runner.run(trigger)
    assert report.status is C.DIRTY
    assert gate.applies_blocked() is False
    gate.ensure_apply_allowed()  # no refusal


def test_fresh_gate_with_writer_disabled_is_not_blocked_and_never_raises():
    gate = ApplyGate(lambda: False)
    assert gate.applies_blocked() is False
    gate.ensure_apply_allowed()
    gate.mark_restore()
    gate.ensure_apply_allowed()


def test_state_recorded_while_disabled_takes_effect_once_the_writer_is_enabled():
    runner, gate, flag = make_runner(FakeLedger([change("c1")]), FakeOneC([]), enabled=False)
    runner.run(Trigger.STARTUP)
    gate.ensure_apply_allowed()
    flag["on"] = True
    with pytest.raises(ApplyBlockedError):
        gate.ensure_apply_allowed()


def test_the_check_itself_never_raises_the_apply_refusal_even_when_dirty_and_enabled():
    # Non-write paths (reads, reconciliation itself) must not see the apply refusal.
    runner, _, _ = make_runner(FakeLedger([change("c1")]), FakeOneC([]), enabled=True)
    assert runner.run(Trigger.STARTUP).status is C.DIRTY
    assert runner.run(Trigger.AFTER_RESTORE).status is C.DIRTY
    assert runner.tick(10_000.0).status is C.DIRTY


def test_writer_enabled_callable_is_consulted_live_and_truthiness_is_coerced():
    values = iter([0, 1])
    gate = ApplyGate(lambda: next(values))
    assert gate.applies_blocked() is False  # 0 -> disabled
    assert gate.applies_blocked() is True  # 1 -> enabled and still blocked
