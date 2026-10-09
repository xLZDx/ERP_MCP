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
    _projection,
    canonical_digest,
    canonical_json,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
FIXTURE = {"account": "521.1", "rows": [{"ref": "A", "amount": Decimal("10.50")}], "at": T0}
KEY = "tb:818HA:521.1:2026-08"
CC24 = {"closing_credit": Decimal(24)}


class Clock:
    def __init__(self):
        self.now = T0 + timedelta(days=10)

    def __call__(self):
        return self.now


def make():
    store = SnapshotStore(Clock())
    return store, RunLedger(store)


def mk(store, native=None, gateway=None, *, tenant="t1", known_at=T0, **extra):
    """A snapshot whose payload carries each side's frozen numbers under ``values``."""
    n = dict(CC24) if native is None else native
    g = dict(n) if gateway is None else gateway
    payload = {**FIXTURE, "values": {"native": n, "gateway": g}, **extra}
    return store.create(tenant, payload, known_at=known_at)


def read(side, snap, digest=None, values=None):
    vals = values if values is not None else (_projection(snap, side) or dict(CC24))
    return SideRead(side, snap.snapshot_id, digest or snap.digest, dict(vals))


def go(ledger, snap, key=KEY, tenant="t1", **kw):
    return ledger.run(tenant, key, read("native", snap), read("gateway", snap),
                      snapshot_id=snap.snapshot_id, **kw)


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


def test_canonical_encoding_is_injective_for_type_tags():
    # Decimal/datetime are encoded as {"$dec": ...}/{"$ts": ...}; a user mapping must not be able
    # to produce the same bytes, so $-prefixed keys are refused at every depth.
    assert canonical_json({"x": Decimal(1)}) == '{"x":{"$dec":"1"}}'
    ts = T0.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    assert canonical_json({"x": T0}) == '{"x":{"$ts":"' + ts + '"}}'
    for forged in ({"x": {"$dec": "1"}}, {"x": {"$ts": ts}}, {"$dec": "1"},
                   {"a": [{"b": {"$other": 1}}]}, {"x": {"$dec": "1", "extra": 2}}):
        with pytest.raises(ComparisonSnapshotError) as exc:
            canonical_json(forged)
        assert exc.value.code == "PAYLOAD_KEY_RESERVED"
    store, _ = make()
    with pytest.raises(ComparisonSnapshotError) as exc:
        store.create("t1", {"x": {"$dec": "1"}})
    assert exc.value.code == "PAYLOAD_KEY_RESERVED"


def test_tc097_snapshot_is_immutable_and_create_is_idempotent():
    store, _ = make()
    snap = store.create("t1", FIXTURE, known_at=T0)
    with pytest.raises(AttributeError):
        snap.digest = "x"  # type: ignore[misc]
    assert store.create("t1", FIXTURE, known_at=T0) is snap
    assert store.create("t1", FIXTURE, known_at=T0 + timedelta(seconds=1)).snapshot_id != snap.snapshot_id
    assert store.get("t2", snap.snapshot_id) is None  # tenant isolated


def test_snapshot_does_not_alias_the_caller_payload():
    store, _ = make()
    payload = {"values": {"native": {"v": Decimal(1)}, "gateway": {"v": Decimal(1)}}, "rows": [1]}
    snap = store.create("t1", payload, known_at=T0)
    before = (snap.canonical, snap.digest)
    payload["rows"].append(2)
    payload["values"]["native"]["v"] = Decimal(99)
    assert (snap.canonical, snap.digest) == before
    assert store.get("t1", snap.snapshot_id).canonical == before[0]


def test_tc097_matching_reads_on_one_snapshot_pass():
    store, ledger = make()
    snap = mk(store)
    rec = go(ledger, snap)
    assert (rec.state, rec.reason_code) == (ComparisonState.PASS, "ALL_VALUES_EQUAL")
    assert rec.snapshot_digest == snap.digest and rec.known_at == T0


