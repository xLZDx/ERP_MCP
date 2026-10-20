"""S7/E1: ERP_MCP-owned Drive consent state machine and fake-token store (TC103-TC105 consent side + S6b
lessons). Offline: no network, no real token, no real Google scope URL."""
from __future__ import annotations

import ast
import inspect
import pickle
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import drive_oauth
from business_ai_gateway.phase2.drive_oauth import (
    ConsentCode,
    ConsentManager,
    ConsentState,
    FakeTokenStore,
)
from business_ai_gateway.phase2.drive_port import DrivePortIdentity
from business_ai_gateway.phase2.drive_scope import Isolation, ScopeClaim


def _ID(v):
    return repr(v)[:40]


IDENT = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")
OTHER_CONN = DrivePortIdentity("account:acc-1", "tenant-1", "conn-2")
OTHER_TENANT = DrivePortIdentity("account:acc-1", "tenant-2", "conn-1")
VERIFIER = "v" * 43
CODE = "FAKE-CODE-1"
NARROW = ("drive.file",)
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class StrSub(str):
    pass


class IntSub(int):
    pass


class DtSub(datetime):
    pass


class IdentSub(DrivePortIdentity):
    pass


class Harness:
    def __init__(self, **kw):
        self.now = T0
        self.states = iter(f"STATE-{i:016d}" for i in range(1, 1000))
        self.tokens: list[str] = []
        self._n = 0

        def token_source() -> str:
            self._n += 1
            tok = f"FAKE-token-{self._n:04d}"
            self.tokens.append(tok)
            return tok

        self.store = FakeTokenStore(token_source)
        self.mgr = ConsentManager(
            lambda: self.now, store=self.store, state_source=lambda: next(self.states), **kw
        )

    def begin(self, ident=IDENT, scopes=NARROW, verifier=VERIFIER, labels=()):
        return self.mgr.begin_consent(ident, scopes, verifier, labels)

    def grant(self, ident=IDENT):
        res = self.begin(ident)
        assert res.ok, res
        done = self.mgr.complete_consent(ident, res.state_value, VERIFIER, CODE)
        assert done.ok, done
        return done


# --- happy path and state machine --------------------------------------------------------------


def test_tc103_consent_flow_new_pending_granted_with_narrow_claim():
    h = Harness()
    assert h.mgr.state_of(IDENT) is ConsentState.NEW and h.mgr.scope_epoch(IDENT) is None
    res = h.begin()
    assert (res.ok, res.code, res.state, res.scope_epoch) == (True, ConsentCode.OK, ConsentState.CONSENT_PENDING, 0)
    assert res.claim is ScopeClaim.NARROW_FILE_SCOPE and res.isolation is Isolation.FILE_GRANT_ONLY
    assert res.state_value == "STATE-0000000000000001"
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING and not h.store.has_tokens(IDENT)
    done = h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE)
    assert (done.ok, done.state, done.scope_epoch, done.state_value) == (True, ConsentState.GRANTED, 0, None)
    snap = h.mgr.snapshot(IDENT)
    assert snap is not None and snap.scopes == ("drive.file",) and snap.broad_accepted is False
    assert h.store.has_tokens(IDENT) and h.store.count() == 1
    assert h.mgr.is_authorized(IDENT, 0) and not h.mgr.is_authorized(IDENT, 1)


def test_tc105_broad_scope_needs_risk_label_and_is_never_isolation_in_the_consent_record():
    h = Harness()
    refused = h.begin(scopes=("drive",))
    assert (refused.ok, refused.code) == (False, ConsentCode.SCOPE_REFUSED)
    assert h.mgr.state_of(IDENT) is ConsentState.NEW
    res = h.begin(scopes=("drive.readonly",), labels=("BROAD_ACCEPTED",))
    assert res.ok and res.claim is ScopeClaim.READONLY_BROAD
    assert res.isolation is Isolation.APPLICATION_FILTER_ONLY
    h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE)
    snap = h.mgr.snapshot(IDENT)
    assert snap is not None and snap.broad_accepted is True
    assert snap.isolation is Isolation.APPLICATION_FILTER_ONLY and snap.claim is ScopeClaim.READONLY_BROAD


def test_state_values_are_not_reused_and_second_begin_supersedes_the_first():
    h = Harness()
    first = h.begin().state_value
    second = h.begin().state_value
    assert first != second
    stale = h.mgr.complete_consent(IDENT, first, VERIFIER, CODE)
    assert (stale.ok, stale.code) == (False, ConsentCode.STATE_REPLAYED)
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING and h.store.count() == 0
    assert h.mgr.complete_consent(IDENT, second, VERIFIER, CODE).ok


