import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2.temporal import EventKind, EventLedger, ModelEvent

T0 = datetime(2026, 10, 8, 9, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)
T2 = T1 + timedelta(hours=1)
T3 = T2 + timedelta(hours=1)


def e(event_id="e1", revision="revA", recorded=T1, observed=T0, effective=None,
      kind=EventKind.OBSERVED, tenant="t1", source="s1", object_id="Purchase"):
    return ModelEvent(event_id, tenant, source, object_id, revision, kind,
                      recorded, observed, effective, "a" * 64)


def test_append_idempotent_identical_event():
    l = EventLedger("t1", "s1")
    assert l.append(e())
    assert not l.append(e())
    assert len(l.events) == 1


def test_conflicting_replay_fails_closed():
    l = EventLedger("t1", "s1")
    l.append(e())
    with pytest.raises(ValueError, match="CONFLICTING_EVENT_ID"):
        l.append(e(revision="revB"))


def test_cross_tenant_append_denied():
    l = EventLedger("t1", "s1")
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        l.append(e(tenant="t2"))


def test_as_known_at_cannot_see_future_observation():
    l = EventLedger("t1", "s1")
    l.append(e("a", recorded=T1))
    l.append(e("b", "revB", recorded=T3, observed=T2))
    assert l.as_known_at(T2)["Purchase"].revision_id == "revA"
    assert l.as_known_at(T3)["Purchase"].revision_id == "revB"


def test_backdated_effective_event_does_not_rewrite_knowledge():
    l = EventLedger("t1", "s1")
    l.append(e("a", "a", recorded=T1, effective=T0))
    l.append(e("b", "b", recorded=T3, observed=T2, effective=T0 + timedelta(minutes=15)))
    assert l.as_effective_at(T2, T2)["Purchase"].revision_id == "a"
    assert l.as_effective_at(T2, T3)["Purchase"].revision_id == "b"


def test_unknown_valid_time_is_not_polling_time():
    l = EventLedger("t1", "s1")
    l.append(e(effective=None))
    assert l.as_known_at(T3)["Purchase"].revision_id == "revA"
    assert l.as_effective_at(T3, T3) == {}


def test_out_of_order_records_choose_later_effective_not_arrival():
    l = EventLedger("t1", "s1")
    l.append(e("early", "first", recorded=T1, effective=T0))
    l.append(e("late", "old-correction", recorded=T3, observed=T2,
               effective=T0 - timedelta(days=1)))
    assert l.as_effective_at(T2, T3)["Purchase"].revision_id == "first"


def test_history_gap_is_explicit():
    l = EventLedger("t1", "s1")
    l.append(e("g", "cursor-lost", kind=EventKind.GAP))
    assert len(l.history_gaps(T2)) == 1
    assert l.history_gaps(T0) == ()


def test_timezone_naive_recording_is_rejected():
    with pytest.raises(ValueError, match="MUST_HAVE_TIMEZONE"):
        e(recorded=datetime.fromisoformat("2026-10-08T09:00:00"))


def test_observed_after_recorded_fails():
    with pytest.raises(ValueError, match="OBSERVATION_AFTER_RECORDING"):
        e(recorded=T0, observed=T1)


def test_insertion_order_does_not_change_replay():
    l = EventLedger("t1", "s1")
    l.append(e("second", "B", recorded=T2))
    l.append(e("first", "A", recorded=T1))
    assert l.as_known_at(T1)["Purchase"].revision_id == "A"
    assert l.as_known_at(T3)["Purchase"].revision_id == "B"


def test_effective_at_rejects_naive_query():
    l = EventLedger("t1", "s1")
    l.append(e())
    with pytest.raises(ValueError, match="MUST_HAVE_TIMEZONE"):
        l.as_effective_at(datetime.fromisoformat("2026-10-08T00:00:00"), T3)


def test_gap_does_not_displace_observed_head():
    l = EventLedger("t1", "s1")
    l.append(e("obs", "revA", recorded=T1, observed=T0))
    l.append(e("gap", "cursor-lost", recorded=T3, observed=T2, kind=EventKind.GAP))
    head = l.as_known_at(T3)["Purchase"]
    assert head.kind is EventKind.OBSERVED and head.revision_id == "revA"
    assert l.status_at(T3)["Purchase"].kind is EventKind.GAP
    assert l.status_at(T2) == {}


@pytest.mark.parametrize("kind", [EventKind.SOURCE_UNAVAILABLE, EventKind.GAP,
                                  EventKind.ATTESTATION_REVOKED])
