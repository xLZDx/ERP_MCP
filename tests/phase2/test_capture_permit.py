"""R2-US-024 bounded capture permit: TC070 / TC071 / TC072 (behavioural, deterministic)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from business_ai_gateway.phase2.capture_permit import (
    AuditEntry,
    CaptureMode,
    Environment,
    Issuer,
    IssuerKind,
    IssueStatus,
    PermitRequest,
    PermitStore,
    _aware,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(hours=2)
DIGEST = "a" * 64
OWNER = Issuer(IssuerKind.HUMAN, "owner-1")
REQ = PermitRequest(
    tenant_id="tenant-a", source_id="src-1", mode=CaptureMode.READ_SNAPSHOT,
    environment=Environment.NON_PROD, not_before=T0, not_after=T1,
    params_digest=DIGEST, requester="requester-1",
)
SNAP = CaptureMode.READ_SNAPSHOT
INCR = CaptureMode.READ_INCREMENTAL
ZWSP = chr(0x200B)
OWNERS = {
    ("tenant-a", "src-1"): frozenset({"owner-1", "owner-2"}),
    ("tenant-a", "src-2"): frozenset({"owner-1"}),
    ("tenant-b", "src-1"): frozenset({"owner-1"}),
}

FIXED_CODES = frozenset({
    "ISSUED", "REPLAYED", "ADMITTED", "REVOKED", "REVOKE_DENIED", "PERMIT_NOT_ADMITTABLE",
    "PERMIT_REVOKED", "MODE_MISMATCH", "PARAMS_MISMATCH", "REQUESTER_MISMATCH", "PROD_DISABLED",
    "NOT_YET_VALID", "EXPIRED", "TIME_INVALID", "USES_EXHAUSTED", "IDEMPOTENCY_KEY_INVALID",
    "IDEMPOTENCY_CONFLICT", "REQUEST_INVALID", "ISSUER_INVALID", "ISSUER_NOT_HUMAN",
    "ISSUER_NOT_OWNER", "ISSUER_IS_REQUESTER", "SCOPE_INVALID", "REQUESTER_INVALID",
    "MODE_INVALID", "ENVIRONMENT_INVALID", "WINDOW_INVALID", "DIGEST_INVALID",
    "MAX_USES_INVALID", "ID_UNAVAILABLE",
})


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make(**kw) -> tuple[PermitStore, Clock]:
    clock = Clock()
    kw.setdefault("owners", OWNERS)
    return PermitStore(clock, **kw), clock


def issued(store: PermitStore, req: PermitRequest = REQ, key: str = "k1"):
    res = store.issue(key, req, OWNER)
    assert res.status is IssueStatus.ISSUED and res.permit is not None
    return res.permit


def adm(store: PermitStore, pid, tenant="tenant-a", source="src-1", mode=SNAP,
        digest=DIGEST, requester="requester-1"):
    return store.admit(pid, tenant, source, mode, digest, requester)


class _BadTz(tzinfo):
    """tzinfo whose utcoffset raises."""

    def utcoffset(self, dt):
        raise RuntimeError("secret-detail")


def _hostile_values() -> list[datetime]:
    return [
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5))),
        datetime(9999, 12, 31, 23, tzinfo=timezone(timedelta(hours=-5))),
        datetime(2026, 1, 1, tzinfo=_BadTz()),
    ]


def test_tc070_control_allowed_and_each_violation_alone_denied() -> None:
    store, clock = make()
    p = issued(store)
    ok = adm(store, p.permit_id)
    assert ok.allowed and ok.code == "ADMITTED"
    cases = {
        "tenant": ({"tenant": "tenant-b"}, T0, "PERMIT_NOT_ADMITTABLE"),
        "source": ({"source": "src-2"}, T0, "PERMIT_NOT_ADMITTABLE"),
        "mode": ({"mode": INCR}, T0, "MODE_MISMATCH"),
        "digest": ({"digest": "b" * 64}, T0, "PARAMS_MISMATCH"),
        "requester": ({"requester": "requester-2"}, T0, "REQUESTER_MISMATCH"),
        "before": ({}, T0 - timedelta(seconds=1), "NOT_YET_VALID"),
        "after": ({}, T1 + timedelta(seconds=1), "EXPIRED"),
    }
    for name, (kw, at, code) in cases.items():
        clock.now = at
        res = adm(store, p.permit_id, **kw)
        assert (res.allowed, res.code) == (False, code), name


def test_tc070_wrong_types_return_codes_not_exceptions() -> None:
    store, clock = make()
    p = issued(store)
    assert adm(store, None).code == "PERMIT_NOT_ADMITTABLE"
    assert adm(store, "nope").code == "PERMIT_NOT_ADMITTABLE"
    assert adm(store, p.permit_id, tenant=5).code == "PERMIT_NOT_ADMITTABLE"
    assert adm(store, p.permit_id, mode="READ_SNAPSHOT").code == "MODE_MISMATCH"
    assert adm(store, p.permit_id, digest=None).code == "PARAMS_MISMATCH"
    assert adm(store, p.permit_id, requester=None).code == "REQUESTER_MISMATCH"
    clock.now = datetime(2026, 1, 1, 12, 30)  # type: ignore[assignment]  # noqa: DTZ001 - naive on purpose
    assert adm(store, p.permit_id).code == "TIME_INVALID"


def test_admit_has_no_caller_chosen_time() -> None:
    store, _ = make()
    p = issued(store)
    with pytest.raises(TypeError):
        store.admit(p.permit_id, "tenant-a", "src-1", SNAP, DIGEST, "requester-1", T0)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        store.admit(p.permit_id, "tenant-a", "src-1", SNAP)  # type: ignore[call-arg]


def test_aware_never_raises() -> None:
    for v in _hostile_values():
        assert _aware(v) is None


def test_hostile_datetimes_are_refused_not_raised_at_issue_and_use() -> None:
    store, clock = make()
    for v in _hostile_values():
        assert store.issue("h1", replace(REQ, not_before=v), OWNER).code == "WINDOW_INVALID"
        assert store.issue("h2", replace(REQ, not_after=v), OWNER).code == "WINDOW_INVALID"
    assert store.count() == 0
    p = issued(store)
    for v in _hostile_values():
        clock.now = v
        res = adm(store, p.permit_id)
        assert (res.allowed, res.code) == (False, "TIME_INVALID")


def test_oracle_cross_tenant_unknown_and_revoked_are_indistinguishable() -> None:
    store, _ = make()
    p = issued(store)
    gone = issued(store, REQ, "k2")
    assert store.revoke(gone.permit_id, "tenant-a", OWNER).revoked
    nonexistent = adm(store, "f" * 32, tenant="tenant-b")
    cross_tenant = adm(store, p.permit_id, tenant="tenant-b")
    cross_source = adm(store, p.permit_id, source="src-2")
    revoked = adm(store, gone.permit_id)
    revoked_wrong_scope = adm(store, gone.permit_id, tenant="tenant-b")
    assert nonexistent == cross_tenant == cross_source == revoked == revoked_wrong_scope
    assert nonexistent == adm(store, p.permit_id, tenant="tenant-b", mode=INCR, digest="c" * 64)
    assert (nonexistent.allowed, nonexistent.code) == (False, "PERMIT_NOT_ADMITTABLE")


def test_permit_ids_are_random_not_derived_from_inputs() -> None:
    a, _ = make()
    b, _ = make()
    pa, pb = issued(a), issued(b)  # identical tenant + key + request in two stores
    assert pa.permit_id != pb.permit_id
    for pid in (pa.permit_id, pb.permit_id):
        assert len(pid) == 32 and set(pid) <= set("0123456789abcdef")


def test_id_source_is_injectable_and_collisions_fail_closed() -> None:
    ids = iter(["id-one", "id-two"])
    store, _ = make(id_source=lambda: next(ids))
    assert issued(store, REQ, "k1").permit_id == "id-one"
    assert issued(store, REQ, "k2").permit_id == "id-two"
    const, _ = make(id_source=lambda: "same")
    issued(const, REQ, "k1")
    res = const.issue("k2", REQ, OWNER)
    assert (res.status, res.permit, res.code) == (IssueStatus.REFUSED, None, "ID_UNAVAILABLE")
    assert const.count() == 1

    def boom() -> str:
        raise RuntimeError("x")

    broken, _ = make(id_source=boom)
    assert broken.issue("k", REQ, OWNER).code == "ID_UNAVAILABLE"
    with pytest.raises(TypeError):
        make(id_source="nope")  # type: ignore[arg-type]


def test_issuer_must_be_registered_owner_of_that_scope() -> None:
    store, _ = make()
    stranger = store.issue("k", REQ, Issuer(IssuerKind.HUMAN, "someone-else"))
    assert (stranger.status, stranger.permit, stranger.code) == (IssueStatus.REFUSED, None, "ISSUER_NOT_OWNER")
    other_source = store.issue("k", replace(REQ, source_id="src-3"), OWNER)  # owner-1 owns src-1/src-2 only
    assert other_source.code == "ISSUER_NOT_OWNER"
    other_tenant = store.issue("k", replace(REQ, tenant_id="tenant-c"), OWNER)
    assert other_tenant.code == "ISSUER_NOT_OWNER"
    # owner-2 owns src-1 but not src-2
    assert store.issue("k", replace(REQ, source_id="src-2"), Issuer(IssuerKind.HUMAN, "owner-2")).code == "ISSUER_NOT_OWNER"
    assert store.issue("k", REQ, Issuer(IssuerKind.HUMAN, " OWNER-2 ")).status is IssueStatus.ISSUED
    assert store.count() == 1


def test_empty_or_default_registry_refuses_everything() -> None:
    for store in (PermitStore(Clock()), PermitStore(Clock(), owners={})):
        assert store.issue("k", REQ, OWNER).code == "ISSUER_NOT_OWNER"
        assert store.count() == 0


def test_owners_registry_is_normalised_and_validated() -> None:
    store = PermitStore(Clock(), owners={(" TENANT-A ", "SRC-1"): frozenset({" Owner-1 "})})
    assert store.issue("k", REQ, OWNER).status is IssueStatus.ISSUED
    with pytest.raises(ValueError):
        PermitStore(Clock(), owners={("", "src-1"): frozenset({"owner-1"})})
    with pytest.raises(ValueError):
        PermitStore(Clock(), max_audit=0)


def test_tc071_prod_default_off_at_issue_and_at_use() -> None:
    store, _ = make()
    prod = replace(REQ, environment=Environment.PROD)
    res = store.issue("k-prod", prod, OWNER)
    assert (res.status, res.permit, res.code) == (IssueStatus.REFUSED, None, "PROD_DISABLED")
    assert store.count() == 0
    # a refused PROD issue is not remembered: same key with a different request is a fresh ISSUED
    assert store.issue("k-prod", REQ, OWNER).status is IssueStatus.ISSUED

    on, _ = make(prod_enabled=True)
    p = issued(on, prod, "k-prod")
    assert adm(on, p.permit_id).allowed
    assert on.set_prod_enabled(False, OWNER)
    res2 = adm(on, p.permit_id)
    assert (res2.allowed, res2.code) == (False, "PROD_DISABLED")
    assert on.set_prod_enabled("yes") is False  # type: ignore[arg-type]


def test_tc071_boundary_instants_exact_and_clock_used() -> None:
    store, clock = make()
    p = issued(store)
    clock.now = T0 - timedelta(microseconds=1)
    assert adm(store, p.permit_id).code == "NOT_YET_VALID"
    clock.now = T0
    assert adm(store, p.permit_id).allowed  # not_before inclusive
    clock.now = T1 - timedelta(microseconds=1)
    assert adm(store, p.permit_id).allowed
    clock.now = T1
    assert adm(store, p.permit_id).code == "EXPIRED"  # not_after exclusive
    clock.now = datetime(2026, 1, 1, 13, 0, tzinfo=timezone(timedelta(hours=1)))  # = 12:00Z
    assert adm(store, p.permit_id).allowed


def test_tc071_naive_datetime_rejected_and_broken_clock_fails_closed() -> None:
    store, clock = make()
    naive = datetime(2026, 1, 1, 12, 0)  # noqa: DTZ001 - naive on purpose
    for bad in (replace(REQ, not_before=naive), replace(REQ, not_after=naive)):
        assert store.issue("k", bad, OWNER).code == "WINDOW_INVALID"
    p = issued(store)
    clock.now = naive  # type: ignore[assignment]
    assert adm(store, p.permit_id).code == "TIME_INVALID"

    def boom() -> datetime:
        raise RuntimeError("secret-detail")

    broken = PermitStore(boom, owners=OWNERS)
    bp = issued(broken)
    res = adm(broken, bp.permit_id)
    assert (res.allowed, res.code) == (False, "TIME_INVALID")
    assert "secret-detail" not in repr(res)


def test_window_must_be_nonempty_and_bounded() -> None:
    store, _ = make()
    assert store.issue("a", replace(REQ, not_after=T0), OWNER).code == "WINDOW_INVALID"
    assert store.issue("b", replace(REQ, not_after=T0 - timedelta(hours=1)), OWNER).code == "WINDOW_INVALID"
    assert store.issue("c", replace(REQ, not_after=T0 + timedelta(hours=24, seconds=1)), OWNER).code == "WINDOW_INVALID"
    assert store.issue("d", replace(REQ, not_after=T0 + timedelta(hours=24)), OWNER).status is IssueStatus.ISSUED
    small = PermitStore(Clock(), max_window=timedelta(minutes=5), owners=OWNERS)
    assert small.issue("e", REQ, OWNER).code == "WINDOW_INVALID"


def test_tc072_same_key_same_params_replays_without_second_permit() -> None:
    store, _ = make()
    first = store.issue("k1", REQ, OWNER)
    second = store.issue("k1", REQ, OWNER)
    assert first.status is IssueStatus.ISSUED and second.status is IssueStatus.REPLAYED
    assert second.permit == first.permit and second.permit is not None
    assert store.count() == 1


def test_tc072_same_key_different_params_conflicts_and_store_unchanged() -> None:
    store, _ = make()
    first = issued(store)
    variants = [
        (REQ, Issuer(IssuerKind.HUMAN, "owner-2")),  # different HUMAN (registered) issuer
        (replace(REQ, params_digest="b" * 64), OWNER),
        (replace(REQ, source_id="src-2"), OWNER),
        (replace(REQ, mode=INCR), OWNER),
        (replace(REQ, not_after=T1 + timedelta(minutes=1)), OWNER),
        (replace(REQ, not_before=T0 + timedelta(minutes=1)), OWNER),
        (replace(REQ, requester="requester-2"), OWNER),
        (replace(REQ, environment=Environment.PROD), OWNER),
        (replace(REQ, max_uses=3), OWNER),
    ]
    for v, who in variants:
        res = store.issue("k1", v, who)
        assert (res.status, res.permit, res.code) == (IssueStatus.REFUSED, None, "IDEMPOTENCY_CONFLICT")
        assert store.count() == 1
    assert adm(store, first.permit_id).allowed
    assert store.issue("k1", REQ, OWNER).status is IssueStatus.REPLAYED


def test_tc072_concurrent_same_key_issues_exactly_one() -> None:
    store, _ = make()
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: store.issue("kc", REQ, OWNER), range(16)))
    statuses = [r.status for r in results]
    assert statuses.count(IssueStatus.ISSUED) == 1
    assert statuses.count(IssueStatus.REPLAYED) == 15
    assert len({r.permit.permit_id for r in results}) == 1
    assert store.count() == 1


def test_tc072_different_keys_and_tenants_are_independent() -> None:
    store, _ = make()
    a = issued(store, REQ, "k1")
    b = issued(store, REQ, "k2")
    c = issued(store, replace(REQ, tenant_id="tenant-b"), "k1")  # same key, other tenant
    assert len({a.permit_id, b.permit_id, c.permit_id}) == 3
    assert store.count() == 3


def test_replay_after_revoke_or_prod_disable_is_refused_not_live() -> None:
    store, _ = make()
    p = issued(store)
    assert store.revoke(p.permit_id, "tenant-a", OWNER).revoked
    res = store.issue("k1", REQ, OWNER)
    assert (res.status, res.permit, res.code) == (IssueStatus.REFUSED, None, "PERMIT_REVOKED")

    prod = replace(REQ, environment=Environment.PROD)
    on, _ = make(prod_enabled=True)
    issued(on, prod, "kp")
    assert on.issue("kp", prod, OWNER).status is IssueStatus.REPLAYED
    on.set_prod_enabled(False, OWNER)
    res2 = on.issue("kp", prod, OWNER)
    assert (res2.status, res2.permit, res2.code) == (IssueStatus.REFUSED, None, "PROD_DISABLED")
    assert on.count() == 1


def test_empty_store_is_truthy_and_counts() -> None:
    store, _ = make()
    assert bool(store) and store.count() == 0


def test_admit_case_variants_and_precedence_order() -> None:
    store, clock = make()
    p = issued(store)
    assert adm(store, p.permit_id, tenant=" TENANT-A ", source="SRC-1", requester=" Requester-1 ").allowed
    clock.now = T1 + timedelta(hours=1)  # window violated in every call below
    bad = {"mode": INCR, "digest": "b" * 64, "requester": "requester-2"}
    # order: scope -> mode -> params -> requester -> prod -> window
    assert adm(store, p.permit_id, tenant="tenant-b", **bad).code == "PERMIT_NOT_ADMITTABLE"
    assert adm(store, p.permit_id, **bad).code == "MODE_MISMATCH"
    assert adm(store, p.permit_id, digest="b" * 64, requester="requester-2").code == "PARAMS_MISMATCH"
    assert adm(store, p.permit_id, requester="requester-2").code == "REQUESTER_MISMATCH"
    assert adm(store, p.permit_id).code == "EXPIRED"
    assert store.revoke(p.permit_id, "tenant-a", OWNER).revoked
    assert adm(store, p.permit_id, tenant="tenant-b", **bad).code == "PERMIT_NOT_ADMITTABLE"
    assert adm(store, p.permit_id).code == "PERMIT_NOT_ADMITTABLE"

    prod = replace(REQ, environment=Environment.PROD)
    on, c2 = make(prod_enabled=True)
    pp = issued(on, prod, "kp")
    on.set_prod_enabled(False, OWNER)
    c2.now = T1 + timedelta(hours=1)
    assert adm(on, pp.permit_id).code == "PROD_DISABLED"
    assert adm(on, pp.permit_id, mode=INCR).code == "MODE_MISMATCH"


def test_max_uses_enforced_and_validated() -> None:
    store, _ = make()
    for bad in (0, -1, True, "2", 1.5):
        assert store.issue("bad", replace(REQ, max_uses=bad), OWNER).code == "MAX_USES_INVALID"  # type: ignore[arg-type]
    assert store.count() == 0
    p = issued(store, replace(REQ, max_uses=2))
    assert p.max_uses == 2
    assert adm(store, p.permit_id, requester="requester-2").code == "REQUESTER_MISMATCH"  # not consumed
    assert adm(store, p.permit_id).allowed
    assert adm(store, p.permit_id).allowed
    res = adm(store, p.permit_id)
    assert (res.allowed, res.code) == (False, "USES_EXHAUSTED")
    unlimited = issued(store, REQ, "k-unlimited")
    assert unlimited.max_uses is None
    assert all(adm(store, unlimited.permit_id).allowed for _ in range(5))


def test_max_uses_holds_under_concurrency() -> None:
    store, _ = make()
    p = issued(store, replace(REQ, max_uses=3))
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: adm(store, p.permit_id), range(16)))
    assert sum(r.allowed for r in results) == 3
    assert {r.code for r in results if not r.allowed} == {"USES_EXHAUSTED"}


def test_issuer_must_be_human() -> None:
    store, _ = make()
    for kind in (IssuerKind.LLM, IssuerKind.AUTOMATION):
        res = store.issue("k", REQ, Issuer(kind, "owner-1"))
        assert (res.status, res.code) == (IssueStatus.REFUSED, "ISSUER_NOT_HUMAN")
    assert store.issue("k", REQ, Issuer("HUMAN", "owner-1")).code == "ISSUER_INVALID"  # type: ignore[arg-type]
    assert store.issue("k", REQ, None).code == "ISSUER_INVALID"  # type: ignore[arg-type]
    assert store.issue("k", REQ, Issuer(IssuerKind.HUMAN, "  ")).code == "ISSUER_INVALID"
    assert store.count() == 0


@pytest.mark.parametrize("issuer_id", ["requester-1", "REQUESTER-1", " Requester-1 ", "ｒequester-1"])
def test_issuer_equal_to_requester_refused_after_normalisation(issuer_id: str) -> None:
    store, _ = make()
    res = store.issue("k", REQ, Issuer(IssuerKind.HUMAN, issuer_id))
    assert res.code == "ISSUER_IS_REQUESTER" and store.count() == 0


def test_zero_width_variant_is_invalid_not_a_distinct_person() -> None:
    store, _ = make()
    res = store.issue("k", REQ, Issuer(IssuerKind.HUMAN, "requester" + ZWSP + "-1"))
    assert res.status is IssueStatus.REFUSED and res.code == "ISSUER_INVALID"
    res2 = store.issue("k", replace(REQ, requester="requester" + ZWSP + "-1"), OWNER)
    assert res2.code == "REQUESTER_INVALID"
    assert store.count() == 0


def test_bad_digest_and_bad_fields_rejected() -> None:
    store, _ = make()
    for bad in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, "", None, 12):
        assert store.issue("k", replace(REQ, params_digest=bad), OWNER).code == "DIGEST_INVALID"  # type: ignore[arg-type]
    assert store.issue("k", replace(REQ, tenant_id=""), OWNER).code == "SCOPE_INVALID"
    assert store.issue("k", replace(REQ, source_id=None), OWNER).code == "SCOPE_INVALID"  # type: ignore[arg-type]
    assert store.issue("k", replace(REQ, mode="READ_SNAPSHOT"), OWNER).code == "MODE_INVALID"  # type: ignore[arg-type]
    assert store.issue("k", replace(REQ, environment="PROD"), OWNER).code == "ENVIRONMENT_INVALID"  # type: ignore[arg-type]
    assert store.issue("", REQ, OWNER).code == "IDEMPOTENCY_KEY_INVALID"
    assert store.issue(None, REQ, OWNER).code == "IDEMPOTENCY_KEY_INVALID"  # type: ignore[arg-type]
    assert store.issue("k", "not a request", OWNER).code == "REQUEST_INVALID"  # type: ignore[arg-type]
    assert store.count() == 0


def test_revoke_only_by_registered_issuer_in_own_tenant_with_single_denial_code() -> None:
    store, _ = make()
    p = issued(store)
    denied = [
        store.revoke(p.permit_id, "tenant-a", Issuer(IssuerKind.HUMAN, "someone-else")),
        store.revoke(p.permit_id, "tenant-a", Issuer(IssuerKind.HUMAN, "owner-2")),  # owner, not the issuer
        store.revoke(p.permit_id, "tenant-a", Issuer(IssuerKind.AUTOMATION, "owner-1")),
        store.revoke(p.permit_id, "tenant-a", Issuer(IssuerKind.HUMAN, "owner" + ZWSP + "-1")),
        store.revoke(p.permit_id, "tenant-b", OWNER),  # right person, wrong tenant
        store.revoke(p.permit_id, None, OWNER),  # type: ignore[arg-type]
        store.revoke("nope", "tenant-a", OWNER),  # unknown: same code as not-issuer
        store.revoke(None, "tenant-a", OWNER),  # type: ignore[arg-type]
    ]
    assert {(r.revoked, r.code) for r in denied} == {(False, "REVOKE_DENIED")}
    assert adm(store, p.permit_id).allowed
    res = store.revoke(p.permit_id, " Tenant-A ", Issuer(IssuerKind.HUMAN, "OWNER-1"))
    assert (res.revoked, res.code) == (True, "REVOKED")
    assert adm(store, p.permit_id).code == "PERMIT_NOT_ADMITTABLE"


def test_revoke_denied_when_issuer_no_longer_registered_owner() -> None:
    # a permit issued under one registry cannot be revoked by an id that is not a registered owner
    store = PermitStore(Clock(), owners={("tenant-a", "src-1"): frozenset({"owner-1"})})
    p = issued(store)
    store._owners.clear()  # simulate de-registration (white-box, registry is not public API)
    assert store.revoke(p.permit_id, "tenant-a", OWNER).code == "REVOKE_DENIED"


def test_audit_prod_flag_actor_normalised_and_non_bool_not_audited() -> None:
    store, clock = make()
    admin = Issuer(IssuerKind.HUMAN, " Admin-1 ")
    store, clock = make(prod_admins={"admin-1", "a" * 200})
    assert store.set_prod_enabled(True, admin)
    assert store.set_prod_enabled("yes", admin) is False  # type: ignore[arg-type]
    assert store.set_prod_enabled(False, OWNER)  # a registered owner of some scope may toggle too
    assert store.audit() == (
        AuditEntry("PROD_FLAG", "admin-1", "", "True", T0),
        AuditEntry("PROD_FLAG", "owner-1", "", "False", T0),
    )
    clock.now = T1
    store.set_prod_enabled(True, Issuer(IssuerKind.HUMAN, "a" * 200))
    assert store.audit()[-1].actor == "a" * 128 and store.audit()[-1].at == T1


@pytest.mark.parametrize("by", [None, "owner-1", Issuer(IssuerKind.LLM, "owner-1"),
                                Issuer(IssuerKind.AUTOMATION, "admin-1"),
                                Issuer(IssuerKind.HUMAN, "stranger"), Issuer(IssuerKind.HUMAN, "")])
def test_set_prod_enabled_denied_for_non_admins_unchanged_and_audited(by) -> None:
    store, _ = make(prod_admins={"admin-1"})
    assert store.set_prod_enabled(True, by) is False  # type: ignore[arg-type]
    assert store.audit() == (AuditEntry("PROD_FLAG", store.audit()[0].actor, "", "PROD_FLAG_DENIED", T0),)
    assert store.issue("k", replace(REQ, environment=Environment.PROD), OWNER).code == "PROD_DISABLED"
    assert PermitStore(Clock()).set_prod_enabled(True, OWNER) is False  # empty registry: nobody
    with pytest.raises(ValueError):
        PermitStore(Clock(), prod_admins="admin-1")  # type: ignore[arg-type]


def test_max_uses_is_bounded_before_formatting_and_audited() -> None:
    store, _ = make()
    for bad in (10**5000, 10**9 + 1, -(10**5000)):
        res = store.issue("k", replace(REQ, max_uses=bad), OWNER)
        assert (res.status, res.permit, res.code) == (IssueStatus.REFUSED, None, "MAX_USES_INVALID")
    assert [e.value for e in store.audit()] == ["MAX_USES_INVALID"] * 3
    assert store.issue("k", replace(REQ, max_uses=10**9), OWNER).status is IssueStatus.ISSUED


def test_owners_and_id_collections_reject_str_bytes_and_non_str_items() -> None:
    for bad in ("alice", b"alice", bytearray(b"a"), 5, None, {"a": 1}, {1, 2}, ["a", 1], {"a", b"b"}):
        with pytest.raises(ValueError):
            PermitStore(Clock(), owners={("t", "s"): bad})  # type: ignore[dict-item]
    ok = PermitStore(Clock(), owners={("t", "s"): ["alice"]})
    assert ok.issue("k", replace(REQ, tenant_id="t", source_id="s"), Issuer(IssuerKind.HUMAN, "alice")).status \
        is IssueStatus.ISSUED


def test_security_audit_entries_survive_admit_flooding_and_drops_are_counted() -> None:
    store, _ = make(max_audit=5, prod_admins={"admin-1"})
    store.set_prod_enabled(True, Issuer(IssuerKind.HUMAN, "admin-1"))
    p = issued(store)
    for _ in range(50):
        adm(store, "f" * 32)
    log = store.audit()
    kinds = [e.kind for e in log]
    assert kinds[:2] == ["PROD_FLAG", "ISSUE"] or {"PROD_FLAG", "ISSUE"} <= set(kinds)
    assert any(e.kind == "ISSUE" and e.subject == p.permit_id for e in log)
    assert sum(k == "ADMIT" for k in kinds) == 5 and store.dropped_admits() == 45
    store.revoke(p.permit_id, "tenant-a", OWNER)
    for _ in range(50):
        adm(store, "f" * 32)
    assert [e.kind for e in store.audit()].count("REVOKE") == 1


def test_audit_order_equals_decision_order_and_clock_read_inside_the_lock() -> None:
    seen: list[bool] = []
    holder: dict[str, PermitStore] = {}

    def clock() -> datetime:
        seen.append(holder["s"]._lock.locked())
        return T0

    store = PermitStore(clock, owners=OWNERS)
    holder["s"] = store
    p = store.issue("k", REQ, OWNER).permit
    assert p is not None
    seen.clear()
    adm(store, p.permit_id)
    store.revoke(p.permit_id, "tenant-a", OWNER)
    store.set_prod_enabled(True, OWNER)
    assert seen == [True, True, True]
    assert [e.kind for e in store.audit()] == ["ISSUE", "ADMIT", "REVOKE", "PROD_FLAG"]


def test_id_source_may_call_store_methods_without_deadlock() -> None:
    holder: dict[str, PermitStore] = {}
    counter = iter(range(100))

    def ids() -> str:
        holder["s"].count()
        holder["s"].audit()
        return f"id-{next(counter)}"

    store = PermitStore(Clock(), owners=OWNERS, id_source=ids)
    holder["s"] = store
    with ThreadPoolExecutor(max_workers=1) as ex:
        res = ex.submit(store.issue, "k", REQ, OWNER).result(timeout=5)
    assert res.status is IssueStatus.ISSUED and res.permit is not None and res.permit.permit_id == "id-0"
    # colliding candidates are retried (bounded) and re-checked under the lock
    seq = iter(["id-0", "id-0", "fresh"])
    store2 = PermitStore(Clock(), owners=OWNERS, id_source=lambda: next(seq))
    issued(store2, REQ, "a")
    assert store2.issue("b", REQ, OWNER).permit.permit_id == "fresh"  # type: ignore[union-attr]


def test_audit_records_issue_admit_revoke_outcomes_with_fixed_codes() -> None:
    store, _ = make()
    p = issued(store)
    store.issue("k1", REQ, OWNER)  # replay
    store.issue("kx", REQ, Issuer(IssuerKind.HUMAN, "Stranger"))
    adm(store, p.permit_id, mode=INCR)
    adm(store, "f" * 32)
    store.revoke(p.permit_id, "tenant-a", Issuer(IssuerKind.HUMAN, "nobody"))
    store.revoke(p.permit_id, "tenant-a", OWNER)
    log = store.audit()
    assert [(e.kind, e.actor, e.subject, e.value) for e in log] == [
        ("ISSUE", "owner-1", p.permit_id, "ISSUED"),
        ("ISSUE", "owner-1", p.permit_id, "REPLAYED"),
        ("ISSUE", "stranger", "", "ISSUER_NOT_OWNER"),
        ("ADMIT", "requester-1", p.permit_id, "MODE_MISMATCH"),
        ("ADMIT", "requester-1", "", "PERMIT_NOT_ADMITTABLE"),
        ("REVOKE", "nobody", "", "REVOKE_DENIED"),
        ("REVOKE", "owner-1", p.permit_id, "REVOKED"),
    ]
    assert all(e.value in FIXED_CODES and e.at == T0 for e in log)


def test_audit_is_bounded_drops_oldest_and_returns_a_copy() -> None:
    store, _ = make(max_audit=3, prod_admins={f"actor-{i}" for i in range(5)})
    for i in range(5):
        store.set_prod_enabled(i % 2 == 0, Issuer(IssuerKind.HUMAN, f"actor-{i}"))
    log = store.audit()
    assert isinstance(log, tuple) and [e.actor for e in log] == ["actor-2", "actor-3", "actor-4"]
    adm(store, "f" * 32)
    assert len(store.audit()) == 4 and store.audit()[0].actor == "actor-2"  # admit log is separate
    assert len(log) == 3  # the earlier copy is unaffected


def test_codes_never_echo_raw_input() -> None:
    store, _ = make()
    marker = "SECRET-MARKER-xyz"
    p = issued(store)
    results = [
        store.issue(marker, replace(REQ, tenant_id=marker, params_digest=marker), OWNER),
        store.issue("k9", replace(REQ, requester=marker), Issuer(IssuerKind.HUMAN, marker)),
        store.issue("k9", replace(REQ, source_id=marker), Issuer(IssuerKind.LLM, marker)),
    ]
    admits = [
        adm(store, marker, marker, marker, digest=marker, requester=marker),
        adm(store, p.permit_id, tenant=marker),
        adm(store, p.permit_id, source=marker),
        adm(store, p.permit_id, digest=marker),
        adm(store, p.permit_id, requester=marker),
    ]
    revokes = [store.revoke(marker, marker, Issuer(IssuerKind.HUMAN, marker)),
               store.revoke(p.permit_id, "tenant-a", Issuer(IssuerKind.HUMAN, marker))]
    for r in [*results, *admits, *revokes]:
        assert marker.lower() not in repr(r).lower()
        assert r.code in FIXED_CODES
    assert all(r.permit is None for r in results)
