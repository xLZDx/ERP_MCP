"""Behavioral tests of the Phase 2 promotion service over the in-memory head/attestation port.

Time comes from the fake store clock. A spy around the port counts ``promote_head`` calls so each
``test_guard_*`` proves the SERVICE guard fired (the port is never reached) and nothing was
written; deleting that guard turns the test red even though the port would reject later.
"""
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from business_ai_gateway.phase2.fakes import PROMOTER, WORKER, InMemoryLiving
from business_ai_gateway.phase2.ports import PortError, Scope, evidence_digest
from business_ai_gateway.phase2.promotion import (
    AttestationView,
    Evidence,
    Outcome,
    PromotionService,
    normalize_identity,
)

SCOPE = Scope("A", "s1")
MODEL = "model/x"
OBSERVER, PROPOSER, APPROVER, REQUESTER = "obs1", "prop1", "prom1", "req1"
LONG_AGO = datetime(2025, 1, 1, tzinfo=UTC)


def uid(n: int) -> UUID:
    return UUID(int=n)


class SpyPort:
    """Delegates to the real fake and counts write calls."""

    def __init__(self, inner):
        self._inner = inner
        self.promote_calls = 0
        self.fail_with: Exception | None = None

    async def promote_head(self, *args, **kwargs):
        self.promote_calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return await self._inner.promote_head(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class FakeReader:
    """Read side over the fake's state; ``stale`` pins a pre-captured view (race simulation)."""

    def __init__(self, living: InMemoryLiving):
        self.living = living
        self.stale: AttestationView | None = None
        self.raises: Exception | None = None

    async def find_attestation(self, scope, revision_id, evidence_ref):
        if self.raises is not None:
            raise self.raises
        if self.stale is not None:
            return self.stale
        src = self.living._st.sources[scope]
        for a in src.atts.values():
            if a.revision_id == revision_id and a.evidence_ref == evidence_ref:
                return AttestationView(a.attestation_id, a.revision_id, a.proposer, a.observer,
                                       a.evidence_ref, a.evidence_digest, a.decision,
                                       a.expires_at, a.revoked_at)
        return None

    async def is_trusted_reviewer(self, scope, subject):
        return self.living._trusted(self.living._st.sources[scope], subject)


class World:
    def __init__(self):
        self.living = InMemoryLiving()
        self.clock = self.living.clock
        self.port = SpyPort(self.living)
        self.reader = FakeReader(self.living)
        self.svc = PromotionService(self.port, self.reader, self.clock.now)
        self.n = 0

    async def setup(self):
        for name, parent in ((OBSERVER, WORKER), (APPROVER, PROMOTER), ("prom2", PROMOTER)):
            await self.living.define_actor(name, (parent,))
        await self.living.create_head(PROMOTER, SCOPE, MODEL)
        return self

    async def attest(self, n, *, ref=None, decision="APPROVE", ttl=3600.0, observer=OBSERVER,
                     proposer=PROPOSER):
        """Observe revision ``n`` (idempotent) and record an attestation for it."""
        rev, digest = uid(100 + n), f"{n:x}".rjust(64, "0")
        await self.living.ingest_observation(
            WORKER, SCOPE, uid(200 + n), "obj", rev, "OBSERVED", digest, None, LONG_AGO)
        ref = ref or f"review-{n}"
        self.n += 1
        att_id = uid(300 + self.n)
        await self.living.record_attestation(
            observer, SCOPE, att_id, rev, proposer, ref, evidence_digest(digest, ref), decision,
            self.clock.now() + timedelta(seconds=ttl))
        return rev, Evidence(digest, ref), att_id

    async def promote(self, rev, ev, *, expected=0, requester=REQUESTER, approver=APPROVER, acc=None):
        self.n += 1
        return await self.svc.promote(SCOPE, MODEL, rev, expected, requester, approver, ev,
                                      acc or uid(400 + self.n))

    async def rollback(self, to_version, ev, *, expected, requester=REQUESTER, approver=APPROVER):
        self.n += 1
        return await self.svc.rollback(SCOPE, MODEL, to_version, expected, requester, approver,
                                       ev, uid(500 + self.n))

    async def snapshot(self):
        self.mark = self.port.promote_calls
        return (await self.living.get_head(PROMOTER, SCOPE, MODEL),
                await self.living.list_acceptances(PROMOTER, SCOPE))

    def att(self, att_id):
        return self.living._st.sources[SCOPE].atts[att_id]


async def world():
    return await World().setup()


async def assert_rejected(w, before, result, outcome, *, port_reached=False):
    reached = w.port.promote_calls > w.mark
    assert result.outcome is outcome, result
    assert result.new_version is None
    assert not result.ok
    assert await w.snapshot() == before
    assert reached is port_reached


# --------------------------------------------------------------------------- happy path
async def test_promote_happy_path_records_acceptance_and_moves_head():
    w = await world()
    rev, ev, _ = await w.attest(1)
    res = await w.promote(rev, ev)
    assert (res.outcome, res.new_version, res.ok) == (Outcome.PROMOTED, 1, True)
    head, accs = await w.snapshot()
    assert (head.revision_id, head.version) == (rev, 1)
    assert [(a.to_version, a.accepted_revision, a.approver_subject) for a in accs] == [(1, rev, APPROVER)]


# --------------------------------------------------------------------------- CAS
@pytest.mark.parametrize("expected", [1, 5, -1])
async def test_guard_cas_mismatch_writes_nothing(expected):
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    res = await w.promote(rev, ev, expected=expected)
    outcome = Outcome.REJECTED_INPUT if expected < 0 else Outcome.REJECTED_CAS
    await assert_rejected(w, before, res, outcome)


async def test_guard_cas_second_promote_with_stale_expected_version():
    w = await world()
    r1, e1, _ = await w.attest(1)
    r2, e2, _ = await w.attest(2)
    assert (await w.promote(r1, e1)).ok
    before, calls = await w.snapshot(), w.port.promote_calls
    res = await w.promote(r2, e2, expected=0)
    assert res.outcome is Outcome.REJECTED_CAS and w.port.promote_calls == calls
    assert await w.snapshot() == before


async def test_unknown_head_is_cas_rejection():
    w = await world()
    rev, ev, _ = await w.attest(1)
    res = await w.svc.promote(SCOPE, "model/missing", rev, 0, REQUESTER, APPROVER, ev, uid(1))
    assert res.outcome is Outcome.REJECTED_CAS and w.port.promote_calls == 0


# --------------------------------------------------------------------------- independence
@pytest.mark.parametrize("requester", ["prom1", "PROM1", "  prom1  ", "ｐｒｏｍ１"])
async def test_guard_approver_independent_of_requester(requester):
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    res = await w.promote(rev, ev, requester=requester)
    await assert_rejected(w, before, res, Outcome.REJECTED_SELF_APPROVAL)
    assert res.code == "APPROVER_IS_REQUESTER"


@pytest.mark.parametrize("approver, observer, proposer", [
    ("obs1", "obs1", "prop1"),
    (" OBS1 ", "obs1", "prop1"),
    ("prop1", "obs1", "prop1"),
    ("PROP1 ", "obs1", "prop1"),
])
async def test_guard_approver_independent_of_observer_and_proposer(approver, observer, proposer):
    w = await world()
    await w.living.define_actor("prop1", (WORKER,))
    rev, ev, _ = await w.attest(1, observer=observer, proposer=proposer)
    before = await w.snapshot()
    res = await w.promote(rev, ev, approver=approver)
    await assert_rejected(w, before, res, Outcome.REJECTED_SELF_APPROVAL)
    assert res.code == "APPROVER_NOT_INDEPENDENT"


@pytest.mark.parametrize("requester, approver", [("", APPROVER), (REQUESTER, ""), ("  ", APPROVER),
                                                 (None, APPROVER), (REQUESTER, None)])
async def test_blank_identity_is_input_rejection(requester, approver):
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    res = await w.promote(rev, ev, requester=requester, approver=approver)
    await assert_rejected(w, before, res, Outcome.REJECTED_INPUT)


async def test_non_promoter_approver_is_rejected_by_port_and_typed():
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    res = await w.promote(rev, ev, approver="stranger-with-worker-role")
    # the unknown actor cannot even read the head: fails closed, nothing written
    assert res.outcome is Outcome.FAILED_CLOSED and res.code == "SCOPE_NOT_GRANTED"
    assert await w.snapshot() == before and w.port.promote_calls == 0
    await w.living.define_actor("plain-worker", (WORKER,))
    res = await w.promote(rev, ev, approver="plain-worker")
    assert res.outcome is Outcome.REJECTED_UNTRUSTED and res.code == "PERMISSION_DENIED"
    assert await w.snapshot() == before


def test_normalize_identity():
    assert normalize_identity("  ＡＢＣ ") == "abc"
    assert normalize_identity(None) == "" and normalize_identity(5) == ""


# --------------------------------------------------------------------------- trust
async def test_guard_untrusted_reviewer():
    w = await world()
    rev, ev, _ = await w.attest(1)
    await w.living.set_trusted_reviewer(WORKER, SCOPE, False, datetime(2099, 1, 1, tzinfo=UTC))
    before = await w.snapshot()
    res = await w.promote(rev, ev)
    await assert_rejected(w, before, res, Outcome.REJECTED_UNTRUSTED)
    assert res.code == "REVIEWER_NOT_TRUSTED"


async def test_guard_trust_window_expired():
    w = await world()
    rev, ev, _ = await w.attest(1)
    await w.living.set_trusted_reviewer(WORKER, SCOPE, True, w.clock.now() + timedelta(seconds=60))
    assert (await w.promote(rev, ev)).ok  # still trusted inside the window
    r2, e2, _ = await w.attest(2)
    w.clock.advance(120)
    before = await w.snapshot()
    calls = w.port.promote_calls
    res = await w.promote(r2, e2, expected=1)
    assert res.outcome is Outcome.REJECTED_UNTRUSTED and w.port.promote_calls == calls
    assert await w.snapshot() == before


# --------------------------------------------------------------------------- evidence
@pytest.mark.parametrize("make", [
    lambda e: None,
    lambda e: Evidence(e.revision_digest, ""),
    lambda e: Evidence(e.revision_digest, "   "),
    lambda e: Evidence("not-a-digest", e.evidence_ref),
    lambda e: Evidence("", e.evidence_ref),
])
async def test_guard_missing_or_blank_evidence(make):
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    res = await w.promote(rev, make(ev))
    await assert_rejected(w, before, res, Outcome.REJECTED_EVIDENCE)
    assert res.code == "EVIDENCE_REQUIRED"


async def test_guard_tampered_evidence_digest_mismatch():
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    tampered = Evidence("f" * 64, ev.evidence_ref)  # same reference, different revision content
    res = await w.promote(rev, tampered)
    await assert_rejected(w, before, res, Outcome.REJECTED_EVIDENCE)
    assert res.code == "EVIDENCE_DIGEST_MISMATCH"


async def test_tampered_reference_matches_no_attestation():
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    res = await w.promote(rev, Evidence(ev.revision_digest, ev.evidence_ref + "-x"))
    await assert_rejected(w, before, res, Outcome.REJECTED_EVIDENCE)


async def test_attestation_for_another_revision_is_not_evidence():
    w = await world()
    _, ev1, _ = await w.attest(1)
    r2, _, _ = await w.attest(2)
    before = await w.snapshot()
    res = await w.promote(r2, ev1)
    await assert_rejected(w, before, res, Outcome.REJECTED_EVIDENCE)


async def test_guard_reject_decision_is_not_approval():
    w = await world()
    rev, ev, _ = await w.attest(1, decision="REJECT")
    before = await w.snapshot()
    res = await w.promote(rev, ev)
    await assert_rejected(w, before, res, Outcome.REJECTED_EVIDENCE)
    assert res.code == "EVIDENCE_NOT_APPROVED"


async def test_guard_expired_attestation():
    w = await world()
    rev, ev, _ = await w.attest(1, ttl=60)
    w.clock.advance(61)
    before = await w.snapshot()
    res = await w.promote(rev, ev)
    await assert_rejected(w, before, res, Outcome.REJECTED_EXPIRED)


async def test_expiry_is_judged_by_injected_clock_at_boundary():
    w = await world()
    rev, ev, att_id = await w.attest(1, ttl=60)
    w.reader.stale = w.reader.stale or await w.reader.find_attestation(SCOPE, rev, ev.evidence_ref)
    exp = w.att(att_id).expires_at
    svc = PromotionService(w.port, w.reader, lambda: exp)  # now == expires_at -> expired
    res = await svc.promote(SCOPE, MODEL, rev, 0, REQUESTER, APPROVER, ev, uid(9))
    assert res.outcome is Outcome.REJECTED_EXPIRED and w.port.promote_calls == 0


async def test_guard_revoked_attestation():
    w = await world()
    rev, ev, att_id = await w.attest(1)
    await w.living.revoke_attestation(OBSERVER, SCOPE, att_id)
    before = await w.snapshot()
    res = await w.promote(rev, ev)
    await assert_rejected(w, before, res, Outcome.REJECTED_REVOKED)


# --------------------------------------------------------------------------- fail closed / atomic
@pytest.mark.parametrize("exc", [RuntimeError("boom"), PortError("SOMETHING_NEW"), TimeoutError()])
async def test_reader_failure_fails_closed(exc):
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    w.reader.raises = exc
    res = await w.promote(rev, ev)
    await assert_rejected(w, before, res, Outcome.FAILED_CLOSED)


@pytest.mark.parametrize("exc, code", [(PortError("SOMETHING_NEW"), "SOMETHING_NEW"),
                                       (ConnectionError("down"), "ConnectionError")])
async def test_port_write_failure_fails_closed(exc, code):
    w = await world()
    rev, ev, _ = await w.attest(1)
    before = await w.snapshot()
    w.port.fail_with = exc
    res = await w.promote(rev, ev)
    assert (res.outcome, res.code) == (Outcome.FAILED_CLOSED, code)
    assert await w.snapshot() == before


async def test_port_rechecks_when_reader_view_is_stale():
    """Revocation lands after the service read: the port's re-verification still blocks it."""
    w = await world()
    rev, ev, att_id = await w.attest(1)
    w.reader.stale = await w.reader.find_attestation(SCOPE, rev, ev.evidence_ref)
    await w.living.revoke_attestation(OBSERVER, SCOPE, att_id)
    before = await w.snapshot()
    res = await w.promote(rev, ev)
    await assert_rejected(w, before, res, Outcome.REJECTED_REVOKED, port_reached=True)
    assert res.code == "EVIDENCE_REVOKED"


async def test_reused_acceptance_id_is_typed_and_writes_nothing():
    w = await world()
    r1, e1, _ = await w.attest(1)
    r2, e2, _ = await w.attest(2)
    assert (await w.promote(r1, e1, acc=uid(77))).ok
    before = await w.snapshot()
    res = await w.promote(r2, e2, expected=1, acc=uid(77))
    assert res.outcome is Outcome.REJECTED_ACCEPTANCE_ID and await w.snapshot() == before


# --------------------------------------------------------------------------- rollback
async def two_versions(w):
    r1, e1, a1 = await w.attest(1)
    r2, e2, a2 = await w.attest(2)
    assert (await w.promote(r1, e1)).new_version == 1
    assert (await w.promote(r2, e2, expected=1)).new_version == 2
    return r1, e1, a1, r2, e2, a2


async def test_rollback_restores_previous_content_as_new_version_history_intact():
    w = await world()
    r1, e1, _a1, r2, _e2, _a2 = await two_versions(w)
    _, history = await w.snapshot()
    res = await w.rollback(1, e1, expected=2)
    assert (res.outcome, res.new_version) == (Outcome.ROLLED_BACK, 3)
    head, after = await w.snapshot()
    assert (head.revision_id, head.version) == (r1, 3)
    assert after[:2] == history                       # earlier acceptances untouched
    assert [a.accepted_revision for a in after] == [r1, r2, r1]


async def test_rollback_does_not_restore_revoked_rights():
    w = await world()
    _r1, e1, a1, _r2, _e2, _a2 = await two_versions(w)
    await w.living.revoke_attestation(OBSERVER, SCOPE, a1)
    revoked_at = w.att(a1).revoked_at
    before = await w.snapshot()
    res = await w.rollback(1, e1, expected=2)           # original approval is revoked now
    await assert_rejected(w, before, res, Outcome.REJECTED_REVOKED)
    assert w.att(a1).revoked_at == revoked_at


async def test_rollback_with_fresh_approval_works_and_old_revocation_stays():
    w = await world()
    r1, _e1, a1, *_ = await two_versions(w)
    await w.living.revoke_attestation(OBSERVER, SCOPE, a1)
    revoked_at = w.att(a1).revoked_at
    _, fresh, _ = await w.attest(1, ref="review-1-fresh")
    res = await w.rollback(1, fresh, expected=2)
    assert res.outcome is Outcome.ROLLED_BACK
    assert w.att(a1).revoked_at == revoked_at           # not resurrected
    again = await w.attest(1, ref="review-1-x")
    await w.living.revoke_attestation(OBSERVER, SCOPE, again[2])
    head, _ = await w.snapshot()
    assert head.revision_id == r1 and head.version == 3


async def test_rollback_refused_when_original_approval_expired():
    w = await world()
    _r1, e1, *_ = await two_versions(w)
    w.clock.advance(7200)
    before = await w.snapshot()
    res = await w.rollback(1, e1, expected=2)
    await assert_rejected(w, before, res, Outcome.REJECTED_EXPIRED)


async def test_guard_rollback_is_cas_guarded():
    w = await world()
    _r1, e1, *_ = await two_versions(w)
    r3, e3, _ = await w.attest(3)
    assert (await w.promote(r3, e3, expected=2)).new_version == 3
    before, calls = await w.snapshot(), w.port.promote_calls
    res = await w.rollback(1, e1, expected=2)           # head is really at 3
    assert res.outcome is Outcome.REJECTED_CAS and w.port.promote_calls == calls
    assert await w.snapshot() == before


async def test_guard_rollback_needs_independent_approver():
    w = await world()
    _r1, e1, *_ = await two_versions(w)
    before, calls = await w.snapshot(), w.port.promote_calls
    same = await w.rollback(1, e1, expected=2, requester=" PROM1")
    observer_as_approver = await w.rollback(1, e1, expected=2, approver=OBSERVER)
    for res in (same, observer_as_approver):
        assert res.outcome is Outcome.REJECTED_SELF_APPROVAL and w.port.promote_calls == calls
    assert await w.snapshot() == before


@pytest.mark.parametrize("to_version", [0, -1, 2, 3, 99, True, "1", None])
async def test_rollback_target_table(to_version):
    w = await world()
    _r1, e1, *_ = await two_versions(w)
    before, calls = await w.snapshot(), w.port.promote_calls
    res = await w.rollback(to_version, e1, expected=2)
    assert res.outcome is Outcome.REJECTED_TARGET and w.port.promote_calls == calls
    assert await w.snapshot() == before


async def test_rollback_to_content_already_at_head_is_refused():
    w = await world()
    _r1, e1, *_ = await two_versions(w)
    assert (await w.rollback(1, e1, expected=2)).ok     # head now shows r1 again at v3
    before, calls = await w.snapshot(), w.port.promote_calls
    res = await w.rollback(1, e1, expected=3)
    assert res.outcome is Outcome.REJECTED_TARGET and w.port.promote_calls == calls
    assert await w.snapshot() == before


async def test_rollback_requires_evidence():
    w = await world()
    await two_versions(w)
    before, calls = await w.snapshot(), w.port.promote_calls
    res = await w.rollback(1, None, expected=2)
    assert res.outcome is Outcome.REJECTED_EVIDENCE and w.port.promote_calls == calls
    assert await w.snapshot() == before


async def test_rollback_evidence_of_another_revision_is_refused():
    w = await world()
    _r1, _e1, _a1, _r2, e2, _a2 = await two_versions(w)
    before = await w.snapshot()
    res = await w.rollback(1, e2, expected=2)           # evidence belongs to v2 content
    await assert_rejected(w, before, res, Outcome.REJECTED_EVIDENCE)


@pytest.mark.parametrize("where", ["reader", "list_acceptances"])
async def test_rollback_failure_fails_closed(where):
    w = await world()
    _r1, e1, *_ = await two_versions(w)
    before = await w.snapshot()
    if where == "reader":
        w.reader.raises = RuntimeError("boom")
    else:
        async def broken(*_a, **_k):
            raise ConnectionError("down")
        w.port.list_acceptances = broken
    res = await w.rollback(1, e1, expected=2)
    await assert_rejected(w, before, res, Outcome.FAILED_CLOSED)
