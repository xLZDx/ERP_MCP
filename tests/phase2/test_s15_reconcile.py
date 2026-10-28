"""S15 epic E15-4: bidirectional ledger<->1C check (R-c), triggers, apply gate, no resend.

Delivered against fakes (S12/S13 not accepted); no real ledger or real 1C is exercised here.
Covers the CR-388 behaviour: closed status set, restore epoch, CLEAN expiry, strict-bool writer
flag, serialized runs, injected clock, retry interval, status accessor and the lookup cap.
"""
from __future__ import annotations

import logging
import threading
import time

import pytest

from erp_mcp_s15 import reconcile as reconcile_module
from erp_mcp_s15.labels import LABEL_MACHINE_VERIFIED
from erp_mcp_s15.reconcile import (
    ApplyBlockedError,
    ApplyGate,
    LedgerChange,
    LedgerListing,
    OneCDocument,
    OneCListing,
    ReconcileStatus,
    ReconciliationReport,
    ReconciliationRunner,
    Trigger,
    reconcile,
)

C = ReconcileStatus
APPLIED, UNKNOWN, PENDING = "APPLIED", "UNKNOWN_OUTCOME", "PENDING"
CLEAN_REPORT = ReconciliationReport(Trigger.STARTUP, ReconcileStatus.CLEAN)
DIRTY_REPORT = ReconciliationReport(Trigger.STARTUP, ReconcileStatus.DIRTY)


class Clock:
    """Injected monotonic clock; tests move it explicitly (forwards and backwards)."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.002)
    return predicate()


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
        self.on_list = None  # optional hook run at the start of every listing

    def list_changes(self):
        if self.on_list is not None:
            self.on_list()
        self.list_calls += 1
        if self.error:
            raise self.error
        if self.payload is not None:
            return self.payload
        return LedgerListing(self.complete, tuple(self.changes))


class BlockingLedger(FakeLedger):
    """The next listing after ``arm()`` parks until ``release`` is set (a run in flight)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entered = threading.Event()
        self.release = threading.Event()
        self._armed = False

    def arm(self):
        self._armed = True

    def list_changes(self):
        if self._armed:
            self._armed = False
            self.entered.set()
            self.release.wait(5.0)
        return super().list_changes()


class FakeOneC:
    """Read port; every attribute outside the read port is recorded as an unexpected call."""

    def __init__(self, docs=(), complete=True, list_error=None, find_error=None, payload=None,
                 find_docs=None, find_payload=None):
        self.docs = list(docs)
        self.find_docs = find_docs  # what the marker lookup sees when it differs from the listing
        self.find_payload = find_payload  # raw lookup result (overrides everything)
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
        if self.find_payload is not None:
            return self.find_payload
        source = self.docs if self.find_docs is None else self.find_docs
        return next((d for d in source if d.change_id == change_id), None)

    def __getattr__(self, name):  # only reached for attributes that do not exist
        if name.startswith("__"):
            raise AttributeError(name)

        def recorder(*args, **kwargs):
            self.unexpected.append(name)
            self.writes.append(name)
        return recorder


def kinds(report):
    return sorted(f.kind for f in report.findings)


def run_reconcile(ledger, onec, trigger=Trigger.STARTUP, **kw):
    return reconcile(trigger, ledger, onec, **kw)


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


# --- CR-388: closed status set, state skew, duplicates, empty hashes ------------------------------

def test_pending_change_with_a_marked_document_is_dirty_state_skew():
    report = run_reconcile(FakeLedger([change("c1", PENDING)]), FakeOneC([doc("c1")]))
    assert report.status is C.DIRTY
    assert [(f.kind, f.change_id, f.document_ref) for f in report.findings] == [
        ("LEDGER_STATE_SKEW", "c1", "ref-c1")]


@pytest.mark.parametrize("status", ["BOGUS", "applied", "Applied", "", "DONE", "APPLIED "])
def test_status_outside_the_closed_set_is_dirty_and_never_clean(status):
    onec = FakeOneC([doc("c1")])
    report = run_reconcile(FakeLedger([change("c1", status)]), onec)
    assert report.status is C.DIRTY
    assert report.status is not C.CLEAN
    assert kinds(report) == ["UNKNOWN_LEDGER_STATUS"]
    assert onec.find_calls == []  # an unknown status is never treated as UNKNOWN_OUTCOME


def test_unknown_status_without_a_document_is_not_also_reported_as_missing():
    report = run_reconcile(FakeLedger([change("c1", "BOGUS")]), FakeOneC())
    assert kinds(report) == ["UNKNOWN_LEDGER_STATUS"]


def test_non_text_status_is_a_malformed_element():
    report = run_reconcile(FakeLedger([LedgerChange("c1", "h", None)]), FakeOneC())
    assert report.status is C.INCONCLUSIVE and report.reason == "MALFORMED_ELEMENT"


def test_duplicate_ledger_change_ids_are_dirty():
    report = run_reconcile(FakeLedger([change("c1"), change("c1")]), FakeOneC([doc("c1")]))
    assert report.status is C.DIRTY
    assert kinds(report) == ["DUPLICATE_LEDGER_CHANGE"]
    assert [f.change_id for f in report.findings] == ["c1"]