def test_value_difference_fails_with_named_measure():
    store, ledger = make()
    snap = mk(store, {"closing_credit": Decimal(24)}, {"closing_credit": Decimal(25)})
    rec = go(ledger, snap)
    assert rec.state == ComparisonState.FAIL and rec.differences == ("closing_credit",)
    assert rec.reason_code == "VALUES_DIFFER"


def test_decimal_equality_is_numeric_not_textual():
    store, ledger = make()
    snap = mk(store, {"v": Decimal("1.50")}, {"v": Decimal("1.5")})
    assert go(ledger, snap).state == ComparisonState.PASS


def test_both_sides_must_reference_the_same_snapshot():
    store, ledger = make()
    s1 = mk(store)
    s2 = store.create("t1", {"other": 1}, known_at=T0)
    rec = ledger.run("t1", "k1", read("native", s1), read("gateway", s2), snapshot_id=s1.snapshot_id)
    assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "SNAPSHOT_REFERENCE_MISMATCH")
    rec = ledger.run("t1", "k2", read("native", s2), read("gateway", s2), snapshot_id=s1.snapshot_id)
    assert rec.reason_code == "SNAPSHOT_REFERENCE_MISMATCH"


def test_unknown_snapshot_and_other_tenant_are_inconclusive():
    store, ledger = make()
    snap = mk(store)
    rec = go(ledger, snap, tenant="t2")
    assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "SNAPSHOT_UNKNOWN")


def test_read_digest_not_matching_snapshot_is_inconclusive():
    store, ledger = make()
    snap = mk(store)
    bad = canonical_digest({"mutated": True})
    rec = ledger.run("t1", KEY, read("native", snap, bad), read("gateway", snap, bad),
                     snapshot_id=snap.snapshot_id)
    assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "SNAPSHOT_DIGEST_MISMATCH")


def test_empty_observations_are_inconclusive_not_pass():
    store, ledger = make()
    snap = mk(store)
    rec = ledger.run("t1", KEY, SideRead("native", snap.snapshot_id, snap.digest, {}),
                     SideRead("gateway", snap.snapshot_id, snap.digest, {}), snapshot_id=snap.snapshot_id)
    assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "NO_OBSERVATIONS")


# ---- each side's values are verified against the snapshot ----
def test_values_not_contained_in_the_snapshot_are_inconclusive_never_pass():
    store, ledger = make()
    snap = mk(store)  # snapshot holds closing_credit 24 on both sides
    forged = {"closing_credit": Decimal(25)}
    for n, g, key in ((forged, forged, "k1"), (forged, CC24, "k2"), (CC24, forged, "k3"),
                      ({**CC24, "extra": Decimal(1)}, CC24, "k4")):
        rec = ledger.run("t1", key, read("native", snap, values=n), read("gateway", snap, values=g),
                         snapshot_id=snap.snapshot_id)
        assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "SIDE_VALUES_NOT_IN_SNAPSHOT")


def test_snapshot_without_a_values_projection_cannot_pass():
    store, ledger = make()
    for i, payload in enumerate((FIXTURE, {"values": {"native": {"v": Decimal(1)}}}, {"values": 5},
                                 {"values": {"native": {"v": 1}, "gateway": {"v": 1}}})):
        snap = store.create("t1", payload, known_at=T0)
        rec = ledger.run("t1", f"k{i}", read("native", snap, values={"v": Decimal(1)}),
                         read("gateway", snap, values={"v": Decimal(1)}), snapshot_id=snap.snapshot_id)
        assert (rec.state, rec.reason_code) == (ComparisonState.INCONCLUSIVE, "SNAPSHOT_VALUES_MISSING")


def test_side_labels_must_match_and_identical_reads_are_rejected():
    store, ledger = make()
    snap = mk(store)
    n, g = read("native", snap), read("gateway", snap)
    cases = (
        (n, n, "SIDE_READS_IDENTICAL"),
        (g, n, "SIDE_LABEL_INVALID"),
        (n, read("native", snap), "SIDE_LABEL_INVALID"),
        (read("gateway", snap), g, "SIDE_LABEL_INVALID"),
        (n, SideRead("gateway", snap.snapshot_id, snap.digest, n.values), "SIDE_READS_IDENTICAL"),
        (n, "gateway", "SIDE_READ_INVALID"),
    )
    for native, gateway, code in cases:
        with pytest.raises(ComparisonSnapshotError) as exc:
            ledger.run("t1", KEY, native, gateway, snapshot_id=snap.snapshot_id)  # type: ignore[arg-type]
        assert exc.value.code == code
    assert ledger.list_runs("t1", KEY) == ()


