"""R2-US-033 one data state: TC097 / TC098 / TC099 plus negative paths."""
import threading
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.comparison_snapshot import (
    ComparisonSnapshotError,
    ComparisonState,
    RunLedger,
    SideRead,
    SnapshotStore,
    canonical_digest,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
FIXTURE = {"account": "521.1", "rows": [{"ref": "A", "amount": Decimal("10.50")}], "at": T0}
KEY = "tb:818HA:521.1:2026-08"


class Clock:
    def __init__(self):
        self.now = T0 + timedelta(days=10)

    def __call__(self):
        return self.now


def make():
    store = SnapshotStore(Clock())
    return store, RunLedger(store)


def read(side, snap, digest=None, **values):
    vals = values or {"closing_credit": Decimal(24)}
    return SideRead(side, snap.snapshot_id, digest or snap.digest, vals)


# ---- TC097: immutable snapshot proven by digest ----
def test_tc097_digest_is_sha256_and_mutated_fixture_changes_it():
    store, _ = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    assert len(snap.digest) == 64 and snap.digest == canonical_digest(FIXTURE)
    assert snap.known_at == T0
    mutated = {**FIXTURE, "rows": [{"ref": "A", "amount": Decimal("10.51")}]}
    assert canonical_digest(mutated) != snap.digest
    assert store.create("t1", mutated, known_at=T0).snapshot_id != snap.snapshot_id
    # the stored snapshot itself is untouched by creating the mutated one
    assert store.get("t1", snap.snapshot_id).digest == snap.digest


def test_tc097_digest_is_canonical_decimal_key_order_and_timezone_independent():
    a = {"x": Decimal("1.50"), "y": T0, "z": [1, 2]}
    b = {"z": (1, 2), "y": T0.astimezone(timezone(timedelta(hours=3))), "x": Decimal("1.5")}
    assert canonical_digest(a) == canonical_digest(b)
    assert canonical_digest({"x": Decimal("0.0")}) == canonical_digest({"x": Decimal(0)})
    assert canonical_digest({"x": Decimal(1)}) != canonical_digest({"x": "1"})


def test_tc097_snapshot_is_immutable_and_create_is_idempotent():
    store, _ = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    with pytest.raises(AttributeError):
        snap.digest = "x"  # type: ignore[misc]
    assert store.create("t1", FIXTURE, known_at=T0) is snap
    assert store.create("t1", FIXTURE, known_at=T0 + timedelta(seconds=1)).snapshot_id != snap.snapshot_id
    assert store.get("t2", snap.snapshot_id) is None  # tenant isolated


def test_tc097_matching_reads_on_one_snapshot_pass():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    rec = ledger.run("t1", KEY, read("native", snap), read("gateway", snap), snapshot_id=snap.snapshot_id)
    assert (rec.state, rec.reason_code) == (ComparisonState.PASS, "ALL_VALUES_EQUAL")
    assert rec.snapshot_digest == snap.digest and rec.known_at == T0


def test_value_difference_fails_with_named_measure():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    rec = ledger.run("t1", KEY, read("native", snap, closing_credit=Decimal(24)),
                     read("gateway", snap, closing_credit=Decimal(25)), snapshot_id=snap.snapshot_id)
    assert rec.state == ComparisonState.FAIL and rec.differences == ("closing_credit",)


def test_decimal_equality_is_numeric_not_textual():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    rec = ledger.run("t1", KEY, read("native", snap, v=Decimal("1.50")),
                     read("gateway", snap, v=Decimal("1.5")), snapshot_id=snap.snapshot_id)
    assert rec.state == ComparisonState.PASS


def test_both_sides_must_reference_the_same_snapshot():
    store, ledger = make()
    s1 = store.create("t1", FIXTURE, known_at=T0)
    s2 = store.create("t1", {"other": 1}, known_at=T0)
    rec = ledger.run("t1", KEY, read("native", s1), read("gateway", s2), snapshot_id=s1.snapshot_id)
    assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "SNAPSHOT_REFERENCE_MISMATCH")
    rec = ledger.run("t1", KEY, read("native", s2), read("gateway", s2), snapshot_id=s1.snapshot_id)
    assert rec.reason_code == "SNAPSHOT_REFERENCE_MISMATCH"