def test_three_rows_with_one_id_give_one_duplicate_finding_and_other_ids_are_unaffected():
    ledger = FakeLedger([change("c1"), change("c1"), change("c1"), change("c2")])
    report = run_reconcile(ledger, FakeOneC([doc("c1"), doc("c2")]))
    assert [(f.kind, f.change_id) for f in report.findings] == [("DUPLICATE_LEDGER_CHANGE", "c1")]


def test_duplicate_ledger_ids_with_different_hashes_are_dirty_not_resolved_by_the_first_row():
    ledger = FakeLedger([change("c1"), LedgerChange("c1", "other-hash", APPLIED)])
    report = run_reconcile(ledger, FakeOneC([doc("c1")]))
    assert report.status is C.DIRTY
    assert "DUPLICATE_LEDGER_CHANGE" in kinds(report)


def test_empty_ledger_hash_is_dirty_even_when_the_document_looks_fine():
    report = run_reconcile(FakeLedger([LedgerChange("c1", "", APPLIED)]), FakeOneC([doc("c1")]))
    assert report.status is C.DIRTY
    assert kinds(report) == ["EMPTY_LEDGER_HASH"]


def test_empty_ledger_hash_never_matches_an_empty_marker_and_empty_content():
    unmarked = OneCDocument("ref-c1", "c1", "", "")
    report = run_reconcile(FakeLedger([LedgerChange("c1", "", APPLIED)]), FakeOneC([unmarked]))
    assert report.status is C.DIRTY
    assert kinds(report) == ["EMPTY_LEDGER_HASH", "LEDGER_MISSING_IN_1C", "UNMARKED_DOCUMENT"]


@pytest.mark.parametrize("cid,marker", [("", "h"), ("c1", ""), ("", ""), (None, "h"), ("c1", None)],
                         ids=["empty_id", "empty_marker", "both_empty", "none_id", "none_marker"])
def test_empty_string_markers_count_as_unmarked_exactly_like_none(cid, marker):
    d = OneCDocument("ref-x", cid, marker, "h")
    report = run_reconcile(FakeLedger(), FakeOneC([d]))
    assert report.status is C.DIRTY
    assert [(f.kind, f.change_id, f.document_ref) for f in report.findings] == [
        ("UNMARKED_DOCUMENT", None, "ref-x")]


def test_empty_ledger_change_id_is_malformed_not_matched_to_unmarked_documents():
    report = run_reconcile(FakeLedger([LedgerChange("", "h", APPLIED)]),
                           FakeOneC([OneCDocument("r", "", "h", "h")]))
    assert report.status is C.INCONCLUSIVE and report.reason == "MALFORMED_ELEMENT"


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

@pytest.mark.parametrize("ledger,onec,reason", [
    (FakeLedger([change("c1")], complete=False), FakeOneC([doc("c1")]), "LISTING_INCOMPLETE"),
    (FakeLedger([change("c1")]), FakeOneC([doc("c1")], complete=False), "LISTING_INCOMPLETE"),
    (FakeLedger(payload=LedgerListing(1, (change("c1"),))), FakeOneC([doc("c1")]),
     "LISTING_INCOMPLETE"),
    (FakeLedger(error=RuntimeError("db")), FakeOneC(), "PORT_ERROR:RuntimeError"),
    (FakeLedger(), FakeOneC(list_error=TimeoutError()), "PORT_ERROR:TimeoutError"),
    (FakeLedger(payload="rows"), FakeOneC(), "MALFORMED_ELEMENT"),
    (FakeLedger(), FakeOneC(payload=object()), "MALFORMED_ELEMENT"),
], ids=["ledger_partial", "1c_partial", "complete_not_literally_true", "ledger_error",
        "1c_error", "ledger_garbage", "1c_garbage"])
def test_incomplete_or_failed_listing_is_inconclusive_never_clean(ledger, onec, reason):
    report = run_reconcile(ledger, onec)
    assert report.status is C.INCONCLUSIVE
    assert report.status is not C.CLEAN
    assert report.findings == ()
    assert report.reason == reason


def test_partial_listing_with_drift_is_inconclusive_not_dirty_or_clean():
    report = run_reconcile(FakeLedger([change("c1")]), FakeOneC([], complete=False))
    assert report.status is C.INCONCLUSIVE


def test_a_clean_report_has_no_reason():
    assert run_reconcile(FakeLedger([change("c1")]), FakeOneC([doc("c1")])).reason == ""


def test_reason_names_the_exception_class_only_never_the_message():
    report = run_reconcile(FakeLedger(error=RuntimeError("secret-db-password")), FakeOneC())
    assert report.reason == "PORT_ERROR:RuntimeError"
    assert "secret-db-password" not in repr(report)