# ---- TC098: correction between reads ----
@pytest.mark.parametrize("changed_side", ["native", "gateway"])
def test_tc098_correction_between_reads_is_inconclusive_never_pass(changed_side):
    store, ledger = make()
    snap = mk(store)
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
    now_snap = mk(store, known_at=T0 + timedelta(days=5))
    first = go(ledger, now_snap)
    before = (first, first.native_values, first.gateway_values, first.known_at, first.snapshot_digest)

    old_snap = mk(store, {"closing_credit": Decimal(23)}, known_at=T0,
                  rows=[{"ref": "A", "amount": Decimal(9)}])  # backdated
    assert old_snap.known_at < now_snap.known_at
    second = go(ledger, old_snap, rerun_of=first.run_id)

    assert second.run_id != first.run_id and second.supersedes == first.run_id
    views = ledger.list_runs("t1", KEY)
    assert [v.record.run_id for v in views] == [first.run_id, second.run_id]
    assert [v.status for v in views] == ["SUPERSEDED", "CURRENT"]
    assert views[0].superseded_by == second.run_id and views[1].superseded_by is None
    assert ledger.current("t1", KEY) is second
    # original still readable and byte-for-byte the same numbers
    again = ledger.get("t1", first.run_id)
    assert again is first
    assert (again, again.native_values, again.gateway_values, again.known_at,
            again.snapshot_digest) == before
    assert dict(again.native_values) == {"closing_credit": Decimal(24)}
    assert dict(second.native_values) == {"closing_credit": Decimal(23)}


def test_tc099_chain_only_supersedes_current_head_and_runs_are_frozen():
    store, ledger = make()
    snap = mk(store)
    r1 = go(ledger, snap)
    r2 = go(ledger, snap, rerun_of=r1.run_id)
    with pytest.raises(ComparisonSnapshotError) as exc:
        go(ledger, snap, rerun_of=r1.run_id)
    assert exc.value.code == "RERUN_TARGET_ALREADY_SUPERSEDED"
    assert len(ledger.list_runs("t1", KEY)) == 2  # failed rerun left no trace
    r3 = go(ledger, snap, rerun_of=r2.run_id)
    assert [v.status for v in ledger.list_runs("t1", KEY)] == ["SUPERSEDED", "SUPERSEDED", "CURRENT"]
    assert r3.supersedes == r2.run_id and ledger.current("t1", KEY) is r3
    with pytest.raises(AttributeError):
        r1.state = ComparisonState.FAIL  # type: ignore[misc]


def test_rerun_target_must_exist_in_same_tenant_and_key():
    store, ledger = make()
    snap = mk(store)
    r1 = go(ledger, snap)
    for tenant, key, target in (("t2", KEY, r1.run_id), ("t1", "other-key", r1.run_id), ("t1", KEY, "run-999999")):
        s = mk(store, tenant=tenant)
        with pytest.raises(ComparisonSnapshotError) as exc:
            go(ledger, s, key=key, tenant=tenant, rerun_of=target)
        assert exc.value.code == "RERUN_TARGET_UNKNOWN"
    assert ledger.list_runs("t1", KEY)[0].status == "CURRENT"


# ---- supersession rule: one chain per key, current() = latest decisive run ----
def test_second_run_for_an_existing_key_without_rerun_of_is_refused():
    store, ledger = make()
    snap = mk(store)
    first = go(ledger, snap)
    with pytest.raises(ComparisonSnapshotError) as exc:
        go(ledger, snap)
    assert exc.value.code == "RERUN_REQUIRED"
    assert [v.record for v in ledger.list_runs("t1", KEY)] == [first]
    assert ledger.current("t1", KEY) is first
    # another tenant or another key is an independent chain
    go(ledger, mk(store, tenant="t2"), tenant="t2")
    go(ledger, snap, key="other")