def test_unknown_snapshot_and_other_tenant_are_inconclusive():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    rec = ledger.run("t2", KEY, read("native", snap), read("gateway", snap), snapshot_id=snap.snapshot_id)
    assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "SNAPSHOT_UNKNOWN")


def test_read_digest_not_matching_snapshot_is_inconclusive():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    bad = canonical_digest({"mutated": True})
    rec = ledger.run("t1", KEY, read("native", snap, bad), read("gateway", snap, bad),
                     snapshot_id=snap.snapshot_id)
    assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "SNAPSHOT_DIGEST_MISMATCH")


def test_empty_observations_are_inconclusive_not_pass():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    rec = ledger.run("t1", KEY, SideRead("native", snap.snapshot_id, snap.digest, {}),
                     SideRead("gateway", snap.snapshot_id, snap.digest, {}), snapshot_id=snap.snapshot_id)
    assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "NO_OBSERVATIONS")


# ---- TC098: correction between reads ----
@pytest.mark.parametrize("changed_side", ["native", "gateway"])
def test_tc098_correction_between_reads_is_inconclusive_never_pass(changed_side):
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    corrected = canonical_digest({**FIXTURE, "correction": 1})
    n = read("native", snap, corrected if changed_side == "native" else None)
    g = read("gateway", snap, corrected if changed_side == "gateway" else None)
    # numbers are identical on both sides: equality alone must not produce PASS
    assert dict(n.values) == dict(g.values)
    rec = ledger.run("t1", KEY, n, g, snapshot_id=snap.snapshot_id)
    assert rec.state == ComparisonState.INCONCLUSIVE
    assert rec.state != ComparisonState.PASS
    assert rec.reason_code == "SOURCE_CHANGED_BETWEEN_READS"


# ---- TC099: backdated rerun supersedes, nothing lost ----
def test_tc099_backdated_rerun_supersedes_and_keeps_original_unchanged():
    store, ledger = make()
    now_snap = store.create("t1", FIXTURE, known_at=T0 + timedelta(days=5))
    first = ledger.run("t1", KEY, read("native", now_snap, closing_credit=Decimal(24)),
                       read("gateway", now_snap, closing_credit=Decimal(24)), snapshot_id=now_snap.snapshot_id)
    before = (first, first.native_values, first.gateway_values, first.known_at, first.snapshot_digest)

    old_payload = {**FIXTURE, "rows": [{"ref": "A", "amount": Decimal(9)}]}
    old_snap = store.create("t1", old_payload, known_at=T0)  # backdated
    assert old_snap.known_at < now_snap.known_at
    second = ledger.run("t1", KEY, read("native", old_snap, closing_credit=Decimal(23)),
                        read("gateway", old_snap, closing_credit=Decimal(23)),
                        snapshot_id=old_snap.snapshot_id, rerun_of=first.run_id)

    assert second.run_id != first.run_id and second.supersedes == first.run_id
    views = ledger.list_runs("t1", KEY)
    assert [v.record.run_id for v in views] == [first.run_id, second.run_id]
    assert [v.status for v in views] == ["SUPERSEDED", "CURRENT"]
    assert views[0].superseded_by == second.run_id and views[1].superseded_by is None
    # original still readable and byte-for-byte the same numbers
    again = ledger.get("t1", first.run_id)
    assert again is first
    assert (again, again.native_values, again.gateway_values, again.known_at,
            again.snapshot_digest) == before
    assert dict(again.native_values) == {"closing_credit": Decimal(24)}
    assert dict(second.native_values) == {"closing_credit": Decimal(23)}


def test_tc099_chain_only_supersedes_current_head_and_runs_are_frozen():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    r1 = ledger.run("t1", KEY, read("native", snap), read("gateway", snap), snapshot_id=snap.snapshot_id)
    r2 = ledger.run("t1", KEY, read("native", snap), read("gateway", snap),
                    snapshot_id=snap.snapshot_id, rerun_of=r1.run_id)
    with pytest.raises(ComparisonSnapshotError) as exc:
        ledger.run("t1", KEY, read("native", snap), read("gateway", snap),
                   snapshot_id=snap.snapshot_id, rerun_of=r1.run_id)
    assert exc.value.code == "RERUN_TARGET_ALREADY_SUPERSEDED"
    assert len(ledger.list_runs("t1", KEY)) == 2  # failed rerun left no trace
    r3 = ledger.run("t1", KEY, read("native", snap), read("gateway", snap),
                    snapshot_id=snap.snapshot_id, rerun_of=r2.run_id)
    assert [v.status for v in ledger.list_runs("t1", KEY)] == ["SUPERSEDED", "SUPERSEDED", "CURRENT"]
    assert r3.supersedes == r2.run_id
    with pytest.raises(AttributeError):
        r1.state = ComparisonState.FAIL  # type: ignore[misc]