BAD_LEDGER_PAYLOADS = [
    LedgerListing(True, ("not-a-change",)),
    LedgerListing(True, ({"change_id": "c1"},)),
    LedgerListing(True, (LedgerChange("c1", "h", None),)),
    LedgerListing(True, (LedgerChange("c1", None, APPLIED),)),
    LedgerListing(True, (LedgerChange(7, "h", APPLIED),)),
    LedgerListing(True, (LedgerChange("", "h", APPLIED),)),
    LedgerListing(True, {change("c1")}),
    LedgerListing(True, None),
]
BAD_ONEC_PAYLOADS = [
    OneCListing(True, ("not-a-doc",)),
    OneCListing(True, (OneCDocument(1, "c1", "h", "h"),)),
    OneCListing(True, (OneCDocument("r", 5, "h", "h"),)),
    OneCListing(True, (OneCDocument("r", "c1", 5, "h"),)),
    OneCListing(True, (OneCDocument("r", "c1", "h", None),)),
    OneCListing(True, {doc("c1")}),
    OneCListing(True, None),
]


@pytest.mark.parametrize("payload", BAD_LEDGER_PAYLOADS,
                         ids=[f"ledger{i}" for i in range(len(BAD_LEDGER_PAYLOADS))])
def test_malformed_ledger_element_is_inconclusive_with_a_reason(payload):
    report = run_reconcile(FakeLedger(payload=payload), FakeOneC([doc("c1")]))
    assert report.status is C.INCONCLUSIVE
    assert report.reason == "MALFORMED_ELEMENT"
    assert report.findings == ()


@pytest.mark.parametrize("payload", BAD_ONEC_PAYLOADS,
                         ids=[f"onec{i}" for i in range(len(BAD_ONEC_PAYLOADS))])
def test_malformed_1c_element_is_inconclusive_with_a_reason(payload):
    report = run_reconcile(FakeLedger([change("c1")]), FakeOneC(payload=payload))
    assert report.status is C.INCONCLUSIVE
    assert report.reason == "MALFORMED_ELEMENT"
    assert report.findings == ()


def test_an_internal_failure_inside_the_check_is_inconclusive_with_the_exception_class():
    # A non-numeric lookup cap fails inside the comparison body; reconcile must not raise.
    report = reconcile(Trigger.STARTUP, FakeLedger([change("c9", UNKNOWN)]), FakeOneC([]),
                       max_unknown_lookups=None)  # type: ignore[arg-type]
    assert report.status is C.INCONCLUSIVE
    assert report.reason == "INTERNAL_ERROR:TypeError"


# --- assertion 5: unknown outcome, classified by marker lookup, no resend ---------------------------------

def test_unknown_outcome_with_a_marked_document_is_found_by_marker_but_stays_non_clean():
    onec = FakeOneC([doc("c9")])
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), onec)
    # The document exists but the ledger still says UNKNOWN_OUTCOME: not CLEAN until resolved.
    assert report.status is C.DIRTY
    assert report.status is not C.CLEAN
    assert report.unknown_outcomes == (("c9", "FOUND_BY_MARKER"),)
    assert [(f.kind, f.change_id, f.document_ref) for f in report.findings] == [
        ("NEEDS_LEDGER_RESOLUTION", "c9", "ref-c9")]
    assert onec.find_calls == ["c9"]
    assert onec.writes == [] and onec.unexpected == []


def test_found_by_marker_blocks_the_gate_until_the_ledger_records_the_resolution():
    ledger = FakeLedger([change("c9", UNKNOWN)])
    runner, gate, _ = make_runner(ledger, FakeOneC([doc("c9")]))
    assert runner.run(Trigger.STARTUP).status is C.DIRTY
    assert gate.applies_blocked() is True
    ledger.changes[0] = change("c9", APPLIED)  # the ledger catches up
    assert runner.run(Trigger.PERIODIC).status is C.CLEAN
    assert gate.applies_blocked() is False


def test_found_by_marker_but_missing_from_the_listing_is_checked_anyway():
    onec = FakeOneC([], find_docs=[doc("c9")])
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), onec)
    assert report.status is C.DIRTY
    assert kinds(report) == ["FOUND_NOT_IN_LISTING", "NEEDS_LEDGER_RESOLUTION"]
    assert report.unknown_outcomes == (("c9", "FOUND_BY_MARKER"),)


@pytest.mark.parametrize("found,extra_kind", [
    (doc("c9", marker="forged", content="forged"), "MARKER_HASH_MISMATCH"),
    (doc("c9", content="tampered"), "CONTENT_CHANGED"),
    (doc("c9", marker=None), "UNMARKED_DOCUMENT"),
    (doc("c9", marker=""), "UNMARKED_DOCUMENT"),
], ids=["forged_marker", "content_changed", "marker_none", "marker_empty"])
def test_document_found_only_by_marker_gets_the_same_checks_as_a_listed_one(found, extra_kind):
    onec = FakeOneC([], find_docs=[found])
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), onec)
    assert report.status is C.DIRTY
    assert kinds(report) == sorted(
        ["FOUND_NOT_IN_LISTING", "NEEDS_LEDGER_RESOLUTION", extra_kind])


def test_listed_document_for_an_unknown_outcome_with_a_wrong_hash_is_dirty_for_both_reasons():
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]),
                           FakeOneC([doc("c9", content="tampered")]))
    assert kinds(report) == ["CONTENT_CHANGED", "NEEDS_LEDGER_RESOLUTION"]