def test_non_observed_events_never_become_head(kind):
    l = EventLedger("t1", "s1")
    l.append(e("o", "revA", recorded=T1, observed=T0))
    l.append(e("x", "revX", recorded=T2, observed=T2, kind=kind))
    assert l.as_known_at(T3)["Purchase"].revision_id == "revA"
    assert l.status_at(T3)["Purchase"].event_id == "x"


def test_object_with_only_status_events_has_no_head():
    l = EventLedger("t1", "s1")
    l.append(e("g", "gap", kind=EventKind.GAP))
    assert l.as_known_at(T3) == {}


def test_head_orders_by_observed_then_recorded_then_event_id():
    l = EventLedger("t1", "s1")
    # arrives later but was observed EARLIER: must not become the head
    l.append(e("late-arrival", "old", recorded=T3, observed=T0))
    l.append(e("newer-obs", "new", recorded=T2, observed=T2))
    assert l.as_known_at(T3)["Purchase"].revision_id == "new"
    # equal observed_at: later recorded_at wins
    l2 = EventLedger("t1", "s1")
    l2.append(e("a", "r1", recorded=T1, observed=T0))
    l2.append(e("b", "r2", recorded=T2, observed=T0))
    assert l2.as_known_at(T3)["Purchase"].revision_id == "r2"
    # equal observed_at and recorded_at: event_id breaks the tie, insertion order irrelevant
    for order in (("a", "b"), ("b", "a")):
        l3 = EventLedger("t1", "s1")
        for eid in order:
            l3.append(e(eid, "rev-" + eid, recorded=T1, observed=T0))
        assert l3.as_known_at(T3)["Purchase"].event_id == "b"


def test_head_respects_recorded_cutoff_with_observed_ordering():
    l = EventLedger("t1", "s1")
    l.append(e("new", "new", recorded=T3, observed=T2))
    l.append(e("old", "old", recorded=T1, observed=T0))
    assert l.as_known_at(T2)["Purchase"].revision_id == "old"
    assert l.as_known_at(T3)["Purchase"].revision_id == "new"


def test_same_revision_with_different_digest_is_a_conflict():
    l = EventLedger("t1", "s1")
    l.append(e("a", "revA"))
    with pytest.raises(ValueError, match="CONFLICTING_REVISION_DIGEST"):
        l.append(replace(e("b", "revA"), digest="b" * 64))
    assert len(l.events) == 1
    assert l.append(e("c", "revA"))  # same digest, new event id is fine
    assert l.append(replace(e("d", "revB"), digest="b" * 64))  # other revision may differ


class _SlowGetDict(dict):
    """Widens the check-then-set window: get() yields after reading."""

    def get(self, key, default=None):
        value = super().get(key, default)
        time.sleep(0.001)
        return value


def test_concurrent_conflicting_revision_digest_admits_only_one_digest():
    for _ in range(5):
        l = EventLedger("t1", "s1")
        l._revision_digests = _SlowGetDict()
        barrier = threading.Barrier(16)
        outcomes = []

        def work(i, l=l, barrier=barrier, outcomes=outcomes):
            barrier.wait()
            digest = ("a" if i % 2 else "b") * 64
            try:
                l.append(replace(e("ev-" + str(i), "revA"), digest=digest))
                outcomes.append(digest)
            except ValueError:
                outcomes.append(None)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len({ev.digest for ev in l.events}) == 1
        assert len(l.events) == len([o for o in outcomes if o])


@pytest.mark.parametrize("digest", [None, 123, b"a" * 64, "", "A" * 64, "g" * 64, "a" * 63])
def test_observed_digest_is_validated_with_coded_value_error(digest):
    with pytest.raises(ValueError, match="OBSERVATION_DIGEST_REQUIRED"):
        replace(e(), digest=digest)


def test_non_observed_event_with_non_str_digest_is_coded_error():
    with pytest.raises(ValueError, match="EVENT_DIGEST_INVALID"):
        replace(e(kind=EventKind.GAP), digest=5)


@pytest.mark.parametrize("field", ["recorded_at", "observed_at"])
def test_none_event_timestamps_are_coded_value_errors(field):
    with pytest.raises(ValueError, match=field.upper() + "_REQUIRED"):
        replace(e(), **{field: None})


def test_none_query_cutoffs_are_coded_value_errors():
    l = EventLedger("t1", "s1")
    for call in (lambda: l.as_known_at(None), lambda: l.as_effective_at(None, T1),
                 lambda: l.as_effective_at(T1, None), lambda: l.history_gaps(None),
                 lambda: l.status_at(None)):
        with pytest.raises(ValueError, match="_REQUIRED"):
            call()


