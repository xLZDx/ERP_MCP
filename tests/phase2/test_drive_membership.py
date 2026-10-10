"""S7/E3 (TC110, TC111): move / shortcut / removal / revoke aware membership re-check. Offline."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import drive_membership
from business_ai_gateway.phase2.drive_changes import (
    FOLDER_MIME_TYPE,
    DriveChange,
    DriveChangeKind,
    DrivePage,
)
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_membership import (
    MAX_LOOKUPS_PER_CHECK,
    Corpus,
    MembershipChecker,
    MembershipVerdict,
    PageStatus,
)
from business_ai_gateway.phase2.drive_port import DriveErrorCode, DrivePortIdentity, FileMeta

IDENT = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")
SECRET_NAME = "Secret Payroll 2026.xlsx"
V = MembershipVerdict


class StrSub(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


def _file(fid, parents, *, name=SECRET_NAME, mime="application/pdf", trashed=False, drive=None, shortcut=None):
    return FileMeta(fid, name, mime, tuple(parents), trashed, drive, shortcut)


def _folder(fid, parents):
    return _file(fid, parents, name="Folder", mime=FOLDER_MIME_TYPE)


def _world():
    """R (root) > F1 > A ; R > F2 ; X (outside, no parent) > OUT."""
    fake = FakeDrivePort()
    fake.set_file(_folder("R", ()))
    fake.set_file(_folder("F1", ("R",)))
    fake.set_file(_folder("F2", ("R",)))
    fake.set_file(_file("A", ("F1",)))
    fake.set_file(_folder("X", ()))
    fake.set_file(_file("OUT", ("X",)))
    return fake


def _checker(fake, epoch=0, **corpus_kw):
    corpus = Corpus("account:acc-1", ("R",), **corpus_kw)
    return MembershipChecker(fake, IDENT, corpus, epoch)


def _page(changes, token="T1", nxt="T2"):
    return DrivePage(token, tuple(changes), next_page_token=nxt)


def _up(cid, fid, rev="r1", **kw):
    return DriveChange(cid, fid, rev, DriveChangeKind.UPSERT, **kw)


# --- in scope / rename / move inside ---------------------------------------------------------------


async def test_file_under_a_root_is_in_scope_and_reaches_candidate():
    fake = _world()
    res = await _checker(fake).check("A")
    assert (res.verdict, res.reason, res.candidate_allowed) == (V.IN_SCOPE, "IN_CORPUS", True)
    prep = await _checker(fake).prepare_page(_page([_up("c1", "A")]), "T1")
    assert prep.status is PageStatus.PREPARED and prep.batch is not None
    assert [c.file_id for c in prep.batch.candidates] == ["A"]
    assert prep.batch.candidates[0].status == "UNATTESTED"
    assert prep.batch.committable_cursor() == "T2"


async def test_rename_alone_keeps_identity():
    fake = _world()
    ck = _checker(fake)
    before = await ck.check("A")
    fake.set_file(_file("A", ("F1",), name="Renamed.pdf"))
    after = await ck.check("A")
    assert (after.file_id, after.object_key, after.verdict) == (before.file_id, before.object_key, V.IN_SCOPE)
    prep = await ck.prepare_page(_page([_up("c2", "A", "r2")]), "T1")
    assert prep.batch is not None and [c.file_id for c in prep.batch.candidates] == ["A"]
    assert prep.batch.tombstones == ()


async def test_object_key_separates_namespaces_for_the_same_raw_id():
    fake = _world()
    a = await _checker(fake).check("A")
    other = MembershipChecker(
        fake, DrivePortIdentity("drive:D1", "tenant-1", "conn-2"), Corpus("drive:D1", ("R",), "D1"), 0
    )
    fake.set_file(_file("A", ("F1",), drive="D1"))
    fake.set_file(_folder("F1", ("R",)))
    b = await other.check("A")
    assert a.object_key != b.object_key


async def test_move_inside_corpus_is_accepted_after_re_resolving_the_chain():
    fake = _world()
    ck = _checker(fake)
    assert (await ck.check("A", use_cache=True)).verdict is V.IN_SCOPE
    fake.set_file(_file("A", ("F2",)))
    before = fake.count("get_file_meta")
    prep = await ck.prepare_page(_page([_up("c3", "A", "r2")]), "T1")
    assert fake.count("get_file_meta") > before  # the cache was NOT trusted for a changed file
    assert prep.batch is not None and [c.file_id for c in prep.batch.candidates] == ["A"]
    assert (await ck.check("A", use_cache=True)).verdict is V.IN_SCOPE


# --- TC110: scope escape ---------------------------------------------------------------------------


async def test_move_out_of_corpus_is_denied_with_tombstone_and_no_disclosure():
    fake = _world()
    ck = _checker(fake)
    await ck.check("A")
    fake.set_file(_file("A", ("X",)))
    prep = await ck.prepare_page(_page([_up("c4", "A", "r2")]), "T1")
    assert prep.status is PageStatus.PREPARED and prep.batch is not None
    assert prep.batch.candidates == ()
    assert [(t.file_id, t.reason) for t in prep.batch.tombstones] == [("A", "MEMBERSHIP_CHANGED")]
    assert prep.results[0].verdict is V.SCOPE_ESCAPE_DENIED
    assert prep.results[0].reason == "OUT_OF_CORPUS"
    assert prep.results[0].candidate_allowed is False
    assert SECRET_NAME not in repr(prep)
    assert await ck.authorize_disclosure("A") is False


async def test_shortcut_outside_corpus_is_denied_and_inside_is_never_evidence():
    fake = _world()
    fake.set_file(_file("S-OUT", ("F1",), shortcut="OUT"))
    fake.set_file(_file("S-IN", ("F1",), shortcut="A"))
    fake.set_file(_file("S-GONE", ("F1",), shortcut="NOPE"))
    ck = _checker(fake)
    out = await ck.check("S-OUT")
    assert (out.verdict, out.reason, out.candidate_allowed) == (V.SCOPE_ESCAPE_DENIED, "SHORTCUT_TARGET_OUTSIDE", False)
    inside = await ck.check("S-IN")
    assert (inside.verdict, inside.reason, inside.candidate_allowed) == (V.NOT_IN_SCOPE, "SHORTCUT_NOT_EVIDENCE", False)
    gone = await ck.check("S-GONE")
    assert (gone.verdict, gone.reason) == (V.NOT_IN_SCOPE, "SHORTCUT_TARGET_UNRESOLVED")
    prep = await ck.prepare_page(_page([_up("c5", "S-OUT"), _up("c6", "S-IN")]), "T1")
    assert prep.batch is not None and prep.batch.candidates == ()
    assert {t.file_id for t in prep.batch.tombstones} == {"S-OUT", "S-IN"}


async def test_unresolvable_parent_is_not_in_scope_not_an_exception():
    fake = _world()
    fake.set_file(_file("LOST", ("GHOST",)))
    res = await _checker(fake).check("LOST")
    assert (res.verdict, res.reason, res.candidate_allowed) == (V.NOT_IN_SCOPE, "PARENT_UNRESOLVED", False)
    fake.set_file(_folder("TF", ("R",)))
    fake.set_file(_file("UNDER-TRASHED", ("TF",)))
    fake.set_file(_file("TF2", ("R",), trashed=True))
    fake.set_file(_file("UNDER-TRASHED2", ("TF2",)))
    assert (await _checker(fake).check("UNDER-TRASHED2")).reason == "PARENT_UNRESOLVED"
    assert (await _checker(fake).check("UNDER-TRASHED")).verdict is V.IN_SCOPE


async def test_cyclic_parent_chain_terminates():
    fake = _world()
    fake.set_file(_folder("C1", ("C2",)))
    fake.set_file(_folder("C2", ("C1",)))
    fake.set_file(_file("INCYCLE", ("C1",)))
    fake.set_file(_folder("SELF", ("SELF",)))
    ck = _checker(fake)
    for fid in ("INCYCLE", "C1", "SELF"):
        res = await asyncio.wait_for(ck.check(fid), timeout=5)
        assert (res.verdict, res.reason) == (V.NOT_IN_SCOPE, "CYCLE_OR_DEPTH")
        assert res.candidate_allowed is False


async def test_very_deep_chain_is_bounded():
    fake = _world()
    prev = "R"
    for i in range(200):
        fake.set_file(_folder(f"D{i}", (prev,)))
        prev = f"D{i}"
    fake.set_file(_file("DEEP", (prev,)))
    res = await _checker(fake).check("DEEP")
    assert (res.verdict, res.reason) == (V.NOT_IN_SCOPE, "CYCLE_OR_DEPTH")
    assert fake.count("get_file_meta") <= MAX_LOOKUPS_PER_CHECK


async def test_shared_drive_corpus_denies_a_file_of_another_drive():
    fake = _world()
    fake.set_file(_file("R", (), mime=FOLDER_MIME_TYPE, drive="D1"))  # root and ancestors of a shared drive carry its drive id
    fake.set_file(_file("F1", ("R",), mime=FOLDER_MIME_TYPE, drive="D1"))
    fake.set_file(_file("A", ("F1",), drive="D1"))
    fake.set_file(_file("B", ("F1",), drive="OTHER"))
    ck = MembershipChecker(
        fake, DrivePortIdentity("drive:D1", "tenant-1", "conn-1"), Corpus("drive:D1", ("R",), "D1"), 0
    )
    assert (await ck.check("A")).verdict is V.IN_SCOPE
    denied = await ck.check("B")
    assert (denied.verdict, denied.reason) == (V.SCOPE_ESCAPE_DENIED, "DRIVE_MISMATCH")
    # an account corpus refuses a file that lives in a shared drive
    assert (await _checker(fake).check("A")).reason == "DRIVE_MISMATCH"
    before = fake.count("get_file_meta")
    prep = await ck.prepare_page(_page([_up("c7", "B", drive_id="OTHER")]), "T1")
    assert prep.batch is not None and prep.batch.denied_changes == 1 and prep.batch.candidates == ()
    assert fake.count("get_file_meta") == before  # another drive's file is not even looked up


# --- TC111: removal, no guessed replacement --------------------------------------------------------


async def test_removed_change_is_a_tombstone_without_port_calls():
    fake = _world()
    ck = _checker(fake)
    removed = DriveChange("c8", "A", "r1", DriveChangeKind.REMOVED)
    prep = await ck.prepare_page(_page([removed]), "T1")
    assert prep.batch is not None
    assert [(t.file_id, t.reason) for t in prep.batch.tombstones] == [("A", "REMOVED")]
    assert prep.batch.candidates == ()
    assert fake.count("get_file_meta") == 0


async def test_trashed_and_inaccessible_files_give_removed_tombstones():
    fake = _world()
    fake.set_file(_file("T", ("F1",), trashed=True))
    fake.remove_file("OUT")
    ck = _checker(fake)
    assert (await ck.check("T")).verdict is V.REMOVED
    assert (await ck.check("OUT")).verdict is V.REMOVED
    prep = await ck.prepare_page(_page([_up("c9", "T"), _up("c10", "OUT")]), "T1")
    assert prep.batch is not None and prep.batch.candidates == ()
    assert {(t.file_id, t.reason) for t in prep.batch.tombstones} == {("T", "REMOVED"), ("OUT", "REMOVED")}


async def test_same_name_and_size_new_file_is_a_separate_candidate_not_a_replacement():
    fake = _world()
    ck = _checker(fake)
    fake.set_file(_file("NEW", ("F1",)))  # same name/mime as A
    fake.remove_file("A")
    removed = DriveChange("c11", "A", "r1", DriveChangeKind.REMOVED)
    prep = await ck.prepare_page(_page([removed, _up("c12", "NEW", "n1")]), "T1")
    assert prep.batch is not None
    assert [t.file_id for t in prep.batch.tombstones] == ["A"]
    assert [c.file_id for c in prep.batch.candidates] == ["NEW"]
    # nothing links them: no replacement field exists and the same ids come back unchanged
    for obj in (prep.batch.tombstones[0], prep.batch.candidates[0], *prep.results):
        assert not any("replace" in f or "successor" in f for f in obj.__slots__)
    assert SECRET_NAME not in repr(prep)


def test_module_never_reads_names_sizes_hashes_or_times():
    tree = ast.parse(Path(drive_membership.__file__).read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"name", "size", "md5", "md5_checksum", "sha256", "modified_time", "created_time", "mime_type"}


# --- folder move / removal requalifies descendants -------------------------------------------------


async def test_folder_change_requalifies_and_drops_cached_descendants():
    fake = _world()
    ck = _checker(fake)
    await ck.check("A")
    assert ck.cached("A") is not None
    folder_change = _up("c13", "F1", "f1", mime_type=FOLDER_MIME_TYPE)
    prep = await ck.prepare_page(_page([folder_change]), "T1")
    assert prep.batch is not None
    assert prep.batch.requalify_folder_ids == ("F1",)
    assert prep.batch.candidates == ()  # a folder is not a document
    assert ck.cached("A") is None  # descendant must be re-resolved before any disclosure
    fake.set_file(_folder("F1", ("X",)))  # folder moved out of the corpus
    assert (await ck.check("A", use_cache=True)).verdict is V.SCOPE_ESCAPE_DENIED


async def test_folder_removal_requalifies_descendants():
    fake = _world()
    ck = _checker(fake)
    await ck.check("A")
    removed = DriveChange("c14", "F1", None, DriveChangeKind.REMOVED)
    prep = await ck.prepare_page(_page([removed]), "T1")
    assert prep.batch is not None and prep.batch.requalify_folder_ids == ("F1",)
    assert [(t.file_id, t.reason) for t in prep.batch.tombstones] == [("F1", "REMOVED")]
    assert ck.cached("A") is None


async def test_invalidate_returns_dropped_descendants():
    fake = _world()
    ck = _checker(fake)
    await ck.check("A")
    assert ck.invalidate("F1") == ("A",)
    assert ck.invalidate("F1") == ()


# --- revoke / scope epoch --------------------------------------------------------------------------


async def test_revoke_rechecks_every_cached_membership_before_disclosure():
    fake = _world()
    ck = _checker(fake)
    assert await ck.authorize_disclosure("A") is True
    calls = fake.count("get_file_meta")
    assert await ck.authorize_disclosure("A") is True  # same epoch: still a FRESH read (S7 gate M02)
    assert fake.count("get_file_meta") > calls
    calls = fake.count("get_file_meta")

    assert ck.advance_epoch(1) is True  # revoke / re-consent: new epoch
    assert ck.cached("A") is None
    # the provider still sits on the old epoch: the re-check fails closed, nothing is disclosed
    assert await ck.authorize_disclosure("A") is False
    assert fake.count("get_file_meta") > calls
    # re-consent completed on the provider side: a fresh check succeeds
    fake.set_scope_epoch(1)
    assert await ck.authorize_disclosure("A") is True


async def test_recheck_all_after_revoke_sees_the_current_state_of_each_cached_file():
    fake = _world()
    ck = _checker(fake)
    await ck.check("A")
    await ck.check("OUT")
    fake.set_scope_epoch(1)
    fake.set_file(_file("A", ("X",)))  # moved out while access was suspended
    assert ck.advance_epoch(1)
    results = {r.file_id: r.verdict for r in await ck.recheck_all()}
    assert results == {"A": V.SCOPE_ESCAPE_DENIED, "OUT": V.SCOPE_ESCAPE_DENIED}
    assert ck.cached("A") is not None and ck.cached("A").verdict is V.SCOPE_ESCAPE_DENIED  # type: ignore[union-attr]


async def test_auth_failure_denies_disclosure():
    fake = _world()
    ck = _checker(fake)
    fake.force_error("get_file_meta", DriveErrorCode.INVALID_GRANT, times=None)
    res = await ck.check("A")
    assert (res.verdict, res.reason, res.candidate_allowed) == (V.CHECK_FAILED, "INVALID_GRANT", False)
    assert await ck.authorize_disclosure("A") is False
    assert ck.cached("A") is None  # failures are never cached


async def test_epoch_change_during_a_page_refuses_the_page():
    fake = _world()
    ck = _checker(fake)
    fake.run_after_calls(1, lambda f: ck.advance_epoch(1))
    prep = await ck.prepare_page(_page([_up("c15", "A")]), "T1")
    assert prep.status is PageStatus.REFUSED and prep.batch is None
    assert ck.cached("A") is None


async def test_unverifiable_membership_refuses_the_page_so_no_cursor_exists():
    fake = _world()
    ck = _checker(fake)
    fake.force_error("get_file_meta", DriveErrorCode.RATE_LIMITED, times=None)
    prep = await ck.prepare_page(_page([_up("c16", "A")]), "T1")
    assert (prep.status, prep.reason, prep.batch) == (PageStatus.REFUSED, "PAGE_MEMBERSHIP_UNVERIFIED", None)


async def test_cursor_mismatch_and_duplicate_change_ids_are_refused():
    fake = _world()
    ck = _checker(fake)
    assert (await ck.prepare_page(_page([_up("c1", "A")]), "OTHER")).reason == "PAGE_CURSOR_MISMATCH"
    dup = await ck.prepare_page(_page([_up("c1", "A"), _up("c1", "A")]), "T1")
    assert dup.status is PageStatus.REFUSED and dup.reason == "PAGE_PROJECTION_REFUSED"


async def test_advance_epoch_never_goes_back_and_refuses_hostile_values():
    ck = _checker(_world(), epoch=5)
    assert ck.advance_epoch(4) is False
    for bad in (None, True, "6", 1.5, -1, 2**63, StrSub("7")):
        assert ck.advance_epoch(bad) is False
    assert ck.scope_epoch == 5
    assert ck.advance_epoch(5) is True and ck.advance_epoch(6) is True


# --- S6b lessons: hostile input, exact types, byte-exact ids ---------------------------------------

HOSTILE = [None, 1, True, b"x", ["x"], object(), "", " A", "A ", "A\x00B", "A\nB", "x" * 5000, StrSub("A")]


@pytest.mark.parametrize("bad", HOSTILE)
async def test_hostile_file_ids_and_pages_never_raise(bad):
    fake = _world()
    ck = _checker(fake)
    res = await ck.check(bad)
    assert res.verdict is V.CHECK_FAILED and res.reason == "INVALID_INPUT" and res.candidate_allowed is False
    assert await ck.authorize_disclosure(bad) is False
    assert ck.cached(bad) is None
    assert ck.invalidate(bad) == ()
    assert (await ck.prepare_page(bad, "T1")).status is PageStatus.REFUSED
    assert (await ck.prepare_page(_page([_up("c1", "A")]), bad)).status is PageStatus.REFUSED
    assert fake.call_count == 0


async def test_page_with_a_forged_change_object_is_refused():
    class Fake:
        change_id = "c"
        file_id = "A"
        revision_id = None
        kind = DriveChangeKind.UPSERT
        drive_id = None
        mime_type = None
        parents = ()

    page = DrivePage.__new__(DrivePage)
    object.__setattr__(page, "requested_page_token", "T1")
    object.__setattr__(page, "changes", (Fake(),))
    object.__setattr__(page, "next_page_token", "T2")
    object.__setattr__(page, "new_start_page_token", None)
    prep = await _checker(_world()).prepare_page(page, "T1")
    assert prep.status is PageStatus.REFUSED and prep.reason == "INVALID_INPUT"


class _ExplodingPort:
    async def get_file_meta(self, identity, scope_epoch, file_id):
        raise RuntimeError("secret-token-xyz leaked")


class _WrongMetaPort:
    async def get_file_meta(self, identity, scope_epoch, file_id):
        return FileMeta("SOMETHING-ELSE", "n", "m", ("R",), False, None)


async def test_port_bugs_fail_closed_without_echo():
    ck = MembershipChecker(_ExplodingPort(), IDENT, Corpus("account:acc-1", ("R",)), 0)  # type: ignore[arg-type]
    res = await ck.check("A")
    assert (res.verdict, res.reason) == (V.CHECK_FAILED, "TRANSIENT")
    assert "secret" not in repr(res)
    assert (await ck.prepare_page(_page([_up("c1", "A")]), "T1")).status is PageStatus.REFUSED
    ck2 = MembershipChecker(_WrongMetaPort(), IDENT, Corpus("account:acc-1", ("R",)), 0)  # type: ignore[arg-type]
    assert (await ck2.check("A")).verdict is V.CHECK_FAILED  # a mismatching answer is never trusted


async def test_ids_stay_byte_exact_in_results():
    fake = _world()
    guid = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"
    fake.set_file(_file(guid, ("F1",)))
    res = await _checker(fake).check(guid)
    assert res.file_id == guid and res.verdict is V.IN_SCOPE
    assert (await _checker(fake).check(guid.lower())).verdict is V.REMOVED  # a different id, not folded


def test_configuration_is_validated_with_fixed_codes():
    fake = _world()
    corpus = Corpus("account:acc-1", ("R",))
    with pytest.raises(ValueError, match="MEMBERSHIP_NAMESPACE_MISMATCH"):
        MembershipChecker(fake, IDENT, Corpus("drive:D1", ("R",), "D1"), 0)
    with pytest.raises(ValueError, match="MEMBERSHIP_CONFIG_INVALID"):
        MembershipChecker(fake, "account:acc-1", corpus, 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="SCOPE_EPOCH_INVALID"):
        MembershipChecker(fake, IDENT, corpus, True)  # type: ignore[arg-type]
    for roots in ((), ["R"], ("R", ""), ("R", StrSub("x")), ("a b",)):
        with pytest.raises(ValueError, match="CORPUS_ROOTS_INVALID"):
            Corpus("account:acc-1", roots)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="DRIVE_NAMESPACE_INVALID"):
        Corpus("acc-1", ("R",))
    with pytest.raises(ValueError, match="CORPUS_DRIVE_INVALID"):
        Corpus("drive:D1", ("R",), " D1")


# --- read-only boundary (AST) ----------------------------------------------------------------------


def test_module_is_read_only_and_offline():
    tree = ast.parse(Path(drive_membership.__file__).read_text(encoding="utf-8"))
    port_calls = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Attribute)
        and n.func.value.attr == "_port"
    }
    assert port_calls == {"get_file_meta"}
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(("." * n.level) + (n.module or ""))
    assert not mods & {"httpx", "requests", "socket", "subprocess", "urllib", "aiohttp", "os", "sqlite3"}
    assert not [m for m in mods if "drive_http" in m or "pdcc" in m.lower()]
    names = {n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.name.lower() for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not [w for w in ("permission", "keepforever", "keep_forever", "write", "delete", "patch") for n in names if w in n]
