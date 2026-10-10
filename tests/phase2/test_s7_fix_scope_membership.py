"""S7 fix batch F3: scope / membership / revisions / port / changes regression tests. Offline.

Written before the fixes; every group below was seen red on the pre-fix code (see the sprint report).
New names are resolved through the module object inside each test so one missing name fails one test.
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from business_ai_gateway.phase2 import (
    drive_changes,
    drive_membership,
    drive_port,
    drive_revisions,
    drive_scope,
)
from business_ai_gateway.phase2.drive_changes import (
    FOLDER_MIME_TYPE,
    DriveChange,
    DriveChangeKind,
    DriveChangeProjector,
    DrivePage,
)
from business_ai_gateway.phase2.drive_cursor import DriveCorpus
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_membership import (
    Corpus,
    MembershipChecker,
    MembershipVerdict,
    PageStatus,
)
from business_ai_gateway.phase2.drive_port import (
    ChangesPage,
    DriveErrorCode,
    DrivePortError,
    DrivePortIdentity,
    FileMeta,
    RevisionMeta,
)
from business_ai_gateway.phase2.drive_revisions import (
    HistoryStatus,
    ObservationOutcome,
    RevisionTracker,
    list_history,
)
from business_ai_gateway.phase2.drive_scope import (
    AccessProof,
    CorpusDeclaration,
    MembershipCode,
    MembershipStatus,
    ScopeClaim,
    observe_new_child_access,
    prove_scoped_read,
    resolve_membership,
)

IDENT = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")
NARROW = ("drive.file",)
V = MembershipVerdict


def _file(fid, parents, *, mime="application/pdf", trashed=False, drive=None, shortcut=None):
    return FileMeta(fid, "n", mime, tuple(parents), trashed, drive, shortcut)


def _folder(fid, parents, **kw):
    return _file(fid, parents, mime=FOLDER_MIME_TYPE, **kw)


def _fake(*metas, **kw):
    fake = FakeDrivePort(**kw)
    for m in metas:
        fake.set_file(m)
    return fake


def _world():
    """R (root) > F1 > A ; X (outside) > OUT."""
    return _fake(
        _folder("R", ()), _folder("F1", ("R",)), _file("A", ("F1",)), _folder("X", ()), _file("OUT", ("X",)),
    )


def _ck(fake, epoch=0, **kw):
    return MembershipChecker(fake, IDENT, Corpus("account:acc-1", ("R",), **kw), epoch)


def _decl(roots=("R",)):
    return CorpusDeclaration("account:acc-1", None, tuple(roots))


def _page(changes, token="T1", nxt="T2"):
    return DrivePage(token, tuple(changes), next_page_token=nxt)


def _up(cid, fid, **kw):
    return DriveChange(cid, fid, "r1", DriveChangeKind.UPSERT, **kw)


# --- 1. cache invalidation reaches the corpus root ---------------------------------------------------


async def test_trashed_root_change_drops_cached_descendants_and_denies_disclosure():
    fake = _world()
    ck = _ck(fake)
    assert await ck.authorize_disclosure("A") is True  # cached under R
    fake.set_file(_folder("R", (), trashed=True))
    prep = await ck.prepare_page(_page([_up("c1", "R")]), "T1")
    assert prep.status in (PageStatus.PREPARED, PageStatus.REFUSED)
    assert ck.cached("A") is None
    assert await ck.authorize_disclosure("A") is False


async def test_removed_root_change_drops_cached_descendants_and_denies_disclosure():
    fake = _world()
    ck = _ck(fake)
    assert await ck.authorize_disclosure("A") is True
    removed = DriveChange("c1", "R", None, DriveChangeKind.REMOVED)
    await ck.prepare_page(_page([removed]), "T1")
    assert await ck.authorize_disclosure("A") is False


async def test_restored_root_is_trusted_again_after_an_upsert_change():
    fake = _world()
    ck = _ck(fake)
    await ck.prepare_page(_page([DriveChange("c1", "R", None, DriveChangeKind.REMOVED)]), "T1")
    assert await ck.authorize_disclosure("A") is False
    await ck.prepare_page(_page([_up("c2", "R")], token="T2", nxt="T3"), "T2")
    assert await ck.authorize_disclosure("A") is True


# --- 2. epoch change while resolving ------------------------------------------------------------------


async def test_check_with_epoch_change_mid_resolve_is_check_failed_stale_and_not_cached():
    fake = _world()
    ck = _ck(fake)
    fake.run_after_calls(1, lambda f: ck.advance_epoch(1))
    res = await ck.check("A")
    assert (res.verdict, res.reason, res.candidate_allowed) == (V.CHECK_FAILED, "SCOPE_EPOCH_STALE", False)
    assert ck.cached("A") is None


async def test_authorize_disclosure_is_false_when_the_epoch_changes_mid_resolve():
    fake = _world()
    ck = _ck(fake)
    fake.run_after_calls(1, lambda f: ck.advance_epoch(1))
    assert await ck.authorize_disclosure("A") is False


async def test_prepare_page_refuses_with_the_epoch_reason_when_the_epoch_changes_mid_page():
    fake = _world()
    ck = _ck(fake)
    fake.run_after_calls(1, lambda f: ck.advance_epoch(1))
    prep = await ck.prepare_page(_page([_up("c1", "A")]), "T1")
    assert (prep.status, prep.reason, prep.batch) == (PageStatus.REFUSED, "EPOCH_CHANGED_DURING_PAGE", None)


# --- 3. one corpus declaration, one limit -------------------------------------------------------------


def test_root_limits_are_one_constant_1_to_1000_everywhere():
    assert drive_scope.MAX_CORPUS_ROOTS == drive_membership.MAX_ROOTS == drive_port.MAX_CORPUS_ROOTS == 1000
    ok = tuple(f"R{i}" for i in range(1000))
    assert len(CorpusDeclaration("account:acc-1", None, ok).root_folder_ids) == 1000
    assert len(Corpus("account:acc-1", ok).root_folder_ids) == 1000
    with pytest.raises(ValueError, match="CORPUS_INVALID"):
        CorpusDeclaration("account:acc-1", None, (*ok, "EXTRA"))


async def test_one_cursor_corpus_feeds_resolve_membership_and_the_checker():
    dc = DriveCorpus(None, ("R",))
    decl = drive_scope.declaration_from_drive_corpus(dc, IDENT)
    corp = drive_membership.corpus_from_drive_corpus(dc, IDENT)
    fake = _world()
    assert (await resolve_membership(fake, IDENT, 0, decl, "A")).in_scope is True
    res = await MembershipChecker(fake, IDENT, corp, 0).check("A")
    assert res.verdict is V.IN_SCOPE


def test_500_root_cursor_corpus_builds_in_both_modules():
    dc = DriveCorpus(None, tuple(f"R{i}" for i in range(500)))
    assert len(drive_scope.declaration_from_drive_corpus(dc, IDENT).root_folder_ids) == 500
    assert len(drive_membership.corpus_from_drive_corpus(dc, IDENT).root_folder_ids) == 500


@pytest.mark.parametrize("identity,drive_id", [
    (IDENT, "D1"),  # account namespace cannot carry a drive id
    (DrivePortIdentity("drive:D1", "tenant-1", "conn-1"), None),
    (DrivePortIdentity("drive:D1", "tenant-1", "conn-1"), "D2"),
])
def test_converters_refuse_a_namespace_or_drive_mismatch_with_a_fixed_code(identity, drive_id):
    dc = DriveCorpus(drive_id, ("R",))
    with pytest.raises(ValueError, match="^CORPUS_IDENTITY_MISMATCH$"):
        drive_scope.declaration_from_drive_corpus(dc, identity)
    with pytest.raises(ValueError, match="^CORPUS_IDENTITY_MISMATCH$"):
        drive_membership.corpus_from_drive_corpus(dc, identity)


def test_converters_accept_the_matching_shared_drive_and_refuse_foreign_objects():
    ident = DrivePortIdentity("drive:D1", "tenant-1", "conn-1")
    dc = DriveCorpus("D1", ("R",))
    assert drive_scope.declaration_from_drive_corpus(dc, ident).drive_id == "D1"
    assert drive_membership.corpus_from_drive_corpus(dc, ident).shared_drive_id == "D1"
    for bad in (None, "x", object.__new__(DriveCorpus)):
        with pytest.raises(ValueError, match="^CORPUS_INVALID$"):
            drive_scope.declaration_from_drive_corpus(bad, ident)
        with pytest.raises(ValueError, match="^CORPUS_INVALID$"):
            drive_membership.corpus_from_drive_corpus(bad, ident)
    with pytest.raises(ValueError, match="^CORPUS_INVALID$"):
        drive_scope.declaration_from_drive_corpus(dc, object())


# --- 4. parity between resolve_membership and MembershipChecker ----------------------------------------


def _chain(n):
    metas = [_folder("R", ())]
    prev = "R"
    for i in range(n):
        metas.append(_folder(f"D{i}", (prev,)))
        prev = f"D{i}"
    metas.append(_file("T", (prev,)))
    return metas


_WORLDS = {
    "cycle": ([_file("T", ("B",)), _folder("B", ("T",))], False),
    "self_parent": ([_file("T", ("T",))], False),
    "trashed_ancestor": ([_file("T", ("P",)), _folder("P", ("R",), trashed=True), _folder("R", ())], False),
    "shortcut_leaf": ([_file("T", ("R",), shortcut="Z"), _file("Z", ("R",)), _folder("R", ())], False),
    "other_drive": ([_file("T", ("R",), drive="OTHER"), _folder("R", ())], False),
    "diamond_in": (
        [_file("T", ("B", "C")), _folder("B", ("D",)), _folder("C", ("D",)), _folder("D", ("R",)), _folder("R", ())],
        True,
    ),
    "diamond_out": (
        [_file("T", ("B", "C")), _folder("B", ("D",)), _folder("C", ("D",)), _folder("D", ()), _folder("R", ())],
        False,
    ),
    "chain_at_limit": (_chain(31), True),
    "chain_over_limit": (_chain(32), False),
}


@pytest.mark.parametrize("name", sorted(_WORLDS))
async def test_scope_and_membership_agree_on_shared_worlds(name):
    metas, expected = _WORLDS[name]
    scope_res = await resolve_membership(_fake(*metas), IDENT, 0, _decl(), "T")
    member_res = await _ck(_fake(*metas)).check("T")
    assert scope_res.in_scope is expected
    assert (member_res.verdict is V.IN_SCOPE) is expected


async def test_a_diamond_is_not_reported_as_a_cycle_by_either_module():
    metas, _ = _WORLDS["diamond_out"]
    scope_res = await resolve_membership(_fake(*metas), IDENT, 0, _decl(), "T")
    member_res = await _ck(_fake(*metas)).check("T")
    assert scope_res.code is MembershipCode.OUTSIDE_CORPUS
    assert (member_res.verdict, member_res.reason) == (V.SCOPE_ESCAPE_DENIED, "OUT_OF_CORPUS")


async def test_a_real_cycle_is_still_a_cycle_in_both_modules():
    metas, _ = _WORLDS["cycle"]
    scope_res = await resolve_membership(_fake(*metas), IDENT, 0, _decl(), "T")
    member_res = await _ck(_fake(*metas)).check("T")
    assert scope_res.code is MembershipCode.CYCLE
    assert (member_res.verdict, member_res.reason) == (V.NOT_IN_SCOPE, "CYCLE_OR_DEPTH")


def test_budget_and_depth_constants_are_shared():
    assert drive_membership.MAX_LOOKUPS_PER_CHECK == drive_scope.DEFAULT_MAX_CALLS
    assert drive_membership.MAX_CHAIN_DEPTH == drive_scope.DEFAULT_MAX_DEPTH


# --- 5. diamonds, foreign tombstones, bounded indexes, page budget ------------------------------------


async def test_shared_ancestor_is_visited_once_not_flagged_as_cycle_in_the_walk():
    metas, _ = _WORLDS["diamond_in"]
    fake = _fake(*metas)
    res = await _ck(fake).check("T")
    assert res.verdict is V.IN_SCOPE
    assert fake.count("get_file_meta") == len({"T", "B", "C", "D", "ROOT"})  # D fetched once; the root is read too (M03)


async def test_foreign_drive_upsert_emits_no_tombstone_and_no_file_id_without_a_shared_drive():
    fake = _world()
    fake.set_file(_file("FOREIGN", ("X",), drive="OTHER"))
    ck = _ck(fake)
    prep = await ck.prepare_page(_page([_up("c1", "FOREIGN", drive_id="OTHER"), _up("c2", "A")]), "T1")
    assert prep.status is PageStatus.PREPARED and prep.batch is not None
    assert all(t.file_id != "FOREIGN" for t in prep.batch.tombstones)
    assert all(c.file_id != "FOREIGN" for c in prep.batch.candidates)
    assert "FOREIGN" not in prep.batch.requalify_folder_ids
    assert prep.batch.denied_changes == 1
    assert all(r.file_id != "FOREIGN" for r in prep.results)


async def test_foreign_drive_removal_emits_no_tombstone_without_a_shared_drive():
    ck = _ck(_world())
    gone = DriveChange("c1", "FOREIGN", None, DriveChangeKind.REMOVED, drive_id="OTHER")
    prep = await ck.prepare_page(_page([gone]), "T1")
    assert prep.status is PageStatus.PREPARED and prep.batch is not None
    assert prep.batch.tombstones == () and prep.batch.requalify_folder_ids == ()
    assert prep.batch.denied_changes == 1


async def test_ancestor_set_of_a_hostile_wide_file_is_capped_and_not_cached():
    wide = _file("W", tuple(f"P{i}" for i in range(5000)))
    ck = _ck(_fake(wide))
    res = await ck.check("W")
    assert (res.verdict, res.reason) == (V.NOT_IN_SCOPE, "CYCLE_OR_DEPTH")
    cap = drive_membership.MAX_ANCESTORS_PER_ENTRY
    assert sum(len(v) for v in ck._by_ancestor.values()) <= cap
    assert ck.cached("W") is None


async def test_total_ancestor_index_is_bounded(monkeypatch):
    monkeypatch.setattr(drive_membership, "MAX_ANCESTOR_INDEX_ENTRIES", 3)
    fake = _world()
    fake.set_file(_file("A2", ("F1",)))
    ck = _ck(fake)
    await ck.check("A")
    await ck.check("A2")
    assert sum(len(v) for v in ck._by_ancestor.values()) <= 3
    assert (await ck.check("A2")).verdict is V.IN_SCOPE  # still correct, just not cached


async def test_page_lookup_budget_refuses_with_a_fixed_reason(monkeypatch):
    monkeypatch.setattr(drive_membership, "MAX_LOOKUPS_PER_PAGE", 3)
    fake = _world()
    for i in range(5):
        fake.set_file(_file(f"A{i}", ("F1",)))
    prep = await _ck(fake).prepare_page(_page([_up(f"c{i}", f"A{i}") for i in range(5)]), "T1")
    assert (prep.status, prep.reason, prep.batch) == (PageStatus.REFUSED, "PAGE_LOOKUP_BUDGET_EXCEEDED", None)
    assert fake.count("get_file_meta") <= 3 + drive_membership.MAX_LOOKUPS_PER_CHECK


# --- 6. unknown change kinds refuse the page --------------------------------------------------------------


async def test_page_with_an_unknown_change_is_refused_with_a_fixed_reason():
    unknown = DriveChange("c9", "U", None, DriveChangeKind.UNKNOWN)
    prep = await _ck(_world()).prepare_page(_page([_up("c1", "A"), unknown]), "T1")
    assert (prep.status, prep.reason, prep.batch) == (PageStatus.REFUSED, "UNKNOWN_CHANGE_KIND", None)


# --- 7. revisions list type, DrivePortError coercion ------------------------------------------------------


class _ListPort:
    def __init__(self, value):
        self.value = value

    async def list_revisions(self, identity, epoch, file_id):
        return self.value


class _TupleSub(tuple):
    pass


@pytest.mark.parametrize("value", [[RevisionMeta("r1")], "r1", 5, _TupleSub((RevisionMeta("r1"),)), {"r1"}])
async def test_a_wrong_typed_revision_list_is_check_failed_not_unavailable(value):
    res = await list_history(_ListPort(value), IDENT, 0, "F1")
    assert (res.status, res.reason) == (HistoryStatus.CHECK_FAILED, "REVISION_LIST_INVALID")


@pytest.mark.parametrize("value", [(), None])
async def test_an_empty_or_missing_revision_list_is_history_unavailable(value):
    res = await list_history(_ListPort(value), IDENT, 0, "F1")
    assert (res.status, res.reason) == (HistoryStatus.HISTORY_UNAVAILABLE, "HISTORY_UNAVAILABLE")


def test_port_error_converts_a_plain_str_that_names_a_member_and_nothing_else():
    assert DrivePortError("NOT_FOUND").code is DriveErrorCode.NOT_FOUND
    assert DrivePortError("RATE_LIMITED").code is DriveErrorCode.RATE_LIMITED
    for bad in ("token=SECRET", "not_found", "", None, 5, b"NOT_FOUND"):
        e = DrivePortError(bad)
        assert e.code is DriveErrorCode.TRANSIENT and str(e) == "TRANSIENT"
    class Sub(str):
        pass
    assert DrivePortError(Sub("NOT_FOUND")).code is DriveErrorCode.TRANSIENT


# --- 8. tracker full must block ---------------------------------------------------------------------------


def test_tracker_full_refusal_tells_the_caller_to_block_the_cursor(monkeypatch):
    monkeypatch.setattr(drive_revisions, "MAX_TRACKED_FILES", 1)
    tr = RevisionTracker(IDENT)
    first = tr.observe("F1", "r1", "c1")
    assert first.outcome is ObservationOutcome.FIRST_SEEN and first.blocks_cursor is False
    full = tr.observe("F2", "r1", "c2")
    assert (full.outcome, full.reason, full.candidate, full.blocks_cursor) == (
        ObservationOutcome.REFUSED, "TRACKER_FULL", None, True)


def test_per_file_revision_cap_also_blocks(monkeypatch):
    monkeypatch.setattr(drive_revisions, "MAX_REVISIONS_PER_FILE", 1)
    tr = RevisionTracker(IDENT)
    tr.observe("F1", "r1", "c1")
    full = tr.observe("F1", "r2", "c2")
    assert (full.reason, full.blocks_cursor) == ("TRACKER_FULL", True)


# --- 9. hostile datetimes keep the fixed ValueError contract ----------------------------------------------


class _RaisingTz(tzinfo):
    def utcoffset(self, dt):
        raise RuntimeError("SECRET")

    def dst(self, dt):
        return None

    def tzname(self, dt):
        return "x"


@pytest.mark.parametrize("value", [
    datetime.min.replace(tzinfo=timezone(timedelta(hours=5))),
    datetime.max.replace(tzinfo=timezone(-timedelta(hours=5))),
    datetime(2026, 1, 1, tzinfo=_RaisingTz()),
])
def test_revision_meta_hostile_datetimes_raise_only_the_fixed_value_error(value):
    with pytest.raises(ValueError, match="^DRIVE_REVISION_INVALID$"):
        RevisionMeta("r1", value)
    assert RevisionMeta("r1", datetime(2026, 1, 1, tzinfo=UTC)).modified_time is not None


def test_changes_page_with_a_forged_change_raises_only_the_fixed_value_error():
    forged = object.__new__(DriveChange)
    with pytest.raises(ValueError, match="^DRIVE_CHANGES_INVALID$"):
        ChangesPage((forged,), next_page_token="T")


# --- 10. immutable allow-list -------------------------------------------------------------------------------


def test_scope_allow_list_and_rank_are_read_only():
    with pytest.raises(TypeError):
        drive_scope.SCOPE_ALLOW_LIST["drive.evil"] = ScopeClaim.NARROW_FILE_SCOPE  # type: ignore[index]
    with pytest.raises(TypeError):
        drive_scope.SCOPE_ALLOW_LIST["drive"] = ScopeClaim.NARROW_FILE_SCOPE  # type: ignore[index]
    with pytest.raises(TypeError):
        drive_scope._RANK[ScopeClaim.BROAD] = 0  # type: ignore[index]
    assert drive_scope.SCOPE_ALLOW_LIST["drive"] is ScopeClaim.BROAD


# --- 11. reason / code fields are fixed enums ---------------------------------------------------------------


def test_scoped_proof_and_child_observation_codes_are_enums():
    ok = drive_scope.ScopedAccessProof(AccessProof.NOT_PROVEN, drive_scope.ScopedAccessCode.INPUT_INVALID)
    assert ok.code == "INPUT_INVALID"
    with pytest.raises(ValueError, match="^PROOF_CODE_INVALID$"):
        drive_scope.ScopedAccessProof(AccessProof.NOT_PROVEN, "INPUT_INVALID")
    with pytest.raises(ValueError, match="^PROOF_CODE_INVALID$"):
        drive_scope.NewChildObservation(AccessProof.NOT_PROVEN, "CHILD_HIDDEN")
    assert drive_scope.NewChildObservation(AccessProof.NOT_PROVEN, drive_scope.NewChildCode.CHILD_HIDDEN).code == "CHILD_HIDDEN"


def test_membership_results_and_page_reasons_are_enums():
    key = "k"
    good = drive_membership.MembershipResult("A", V.IN_SCOPE, drive_membership.MembershipReason.IN_CORPUS, key, True)
    assert good.reason == "IN_CORPUS"
    with pytest.raises(ValueError, match="^MEMBERSHIP_REASON_INVALID$"):
        drive_membership.MembershipResult("A", V.IN_SCOPE, "IN_CORPUS", key, True)
    with pytest.raises(ValueError, match="^PAGE_REASON_INVALID$"):
        drive_membership.PagePreparation(PageStatus.REFUSED, "PAGE_PREPARED")
    assert drive_membership.PagePreparation(PageStatus.REFUSED, drive_membership.PageReason.INVALID_INPUT)


def test_history_and_observation_reasons_are_enums():
    H = drive_revisions
    assert H.HistoryResult(HistoryStatus.CHECK_FAILED, H.HistoryCoverage.NONE, H.HistoryReason.INVALID_INPUT)
    with pytest.raises(ValueError, match="^HISTORY_REASON_INVALID$"):
        H.HistoryResult(HistoryStatus.CHECK_FAILED, H.HistoryCoverage.NONE, "INVALID_INPUT")
    assert H.RevisionObservation(ObservationOutcome.REFUSED, H.ObservationReason.INVALID_INPUT)
    with pytest.raises(ValueError, match="^OBSERVATION_REASON_INVALID$"):
        H.RevisionObservation(ObservationOutcome.REFUSED, "INVALID_INPUT")


async def test_every_emitted_reason_is_an_enum_member():
    fake = _world()
    ck = _ck(fake)
    for fid in ("A", "OUT", "MISSING", "bad id"):
        assert type((await ck.check(fid)).reason) is drive_membership.MembershipReason
    prep = await ck.prepare_page(_page([_up("c1", "A")]), "T1")
    assert type(prep.reason) is drive_membership.PageReason
    assert type(drive_revisions.RevisionTracker(IDENT).observe("F", "r", "c").reason) is drive_revisions.ObservationReason
    hist = await list_history(_ListPort(()), IDENT, 0, "F1")
    assert type(hist.reason) is drive_revisions.HistoryReason
    proof = await prove_scoped_read(fake, IDENT, 0, _decl(), "A", NARROW, "O")
    assert type(proof.code) is drive_scope.ScopedAccessCode
    child = await observe_new_child_access(fake, IDENT, 0, _decl(), "A", NARROW, "O")
    assert type(child.code) is drive_scope.NewChildCode


# --- 12. drive_changes exact types ---------------------------------------------------------------------------


class _LyingStr(str):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


def _projector():
    return DriveChangeProjector(connection_id="conn-1", drive_id=None, file_scope_allowed=lambda _: True)


def test_lying_eq_page_token_cannot_pass_the_cursor_compare():
    page = DrivePage("c1", (), None, "c2")
    object.__setattr__(page, "requested_page_token", _LyingStr("zzz"))
    with pytest.raises(ValueError, match="CURSOR_COMPARE_AND_SWAP_FAILED"):
        _projector().prepare(page, stored_cursor="c1")
    good = DrivePage("c1", (), None, "c2")
    with pytest.raises(ValueError, match="CURSOR_COMPARE_AND_SWAP_FAILED"):
        _projector().prepare(good, stored_cursor=_LyingStr("c1"))
    with pytest.raises(ValueError, match="CURSOR_COMPARE_AND_SWAP_FAILED"):
        _projector().prepare(good, stored_cursor=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("kwargs", [
    {"requested_page_token": _LyingStr("c1")},
    {"requested_page_token": 5},
    {"new_start_page_token": _LyingStr("c2")},
    {"new_start_page_token": 7},
    {"changes": [DriveChange("1", "a", None, DriveChangeKind.UPSERT)]},
    {"changes": (object.__new__(DriveChange),)},
])
def test_drive_page_rejects_inexact_types_with_a_fixed_code(kwargs):
    base = {"requested_page_token": "c1", "changes": (), "next_page_token": None, "new_start_page_token": "c2"}
    base.update(kwargs)
    with pytest.raises(ValueError) as exc:
        DrivePage(**base)
    assert str(exc.value) in {"PAGE_TOKEN_REQUIRED", "PAGE_CONTINUATION_XOR_NEW_START_REQUIRED", "INVALID_DRIVE_CHANGE"}


def test_drive_change_kind_must_be_the_exact_enum():
    class Kind(str):
        pass

    bad = DriveChange("1", "a", None, DriveChangeKind.UPSERT)
    object.__setattr__(bad, "kind", Kind("UPSERT"))
    with pytest.raises(ValueError, match="INVALID_DRIVE_CHANGE"):
        DrivePage("c1", (bad,), None, "c2")


def _batch_with_unknown():
    unknown = DriveChange("1", "a", None, DriveChangeKind.UNKNOWN)
    return _projector().prepare(DrivePage("c1", (unknown,), None, "c2"), stored_cursor="c1")


@pytest.mark.parametrize("gap", ["  ", "", "gap id", "gap\x00", _LyingStr("g"), None, 5, b"g", "g" * 5000],
    ids=lambda v: f"{type(v).__name__}-{len(v) if hasattr(v, '__len__') else v}")
def test_a_non_opaque_or_lying_gap_id_keeps_the_cursor_at_prior(gap):
    assert _batch_with_unknown().committable_cursor(recorded_gap=gap) == "c1"


def test_an_opaque_gap_id_releases_the_proposed_cursor():
    assert _batch_with_unknown().committable_cursor(recorded_gap="GAP-1") == "c2"


def test_requalify_ids_stay_unique_and_ordered():
    changes = tuple(DriveChange(str(i), f, None, DriveChangeKind.REMOVED) for i, f in enumerate("abab"))
    batch = _projector().prepare(DrivePage("c1", changes, None, "c2"), stored_cursor="c1")
    assert batch.requalify_folder_ids == ("a", "b")


# --- 13. prove_scoped_read mapping rows with exact codes ---------------------------------------------------------


async def test_prove_scoped_read_mapping_rows_have_exact_codes():
    fake = _fake(
        _file("OTHERDRIVE", ("ROOT",), drive="D9"),
        _file("SC", ("ROOT",), shortcut="Z"),
        _file("TR", ("ROOT",), trashed=True),
        _file("GONE", ("MISSING",)),
    )
    corpus = CorpusDeclaration("account:acc-1", None, ("ROOT",))
    rows = {
        "OTHERDRIVE": (AccessProof.DENIED, "OUT_OF_CORPUS"),
        "SC": (AccessProof.DENIED, "OUT_OF_CORPUS"),
        "TR": (AccessProof.NOT_PROVEN, "TRASHED"),
        "GONE": (AccessProof.NOT_PROVEN, "PARENT_UNRESOLVED"),
        "NOPE": (AccessProof.NOT_PROVEN, "FILE_UNRESOLVED"),
    }
    for fid, (status, code) in rows.items():
        proof = await prove_scoped_read(fake, IDENT, 0, corpus, fid, NARROW, "O")
        assert (proof.status, proof.code, proof.basis) == (status, code, None), fid


# --- 14. forged instances at the public entry points -------------------------------------------------------------


class _FixedPort:
    def __init__(self, meta):
        self.meta = meta

    async def get_file_meta(self, identity, epoch, file_id):
        return self.meta


class _LyingMeta(FileMeta):
    def __eq__(self, other):
        return True

    __hash__ = None  # type: ignore[assignment]


def _lying_meta():
    m = object.__new__(_LyingMeta)
    return m


@pytest.mark.parametrize("meta", [object.__new__(FileMeta), _lying_meta()])
async def test_forged_file_meta_from_a_port_is_a_fixed_refusal(meta):
    port = _FixedPort(meta)
    res = await resolve_membership(port, IDENT, 0, _decl(), "A")
    assert res.status is MembershipStatus.NOT_IN_SCOPE
    chk = await _ck(port).check("A")
    assert chk.verdict is V.CHECK_FAILED and chk.candidate_allowed is False
    assert (await _ck(port).authorize_disclosure("A")) is False


def _forged_identity():
    return object.__new__(DrivePortIdentity)


class _LyingIdentity(DrivePortIdentity):
    def __eq__(self, other):
        return True

    __hash__ = None  # type: ignore[assignment]


async def test_forged_identity_is_refused_at_every_entry_point():
    fake = _world()
    for ident in (_forged_identity(), object.__new__(_LyingIdentity)):
        res = await resolve_membership(fake, ident, 0, _decl(), "A")
        assert (res.status, res.code) == (MembershipStatus.NOT_IN_SCOPE, MembershipCode.INPUT_INVALID)
        proof = await prove_scoped_read(fake, ident, 0, _decl(), "A", NARROW, "O")
        assert (proof.status, proof.code) == (AccessProof.NOT_PROVEN, "INPUT_INVALID")
        child = await observe_new_child_access(fake, ident, 0, _decl(), "A", NARROW, "O")
        assert (child.status, child.code) == (AccessProof.NOT_PROVEN, "INPUT_INVALID")
        hist = await list_history(fake, ident, 0, "A")
        assert (hist.status, hist.reason) == (HistoryStatus.CHECK_FAILED, "INVALID_INPUT")
        with pytest.raises(ValueError, match="^MEMBERSHIP_CONFIG_INVALID$"):
            MembershipChecker(fake, ident, Corpus("account:acc-1", ("R",)), 0)
        with pytest.raises(ValueError, match="^DRIVE_IDENTITY_INVALID$"):
            RevisionTracker(ident)
    assert fake.call_count == 0


async def test_forged_corpus_is_refused_at_every_entry_point():
    fake = _world()
    for corpus in (object.__new__(CorpusDeclaration),):
        res = await resolve_membership(fake, IDENT, 0, corpus, "A")
        assert (res.status, res.code) == (MembershipStatus.NOT_IN_SCOPE, MembershipCode.INPUT_INVALID)
        proof = await prove_scoped_read(fake, IDENT, 0, corpus, "A", NARROW, "O")
        assert (proof.status, proof.code) == (AccessProof.NOT_PROVEN, "INPUT_INVALID")
        child = await observe_new_child_access(fake, IDENT, 0, corpus, "A", NARROW, "O")
        assert (child.status, child.code) == (AccessProof.NOT_PROVEN, "INPUT_INVALID")
    with pytest.raises(ValueError, match="^MEMBERSHIP_CONFIG_INVALID$"):
        MembershipChecker(fake, IDENT, object.__new__(Corpus), 0)
    assert fake.call_count == 0


async def test_forged_pages_are_refused_by_prepare_page():
    ck = _ck(_world())
    forged_page = object.__new__(DrivePage)

    class LyingPage(DrivePage):
        def __eq__(self, other):
            return True

        __hash__ = None  # type: ignore[assignment]

    for page in (forged_page, object.__new__(LyingPage), object.__new__(ChangesPage), None):
        prep = await ck.prepare_page(page, "T1")
        assert prep.status is PageStatus.REFUSED and prep.batch is None
        assert type(prep.reason) is drive_membership.PageReason
    with pytest.raises(ValueError, match="^DRIVE_CHANGES_INVALID$"):
        object.__new__(ChangesPage).to_drive_page("T1")


def test_dataclass_field_names_unchanged_for_existing_callers():
    assert [f.name for f in dataclasses.fields(drive_membership.MembershipResult)] == [
        "file_id", "verdict", "reason", "object_key", "candidate_allowed"]
    assert [f.name for f in dataclasses.fields(drive_revisions.RevisionObservation)][:4] == [
        "outcome", "reason", "candidate", "historical_revision_ids"]
    assert drive_changes.FOLDER_MIME_TYPE == FOLDER_MIME_TYPE