@pytest.mark.parametrize("payload", [
    OneCDocument("r", "other-id", "h", "h"),  # a different change id than asked for
    OneCDocument(5, "c9", "h", "h"), OneCDocument("r", "c9", 5, "h"),
    OneCDocument("r", "c9", "h", None), "a document", {"change_id": "c9"},
], ids=["wrong_id", "ref_int", "marker_int", "content_none", "text", "dict"])
def test_malformed_marker_lookup_result_is_a_failed_lookup_not_agreement(payload):
    onec = FakeOneC([], find_payload=payload)
    report = run_reconcile(FakeLedger([change("c9", UNKNOWN)]), onec)
    assert report.status is C.INCONCLUSIVE
    assert report.reason == "MALFORMED_ELEMENT"
    assert report.unknown_outcomes == (("c9", "LOOKUP_FAILED"),)
    assert onec.writes == []


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
    assert report.reason == "PORT_ERROR:RuntimeError"
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


# --- CR-388: lookup cap -----------------------------------------------------------------------------------

def unknown_rows(n):
    return [change(f"u{i}", UNKNOWN) for i in range(n)]


def test_more_unknown_outcomes_than_the_cap_is_inconclusive_and_stops_looking_up():
    onec = FakeOneC([])
    report = run_reconcile(FakeLedger(unknown_rows(3)), onec, max_unknown_lookups=2)
    assert report.status is C.INCONCLUSIVE
    assert report.reason == "LOOKUP_CAP_EXCEEDED"
    assert onec.find_calls == ["u0", "u1"]  # the third lookup was never made
    assert onec.writes == []


def test_exactly_the_cap_is_allowed():
    onec = FakeOneC([])
    report = run_reconcile(FakeLedger(unknown_rows(2)), onec, max_unknown_lookups=2)
    assert report.reason != "LOOKUP_CAP_EXCEEDED"
    assert report.status is C.DIRTY  # both unresolved
    assert len(onec.find_calls) == 2


def test_cap_zero_allows_no_lookup_at_all():
    onec = FakeOneC([])
    report = run_reconcile(FakeLedger(unknown_rows(1)), onec, max_unknown_lookups=0)
    assert report.status is C.INCONCLUSIVE and report.reason == "LOOKUP_CAP_EXCEEDED"
    assert onec.find_calls == []


def test_default_cap_is_fifty():
    onec = FakeOneC([])
    assert run_reconcile(FakeLedger(unknown_rows(50)), onec).reason != "LOOKUP_CAP_EXCEEDED"
    onec = FakeOneC([])
    report = run_reconcile(FakeLedger(unknown_rows(51)), onec)
    assert report.status is C.INCONCLUSIVE and report.reason == "LOOKUP_CAP_EXCEEDED"
    assert len(onec.find_calls) == 50


def test_pending_and_applied_rows_do_not_count_against_the_cap():
    ledger = FakeLedger([change("a1"), change("p1", PENDING), change("u0", UNKNOWN)])
    report = run_reconcile(ledger, FakeOneC([doc("a1")]), max_unknown_lookups=1)
    assert report.reason != "LOOKUP_CAP_EXCEEDED"


def test_runner_passes_its_cap_to_every_run_and_the_gate_stays_blocked():
    onec = FakeOneC([])
    runner, gate, _ = make_runner(FakeLedger(unknown_rows(2)), onec, max_unknown_lookups=1)
    report = runner.run(Trigger.STARTUP)
    assert report.reason == "LOOKUP_CAP_EXCEEDED"
    assert gate.applies_blocked() is True


# --- assertion 3: three triggers each produce a run ----------------------------------------------------------

def make_runner(ledger, onec, enabled=True, interval=60.0, clock=None, max_age=1000.0, **kw):
    flag = {"on": enabled}
    clock = Clock() if clock is None else clock
    gate = ApplyGate(lambda: flag["on"], max_age, clock)
    return ReconciliationRunner(ledger, onec, gate, interval, clock=clock, **kw), gate, flag


def test_startup_trigger_runs_one_check_and_reports_its_trigger():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, _, _ = make_runner(ledger, onec)
    report = runner.run(Trigger.STARTUP)
    assert (ledger.list_calls, onec.list_calls) == (1, 1)
    assert report.trigger is Trigger.STARTUP and report.status is C.CLEAN


def test_start_is_the_startup_trigger():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, gate, _ = make_runner(ledger, onec)
    report = runner.start()
    assert report.trigger is Trigger.STARTUP and report.status is C.CLEAN
    assert (ledger.list_calls, onec.list_calls) == (1, 1)
    assert gate.applies_blocked() is False


def test_after_restore_trigger_runs_one_check_and_reports_its_trigger():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, _, _ = make_runner(ledger, onec)
    report = runner.run(Trigger.AFTER_RESTORE)
    assert (ledger.list_calls, onec.list_calls) == (1, 1)
    assert report.trigger is Trigger.AFTER_RESTORE