def test_replay_of_a_used_state_is_refused_and_mints_nothing_more():
    h = Harness()
    res = h.begin()
    assert h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).ok
    minted = list(h.tokens)
    again = h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE)
    assert (again.ok, again.code) == (False, ConsentCode.STATE_REPLAYED)
    assert h.tokens == minted and h.store.count() == 1
    assert h.mgr.begin_consent(IDENT, NARROW, VERIFIER).code is ConsentCode.ALREADY_GRANTED


def test_callback_for_another_tenant_or_connection_is_refused_like_an_unknown_state_and_does_not_burn_it():
    h = Harness()
    res = h.begin()
    unknown = h.mgr.complete_consent(IDENT, "STATE-9999999999999999", VERIFIER, CODE)
    for foreign in (OTHER_CONN, OTHER_TENANT):
        got = h.mgr.complete_consent(foreign, res.state_value, VERIFIER, CODE)
        assert (got.ok, got.code) == (False, unknown.code) and got.code is ConsentCode.STATE_UNKNOWN
        assert h.mgr.state_of(foreign) is ConsentState.NEW and not h.store.has_tokens(foreign)
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING
    assert h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).ok  # owner still can


def test_pending_lifetime_is_bounded_on_the_injected_clock():
    h = Harness(pending_ttl=timedelta(minutes=5))
    res = h.begin()
    h.now = T0 + timedelta(minutes=5) - timedelta(microseconds=1)
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING
    h.now = T0 + timedelta(minutes=5)  # half-open: expired exactly at the boundary
    expired = h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE)
    assert (expired.ok, expired.code) == (False, ConsentCode.STATE_EXPIRED)
    assert h.mgr.state_of(IDENT) is ConsentState.NEW and h.store.count() == 0
    assert h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).code is ConsentCode.STATE_REPLAYED
    fresh = h.begin()
    assert fresh.ok and h.mgr.complete_consent(IDENT, fresh.state_value, VERIFIER, CODE).ok


def test_state_of_reports_new_once_the_pending_state_has_expired():
    h = Harness(pending_ttl=timedelta(minutes=1))
    h.begin()
    h.now = T0 + timedelta(minutes=2)
    assert h.mgr.state_of(IDENT) is ConsentState.NEW


def test_pkce_verifier_binding_wrong_verifier_burns_the_state_and_grants_nothing():
    h = Harness()
    res = h.begin()
    bad = h.mgr.complete_consent(IDENT, res.state_value, "w" * 43, CODE)
    assert (bad.ok, bad.code) == (False, ConsentCode.VERIFIER_MISMATCH)
    assert h.mgr.state_of(IDENT) is ConsentState.NEW and h.store.count() == 0
    again = h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE)
    assert again.code is ConsentCode.STATE_REPLAYED  # the right verifier cannot rescue a burnt state


@pytest.mark.parametrize("verifier", [
    None, "", "short", "v" * 15, "v" * 129, "v" * 42 + "\x00", "v" * 42 + " ", "é" * 43,
    StrSub("v" * 43), b"v" * 43, 5, ["v"] * 43,
], ids=_ID)
def test_hostile_verifier_is_refused_without_state_change(verifier):
    h = Harness()
    assert h.mgr.begin_consent(IDENT, NARROW, verifier).code is ConsentCode.VERIFIER_INVALID
    assert h.mgr.state_of(IDENT) is ConsentState.NEW
    res = h.begin()
    got = h.mgr.complete_consent(IDENT, res.state_value, verifier, CODE)
    assert got.code is ConsentCode.VERIFIER_INVALID
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING  # not burnt by a malformed call


@pytest.mark.parametrize("state", [
    None, "", "short", StrSub("STATE-0000000000000001"), "STATE-000000000000001\x00",
    "S" * 100_000, 5, b"STATE-0000000000000001", "STATE 0000000000000001", ["x"],
], ids=_ID)
def test_hostile_state_is_refused_without_burning_the_real_one(state):
    h = Harness()
    res = h.begin()
    assert h.mgr.complete_consent(IDENT, state, VERIFIER, CODE).code is ConsentCode.STATE_INVALID
    assert h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).ok