def test_inconclusive_rerun_does_not_hide_the_only_decisive_run():
    store, ledger = make()
    snap = mk(store)
    decisive = go(ledger, snap)
    bad = canonical_digest({"drift": 1})
    drifted = ledger.run("t1", KEY, read("native", snap, bad), read("gateway", snap),
                         snapshot_id=snap.snapshot_id, rerun_of=decisive.run_id)
    assert drifted.state is ComparisonState.INCONCLUSIVE
    views = ledger.list_runs("t1", KEY)
    assert [v.status for v in views] == ["CURRENT", "LATEST_ATTEMPT"]
    assert views[0].superseded_by == drifted.run_id  # raw chain relation is kept
    assert ledger.current("t1", KEY) is decisive
    assert ledger.get("t1", decisive.run_id) is decisive
    # a later decisive rerun takes over
    final = go(ledger, snap, rerun_of=drifted.run_id)
    assert ledger.current("t1", KEY) is final
    assert [v.status for v in ledger.list_runs("t1", KEY)] == ["SUPERSEDED", "SUPERSEDED", "CURRENT"]


def test_double_drift_inconclusive_has_no_current_and_both_attempts_listed():
    store, ledger = make()
    snap = mk(store)
    bad = canonical_digest({"drift": 1})
    first = ledger.run("t1", KEY, read("native", snap, bad), read("gateway", snap),
                       snapshot_id=snap.snapshot_id)
    second = ledger.run("t1", KEY, read("native", snap), read("gateway", snap, bad),
                        snapshot_id=snap.snapshot_id, rerun_of=first.run_id)
    assert (first.state, second.state) == (ComparisonState.INCONCLUSIVE,) * 2
    assert (first.reason_code, second.reason_code) == ("SOURCE_CHANGED_BETWEEN_READS",) * 2
    assert ledger.current("t1", KEY) is None
    assert [(v.record.run_id, v.status) for v in ledger.list_runs("t1", KEY)] == [
        (first.run_id, "SUPERSEDED"), (second.run_id, "LATEST_ATTEMPT")]
    assert ledger.current("t2", KEY) is None and ledger.current("t1", "nope") is None


def test_fail_is_decisive_and_current():
    store, ledger = make()
    snap = mk(store, {"v": Decimal(1)}, {"v": Decimal(2)})
    failed = go(ledger, snap)
    assert failed.state is ComparisonState.FAIL
    assert ledger.current("t1", KEY) is failed


def test_listing_is_scoped_by_tenant_and_key():
    store, ledger = make()
    go(ledger, mk(store))
    assert ledger.list_runs("t2", KEY) == () and ledger.list_runs("t1", "x") == ()


