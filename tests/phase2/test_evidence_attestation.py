"""R2-US-028 independent accountant evidence attestation: TC082 / TC083 / TC084 (behavioural)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2.evidence_attestation import (
    AttestationDecision,
    AttestationRequest,
    AttestationStore,
    Signer,
    SignerKind,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
REV = "a" * 64
REV2 = "b" * 64
POL = "c" * 64
POL2 = "d" * 64
VER = "policy-v1"
ACC = Signer(SignerKind.HUMAN, "accountant-1")
REQ = AttestationRequest(
    tenant_id="tenant-a", revision_digest=REV, policy_version=VER, policy_digest=POL,
    proposer="proposer-1", requester="requester-1", decision=AttestationDecision.PASS,
)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make(clock: Clock | None = None, **kw) -> tuple[AttestationStore, Clock]:
    clk = clock or Clock()
    kw.setdefault("accountants", {"tenant-a": {"accountant-1", "accountant-2"}})
    return AttestationStore(clk, **kw), clk


def signed(store: AttestationStore, request: AttestationRequest = REQ, signer: Signer = ACC):
    res = store.sign(request, signer)
    assert res.signed and res.attestation is not None and res.code == "SIGNED"
    return res.attestation


def chk(store, att, rev=REV, ver=VER, pol=POL, tenant="tenant-a", at=None):
    if at is None:
        return store.check_current(att.attestation_id, tenant, rev, ver, pol)
    return store.check_as_of(att.attestation_id, tenant, rev, ver, pol, at)


# ---------------------------------------------------------------- TC082
def test_tc082_sign_exact_revision_and_policy_is_valid():
    store, _ = make()
    att = signed(store)
    assert (att.revision_digest, att.policy_version, att.policy_digest) == (REV, VER, POL)
    assert att.signer == "accountant-1" and att.signed_at == T0 and not att.historical
    res = chk(store, att)
    assert res.valid is True and res.code == "VALID"
    assert store.count() == 1


def test_tc082_changed_revision_digest_invalidates():
    store, _ = make()
    att = signed(store)
    res = chk(store, att, rev=REV2)
    assert (res.valid, res.code) == (False, "REVISION_MISMATCH")


def test_tc082_changed_policy_digest_or_version_invalidates():
    store, _ = make()
    att = signed(store)
    assert chk(store, att, pol=POL2).code == "POLICY_DIGEST_MISMATCH"
    assert chk(store, att, ver="policy-v2").code == "POLICY_VERSION_MISMATCH"
    assert not chk(store, att, pol=POL2).valid and not chk(store, att, ver="policy-v2").valid


def test_tc082_attestation_for_other_revision_is_separate_evidence():
    store, _ = make()
    a1 = signed(store)
    a2 = signed(store, replace(REQ, revision_digest=REV2))
    assert a1.attestation_id != a2.attestation_id
    assert chk(store, a1).valid and chk(store, a2, rev=REV2).valid
    assert not chk(store, a1, rev=REV2).valid and not chk(store, a2).valid


def test_tc082_wrong_or_unknown_tenant_and_id_share_one_code():
    store, _ = make()
    att = signed(store)
    assert chk(store, att, tenant="tenant-b").code == "ATTESTATION_NOT_VALID"
    assert store.check_current("nope", "tenant-a", REV, VER, POL).code == "ATTESTATION_NOT_VALID"
    assert store.check_current(None, "tenant-a", REV, VER, POL).code == "ATTESTATION_NOT_VALID"  # type: ignore[arg-type]
    # a wrong tenant with a wrong revision still reveals nothing about the attestation
    assert chk(store, att, tenant="tenant-b", rev=REV2).code == "ATTESTATION_NOT_VALID"


@pytest.mark.parametrize("field,value,code", [
    ("revision_digest", "A" * 64, "REVISION_DIGEST_INVALID"),
    ("revision_digest", "a" * 63, "REVISION_DIGEST_INVALID"),
    ("revision_digest", 123, "REVISION_DIGEST_INVALID"),
    ("policy_digest", "z" * 64, "POLICY_DIGEST_INVALID"),
    ("policy_digest", "", "POLICY_DIGEST_INVALID"),
    ("policy_version", "   ", "POLICY_VERSION_INVALID"),
    ("policy_version", None, "POLICY_VERSION_INVALID"),
    ("tenant_id", "", "SCOPE_INVALID"),
    ("tenant_id", "ten\u200bant-a", "SCOPE_INVALID"),
    ("proposer", "", "PARTY_INVALID"),
    ("requester", None, "PARTY_INVALID"),
])
def test_tc082_malformed_binding_is_denied_and_nothing_recorded(field, value, code):
    store, _ = make()
    res = store.sign(replace(REQ, **{field: value}), ACC)
    assert (res.signed, res.attestation, res.code) == (False, None, code)
    assert store.count() == 0 and store.history("tenant-a") == ()


# ---------------------------------------------------------------- TC083
def test_tc083_self_sign_requester_and_proposer_denied():
    store, _ = make()
    as_requester = store.sign(replace(REQ, requester="accountant-1"), ACC)
    as_proposer = store.sign(replace(REQ, proposer="accountant-1"), ACC)
    assert as_requester.code == "SIGNER_IS_REQUESTER" and not as_requester.signed
    assert as_proposer.code == "SIGNER_IS_PROPOSER" and not as_proposer.signed
    assert store.count() == 0 and store.history("tenant-a") == ()


@pytest.mark.parametrize("alias", [
    "ACCOUNTANT-1", "  accountant-1 ", "ａccountant-1",  # case, spaces, fullwidth a (NFKC)
])
def test_tc083_strict_identity_variants_of_signer_are_the_same_person(alias):
    store, _ = make(accountants={"tenant-a": {"accountant-1", alias.strip().casefold() or "x"}})
    res = store.sign(replace(REQ, requester=alias), ACC)
    assert not res.signed and res.code == "SIGNER_IS_REQUESTER"
    res = store.sign(replace(REQ, proposer=alias), ACC)
    assert not res.signed and res.code == "SIGNER_IS_PROPOSER"
    assert store.count() == 0


def test_tc083_mixed_script_lookalike_party_is_invalid_not_independent():
    store, _ = make()
    res = store.sign(replace(REQ, requester="аccountant-1"), ACC)  # Cyrillic a + Latin
    assert (res.signed, res.code) == (False, "PARTY_INVALID")
    assert store.count() == 0


def test_tc083_zero_width_party_is_invalid_not_independent():
    store, _ = make()
    res = store.sign(replace(REQ, requester="accountant\u200b-1"), ACC)
    assert (res.signed, res.code) == (False, "PARTY_INVALID")
    assert store.count() == 0


@pytest.mark.parametrize("kind,code", [
    (SignerKind.LLM, "SIGNER_NOT_HUMAN"),
    (SignerKind.AUTOMATION, "SIGNER_NOT_HUMAN"),
])
def test_tc083_llm_and_automation_signers_denied(kind, code):
    store, _ = make()
    res = store.sign(REQ, Signer(kind, "accountant-1"))
    assert (res.signed, res.attestation, res.code) == (False, None, code)
    assert store.count() == 0


def test_tc083_forged_signer_kinds_and_types_denied():
    store, _ = make()
    class FakeKind:
        value = "HUMAN"
    for bad in (Signer("HUMAN", "accountant-1"), Signer(FakeKind(), "accountant-1"),  # type: ignore[arg-type]
                "accountant-1", None):
        res = store.sign(REQ, bad)  # type: ignore[arg-type]
        assert not res.signed and res.code == "SIGNER_INVALID"
    assert store.count() == 0
    assert store.sign(REQ, Signer(SignerKind.HUMAN, "")).code == "SIGNER_INVALID"
    assert store.sign(REQ, Signer(SignerKind.HUMAN, "acc\u200bountant-1")).code == "SIGNER_INVALID"
    assert store.count() == 0


def test_tc083_unregistered_human_and_default_registry_denied():
    store, _ = make()
    res = store.sign(REQ, Signer(SignerKind.HUMAN, "stranger"))
    assert (res.signed, res.code) == (False, "SIGNER_NOT_ACCOUNTANT")
    assert store.sign(REQ, ACC).signed  # registered in tenant-a
    assert store.sign(replace(REQ, tenant_id="tenant-b"), ACC).code == "SIGNER_NOT_ACCOUNTANT"
    empty = AttestationStore(Clock())
    assert empty.sign(REQ, ACC).code == "SIGNER_NOT_ACCOUNTANT" and empty.count() == 0


def test_tc083_wrong_decision_type_and_fabricated_pass_denied():
    store, _ = make()

    class FakePass:
        value = "PASS"

        def __eq__(self, other):
            return True

        __hash__ = None  # type: ignore[assignment]

    for fake in ("PASS", True, 1, None, FakePass(), {"decision": "PASS"}):
        res = store.sign(replace(REQ, decision=fake), ACC)  # type: ignore[arg-type]
        assert (res.signed, res.attestation, res.code) == (False, None, "DECISION_INVALID")
    fail = store.sign(replace(REQ, decision=AttestationDecision.FAIL), ACC)
    assert (fail.signed, fail.code) == (False, "DECISION_NOT_PASS")
    assert store.count() == 0 and store.history("tenant-a") == ()


def test_tc083_fabricated_request_object_denied():
    store, _ = make()

    class Fake:
        tenant_id = "tenant-a"
        revision_digest = REV
        policy_version = VER
        policy_digest = POL
        proposer = "proposer-1"
        requester = "requester-1"
        decision = AttestationDecision.PASS

    for fake in (Fake(), {"tenant_id": "tenant-a"}, None, "PASS"):
        res = store.sign(fake, ACC)  # type: ignore[arg-type]
        assert (res.signed, res.code) == (False, "REQUEST_INVALID")
    assert store.count() == 0


def test_tc083_fabricated_attestation_id_is_not_evidence():
    store, _ = make()
    store.sign(replace(REQ, requester="accountant-1"), ACC)  # denied
    for fake in ("PASS", "0" * 32, "", "accountant-1"):
        assert store.check_current(fake, "tenant-a", REV, VER, POL).code == "ATTESTATION_NOT_VALID"


def test_tc083_denied_results_never_echo_caller_input():
    store, _ = make()
    secret = "SECRET-xyz-987"
    res = store.sign(replace(REQ, proposer=secret, requester=secret), Signer(SignerKind.LLM, secret))
    assert secret not in repr(res)
    assert secret.casefold() not in repr(store.check_current(secret, secret, secret, secret, secret))
    assert secret.casefold() not in repr(store.revoke(secret, secret, Signer(SignerKind.HUMAN, secret)))


def test_tc083_broken_clock_and_id_source_fail_closed():
    def boom():
        raise RuntimeError("secret-text")

    store = AttestationStore(boom, accountants={"tenant-a": {"accountant-1"}})
    res = store.sign(REQ, ACC)
    assert (res.signed, res.code) == (False, "TIME_INVALID") and "secret" not in repr(res)
    assert store.count() == 0
    naive = AttestationStore(lambda: datetime(2026, 1, 1), accountants={"tenant-a": {"accountant-1"}})  # noqa: DTZ001 - naive on purpose
    assert naive.sign(REQ, ACC).code == "TIME_INVALID"

    store2, _ = make(id_source=boom)
    assert store2.sign(REQ, ACC).code == "ID_UNAVAILABLE" and store2.count() == 0
    store3, _ = make(id_source=lambda: "same")
    assert store3.sign(REQ, ACC).signed
    assert store3.sign(replace(REQ, revision_digest=REV2), ACC).code == "ID_UNAVAILABLE"
    assert store3.count() == 1


def test_constructor_validation():
    with pytest.raises(TypeError):
        AttestationStore("not callable")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AttestationStore(Clock(), max_audit=0)
    with pytest.raises(ValueError):
        AttestationStore(Clock(), accountants={"tenant-a": "accountant-1"})  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        AttestationStore(Clock(), accountants={"": {"x"}})


# ---------------------------------------------------------------- TC084
def test_tc084_revoke_valid_before_invalid_at_and_after_instant():
    store, clk = make()
    att = signed(store)
    clk.now = T0 + timedelta(minutes=10)
    revoked_at = clk.now
    res = store.revoke(att.attestation_id, "tenant-a", ACC)
    assert (res.revoked, res.code) == (True, "REVOKED")

    before = revoked_at - timedelta(microseconds=1)
    historical = chk(store, att, at=before)
    assert (historical.valid, historical.code) == (True, "VALID_HISTORICAL")
    at = chk(store, att, at=revoked_at)
    assert (at.valid, at.code) == (False, "REVOKED")
    assert chk(store, att, at=revoked_at + timedelta(seconds=1)).code == "REVOKED"
    # current validity via the clock: invalid now, and after the clock moves on
    assert chk(store, att).code == "REVOKED"
    clk.now += timedelta(days=1)
    assert chk(store, att).code == "REVOKED"
    # not valid before it was signed either
    assert chk(store, att, at=T0 - timedelta(seconds=1)).code == "NOT_YET_VALID"
    assert chk(store, att, at=T0).code == "VALID_HISTORICAL"


def test_tc084_history_preserved_and_labelled_historical():
    store, clk = make()
    a1 = signed(store)
    a2 = signed(store, replace(REQ, revision_digest=REV2))
    clk.now = T0 + timedelta(hours=1)
    assert store.revoke(a1.attestation_id, "tenant-a", ACC).revoked
    hist = store.history("tenant-a")
    assert [h.attestation_id for h in hist] == [a1.attestation_id, a2.attestation_id]
    assert hist[0].historical is True and hist[0].revoked_at == clk.now
    assert hist[0].revision_digest == REV and hist[0].signer == "accountant-1"
    assert hist[0].signed_at == T0  # the original record is unchanged apart from revoked_at
    assert hist[1].historical is False and hist[1].revoked_at is None
    assert store.count() == 2
    assert [h.attestation_id for h in store.history("tenant-a", REV2)] == [a2.attestation_id]
    # the untouched attestation stays valid; the revoked one is only readable, not evidence
    assert chk(store, a2, rev=REV2).valid and not chk(store, a1).valid
    # history never crosses tenants and rejects garbage tenants
    assert store.history("tenant-b") == () and store.history("") == () and store.history(None) == ()  # type: ignore[arg-type]


def test_tc084_revoke_denied_cases_change_nothing():
    store, clk = make()
    att = signed(store)
    clk.now = T0 + timedelta(minutes=5)
    denied = [
        store.revoke(att.attestation_id, "tenant-a", Signer(SignerKind.HUMAN, "accountant-2")),
        store.revoke(att.attestation_id, "tenant-a", Signer(SignerKind.LLM, "accountant-1")),
        store.revoke(att.attestation_id, "tenant-a", Signer(SignerKind.AUTOMATION, "accountant-1")),
        store.revoke(att.attestation_id, "tenant-b", ACC),
        store.revoke("unknown", "tenant-a", ACC),
        store.revoke(None, "tenant-a", ACC),  # type: ignore[arg-type]
        store.revoke(att.attestation_id, "tenant-a", "accountant-1"),  # type: ignore[arg-type]
    ]
    assert all((r.revoked, r.code) == (False, "REVOKE_DENIED") for r in denied)
    assert store.history("tenant-a")[0].revoked_at is None
    assert chk(store, att).valid


def test_tc084_second_revoke_does_not_move_the_instant():
    store, clk = make()
    att = signed(store)
    clk.now = T0 + timedelta(minutes=1)
    assert store.revoke(att.attestation_id, "tenant-a", ACC).revoked
    first = store.history("tenant-a")[0].revoked_at
    clk.now = T0 + timedelta(minutes=30)
    assert store.revoke(att.attestation_id, "tenant-a", ACC).code == "REVOKE_DENIED"
    assert store.history("tenant-a")[0].revoked_at == first


def test_tc084_revoke_with_broken_clock_fails_closed():
    state = {"bad": False}

    def clock():
        if state["bad"]:
            raise RuntimeError("x")
        return T0

    store = AttestationStore(clock, accountants={"tenant-a": {"accountant-1"}})
    att = signed(store)
    state["bad"] = True
    assert store.revoke(att.attestation_id, "tenant-a", ACC).code == "REVOKE_DENIED"
    assert store.history("tenant-a")[0].revoked_at is None
    assert chk(store, att).code == "TIME_INVALID"


def test_revoked_attestation_is_never_valid_via_check_current():
    store, clk = make()
    att = signed(store)
    assert chk(store, att).code == "VALID"
    clk.now = T0 + timedelta(minutes=1)
    assert store.revoke(att.attestation_id, "tenant-a", ACC).revoked
    for delta in (0, 1, 3600, 86400 * 365):
        clk.now = T0 + timedelta(minutes=1, seconds=delta)
        res = chk(store, att)
        assert (res.valid, res.code) == (False, "REVOKED")
    # the point-in-time query cannot produce the gating code VALID, even for a time before revocation
    past = chk(store, att, at=T0 + timedelta(seconds=30))
    assert past.valid is True and past.code == "VALID_HISTORICAL"
    assert not hasattr(store, "check")


def test_check_as_of_never_returns_the_gating_valid_code():
    store, _ = make()
    att = signed(store)
    for at in (T0, T0 + timedelta(days=1)):
        assert chk(store, att, at=at).code == "VALID_HISTORICAL"
    assert chk(store, att).code == "VALID"


def test_revoke_clamps_revoked_at_to_signed_at_when_clock_goes_backwards():
    store, clk = make()
    att = signed(store)
    clk.now = T0 - timedelta(hours=1)  # clock regressed before the signature
    assert store.revoke(att.attestation_id, "tenant-a", ACC).revoked
    rec = store.history("tenant-a")[0]
    assert rec.revoked_at == T0 and rec.revoked_at >= rec.signed_at
    clk.now = T0
    assert chk(store, att).code == "REVOKED"


def test_check_with_naive_explicit_time_is_invalid():
    store, _ = make()
    att = signed(store)
    assert chk(store, att, at=datetime(2026, 1, 1, 12, 0)).code == "TIME_INVALID"  # type: ignore[arg-type]  # noqa: DTZ001


# ----------------------------------------------------------------- audit
def test_audit_records_outcomes_with_fixed_codes_and_is_bounded():
    store, clk = make(max_audit=3)
    att = signed(store)
    store.sign(replace(REQ, requester="accountant-1"), ACC)
    entries = store.audit()
    assert [(e.kind, e.value) for e in entries] == [("SIGN", "SIGNED"), ("SIGN", "SIGNER_IS_REQUESTER")]
    assert entries[0].subject == att.attestation_id and entries[0].at == T0
    for _ in range(5):
        chk(store, att)
    assert len(store.audit()) == 3
    assert isinstance(store.audit(), tuple)
    assert {e.kind for e in store.audit()} == {"CHECK"}
    clk.now = T0


def test_concurrent_sign_and_revoke_are_consistent():
    store, _ = make()
    digests = [f"{i:064x}" for i in range(40)]

    def work(d):
        res = store.sign(replace(REQ, revision_digest=d), ACC)
        assert res.signed
        return res.attestation.attestation_id

    with ThreadPoolExecutor(max_workers=8) as ex:
        ids = list(ex.map(work, digests))
    assert len(set(ids)) == 40 and store.count() == 40
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda i: store.revoke(i, "tenant-a", ACC).revoked, ids))
    assert all(results)
    assert all(h.historical for h in store.history("tenant-a"))
    assert len(store.history("tenant-a")) == 40