def test_periodic_trigger_runs_one_check_and_reports_its_trigger():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, _, _ = make_runner(ledger, onec, clock=Clock(1000.0))
    report = runner.tick()
    assert report is not None
    assert (ledger.list_calls, onec.list_calls) == (1, 1)
    assert report.trigger is Trigger.PERIODIC


def test_periodic_tick_runs_only_when_the_interval_has_elapsed():
    ledger, onec = FakeLedger(), FakeOneC()
    clock = Clock(100.0)
    runner, _, _ = make_runner(ledger, onec, interval=10.0, clock=clock)
    assert runner.tick() is not None and ledger.list_calls == 1
    clock.now = 105.0
    assert runner.tick() is None and ledger.list_calls == 1
    clock.now = 109.999
    assert runner.tick() is None and ledger.list_calls == 1
    clock.now = 110.0
    assert runner.tick() is not None and ledger.list_calls == 2
    clock.now = 111.0
    assert runner.tick() is None and ledger.list_calls == 2


def test_a_startup_run_defers_the_first_periodic_run():
    ledger, onec = FakeLedger(), FakeOneC()
    clock = Clock(50.0)
    runner, _, _ = make_runner(ledger, onec, interval=10.0, clock=clock)
    runner.start()
    clock.now = 55.0
    assert runner.tick() is None
    clock.now = 60.0
    assert runner.tick() is not None
    assert ledger.list_calls == 2


def test_every_trigger_run_reads_both_sides_afresh():
    ledger, onec = FakeLedger(), FakeOneC()
    clock = Clock(0.0)
    runner, _, _ = make_runner(ledger, onec, interval=1.0, clock=clock)
    runner.run(Trigger.STARTUP)
    runner.run(Trigger.AFTER_RESTORE)
    clock.now = 5.0
    runner.tick()
    assert (ledger.list_calls, onec.list_calls) == (3, 3)


@pytest.mark.parametrize("interval", [0, -1, -0.5, float("nan")])
def test_runner_rejects_a_non_positive_interval(interval):
    with pytest.raises(ValueError, match="RECONCILE_INTERVAL_INVALID"):
        ReconciliationRunner(FakeLedger(), FakeOneC(), ApplyGate(lambda: True, 10.0), interval)


@pytest.mark.parametrize("retry", [0, -1, float("nan")])
def test_runner_rejects_a_non_positive_retry_interval(retry):
    with pytest.raises(ValueError, match="RECONCILE_RETRY_INTERVAL_INVALID"):
        ReconciliationRunner(FakeLedger(), FakeOneC(), ApplyGate(lambda: True, 10.0), 60.0,
                             retry_interval_seconds=retry)


@pytest.mark.parametrize("max_age", [0, -1, float("nan")])
def test_gate_rejects_a_non_positive_max_age(max_age):
    with pytest.raises(ValueError, match="GATE_MAX_AGE_INVALID"):
        ApplyGate(lambda: True, max_age)


# --- CR-388: retry interval, backwards clock, restore pending -------------------------------------------------

def test_after_a_non_clean_run_the_default_retry_interval_is_a_quarter_of_the_interval():
    clock = Clock(0.0)
    ledger = FakeLedger([change("c1")])  # applied, 1C empty: DIRTY
    runner, _, _ = make_runner(ledger, FakeOneC([]), interval=40.0, clock=clock)
    assert runner.tick().status is C.DIRTY
    clock.now = 9.9
    assert runner.tick() is None
    clock.now = 10.0
    assert runner.tick() is not None and ledger.list_calls == 2


def test_after_a_clean_run_the_normal_interval_applies_again():
    clock = Clock(0.0)
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([])
    runner, _, _ = make_runner(ledger, onec, interval=40.0, clock=clock)
    runner.tick()  # DIRTY
    onec.docs.append(doc("c1"))
    clock.now = 10.0
    assert runner.tick().status is C.CLEAN
    clock.now = 20.0  # past the retry interval but inside the normal one
    assert runner.tick() is None
    clock.now = 50.0
    assert runner.tick() is not None


def test_explicit_retry_interval_is_used_and_capped_at_the_interval():
    clock = Clock(0.0)
    ledger = FakeLedger([change("c1")])
    runner, _, _ = make_runner(ledger, FakeOneC([]), interval=100.0, clock=clock,
                               retry_interval_seconds=7.0)
    runner.tick()
    clock.now = 6.9
    assert runner.tick() is None
    clock.now = 7.0
    assert runner.tick() is not None

    clock2 = Clock(0.0)
    ledger2 = FakeLedger([change("c1")])
    capped, _, _ = make_runner(ledger2, FakeOneC([]), interval=100.0, clock=clock2,
                               retry_interval_seconds=500.0)
    capped.tick()
    clock2.now = 99.0
    assert capped.tick() is None
    clock2.now = 100.0
    assert capped.tick() is not None


def test_a_backwards_clock_does_not_suppress_a_due_tick():
    ledger = FakeLedger()
    clock = Clock(100.0)
    runner, _, _ = make_runner(ledger, FakeOneC(), interval=10.0, clock=clock)
    runner.start()
    clock.now = 10.0  # the clock went backwards: now - last is negative
    assert runner.tick() is not None
    assert ledger.list_calls == 2