@pytest.mark.parametrize("code", [
    None, "", "FAKE-CODE-", "REAL-CODE-1", "fake-code-1", StrSub("FAKE-CODE-1"), "FAKE-CODE-1\x00",
    "FAKE-CODE-" + "x" * 1000, 7, b"FAKE-CODE-1",
], ids=_ID)
def test_authorization_code_must_be_an_exact_fake_code(code):
    h = Harness()
    res = h.begin()
    assert h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, code).code is ConsentCode.CODE_INVALID
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING and h.store.count() == 0


def test_granted_scopes_may_narrow_but_never_widen_the_request():
    h = Harness()
    res = h.begin(scopes=("drive.file", "drive.readonly"), labels=("BROAD_ACCEPTED",))
    widen = h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE, ("drive",))
    assert widen.code is ConsentCode.GRANT_NOT_SUBSET  # a scope that was never requested
    unlabeled = Harness()
    pending = unlabeled.begin()
    refused = unlabeled.mgr.complete_consent(IDENT, pending.state_value, VERIFIER, CODE, ("drive",))
    assert refused.code is ConsentCode.SCOPE_REFUSED  # broad without the risk label
    not_subset = h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE, ("drive.metadata.readonly",))
    assert not_subset.code is ConsentCode.GRANT_NOT_SUBSET
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING  # refusals did not burn the state
    ok = h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE, ("drive.file",))
    assert ok.ok and ok.claim is ScopeClaim.NARROW_FILE_SCOPE
    snap = h.mgr.snapshot(IDENT)
    assert snap is not None and snap.scopes == ("drive.file",) and snap.isolation is Isolation.FILE_GRANT_ONLY


@pytest.mark.parametrize("granted", [(), "drive.file", ["drive.file", None], (StrSub("drive.file"),)], ids=_ID)
def test_hostile_granted_scopes_are_refused(granted):
    h = Harness()
    res = h.begin()
    assert h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE, granted).code is ConsentCode.SCOPE_REFUSED
    assert h.store.count() == 0


# --- tokens ------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", [
    lambda: "PDCC-real-looking-token", lambda: "ya29.a0AfH6SMB", lambda: "", lambda: None,
    lambda: StrSub("FAKE-x"), lambda: "FAKE-", lambda: "FAKE-x y", lambda: "FAKE-" + "x" * 600,
    lambda: (_ for _ in ()).throw(RuntimeError("provider text")), lambda: "fake-lowercase",
], ids=_ID)
def test_store_refuses_any_token_without_the_exact_fake_prefix_and_grants_nothing(source):
    mgr = ConsentManager(lambda: T0, store=FakeTokenStore(source), state_source=lambda: "S" * 24)
    res = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    got = mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE)
    assert (got.ok, got.code) == (False, ConsentCode.TOKEN_INVALID)
    assert mgr.state_of(IDENT) is ConsentState.NEW and mgr.store.count() == 0
    assert "provider text" not in repr(got)


def test_identical_access_and_refresh_token_are_refused():
    mgr = ConsentManager(lambda: T0, store=FakeTokenStore(lambda: "FAKE-same"), state_source=lambda: "S" * 24)
    res = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).code is ConsentCode.TOKEN_INVALID


def test_tokens_never_appear_in_repr_str_results_digest_snapshot_or_pickle():
    h = Harness()
    begin = h.begin()
    done = h.mgr.complete_consent(IDENT, begin.state_value, VERIFIER, CODE)
    refused = h.mgr.complete_consent(IDENT, begin.state_value, VERIFIER, CODE)
    revoked = h.mgr.revoke(IDENT)
    assert len(h.tokens) == 2 and all(t.startswith("FAKE-") for t in h.tokens)
    surfaces = [
        repr(h.mgr), str(h.mgr), repr(h.store), str(h.store), repr(done), str(done), repr(refused),
        repr(revoked), repr(h.mgr.snapshot(IDENT)), h.mgr.consent_digest(IDENT) or "",
        repr(drive_oauth.ConsentCode), vars_text(h.mgr), vars_text(h.store),
    ]
    for tok in h.tokens:
        for text in surfaces:
            assert tok not in text
    for obj in (h.mgr, h.store):
        with pytest.raises(TypeError):
            pickle.dumps(obj)
    assert begin.state_value not in (h.mgr.consent_digest(IDENT) or "")


def vars_text(obj: object) -> str:
    return repr(sorted(n for n in dir(obj) if not n.startswith("_")))