def test_rerun_target_must_exist_in_same_tenant_and_key():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    r1 = ledger.run("t1", KEY, read("native", snap), read("gateway", snap), snapshot_id=snap.snapshot_id)
    for tenant, key, target in (("t2", KEY, r1.run_id), ("t1", "other-key", r1.run_id), ("t1", KEY, "run-999999")):
        s = store.create(tenant, FIXTURE, known_at=T0)
        with pytest.raises(ComparisonSnapshotError) as exc:
            ledger.run(tenant, key, read("native", s), read("gateway", s), snapshot_id=s.snapshot_id,
                       rerun_of=target)
        assert exc.value.code == "RERUN_TARGET_UNKNOWN"
    assert ledger.list_runs("t1", KEY)[0].status == "CURRENT"


def test_listing_is_scoped_by_tenant_and_key():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    ledger.run("t1", KEY, read("native", snap), read("gateway", snap), snapshot_id=snap.snapshot_id)
    assert ledger.list_runs("t2", KEY) == () and ledger.list_runs("t1", "x") == ()


# ---- input validation ----
@pytest.mark.parametrize("payload,code", [
    ({"f": 1.5}, "PAYLOAD_TYPE_UNSUPPORTED"),
    ({"d": Decimal("NaN")}, "FINITE_DECIMAL_REQUIRED"),
    ({"d": datetime(2026, 1, 1)}, "TIMEZONE_REQUIRED"),  # noqa: DTZ001
    ({1: "x"}, "PAYLOAD_KEY_NOT_TEXT"),
    ({"d": Decimal("1e100000")}, "DECIMAL_PRECISION_EXCEEDED"),
])
def test_bad_payload_rejected_with_fixed_code(payload, code):
    store, _ = make()
    with pytest.raises(ComparisonSnapshotError) as exc:
        store.create("t1", payload)
    assert exc.value.code == code


def test_depth_limit_and_known_at_rules():
    store, _ = make()
    deep: object = 1
    for _ in range(40):
        deep = [deep]
    with pytest.raises(ComparisonSnapshotError) as exc:
        store.create("t1", deep)
    assert exc.value.code == "PAYLOAD_TOO_DEEP"
    with pytest.raises(ComparisonSnapshotError) as exc:
        store.create("t1", {}, known_at=datetime(2026, 1, 1))  # noqa: DTZ001
    assert exc.value.code == "TIMEZONE_REQUIRED"
    with pytest.raises(ComparisonSnapshotError) as exc:
        store.create("t1", {}, known_at=store.now() + timedelta(seconds=1))
    assert exc.value.code == "KNOWN_AT_IN_FUTURE"
    with pytest.raises(ComparisonSnapshotError) as exc:
        store.create("", {})
    assert exc.value.code == "TENANT_REQUIRED"


def test_side_values_must_be_decimals():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    bad = SideRead("native", snap.snapshot_id, snap.digest, {"v": 1.0})  # type: ignore[dict-item]
    with pytest.raises(ComparisonSnapshotError) as exc:
        ledger.run("t1", KEY, bad, read("gateway", snap), snapshot_id=snap.snapshot_id)
    assert exc.value.code == "FINITE_DECIMAL_REQUIRED"
    assert ledger.list_runs("t1", KEY) == ()


def test_concurrent_runs_get_unique_sequential_ids():
    store, ledger = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    out = []

    def work():
        out.append(ledger.run("t1", KEY, read("native", snap), read("gateway", snap),
                              snapshot_id=snap.snapshot_id).run_id)

    threads = [threading.Thread(target=work) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(out)) == 32 and len(ledger.list_runs("t1", KEY)) == 32