def test_forward_progress_inside_the_interval_still_skips_the_tick():
    ledger = FakeLedger()
    clock = Clock(100.0)
    runner, _, _ = make_runner(ledger, FakeOneC(), interval=10.0, clock=clock)
    runner.start()
    clock.now = 105.0
    assert runner.tick() is None
    assert ledger.list_calls == 1


def test_a_restore_pending_makes_the_next_tick_run_inside_the_interval():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    clock = Clock(0.0)
    runner, gate, _ = make_runner(ledger, onec, interval=60.0, clock=clock)
    runner.start()
    clock.now = 1.0
    assert runner.tick() is None  # nothing pending
    gate.mark_restore()
    assert gate.applies_blocked() is True
    assert runner.tick() is not None  # runs although the interval has not elapsed
    assert gate.applies_blocked() is False


# --- CR-388: runner status accessor --------------------------------------------------------------------------

def test_status_before_any_run_is_empty():
    runner, _, _ = make_runner(FakeLedger(), FakeOneC())
    status = runner.status()
    assert status.last_report is None
    assert status.last_run_at is None and status.last_clean_at is None
    assert status.consecutive_non_clean == 0


def test_status_tracks_the_last_report_times_and_consecutive_non_clean_runs():
    clock = Clock(100.0)
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, _, _ = make_runner(ledger, onec, clock=clock)
    clean = runner.run(Trigger.STARTUP)
    status = runner.status()
    assert status.last_report is clean
    assert (status.last_run_at, status.last_clean_at, status.consecutive_non_clean) == (
        100.0, 100.0, 0)

    onec.docs.clear()  # now DIRTY
    clock.now = 110.0
    dirty = runner.run(Trigger.PERIODIC)
    status = runner.status()
    assert status.last_report is dirty and dirty.status is C.DIRTY
    assert (status.last_run_at, status.last_clean_at, status.consecutive_non_clean) == (
        110.0, 100.0, 1)

    ledger.error = RuntimeError("down")  # INCONCLUSIVE counts as non-clean too
    clock.now = 120.0
    runner.run(Trigger.PERIODIC)
    assert runner.status().consecutive_non_clean == 2

    ledger.error = None
    onec.docs.append(doc("c1"))
    clock.now = 130.0
    runner.run(Trigger.PERIODIC)
    status = runner.status()
    assert (status.last_run_at, status.last_clean_at, status.consecutive_non_clean) == (
        130.0, 130.0, 0)


def test_runner_logs_class_and_reason_but_never_the_exception_message(caplog):
    runner, _, _ = make_runner(FakeLedger(error=RuntimeError("secret-xyz")), FakeOneC())
    with caplog.at_level(logging.INFO, logger="erp_mcp_s15.reconcile"):
        runner.run(Trigger.STARTUP)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "PORT_ERROR:RuntimeError" in text and "INCONCLUSIVE" in text
    assert "secret-xyz" not in text
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# --- CR-388: runner failures are INCONCLUSIVE on the gate ----------------------------------------------------

def test_an_internal_error_in_the_body_is_recorded_on_the_gate_and_closes_a_previous_clean():
    ledger = FakeLedger([change("c1")])
    onec = FakeOneC([doc("c1")])
    runner, gate, _ = make_runner(ledger, onec, max_unknown_lookups=None)
    assert runner.run(Trigger.STARTUP).status is C.CLEAN
    assert gate.applies_blocked() is False
    ledger.changes.append(change("c9", UNKNOWN))  # makes the comparison body raise TypeError
    report = runner.run(Trigger.PERIODIC)
    assert report.status is C.INCONCLUSIVE
    assert report.reason == "INTERNAL_ERROR:TypeError"
    assert gate.applies_blocked() is True  # the earlier CLEAN is not left open
    assert gate.clean_at is None


def test_an_exception_escaping_reconcile_becomes_a_runner_error_and_blocks_the_gate(monkeypatch):
    runner, gate, _ = make_runner(FakeLedger([change("c1")]), FakeOneC([doc("c1")]))
    runner.run(Trigger.STARTUP)
    assert gate.applies_blocked() is False

    def boom(*args, **kwargs):
        raise MemoryError("secret-payload")

    monkeypatch.setattr(reconcile_module, "reconcile", boom)
    report = runner.run(Trigger.PERIODIC)  # must not raise
    assert report.status is C.INCONCLUSIVE
    assert report.reason == "RUNNER_ERROR:MemoryError"
    assert "secret-payload" not in repr(report)
    assert gate.applies_blocked() is True
    assert runner.status().consecutive_non_clean == 1


def test_a_gate_that_fails_to_record_is_reported_as_a_runner_error_not_raised():
    class BrokenGate(ApplyGate):
        def record(self, report, epoch=None):
            raise OSError("disk")

    gate = BrokenGate(lambda: True, 10.0)
    runner = ReconciliationRunner(FakeLedger(), FakeOneC(), gate, 60.0)
    report = runner.run(Trigger.STARTUP)
    assert report.status is C.INCONCLUSIVE and report.reason == "RUNNER_ERROR:OSError"
    assert runner.status().consecutive_non_clean == 1


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