def test_live_tokens_are_also_absent_from_every_public_surface_while_granted():
    h = Harness()
    h.grant()
    live = list(h.tokens)
    texts = [repr(h.mgr), repr(h.store), repr(h.mgr.snapshot(IDENT)), h.mgr.consent_digest(IDENT)]
    texts += [repr(h.mgr.begin_consent(IDENT, NARROW, VERIFIER)), repr(h.mgr.revoke(OTHER_CONN))]
    assert all(t not in text for t in live for text in texts)


def test_no_public_method_accepts_or_returns_a_token_so_a_foreign_store_is_unreachable():
    assert sorted(n for n in dir(FakeTokenStore) if not n.startswith("_")) == ["count", "has_tokens"]
    for cls in (ConsentManager, FakeTokenStore):
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            params = [p for p in inspect.signature(member).parameters if p != "self"]
            assert not any("token" in p for p in params), (cls.__name__, name)
    with pytest.raises(TypeError):
        ConsentManager(lambda: T0, store=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ConsentManager(lambda: T0, store={"tenant-1": "FAKE-injected"})  # type: ignore[arg-type]


def test_a_grant_held_in_another_store_confers_nothing_here():
    pdcc_like = Harness()
    pdcc_like.grant()
    mine = Harness()
    assert not mine.store.has_tokens(IDENT) and not mine.mgr.is_authorized(IDENT, 0)
    assert mine.mgr.state_of(IDENT) is ConsentState.NEW and mine.store.count() == 0


# --- revoke / auth required --------------------------------------------------------------------


def test_revoke_deletes_tokens_bumps_epoch_and_old_epoch_stays_dead_after_reconsent():
    h = Harness()
    h.grant()
    assert h.mgr.is_authorized(IDENT, 0)
    res = h.mgr.revoke(IDENT)
    assert (res.ok, res.state, res.scope_epoch) == (True, ConsentState.REVOKED, 1)
    assert not h.store.has_tokens(IDENT) and h.store.count() == 0
    assert not h.mgr.is_authorized(IDENT, 0) and not h.mgr.is_authorized(IDENT, 1)
    assert h.mgr.snapshot(IDENT).scopes == ()
    assert h.mgr.revoke(IDENT).code is ConsentCode.NOT_GRANTED
    re = h.begin()
    assert re.ok and re.scope_epoch == 1
    assert h.mgr.complete_consent(IDENT, re.state_value, VERIFIER, CODE).ok
    assert h.mgr.is_authorized(IDENT, 1) and not h.mgr.is_authorized(IDENT, 0)  # no resurrection
    assert h.mgr.revoke(IDENT).scope_epoch == 2


def test_invalid_grant_moves_to_auth_required_deletes_tokens_bumps_epoch_and_reconsent_works():
    h = Harness()
    assert h.mgr.mark_auth_required(IDENT).code is ConsentCode.NOT_GRANTED
    h.grant()
    res = h.mgr.mark_auth_required(IDENT)
    assert (res.ok, res.state, res.scope_epoch) == (True, ConsentState.AUTH_REQUIRED, 1)
    assert h.store.count() == 0 and not h.mgr.is_authorized(IDENT, 1)
    assert h.mgr.mark_auth_required(IDENT).code is ConsentCode.NOT_GRANTED
    assert h.mgr.begin_consent(IDENT, NARROW, VERIFIER).ok
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING


def test_auth_required_can_be_revoked_and_revoke_of_one_connection_leaves_another():
    h = Harness()
    h.grant()
    h.grant(OTHER_CONN)
    h.mgr.mark_auth_required(IDENT)
    assert h.mgr.revoke(IDENT).state is ConsentState.REVOKED
    assert h.mgr.is_authorized(OTHER_CONN, 0) and h.store.has_tokens(OTHER_CONN)
    assert h.store.count() == 1


def test_revoke_of_unknown_or_pending_connection_is_not_granted_and_changes_nothing():
    h = Harness()
    assert h.mgr.revoke(IDENT).code is ConsentCode.NOT_GRANTED
    h.begin()
    assert h.mgr.revoke(IDENT).code is ConsentCode.NOT_GRANTED
    assert h.mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING


def test_consent_digest_tracks_state_and_epoch_but_is_stable_otherwise():
    h = Harness()
    assert h.mgr.consent_digest(IDENT) is None
    h.grant()
    d1 = h.mgr.consent_digest(IDENT)
    assert d1 == h.mgr.consent_digest(IDENT) and len(d1) == 64
    h.mgr.revoke(IDENT)
    assert h.mgr.consent_digest(IDENT) != d1


# --- hostile inputs, clock, sources ------------------------------------------------------------


def _rec():
    items: list = []
    items.append(items)
    return items


HOSTILE = [None, "", "x" * 100_000, "a\x00b", 5, 2**200, b"x", StrSub("x"), IntSub(1), _rec(), {}, object(),
           IdentSub("account:acc-1", "tenant-1", "conn-1")]


@pytest.mark.parametrize("bad", HOSTILE, ids=lambda v: type(v).__name__)
def test_hostile_values_in_every_position_return_fixed_refusals_and_never_raise(bad):
    h = Harness()
    res = h.begin()
    results = [
        h.mgr.begin_consent(bad, NARROW, VERIFIER),
        h.mgr.begin_consent(IDENT, bad, VERIFIER),
        h.mgr.begin_consent(IDENT, NARROW, bad),
        h.mgr.begin_consent(IDENT, NARROW, VERIFIER, bad),
        h.mgr.complete_consent(bad, res.state_value, VERIFIER, CODE),
        h.mgr.complete_consent(IDENT, bad, VERIFIER, CODE),
        h.mgr.complete_consent(IDENT, res.state_value, bad, CODE),
        h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, bad),
        h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE, bad) if bad is not None else None,
        h.mgr.revoke(bad), h.mgr.mark_auth_required(bad),
    ]
    for got in results:
        if got is None:
            continue
        assert got.ok is False and type(got.code) is ConsentCode
        assert got.state_value is None
    assert h.mgr.snapshot(bad) is None
    assert h.mgr.state_of(bad) is ConsentState.NEW
    assert h.mgr.is_authorized(bad, 0) is False and h.mgr.consent_digest(bad) is None
    assert h.store.has_tokens(bad) is False