def test_supersedes_is_validated():
    l = EventLedger("t1", "s1")
    l.append(e("first", "revA", recorded=T1))
    l.append(e("other", "revO", recorded=T1, object_id="Other"))
    with pytest.raises(ValueError, match="SUPERSEDES_SELF"):
        replace(e("x", "revB"), supersedes_event_id="x")
    with pytest.raises(ValueError, match="SUPERSEDES_INVALID"):
        replace(e("x", "revB"), supersedes_event_id="")
    with pytest.raises(ValueError, match="SUPERSEDES_UNKNOWN_EVENT"):
        l.append(replace(e("x", "revB", recorded=T2, observed=T2), supersedes_event_id="nope"))
    with pytest.raises(ValueError, match="SUPERSEDES_OBJECT_MISMATCH"):
        l.append(replace(e("x", "revB", recorded=T2, observed=T2), supersedes_event_id="other"))
    ok = replace(e("x", "revB", recorded=T2, observed=T2), supersedes_event_id="first")
    assert l.append(ok)
    assert l.as_known_at(T3)["Purchase"].supersedes_event_id == "first"


def test_revoked_attestation_removes_effective_fact_without_effective_time():
    l = EventLedger("t1", "s1")
    l.append(e("obs", "revA", recorded=T1, observed=T0, effective=T0))
    l.append(e("rev", "revA", recorded=T2, observed=T2, kind=EventKind.ATTESTATION_REVOKED))
    assert l.as_effective_at(T3, T1)["Purchase"].revision_id == "revA"  # before revocation known
    assert l.as_effective_at(T3, T2) == {}
    assert l.as_effective_at(T3, T3) == {}
    assert l.revoked_revisions(T3) == frozenset({("Purchase", "revA")})
    assert l.revoked_revisions(T1) == frozenset()


def test_revocation_with_future_effective_time_still_applies_immediately():
    l = EventLedger("t1", "s1")
    l.append(e("obs", "revA", recorded=T1, observed=T0, effective=T0))
    l.append(e("rev", "revA", recorded=T2, observed=T2, effective=T3 + timedelta(days=30),
               kind=EventKind.ATTESTATION_REVOKED))
    assert l.as_effective_at(T2, T2) == {}


def test_revocation_of_old_revision_does_not_remove_newer_effective_fact():
    l = EventLedger("t1", "s1")
    l.append(e("a", "revA", recorded=T1, observed=T0, effective=T0))
    l.append(e("b", "revB", recorded=T2, observed=T1, effective=T1))
    l.append(e("r", "revA", recorded=T3, observed=T3, kind=EventKind.ATTESTATION_REVOKED))
    assert l.as_effective_at(T3, T3)["Purchase"].revision_id == "revB"


def test_revoked_head_is_not_replaced_by_older_revision():
    l = EventLedger("t1", "s1")
    l.append(e("a", "revA", recorded=T1, observed=T0, effective=T0))
    l.append(e("b", "revB", recorded=T2, observed=T1, effective=T1))
    l.append(e("r", "revB", recorded=T3, observed=T3, kind=EventKind.ATTESTATION_REVOKED))
    assert l.as_effective_at(T3, T3) == {}


def test_status_event_with_effective_time_does_not_displace_effective_fact():
    l = EventLedger("t1", "s1")
    l.append(e("a", "revA", recorded=T1, observed=T0, effective=T0))
    l.append(e("g", "gap", recorded=T2, observed=T2, effective=T1, kind=EventKind.GAP))
    assert l.as_effective_at(T3, T3)["Purchase"].revision_id == "revA"


def _revoked_then_gap():
    l = EventLedger("t1", "s1")
    l.append(e("obs", "revA", recorded=T1, observed=T0))
    l.append(e("rev", "revA", recorded=T2, observed=T2, kind=EventKind.ATTESTATION_REVOKED))
    l.append(e("gap", "cursor-lost", recorded=T3, observed=T3, kind=EventKind.GAP))
    return l


def test_head_exposes_revoked_flag_instead_of_serving_silently():
    l = _revoked_then_gap()
    assert l.as_known_at_with_revocation(T1)["Purchase"][1] is False
    event, revoked = l.as_known_at_with_revocation(T2)["Purchase"]
    assert event.revision_id == "revA" and revoked is True


def test_revocation_stays_visible_after_later_gap():
    l = _revoked_then_gap()
    assert l.status_at(T3)["Purchase"].kind is EventKind.ATTESTATION_REVOKED
    assert l.revocation_status_at(T3)["Purchase"].event_id == "rev"
    assert l.revocation_status_at(T1) == {}