def test_a_non_clean_report_closes_a_gate_that_was_clean():
    clock = Clock(0.0)
    gate = ApplyGate(lambda: True, 100.0, clock)
    assert gate.record(CLEAN_REPORT) is True
    assert gate.applies_blocked() is False
    assert gate.record(DIRTY_REPORT) is True
    assert gate.applies_blocked() is True
    assert gate.clean_at is None


# --- CR-388: restore epoch (stale reports never unblock) ---------------------------------------------------------

def test_mark_restore_bumps_the_epoch_blocks_and_forgets_the_clean_time():
    gate = ApplyGate(lambda: True, 100.0, Clock(5.0))
    gate.record(CLEAN_REPORT)
    assert gate.epoch == 0 and gate.clean_at == 5.0
    gate.mark_restore()
    assert gate.epoch == 1 and gate.clean_at is None
    assert gate.applies_blocked() is True
    gate.mark_restore()
    assert gate.epoch == 2


def test_a_clean_report_from_before_the_restore_is_discarded_and_does_not_unblock():
    gate = ApplyGate(lambda: True, 100.0, Clock())
    started_at = gate.epoch
    gate.mark_restore()
    assert gate.record(CLEAN_REPORT, started_at) is False
    assert gate.applies_blocked() is True
    assert gate.clean_at is None


def test_a_report_with_the_current_epoch_or_without_one_is_applied():
    gate = ApplyGate(lambda: True, 100.0, Clock())
    gate.mark_restore()
    assert gate.record(CLEAN_REPORT, gate.epoch) is True
    assert gate.applies_blocked() is False
    gate.mark_restore()
    assert gate.record(CLEAN_REPORT) is True  # None means "current"
    assert gate.applies_blocked() is False


def test_a_stale_non_clean_report_is_discarded_as_well():
    gate = ApplyGate(lambda: True, 100.0, Clock())
    old = gate.epoch
    gate.mark_restore()
    gate.record(CLEAN_REPORT, gate.epoch)
    assert gate.record(DIRTY_REPORT, old) is False
    assert gate.applies_blocked() is False  # the stale DIRTY did not touch the fresh state


def test_a_periodic_report_finishing_after_a_restore_leaves_the_gate_blocked():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    clock = Clock(0.0)
    runner, gate, _ = make_runner(ledger, onec, interval=60.0, clock=clock)
    runner.start()
    assert gate.applies_blocked() is False
    # The restore happens while the next periodic run is reading the (pre-restore) state.
    ledger.on_list = gate.mark_restore
    clock.now = 61.0
    report = runner.tick()
    ledger.on_list = None
    assert report.status is C.CLEAN  # computed from pre-restore data ...
    assert gate.epoch == 1
    assert gate.applies_blocked() is True  # ... and must not unblock the post-restore gate
    with pytest.raises(ApplyBlockedError):
        gate.ensure_apply_allowed()
    # The pending restore makes the very next tick run, even inside the interval.
    clock.now = 62.0
    assert runner.tick() is not None
    assert gate.applies_blocked() is False


def test_a_fresh_blocked_gate_is_not_opened_by_a_run_that_overlapped_a_restore():
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, gate, _ = make_runner(ledger, onec)
    ledger.on_list = gate.mark_restore
    runner.start()
    assert gate.applies_blocked() is True


def test_after_restore_marks_the_gate_before_waiting_for_a_run_in_flight():
    ledger = BlockingLedger([change("c1")])
    onec = FakeOneC([doc("c1")])
    clock = Clock(0.0)
    runner, gate, _ = make_runner(ledger, onec, interval=60.0, clock=clock)
    runner.start()
    assert gate.applies_blocked() is False

    clock.now = 61.0
    ledger.arm()
    results = {}
    periodic = threading.Thread(target=lambda: results.setdefault("periodic", runner.tick()))
    periodic.start()
    assert ledger.entered.wait(5.0)  # the periodic run is in flight
    restore = threading.Thread(
        target=lambda: results.setdefault("restore", runner.run(Trigger.AFTER_RESTORE)))
    restore.start()
    # mark_restore happens immediately, while the periodic run still holds the run lock.
    assert wait_until(lambda: gate.epoch == 1)
    assert gate.applies_blocked() is True
    ledger.release.set()
    periodic.join(5.0)
    restore.join(5.0)
    assert not periodic.is_alive() and not restore.is_alive()
    assert results["restore"].trigger is Trigger.AFTER_RESTORE
    assert gate.applies_blocked() is False  # the post-restore run, not the stale one, opened it
    assert ledger.list_calls == 3


# --- CR-388: serialized runs -----------------------------------------------------------------------------------

def test_an_overlapping_periodic_tick_is_skipped():
    ledger = BlockingLedger()
    runner, _, _ = make_runner(ledger, FakeOneC())
    ledger.arm()
    results = {}
    first = threading.Thread(target=lambda: results.setdefault("first", runner.tick()))
    first.start()
    assert ledger.entered.wait(5.0)
    assert runner.tick() is None  # due, but a run is in flight: skipped, not queued
    ledger.release.set()
    first.join(5.0)
    assert not first.is_alive()
    assert results["first"].status is C.CLEAN
    assert ledger.list_calls == 1  # the skipped tick never read the ports