@pytest.mark.parametrize("epoch", [None, True, IntSub(0), -1, 2**63, 1.0, "0"], ids=_ID)
def test_is_authorized_refuses_non_exact_epochs(epoch):
    h = Harness()
    h.grant()
    assert h.mgr.is_authorized(IDENT, epoch) is False


def test_identity_subclass_is_refused_even_when_it_equals_a_real_identity():
    h = Harness()
    sub = IdentSub("account:acc-1", "tenant-1", "conn-1")
    assert h.mgr.begin_consent(sub, NARROW, VERIFIER).code is ConsentCode.IDENTITY_INVALID


def test_guid_tenant_and_connection_are_canonicalised_but_drive_namespace_ids_stay_exact():
    h = Harness()
    upper = DrivePortIdentity("account:AbC", "3F2504E0-4F89-11D3-9A0C-0305E82C3301", "{3F2504E0-4F89-11D3-9A0C-0305E82C3302}")
    lower = DrivePortIdentity("account:AbC", "3f2504e0-4f89-11d3-9a0c-0305e82c3301", "3f2504e0-4f89-11d3-9a0c-0305e82c3302")
    other_case = DrivePortIdentity("account:abc", lower.tenant, lower.connection_id)
    h.grant(upper)
    assert h.mgr.is_authorized(lower, 0) and not h.mgr.is_authorized(other_case, 0)


def test_clock_naive_subclass_raising_or_wrong_type_is_refused_before_any_state_change():
    for bad_clock in (
        lambda: datetime(2026, 1, 1),  # noqa: DTZ001 - naive on purpose
        lambda: DtSub(2026, 1, 1, tzinfo=UTC),
        lambda: "2026-01-01",
        lambda: None, lambda: 1.0, lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    ):
        mgr = ConsentManager(bad_clock, state_source=lambda: "S" * 24)
        got = mgr.begin_consent(IDENT, NARROW, VERIFIER)
        assert (got.ok, got.code) == (False, ConsentCode.CLOCK_INVALID)
        assert mgr.snapshot(IDENT) is None


def test_aware_clock_in_another_zone_is_flattened_to_utc_for_the_lifetime():
    now = {"t": datetime(2026, 1, 1, 17, 0, tzinfo=timezone(timedelta(hours=5)))}  # 12:00Z
    mgr = ConsentManager(lambda: now["t"], state_source=lambda: "S" * 24, pending_ttl=timedelta(minutes=10))
    res = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    now["t"] = datetime(2026, 1, 1, 12, 9, tzinfo=UTC)
    assert mgr.state_of(IDENT) is ConsentState.CONSENT_PENDING
    now["t"] = datetime(2026, 1, 1, 17, 11, tzinfo=timezone(timedelta(hours=5)))  # 12:11Z
    assert mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).code is ConsentCode.STATE_EXPIRED


