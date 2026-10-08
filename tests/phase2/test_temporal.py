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


def test_observed_requires_valid_digest():
    with pytest.raises(ValueError, match="DIGEST_REQUIRED"):
        replace(e(), digest="bogus")


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
