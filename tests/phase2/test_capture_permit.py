"""R2-US-024 bounded capture permit: TC070 / TC071 / TC072 (behavioural, deterministic)."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from business_ai_gateway.phase2.capture_permit import (
    CaptureMode,
    Environment,
    Issuer,
    IssuerKind,
    IssueStatus,
    PermitRequest,
    PermitStore,
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


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make(**kw) -> tuple[PermitStore, Clock]:
    clock = Clock()
    return PermitStore(clock, **kw), clock


def issued(store: PermitStore, req: PermitRequest = REQ, key: str = "k1"):
    res = store.issue(key, req, OWNER)
    assert res.status is IssueStatus.ISSUED and res.permit is not None
    return res.permit


def test_tc070_control_allowed_and_each_violation_alone_denied() -> None:
    store, _ = make()
    p = issued(store)
    ok = store.admit(p.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT)
    assert ok.allowed and ok.code == "ADMITTED"
    cases = {
        "tenant": (("tenant-b", "src-1", CaptureMode.READ_SNAPSHOT, None), "SCOPE_MISMATCH"),
        "source": (("tenant-a", "src-2", CaptureMode.READ_SNAPSHOT, None), "SCOPE_MISMATCH"),
        "mode": (("tenant-a", "src-1", CaptureMode.READ_INCREMENTAL, None), "MODE_MISMATCH"),
        "before": (("tenant-a", "src-1", CaptureMode.READ_SNAPSHOT, T0 - timedelta(seconds=1)),
                   "NOT_YET_VALID"),
        "after": (("tenant-a", "src-1", CaptureMode.READ_SNAPSHOT, T1 + timedelta(seconds=1)),
                  "EXPIRED"),
    }
    for name, ((t, s, m, at), code) in cases.items():
        res = store.admit(p.permit_id, t, s, m, at)
        assert (res.allowed, res.code) == (False, code), name


def test_tc070_wrong_types_return_codes_not_exceptions() -> None:
    store, _ = make()
    p = issued(store)
    assert store.admit(None, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT).code == "PERMIT_UNKNOWN"  # type: ignore[arg-type]
    assert store.admit("nope", "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT).code == "PERMIT_UNKNOWN"
    assert store.admit(p.permit_id, 5, "src-1", CaptureMode.READ_SNAPSHOT).code == "SCOPE_MISMATCH"  # type: ignore[arg-type]
    assert store.admit(p.permit_id, "tenant-a", "src-1", "READ_SNAPSHOT").code == "MODE_MISMATCH"  # type: ignore[arg-type]
    naive = datetime(2026, 1, 1, 12, 30)  # noqa: DTZ001 - naive on purpose
    assert store.admit(p.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT, naive).code == "TIME_INVALID"


def test_tc071_prod_default_off_at_issue_and_at_use() -> None:
    store, _ = make()
    prod = replace(REQ, environment=Environment.PROD)
    res = store.issue("k-prod", prod, OWNER)
    assert (res.status, res.permit, res.code) == (IssueStatus.REFUSED, None, "PROD_DISABLED")
    assert len(store) == 0

    on, _ = make(prod_enabled=True)
    p = issued(on, prod, "k-prod")
    assert on.admit(p.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT).allowed
    assert on.set_prod_enabled(False)
    res2 = on.admit(p.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT)
    assert (res2.allowed, res2.code) == (False, "PROD_DISABLED")
    assert on.set_prod_enabled("yes") is False  # type: ignore[arg-type]


def test_tc071_boundary_instants_exact_and_clock_used() -> None:
    store, clock = make()
    p = issued(store)
    args = (p.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT)
    clock.now = T0 - timedelta(microseconds=1)
    assert store.admit(*args).code == "NOT_YET_VALID"
    clock.now = T0
    assert store.admit(*args).allowed  # not_before inclusive
    clock.now = T1 - timedelta(microseconds=1)
    assert store.admit(*args).allowed
    clock.now = T1
    assert store.admit(*args).code == "EXPIRED"  # not_after exclusive
    clock.now = datetime(2026, 1, 1, 13, 0, tzinfo=timezone(timedelta(hours=1)))  # = 12:00Z
    assert store.admit(*args).allowed


def test_tc071_naive_datetime_rejected_and_broken_clock_fails_closed() -> None:
    store, clock = make()
    naive = datetime(2026, 1, 1, 12, 0)  # noqa: DTZ001 - naive on purpose
    for bad in (replace(REQ, not_before=naive), replace(REQ, not_after=naive)):
        assert store.issue("k", bad, OWNER).code == "WINDOW_INVALID"
    p = issued(store)
    clock.now = naive  # type: ignore[assignment]
    assert store.admit(p.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT).code == "TIME_INVALID"

    def boom() -> datetime:
        raise RuntimeError("secret-detail")

    store._clock = boom
    res = store.admit(p.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT)
    assert (res.allowed, res.code) == (False, "TIME_INVALID")


def test_window_must_be_nonempty_and_bounded() -> None:
    store, _ = make()
    assert store.issue("a", replace(REQ, not_after=T0), OWNER).code == "WINDOW_INVALID"
    assert store.issue("b", replace(REQ, not_after=T0 - timedelta(hours=1)), OWNER).code == "WINDOW_INVALID"
    assert store.issue("c", replace(REQ, not_after=T0 + timedelta(hours=24, seconds=1)), OWNER).code == "WINDOW_INVALID"
    assert store.issue("d", replace(REQ, not_after=T0 + timedelta(hours=24)), OWNER).status is IssueStatus.ISSUED
    small = PermitStore(Clock(), max_window=timedelta(minutes=5))
    assert small.issue("e", REQ, OWNER).code == "WINDOW_INVALID"


def test_tc072_same_key_same_params_replays_without_second_permit() -> None:
    store, _ = make()
    first = store.issue("k1", REQ, OWNER)
    second = store.issue("k1", REQ, OWNER)
    assert first.status is IssueStatus.ISSUED and second.status is IssueStatus.REPLAYED
    assert second.permit == first.permit and second.permit is not None
    assert len(store) == 1


def test_tc072_same_key_different_params_conflicts_and_store_unchanged() -> None:
    store, _ = make()
    first = issued(store)
    variants = [
        replace(REQ, params_digest="b" * 64),
        replace(REQ, source_id="src-2"),
        replace(REQ, mode=CaptureMode.READ_INCREMENTAL),
        replace(REQ, not_after=T1 + timedelta(minutes=1)),
        replace(REQ, requester="requester-2"),
    ]
    for v in variants:
        res = store.issue("k1", v, OWNER)
        assert (res.status, res.permit, res.code) == (IssueStatus.REFUSED, None, "IDEMPOTENCY_CONFLICT")
    assert len(store) == 1
    assert store.admit(first.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT).allowed
    assert store.issue("k1", REQ, OWNER).status is IssueStatus.REPLAYED


def test_tc072_different_keys_and_tenants_are_independent() -> None:
    store, _ = make()
    a = issued(store, REQ, "k1")
    b = issued(store, REQ, "k2")
    c = issued(store, replace(REQ, tenant_id="tenant-b"), "k1")  # same key, other tenant
    assert len({a.permit_id, b.permit_id, c.permit_id}) == 3
    assert len(store) == 3


def test_issuer_must_be_human() -> None:
    store, _ = make()
    for kind in (IssuerKind.LLM, IssuerKind.AUTOMATION):
        res = store.issue("k", REQ, Issuer(kind, "owner-1"))
        assert (res.status, res.code) == (IssueStatus.REFUSED, "ISSUER_NOT_HUMAN")
    assert store.issue("k", REQ, Issuer("HUMAN", "owner-1")).code == "ISSUER_INVALID"  # type: ignore[arg-type]
    assert store.issue("k", REQ, None).code == "ISSUER_INVALID"  # type: ignore[arg-type]
    assert store.issue("k", REQ, Issuer(IssuerKind.HUMAN, "  ")).code == "ISSUER_INVALID"
    assert len(store) == 0


@pytest.mark.parametrize("issuer_id", ["requester-1", "REQUESTER-1", " Requester-1 ", "ｒequester-1"])
def test_issuer_equal_to_requester_refused_after_normalisation(issuer_id: str) -> None:
    store, _ = make()
    res = store.issue("k", REQ, Issuer(IssuerKind.HUMAN, issuer_id))
    assert res.code == "ISSUER_IS_REQUESTER" and len(store) == 0


def test_zero_width_variant_is_invalid_not_a_distinct_person() -> None:
    store, _ = make()
    res = store.issue("k", REQ, Issuer(IssuerKind.HUMAN, "requester\u200b-1"))
    assert res.status is IssueStatus.REFUSED and res.code == "ISSUER_INVALID"
    res2 = store.issue("k", replace(REQ, requester="requester\u200b-1"), OWNER)
    assert res2.code == "REQUESTER_INVALID"
    assert len(store) == 0


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
    assert len(store) == 0


def test_revoke_only_by_issuer() -> None:
    store, _ = make()
    p = issued(store)
    args = (p.permit_id, "tenant-a", "src-1", CaptureMode.READ_SNAPSHOT)
    assert store.revoke(p.permit_id, Issuer(IssuerKind.HUMAN, "someone-else")).code == "REVOKER_NOT_ISSUER"
    assert store.revoke(p.permit_id, Issuer(IssuerKind.AUTOMATION, "owner-1")).code == "REVOKER_NOT_ISSUER"
    assert store.revoke(p.permit_id, Issuer(IssuerKind.HUMAN, "owner\u200b-1")).code == "REVOKER_NOT_ISSUER"
    assert store.revoke("nope", OWNER).code == "PERMIT_UNKNOWN"
    assert store.admit(*args).allowed
    res = store.revoke(p.permit_id, Issuer(IssuerKind.HUMAN, "OWNER-1"))
    assert (res.revoked, res.code) == (True, "REVOKED")
    assert store.admit(*args).code == "PERMIT_REVOKED"


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
        store.admit(marker, marker, marker, CaptureMode.READ_SNAPSHOT),
        store.admit(p.permit_id, marker, "src-1", CaptureMode.READ_SNAPSHOT),
        store.admit(p.permit_id, "tenant-a", marker, CaptureMode.READ_SNAPSHOT),
    ]
    revokes = [store.revoke(marker, Issuer(IssuerKind.HUMAN, marker)),
               store.revoke(p.permit_id, Issuer(IssuerKind.HUMAN, marker))]
    for r in [*results, *admits, *revokes]:
        assert marker.lower() not in repr(r).lower()
        assert r.code.isupper() or "_" in r.code
    assert all(r.permit is None for r in results[:1])