def test_clock_failure_at_callback_does_not_burn_the_state():
    h = Harness()
    res = h.begin()
    good = h.now
    h.now = datetime(2026, 1, 1, 12, 1)  # noqa: DTZ001 - naive on purpose
    assert h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).code is ConsentCode.CLOCK_INVALID
    h.now = good
    assert h.mgr.complete_consent(IDENT, res.state_value, VERIFIER, CODE).ok


@pytest.mark.parametrize("source", [
    lambda: "S" * 24 + "\x00", lambda: "short", lambda: None, lambda: StrSub("S" * 24),
    lambda: "S" * 24 + " ", lambda: "é" * 24, lambda: (_ for _ in ()).throw(RuntimeError("boom")),
], ids=_ID)
def test_invalid_or_failing_state_source_is_refused_with_a_fixed_code(source):
    mgr = ConsentManager(lambda: T0, state_source=source)
    got = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert (got.ok, got.code, got.state_value) == (False, ConsentCode.STATE_SOURCE_INVALID, None)
    assert "boom" not in repr(got)


def test_a_state_source_that_repeats_a_value_cannot_reissue_a_used_state():
    mgr = ConsentManager(lambda: T0, state_source=lambda: "R" * 24)
    first = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert first.ok
    mgr.complete_consent(IDENT, first.state_value, VERIFIER, CODE)
    mgr.revoke(IDENT)
    again = mgr.begin_consent(IDENT, NARROW, VERIFIER)
    assert again.code is ConsentCode.STATE_SOURCE_INVALID  # a used value is never reissued


def test_default_state_source_is_unguessable_and_distinct():
    mgr = ConsentManager(lambda: T0)
    a = mgr.begin_consent(IDENT, NARROW, VERIFIER).state_value
    b = mgr.begin_consent(OTHER_CONN, NARROW, VERIFIER).state_value
    assert a != b and len(a) >= 32 and len(b) >= 32


def test_capacity_limits_are_fixed_refusals_not_growth():
    mgr = ConsentManager(lambda: T0, max_states=1, state_source=iter(f"STATE-{i:016d}" for i in range(9)).__next__)
    assert mgr.begin_consent(IDENT, NARROW, VERIFIER).ok
    assert mgr.begin_consent(OTHER_CONN, NARROW, VERIFIER).code is ConsentCode.CAPACITY
    small = ConsentManager(lambda: T0, max_records=1, state_source=iter(f"STATE-{i:016d}" for i in range(9)).__next__)
    assert small.begin_consent(IDENT, NARROW, VERIFIER).ok
    assert small.begin_consent(OTHER_CONN, NARROW, VERIFIER).code is ConsentCode.CAPACITY


def test_epoch_exhaustion_is_a_fixed_refusal():
    h = Harness()
    h.grant()
    key = (IDENT.namespace, IDENT.tenant, IDENT.connection_id)
    h.mgr._records[key].epoch = 2**63 - 1
    got = h.mgr.revoke(IDENT)
    assert (got.ok, got.code) == (False, ConsentCode.EPOCH_EXHAUSTED)


@pytest.mark.parametrize("kwargs", [
    {"pending_ttl": timedelta(0)}, {"pending_ttl": timedelta(hours=2)}, {"pending_ttl": 5},
    {"max_states": 0}, {"max_states": True}, {"max_records": -1}, {"state_source": 5}, {"store": 5},
], ids=_ID)
def test_constructor_configuration_errors_raise(kwargs):
    with pytest.raises((TypeError, ValueError)):
        ConsentManager(lambda: T0, **kwargs)
    with pytest.raises(TypeError):
        ConsentManager(5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        FakeTokenStore(5)  # type: ignore[arg-type]


# --- boundary of this module -------------------------------------------------------------------


def test_oauth_module_has_no_network_release1_pdcc_or_secret_io_imports_and_no_real_url():
    src = Path(drive_oauth.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0] or "." * node.level)
            imported.update(a.name for a in node.names if node.level)
    assert not (imported & {"httpx", "requests", "socket", "subprocess", "urllib", "os", "sqlite3", "aiohttp"})
    assert not any(("release1" in m.lower() or "pdcc" in m.lower()) for m in imported)
    assert "drive_http" not in imported and "ports" not in imported and "fakes" not in imported
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "googleapis" not in node.value and "://" not in node.value