def test_an_explicit_run_waits_for_the_run_in_flight_instead_of_being_skipped():
    ledger = BlockingLedger()
    runner, _, _ = make_runner(ledger, FakeOneC())
    ledger.arm()
    results = {}
    first = threading.Thread(target=lambda: results.setdefault("tick", runner.tick()))
    first.start()
    assert ledger.entered.wait(5.0)
    second = threading.Thread(
        target=lambda: results.setdefault("run", runner.run(Trigger.PERIODIC)))
    second.start()
    ledger.release.set()
    first.join(5.0)
    second.join(5.0)
    assert not first.is_alive() and not second.is_alive()
    assert results["tick"] is not None and results["run"] is not None
    assert ledger.list_calls == 2


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
    gate = ApplyGate(lambda: False, 10.0)
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
    clock = Clock(10_000.0)
    runner, _, _ = make_runner(FakeLedger([change("c1")]), FakeOneC([]), enabled=True,
                               clock=clock)
    assert runner.run(Trigger.STARTUP).status is C.DIRTY
    assert runner.run(Trigger.AFTER_RESTORE).status is C.DIRTY
    clock.now = 20_000.0
    assert runner.tick().status is C.DIRTY


# --- CR-388: strict-bool writer flag ---------------------------------------------------------------------------

def test_only_an_exact_false_makes_the_gate_inert_and_the_flag_is_consulted_live():
    values = iter([False, None, False, True])
    gate = ApplyGate(lambda: next(values), 10.0)
    assert gate.applies_blocked() is False  # False: inert
    assert gate.applies_blocked() is True  # None: counts as enabled, still blocked
    assert gate.applies_blocked() is False  # read again every call
    assert gate.applies_blocked() is True  # True: enabled


@pytest.mark.parametrize("value", [None, 0, "", [], 0.0, "false", "False", 1, True],
                         ids=repr)
def test_any_writer_flag_other_than_false_is_enabled_and_blocking(value):
    gate = ApplyGate(lambda: value, 10.0)
    assert gate.applies_blocked() is True
    with pytest.raises(ApplyBlockedError, match="RECONCILIATION_NOT_CLEAN"):
        gate.ensure_apply_allowed()


def test_a_failing_writer_flag_is_enabled_and_blocking_and_raises_the_apply_refusal_only():
    def broken():
        raise RuntimeError("config unreadable")

    gate = ApplyGate(broken, 10.0)
    assert gate.applies_blocked() is True
    with pytest.raises(ApplyBlockedError):
        gate.ensure_apply_allowed()


@pytest.mark.parametrize("value", [None, 0, True])
def test_an_enabled_but_unclear_flag_is_still_open_after_a_fresh_clean_run(value):
    gate = ApplyGate(lambda: value, 10.0, Clock())
    gate.record(CLEAN_REPORT)
    assert gate.applies_blocked() is False


# --- CR-388: CLEAN expires --------------------------------------------------------------------------------------

def test_clean_expires_after_the_max_age_and_a_new_clean_reopens_the_gate():
    clock = Clock(0.0)
    gate = ApplyGate(lambda: True, 30.0, clock)
    gate.record(CLEAN_REPORT)
    clock.now = 30.0
    assert gate.applies_blocked() is False  # exactly max_age is still fresh
    clock.now = 30.001
    assert gate.applies_blocked() is True
    with pytest.raises(ApplyBlockedError, match="RECONCILIATION_NOT_CLEAN"):
        gate.ensure_apply_allowed()
    gate.record(CLEAN_REPORT)
    assert gate.applies_blocked() is False


def test_an_expired_clean_does_not_block_while_the_writer_is_disabled():
    clock = Clock(0.0)
    flag = {"on": False}
    gate = ApplyGate(lambda: flag["on"], 30.0, clock)
    gate.record(CLEAN_REPORT)
    clock.now = 500.0
    assert gate.applies_blocked() is False
    flag["on"] = True
    assert gate.applies_blocked() is True


def test_a_clock_that_went_backwards_never_leaves_a_clean_open():
    clock = Clock(100.0)
    gate = ApplyGate(lambda: True, 30.0, clock)
    gate.record(CLEAN_REPORT)
    assert gate.applies_blocked() is False
    clock.now = 50.0
    assert gate.applies_blocked() is True


def test_a_stalled_scheduler_lets_the_clean_expire_until_the_next_clean_tick():
    clock = Clock(0.0)
    ledger, onec = FakeLedger([change("c1")]), FakeOneC([doc("c1")])
    runner, gate, _ = make_runner(ledger, onec, interval=10.0, clock=clock, max_age=25.0)
    runner.start()
    assert gate.applies_blocked() is False
    clock.now = 26.0  # nobody ticked for longer than max_age
    assert gate.applies_blocked() is True
    assert runner.tick() is not None
    assert gate.applies_blocked() is False