# ---- input validation ----
@pytest.mark.parametrize("payload,code", [
    ({"f": 1.5}, "PAYLOAD_TYPE_UNSUPPORTED"),
    ({"d": Decimal("NaN")}, "FINITE_DECIMAL_REQUIRED"),
    ({"d": datetime(2026, 1, 1)}, "TIMEZONE_REQUIRED"),  # noqa: DTZ001
    ({1: "x"}, "PAYLOAD_KEY_NOT_TEXT"),
    ({"d": Decimal("1e100000")}, "DECIMAL_PRECISION_EXCEEDED"),
    ({"$dec": "1"}, "PAYLOAD_KEY_RESERVED"),
    ({"i": 10 ** 5000}, "PAYLOAD_UNENCODABLE"),
    ({"d": datetime.max.replace(tzinfo=timezone(timedelta(hours=-12)))}, "TIMESTAMP_OUT_OF_RANGE"),
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
        store.create("t1", {}, known_at=datetime.min.replace(tzinfo=timezone(timedelta(hours=12))))
    assert exc.value.code == "TIMESTAMP_OUT_OF_RANGE"
    with pytest.raises(ComparisonSnapshotError) as exc:
        store.create("", {})
    assert exc.value.code == "TENANT_REQUIRED"


def test_side_values_must_be_decimals():
    store, ledger = make()
    snap = mk(store)
    bad = SideRead("native", snap.snapshot_id, snap.digest, {"v": 1.0})  # type: ignore[dict-item]
    with pytest.raises(ComparisonSnapshotError) as exc:
        ledger.run("t1", KEY, bad, read("gateway", snap), snapshot_id=snap.snapshot_id)
    assert exc.value.code == "FINITE_DECIMAL_REQUIRED"
    assert ledger.list_runs("t1", KEY) == ()


def test_stored_numbers_do_not_change_when_the_caller_mutates_its_input_after_run():
    store, ledger = make()
    snap = mk(store)
    n_in, g_in = dict(CC24), dict(CC24)
    rec = ledger.run("t1", KEY, SideRead("native", snap.snapshot_id, snap.digest, n_in),
                     SideRead("gateway", snap.snapshot_id, snap.digest, g_in),
                     snapshot_id=snap.snapshot_id)
    assert rec.state is ComparisonState.PASS
    n_in["closing_credit"] = Decimal(999)
    n_in["injected"] = Decimal(1)
    g_in.clear()
    stored = ledger.get("t1", rec.run_id)
    assert stored is rec
    assert dict(rec.native_values) == CC24 and dict(rec.gateway_values) == CC24
    assert (rec.state, rec.reason_code, rec.differences) == (ComparisonState.PASS, "ALL_VALUES_EQUAL", ())
    assert dict(ledger.current("t1", KEY).native_values) == CC24


# ---- concurrency ----
def test_concurrent_runs_get_unique_sequential_ids_and_decisive_states():
    store, ledger = make()
    snap = mk(store)
    out, errors = [], []

    def work(i):
        try:
            out.append(go(ledger, snap, key=f"{KEY}:{i}"))
        except ComparisonSnapshotError as exc:  # would fail the assertions below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len({r.run_id for r in out}) == 32
    assert sorted(r.seq for r in out) == list(range(1, 33))
    assert {(r.state, r.reason_code) for r in out} == {(ComparisonState.PASS, "ALL_VALUES_EQUAL")}
    assert all(ledger.current("t1", f"{KEY}:{i}") is not None for i in range(32))


def test_concurrent_runs_for_one_key_admit_exactly_one_first_run():
    store, ledger = make()
    snap = mk(store)
    won, refused = [], []

    def work():
        try:
            won.append(go(ledger, snap))
        except ComparisonSnapshotError as exc:
            refused.append(exc.code)

    threads = [threading.Thread(target=work) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 1 and refused == ["RERUN_REQUIRED"] * 15
    assert len(ledger.list_runs("t1", KEY)) == 1


def test_concurrent_reruns_of_one_target_admit_exactly_one():
    store, ledger = make()
    snap = mk(store)
    first = go(ledger, snap)
    won, refused = [], []

    def work():
        try:
            won.append(go(ledger, snap, rerun_of=first.run_id))
        except ComparisonSnapshotError as exc:
            refused.append(exc.code)

    threads = [threading.Thread(target=work) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 1 and refused == ["RERUN_TARGET_ALREADY_SUPERSEDED"] * 15
    assert [v.status for v in ledger.list_runs("t1", KEY)] == ["SUPERSEDED", "CURRENT"]


def test_recorded_at_is_taken_inside_the_lock_so_it_follows_run_order():
    tick = {"n": 0}
    guard = threading.Lock()

    def clock():
        with guard:
            tick["n"] += 1
            return T0 + timedelta(days=10, microseconds=tick["n"])

    store = SnapshotStore(clock)
    ledger = RunLedger(store)
    snap = mk(store)
    out = []

    def work(i):
        out.append(go(ledger, snap, key=f"k{i}"))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    by_seq = sorted(out, key=lambda r: r.seq)
    stamps = [r.recorded_at for r in by_seq]
    assert stamps == sorted(stamps) and len(set(stamps)) == 32
