"""S7 GPT-PM gate remediation (stream H2): membership / ancestors / removals / hostile drive ids. Offline.

Findings M01 (identity helper), M02 (stale cache disclosure), M03 (invalid ancestor chains),
M06 (silently skipped removal), M07 (hostile drive_id comparison).
"""
from __future__ import annotations

import pytest

from business_ai_gateway.phase2 import drive_port
from business_ai_gateway.phase2.drive_changes import (
    FOLDER_MIME_TYPE,
    DriveChange,
    DriveChangeKind,
    DriveChangeProjector,
    DrivePage,
)
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_membership import (
    Corpus,
    MembershipChecker,
    MembershipVerdict,
    PageStatus,
)
from business_ai_gateway.phase2.drive_port import ChangesPage, DrivePortIdentity, FileMeta
from business_ai_gateway.phase2.drive_scope import (
    CorpusDeclaration,
    MembershipStatus,
    resolve_membership,
)

ACC = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")
DRV = DrivePortIdentity("drive:D1", "tenant-1", "conn-1")
V = MembershipVerdict


class HostileStr(str):
    """Compares equal to everything and never unequal: defeats a naive ``!=`` drive filter."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


def _file(fid, parents, *, mime="application/pdf", trashed=False, drive=None, shortcut=None):
    return FileMeta(fid, "n", mime, tuple(parents), trashed, drive, shortcut)


def _folder(fid, parents, **kw):
    return _file(fid, parents, mime=FOLDER_MIME_TYPE, **kw)


def _up(cid, fid, **kw):
    return DriveChange(cid, fid, "r1", DriveChangeKind.UPSERT, **kw)


def _rm(cid, fid, **kw):
    return DriveChange(cid, fid, None, DriveChangeKind.REMOVED, **kw)


def _page(changes):
    return DrivePage("T1", tuple(changes), next_page_token="T2")


def _forge_change(**fields):
    obj = object.__new__(DriveChange)
    for name, value in fields.items():
        object.__setattr__(obj, name, value)
    return obj


async def _both(fake, file_id, *, drive="D1", identity=DRV, roots=("R",)):
    """Verdict of the checker and of drive_scope.resolve_membership for the same world."""
    ns = identity.namespace
    ck = MembershipChecker(fake, identity, Corpus(ns, roots, drive), 0)
    res = await ck.check(file_id)
    scope = await resolve_membership(fake, identity, 0, CorpusDeclaration(ns, drive, roots), file_id)
    return res.verdict is V.IN_SCOPE, scope.status is MembershipStatus.IN_SCOPE


def _shared_world(**over):
    fake = FakeDrivePort()
    fake.set_file(over.get("R") or _folder("R", (), drive="D1"))
    fake.set_file(over.get("F1") or _folder("F1", ("R",), drive="D1"))
    fake.set_file(over.get("A") or _file("A", ("F1",), drive="D1"))
    return fake


# --- M03: ancestor validation ----------------------------------------------------------------------


async def test_valid_same_drive_chain_still_passes():
    assert await _both(_shared_world(), "A") == (True, True)


@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"F1": _folder("F1", ("R",), drive="OTHER")}, id="foreign-drive-ancestor"),
        pytest.param({"F1": _folder("F1", ("R",), drive=None)}, id="driveless-ancestor-in-shared-drive"),
        pytest.param({"R": _folder("R", (), drive="D1", trashed=True)}, id="trashed-root"),
        pytest.param({"R": _folder("R", (), drive="OTHER")}, id="root-of-another-drive"),
        pytest.param({"R": _file("R", (), drive="D1", shortcut="Z")}, id="root-is-a-shortcut"),
    ],
)
async def test_invalid_ancestor_never_proves_membership(over):
    assert await _both(_shared_world(**over), "A") == (False, False)


async def test_direct_child_of_trashed_or_foreign_root_is_refused():
    for root in (_folder("R", (), drive="D1", trashed=True), _folder("R", (), drive="OTHER")):
        fake = _shared_world(R=root, A=_file("A", ("R",), drive="D1"))
        assert await _both(fake, "A") == (False, False)


async def test_account_corpus_foreign_drive_ancestor_is_refused():
    fake = FakeDrivePort()
    fake.set_file(_folder("R", ()))
    fake.set_file(_folder("F1", ("R",), drive="OTHER"))
    fake.set_file(_file("A", ("F1",)))
    assert await _both(fake, "A", drive=None, identity=ACC) == (False, False)


async def test_removed_root_recorded_by_the_feed_cannot_prove_membership():
    fake = _shared_world(A=_file("A", ("R",), drive="D1"))
    ck = MembershipChecker(fake, DRV, Corpus("drive:D1", ("R",), "D1"), 0)
    assert (await ck.check("A")).verdict is V.IN_SCOPE
    prep = await ck.prepare_page(_page([_rm("c1", "R", drive_id="D1")]), "T1")
    assert prep.status is PageStatus.PREPARED
    fake.set_file(_folder("R", (), drive="D1"))  # even if a stale read still shows the root alive
    assert (await ck.check("A")).verdict is not V.IN_SCOPE


async def test_root_itself_when_trashed_is_not_in_scope():
    fake = _shared_world(R=_folder("R", (), drive="D1", trashed=True))
    assert await _both(fake, "R") == (False, False)


# --- M02: disclosure needs a fresh read ------------------------------------------------------------


async def test_unannounced_move_out_of_corpus_blocks_disclosure():
    fake = FakeDrivePort()
    fake.set_file(_folder("R", ()))
    fake.set_file(_folder("F1", ("R",)))
    fake.set_file(_folder("X", ()))
    fake.set_file(_file("A", ("F1",)))
    ck = MembershipChecker(fake, ACC, Corpus("account:acc-1", ("R",)), 0)
    assert (await ck.check("A", use_cache=True)).verdict is V.IN_SCOPE
    assert await ck.authorize_disclosure("A") is True
    fake.set_file(_file("A", ("X",)))  # moved out: no change event, same epoch
    before = fake.count("get_file_meta")
    assert await ck.authorize_disclosure("A") is False
    assert fake.count("get_file_meta") > before  # a fresh read, not the cache
    assert (await ck.check("A", use_cache=True)).verdict is not V.IN_SCOPE


async def test_unannounced_trash_blocks_disclosure():
    fake = _shared_world()
    ck = MembershipChecker(fake, DRV, Corpus("drive:D1", ("R",), "D1"), 0)
    await ck.check("A", use_cache=True)
    fake.set_file(_file("A", ("F1",), drive="D1", trashed=True))
    assert await ck.authorize_disclosure("A") is False


# --- M06: removals of unknown origin -----------------------------------------------------------------


def _projector(drive):
    return DriveChangeProjector(connection_id="conn-1", drive_id=drive, file_scope_allowed=lambda f: True)


def test_removal_without_drive_id_is_not_silently_dropped_in_a_shared_drive():
    batch = _projector("D1").prepare(_page([_rm("c1", "F")]), stored_cursor="T1")
    assert [(t.file_id, t.reason) for t in batch.tombstones] == [("F", "REMOVED")]
    assert "F" in batch.requalify_folder_ids
    assert batch.denied_changes == 0


def test_removal_of_a_provably_foreign_drive_is_still_denied_without_tombstone():
    batch = _projector("D1").prepare(_page([_rm("c1", "F", drive_id="OTHER")]), stored_cursor="T1")
    assert batch.tombstones == () and batch.denied_changes == 1


async def test_checker_invalidates_cache_and_tombstones_a_removal_without_drive_id():
    fake = _shared_world()
    ck = MembershipChecker(fake, DRV, Corpus("drive:D1", ("R",), "D1"), 0)
    await ck.check("A")
    assert ck.cached("A") is not None
    prep = await ck.prepare_page(_page([_rm("c1", "A")]), "T1")
    assert prep.status is PageStatus.PREPARED and prep.batch is not None
    assert [(t.file_id, t.reason) for t in prep.batch.tombstones] == [("A", "REMOVED")]
    assert ck.cached("A") is None  # earlier evidence cannot stay current through the cache


# --- M07: hostile drive_id ----------------------------------------------------------------------------


def test_change_refuses_a_str_subclass_drive_id():
    with pytest.raises(ValueError, match="INVALID_DRIVE_CHANGE"):
        _up("c1", "F", drive_id=HostileStr("OTHER"))


def test_projector_refuses_a_str_subclass_own_drive_id():
    with pytest.raises(ValueError):
        DriveChangeProjector(connection_id="c", drive_id=HostileStr("D1"), file_scope_allowed=lambda f: True)


def test_forged_change_with_hostile_drive_id_cannot_reach_the_projector_through_a_page():
    forged = _forge_change(
        change_id="c1", file_id="F", revision_id="r1", kind=DriveChangeKind.UPSERT,
        drive_id=HostileStr("OTHER"), mime_type=None, parents=(),
    )
    with pytest.raises(ValueError):
        DrivePage("T1", (forged,), next_page_token="T2")
    with pytest.raises(ValueError):
        ChangesPage((forged,), next_page_token="T2")


@pytest.mark.parametrize("kind", [DriveChangeKind.UPSERT, DriveChangeKind.REMOVED])
def test_projector_refuses_a_forged_page_with_hostile_drive_id(kind):
    forged = _forge_change(
        change_id="c1", file_id="F", revision_id="r1", kind=kind,
        drive_id=HostileStr("OTHER"), mime_type=None, parents=(),
    )
    page = object.__new__(DrivePage)  # bypasses the page validation
    for name, value in (
        ("requested_page_token", "T1"), ("changes", (forged,)),
        ("next_page_token", "T2"), ("new_start_page_token", None),
    ):
        object.__setattr__(page, name, value)
    with pytest.raises(ValueError):
        _projector("D1").prepare(page, stored_cursor="T1")


async def test_checker_prepare_page_refuses_a_forged_page_and_a_half_forged_change():
    fake = _shared_world()
    ck = MembershipChecker(fake, DRV, Corpus("drive:D1", ("R",), "D1"), 0)
    hostile = _forge_change(
        change_id="c1", file_id="A", revision_id="r1", kind=DriveChangeKind.UPSERT,
        drive_id=HostileStr("OTHER"), mime_type=None, parents=(),
    )
    page = object.__new__(DrivePage)
    for name, value in (
        ("requested_page_token", "T1"), ("changes", (hostile,)),
        ("next_page_token", "T2"), ("new_start_page_token", None),
    ):
        object.__setattr__(page, name, value)
    prep = await ck.prepare_page(page, "T1")
    assert prep.status is PageStatus.REFUSED and prep.batch is None
    unset = _forge_change(change_id="c2", file_id="A", kind=DriveChangeKind.UPSERT)  # slots left unset
    page2 = object.__new__(DrivePage)
    for name, value in (
        ("requested_page_token", "T1"), ("changes", (unset,)),
        ("next_page_token", "T2"), ("new_start_page_token", None),
    ):
        object.__setattr__(page2, name, value)
    prep2 = await ck.prepare_page(page2, "T1")
    assert prep2.status is PageStatus.REFUSED and prep2.batch is None


# --- M01: canonical identity ----------------------------------------------------------------------------


def test_canonical_identity_returns_an_equal_plain_copy():
    out = drive_port.canonical_identity(ACC)
    assert out == ACC and out is not ACC and type(out) is DrivePortIdentity
    assert type(out.namespace) is str and type(out.tenant) is str and type(out.connection_id) is str


def test_canonical_identity_refuses_forged_and_foreign_objects():
    shell = object.__new__(DrivePortIdentity)
    assert drive_port.canonical_identity(shell) is None
    assert drive_port.canonical_identity("account:x") is None
    assert drive_port.canonical_identity(None) is None
    bad = object.__new__(DrivePortIdentity)
    for name, value in (("namespace", "nonsense"), ("tenant", "t"), ("connection_id", "c")):
        object.__setattr__(bad, name, value)
    assert drive_port.canonical_identity(bad) is None
    assert drive_port.is_sound_identity(bad) is False
    sub = object.__new__(DrivePortIdentity)
    for name, value in (("namespace", HostileStr("account:x")), ("tenant", "t"), ("connection_id", "c")):
        object.__setattr__(sub, name, value)
    assert drive_port.canonical_identity(sub) is None
