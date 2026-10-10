"""S7/E1: Drive scope allow-list evaluator and corpus membership (TC103, TC104, TC105 + S6b lessons).

Everything runs over the scripted FakeDrivePort: the results prove the logic over those scripts only,
not real Google behaviour.
"""
from __future__ import annotations

import ast
import itertools
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import drive_scope
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_port import (
    DriveErrorCode,
    DrivePortIdentity,
    FileMeta,
)
from business_ai_gateway.phase2.drive_scope import (
    SCOPE_ALLOW_LIST,
    AccessProof,
    CorpusDeclaration,
    Isolation,
    MembershipCode,
    MembershipStatus,
    ScopeClaim,
    ScopeCode,
    ScopeEvaluation,
    check_isolation_label,
    evaluate_scopes,
    observe_new_child_access,
    prove_scoped_read,
    resolve_membership,
)


def _ID(v):
    return repr(v)[:40]


IDENT = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")
CORPUS = CorpusDeclaration("account:acc-1", None, ("ROOT",))
NARROW = ("drive.file",)


class StrSub(str):
    pass


class IntSub(int):
    pass


class TupleSub(tuple):
    pass


def _meta(fid: str, parents=(), **kw) -> FileMeta:
    base = {"name": "n", "mime_type": "application/pdf", "trashed": False, "drive_id": None}
    base.update(kw)
    return FileMeta(file_id=fid, parents=tuple(parents), **base)


def _fake(*metas: FileMeta, **kw) -> FakeDrivePort:
    fake = FakeDrivePort(**kw)
    for m in metas:
        fake.set_file(m)
    return fake


def _recursive_list():
    items: list = []
    items.append(items)
    return items


HOSTILE_NAMES = [
    None, 5, b"drive.file", "drive.file", StrSub("drive.file"), TupleSub(("drive.file",)),
    (), [], {"drive.file": 1}, (None,), ("drive.file", None), ("drive.file\x00",), ("x" * 100_000,),
    (StrSub("drive.file"),), (b"drive.file",), _recursive_list(), (_recursive_list(),),
    ("https://www.googleapis.com/auth/drive.file",), ("Drive.File",), ("drive file",),
    ("drive.appdata",), tuple(f"drive.s{i}" for i in range(40)), (1, 2),
]


# --- TC105 scope evaluator ---------------------------------------------------------------------


def test_narrow_file_scope_proceeds_and_claims_file_grant_only_not_folder_isolation():
    ev = evaluate_scopes(NARROW)
    assert ev == ScopeEvaluation(
        ScopeCode.OK, ScopeClaim.NARROW_FILE_SCOPE, Isolation.FILE_GRANT_ONLY, True, ("drive.file",)
    )


@pytest.mark.parametrize("name,claim", [
    ("drive.readonly", ScopeClaim.READONLY_BROAD),
    ("drive.metadata.readonly", ScopeClaim.READONLY_BROAD),
    ("drive", ScopeClaim.BROAD),
], ids=_ID)
def test_broad_grant_without_risk_label_is_reported_but_may_not_proceed(name, claim):
    ev = evaluate_scopes((name,))
    assert ev.code is ScopeCode.BROAD_REQUIRES_RISK_LABEL
    assert ev.claim is claim
    assert ev.isolation is Isolation.APPLICATION_FILTER_ONLY
    assert ev.may_proceed is False


@pytest.mark.parametrize("name,claim", [
    ("drive.readonly", ScopeClaim.READONLY_BROAD), ("drive", ScopeClaim.BROAD),
], ids=_ID)
def test_broad_accepted_label_lets_broad_proceed_but_isolation_stays_application_filter(name, claim):
    ev = evaluate_scopes((name,), ("BROAD_ACCEPTED",))
    assert (ev.code, ev.claim, ev.may_proceed) == (ScopeCode.OK, claim, True)
    assert ev.isolation is Isolation.APPLICATION_FILTER_ONLY


def test_no_scope_combination_ever_yields_folder_isolation_and_broadest_name_wins():
    names = sorted(SCOPE_ALLOW_LIST)
    for r in range(1, len(names) + 1):
        for combo in itertools.combinations(names, r):
            for labels in ((), ("BROAD_ACCEPTED",)):
                ev = evaluate_scopes(combo, labels)
                assert ev.isolation is not Isolation.FOLDER_ISOLATED
                broadest = max(SCOPE_ALLOW_LIST[n] is ScopeClaim.BROAD for n in combo)
                if broadest:
                    assert ev.claim is ScopeClaim.BROAD
                if ev.claim is not ScopeClaim.NARROW_FILE_SCOPE:
                    assert ev.isolation is Isolation.APPLICATION_FILTER_ONLY
                    assert ev.may_proceed == bool(labels)
    assert evaluate_scopes(("drive.file", "drive"), ("BROAD_ACCEPTED",)).claim is ScopeClaim.BROAD


def test_set_and_list_forms_are_equivalent_and_order_is_irrelevant():
    a = evaluate_scopes(("drive.file", "drive.readonly"), ("BROAD_ACCEPTED",))
    b = evaluate_scopes(frozenset({"drive.readonly", "drive.file"}), ["BROAD_ACCEPTED"])
    assert a == b and a.scopes == ("drive.file", "drive.readonly")


def test_attempt_to_label_a_broad_grant_as_isolated_is_refused():
    broad = evaluate_scopes(("drive",), ("BROAD_ACCEPTED",))
    narrow = evaluate_scopes(NARROW)
    assert check_isolation_label(broad, Isolation.FOLDER_ISOLATED) is ScopeCode.ISOLATION_LABEL_REFUSED
    assert check_isolation_label(narrow, Isolation.FOLDER_ISOLATED) is ScopeCode.ISOLATION_LABEL_REFUSED
    assert check_isolation_label(broad, Isolation.FILE_GRANT_ONLY) is ScopeCode.ISOLATION_LABEL_REFUSED
    assert check_isolation_label(broad, "FOLDER_ISOLATED") is ScopeCode.ISOLATION_LABEL_REFUSED
    assert check_isolation_label(broad, Isolation.APPLICATION_FILTER_ONLY) is ScopeCode.OK
    assert check_isolation_label(narrow, Isolation.FILE_GRANT_ONLY) is ScopeCode.OK
    forged = ScopeEvaluation(ScopeCode.OK, ScopeClaim.BROAD, Isolation.FOLDER_ISOLATED, True, ("drive",))
    assert check_isolation_label(forged, Isolation.FOLDER_ISOLATED) is ScopeCode.ISOLATION_LABEL_REFUSED
    for bad in (None, "x", 1, object()):
        assert check_isolation_label(bad, Isolation.FILE_GRANT_ONLY) is ScopeCode.ISOLATION_LABEL_REFUSED


@pytest.mark.parametrize("bad", HOSTILE_NAMES, ids=_ID)
def test_hostile_scope_names_return_a_fixed_refusal_and_never_raise(bad):
    ev = evaluate_scopes(bad)
    assert ev.may_proceed is False
    assert ev.claim is None and ev.isolation is None and ev.scopes == ()
    assert type(ev.code) is ScopeCode and ev.code is not ScopeCode.OK


def test_scope_url_is_a_refused_name_not_a_call_target():
    ev = evaluate_scopes(("https://www.googleapis.com/auth/drive",), ("BROAD_ACCEPTED",))
    assert ev.code is ScopeCode.SCOPE_NAME_INVALID and not ev.may_proceed
    assert evaluate_scopes(("drive.appdata",)).code is ScopeCode.SCOPE_UNKNOWN


@pytest.mark.parametrize("labels", [
    "BROAD_ACCEPTED", None, 5, (StrSub("BROAD_ACCEPTED"),), (None,), TupleSub(("BROAD_ACCEPTED",)),
    _recursive_list(), tuple(["BROAD_ACCEPTED"] * 9),
], ids=_ID)
def test_hostile_risk_labels_never_unlock_broad(labels):
    ev = evaluate_scopes(("drive",), labels)
    assert ev.may_proceed is False


@pytest.mark.parametrize("label", ["broad_accepted", "BROAD_ACCEPTED ", "BROAD_ACCEPTED\x00", "OTHER"], ids=_ID)
def test_unknown_risk_label_is_refused_not_ignored(label):
    ev = evaluate_scopes(NARROW, (label,))
    assert ev.code is ScopeCode.RISK_LABEL_UNKNOWN and not ev.may_proceed


# --- corpus declaration ------------------------------------------------------------------------


@pytest.mark.parametrize("args", [
    ("bogus:x", None, ("R",)), ("account:", None, ("R",)), (StrSub("account:x"), None, ("R",)),
    ("account:x", StrSub("d"), ("R",)), ("account:x", None, ["R"]), ("account:x", None, ("R", "R")),
    ("account:x", None, (StrSub("R"),)), ("account:x", None, ("R\x00",)), ("account:x", None, ("R S",)),
    ("account:x", None, tuple(f"r{i}" for i in range(65))), ("account:x", None, TupleSub(("R",))),
    ("account:x", "", ("R",)), (None, None, ("R",)), ("account:x", None, (None,)),
], ids=_ID)
def test_corpus_declaration_refuses_bad_input_with_fixed_code_not_echoing_the_value(args):
    with pytest.raises(ValueError) as exc:
        CorpusDeclaration(*args)
    assert str(exc.value) == "CORPUS_INVALID"


def test_corpus_roots_are_preserved_byte_exact_and_case_sensitive():
    c = CorpusDeclaration("drive:AbC", "AbC", ("Root-1", "root-1"))
    assert c.root_folder_ids == ("Root-1", "root-1") and c.drive_id == "AbC"


# --- membership --------------------------------------------------------------------------------


async def test_direct_child_deep_chain_multi_parent_and_root_itself_are_in_scope():
    fake = _fake(
        _meta("X1", ("ROOT",)), _meta("F2", ("F1",)), _meta("F1", ("ROOT",)),
        _meta("X2", ("F2",)), _meta("X3", ("OUT", "F1")), _meta("ROOT", ("MYDRIVE",)),
    )
    for fid in ("X1", "X2", "X3", "ROOT"):
        res = await resolve_membership(fake, IDENT, 0, CORPUS, fid)
        assert (res.status, res.code, res.in_scope) == (
            MembershipStatus.IN_SCOPE, MembershipCode.IN_CORPUS, True), fid


async def test_fully_resolved_chain_that_misses_every_root_is_outside_corpus_not_an_error():
    fake = _fake(_meta("X", ("OTHER",)), _meta("OTHER", ("MYDRIVE",)), _meta("MYDRIVE", ()))
    res = await resolve_membership(fake, IDENT, 0, CORPUS, "X")
    assert (res.status, res.code) == (MembershipStatus.NOT_IN_SCOPE, MembershipCode.OUTSIDE_CORPUS)
    top = await resolve_membership(_fake(_meta("T", ())), IDENT, 0, CORPUS, "T")
    assert top.code is MembershipCode.OUTSIDE_CORPUS


async def test_unknown_parent_and_unknown_file_are_not_in_scope_and_do_not_raise():
    fake = _fake(_meta("X", ("GONE",)))
    res = await resolve_membership(fake, IDENT, 0, CORPUS, "X")
    assert (res.status, res.code) == (MembershipStatus.NOT_IN_SCOPE, MembershipCode.PARENT_UNRESOLVED)
    res = await resolve_membership(fake, IDENT, 0, CORPUS, "MISSING")
    assert res.code is MembershipCode.FILE_UNRESOLVED and not res.in_scope


async def test_case_variant_of_a_root_id_is_not_the_root():
    fake = _fake(_meta("X", ("root",)), _meta("root", ()))
    res = await resolve_membership(fake, IDENT, 0, CORPUS, "X")
    assert not res.in_scope


async def test_cyclic_parent_chain_terminates_with_bounded_calls():
    fake = _fake(_meta("X", ("A",)), _meta("A", ("B",)), _meta("B", ("A",)))
    res = await resolve_membership(fake, IDENT, 0, CORPUS, "X")
    assert (res.status, res.code) == (MembershipStatus.NOT_IN_SCOPE, MembershipCode.CYCLE)
    assert fake.call_count == 3
    selfloop = _fake(_meta("S", ("S",)))
    res = await resolve_membership(selfloop, IDENT, 0, CORPUS, "S")
    assert res.code is MembershipCode.CYCLE and selfloop.call_count == 1


async def test_cycle_with_an_exit_to_the_root_is_still_in_scope():
    fake = _fake(_meta("X", ("A",)), _meta("A", ("B", "ROOT")), _meta("B", ("A",)))
    assert (await resolve_membership(fake, IDENT, 0, CORPUS, "X")).in_scope


async def test_depth_bound_is_enforced_and_exact():
    chain = [_meta(f"D{i}", (f"D{i + 1}",)) for i in range(5)] + [_meta("D5", ("ROOT",))]
    fake = _fake(*chain)
    short = await resolve_membership(fake, IDENT, 0, CORPUS, "D0", max_depth=3)
    assert (short.status, short.code) == (MembershipStatus.NOT_IN_SCOPE, MembershipCode.DEPTH_EXCEEDED)
    assert (await resolve_membership(fake, IDENT, 0, CORPUS, "D0", max_depth=6)).in_scope
    assert not (await resolve_membership(fake, IDENT, 0, CORPUS, "D0", max_depth=5)).in_scope


async def test_call_budget_is_enforced():
    chain = [_meta(f"D{i}", (f"D{i + 1}",)) for i in range(5)] + [_meta("D5", ("ROOT",))]
    fake = _fake(*chain)
    res = await resolve_membership(fake, IDENT, 0, CORPUS, "D0", max_calls=3)
    assert res.code is MembershipCode.BUDGET_EXCEEDED and fake.call_count == 3


async def test_shortcut_is_never_a_membership_proof_in_either_direction():
    # a shortcut sitting inside the corpus
    fake = _fake(_meta("SC", ("ROOT",), shortcut_target="TARGET"), _meta("TARGET", ("OUT",)),
                 _meta("OUT", ()))
    assert (await resolve_membership(fake, IDENT, 0, CORPUS, "SC")).code is MembershipCode.SHORTCUT_NOT_PROOF
    # the target is judged by its own chain only, so a shortcut in the corpus does not pull it in
    assert (await resolve_membership(fake, IDENT, 0, CORPUS, "TARGET")).code is MembershipCode.OUTSIDE_CORPUS
    # a shortcut used as an ancestor is a dead branch
    fake2 = _fake(_meta("X", ("SF",)), _meta("SF", ("ROOT",), shortcut_target="F"))
    res = await resolve_membership(fake2, IDENT, 0, CORPUS, "X")
    assert not res.in_scope and res.code is MembershipCode.SHORTCUT_NOT_PROOF


async def test_trashed_leaf_or_ancestor_is_not_in_scope():
    fake = _fake(_meta("X", ("ROOT",), trashed=True), _meta("Y", ("T",)), _meta("T", ("ROOT",), trashed=True))
    assert (await resolve_membership(fake, IDENT, 0, CORPUS, "X")).code is MembershipCode.TRASHED
    assert (await resolve_membership(fake, IDENT, 0, CORPUS, "Y")).code is MembershipCode.TRASHED


async def test_namespace_and_drive_id_must_match_the_corpus_declaration():
    fake = _fake(_meta("X", ("ROOT",)), _meta("SD", ("ROOT",), drive_id="D1"))
    other_ns = DrivePortIdentity("drive:D1", "tenant-1", "conn-1")
    res = await resolve_membership(fake, other_ns, 0, CORPUS, "X")
    assert res.code is MembershipCode.NAMESPACE_MISMATCH and fake.call_count == 0
    assert (await resolve_membership(fake, IDENT, 0, CORPUS, "SD")).code is MembershipCode.NAMESPACE_MISMATCH
    shared = CorpusDeclaration("drive:D1", "D1", ("ROOT",))
    assert (await resolve_membership(fake, other_ns, 0, shared, "SD")).in_scope
    assert (await resolve_membership(fake, other_ns, 0, shared, "X")).code is MembershipCode.NAMESPACE_MISMATCH


async def test_empty_corpus_proves_nothing_and_makes_no_call():
    fake = _fake(_meta("X", ("ROOT",)))
    empty = CorpusDeclaration("account:acc-1", None, ())
    res = await resolve_membership(fake, IDENT, 0, empty, "X")
    assert res.code is MembershipCode.EMPTY_CORPUS and fake.call_count == 0


async def test_port_refusals_fail_closed_with_the_fixed_port_code():
    fake = _fake(_meta("X", ("ROOT",)))
    fake.force_error("get_file_meta", DriveErrorCode.AUTH_REQUIRED)
    res = await resolve_membership(fake, IDENT, 0, CORPUS, "X")
    assert (res.status, res.code, res.port_code) == (
        MembershipStatus.NOT_IN_SCOPE, MembershipCode.PORT_REFUSED, DriveErrorCode.AUTH_REQUIRED)
    fake.set_scope_epoch(1)
    res = await resolve_membership(fake, IDENT, 0, CORPUS, "X")
    assert res.port_code is DriveErrorCode.SCOPE_EPOCH_STALE
    assert (await resolve_membership(fake, IDENT, 1, CORPUS, "X")).in_scope


async def test_port_that_raises_or_answers_nonsense_is_refused_not_propagated():
    class Boom:
        async def get_file_meta(self, *a):
            raise RuntimeError("provider says SECRET-TEXT")

    class Wrong:
        async def get_file_meta(self, identity, epoch, file_id):
            return _meta("OTHER-ID", ("ROOT",))

    class Junk:
        async def get_file_meta(self, *a):
            return {"parents": ["ROOT"]}

    res = await resolve_membership(Boom(), IDENT, 0, CORPUS, "X")
    assert res.code is MembershipCode.PORT_REFUSED and "SECRET" not in repr(res)
    assert (await resolve_membership(Wrong(), IDENT, 0, CORPUS, "X")).code is MembershipCode.FILE_UNRESOLVED
    assert (await resolve_membership(Junk(), IDENT, 0, CORPUS, "X")).code is MembershipCode.FILE_UNRESOLVED
    assert (await resolve_membership(None, IDENT, 0, CORPUS, "X")).code is MembershipCode.PORT_REFUSED


@pytest.mark.parametrize("kwargs", [
    {"identity": None}, {"identity": "account:acc-1"}, {"scope_epoch": IntSub(0)},
    {"scope_epoch": True}, {"scope_epoch": -1}, {"scope_epoch": None}, {"corpus": None},
    {"file_id": None}, {"file_id": StrSub("X")}, {"file_id": "X\x00"}, {"file_id": "X" * 100_000},
    {"file_id": " X"}, {"file_id": ""}, {"file_id": b"X"}, {"file_id": ["X"]},
    {"max_depth": True}, {"max_depth": 0}, {"max_depth": 10**6}, {"max_depth": IntSub(3)},
    {"max_calls": 0}, {"max_calls": None}, {"max_calls": 10**9},
], ids=_ID)
async def test_hostile_membership_inputs_return_not_in_scope_without_a_port_call(kwargs):
    fake = _fake(_meta("X", ("ROOT",)))
    args = {"identity": IDENT, "scope_epoch": 0, "corpus": CORPUS, "file_id": "X"}
    extra = {k: kwargs[k] for k in ("max_depth", "max_calls") if k in kwargs}
    args.update({k: v for k, v in kwargs.items() if k not in extra})
    res = await resolve_membership(fake, args["identity"], args["scope_epoch"], args["corpus"],
                                   args["file_id"], **extra)
    assert (res.status, res.code) == (MembershipStatus.NOT_IN_SCOPE, MembershipCode.INPUT_INVALID)
    assert fake.call_count == 0


async def test_recursive_and_huge_parent_graphs_stay_bounded():
    wide = _fake(_meta("X", tuple(f"P{i}" for i in range(500))))
    res = await resolve_membership(wide, IDENT, 0, CORPUS, "X", max_calls=10)
    assert res.code is MembershipCode.BUDGET_EXCEEDED and wide.call_count == 10


# --- TC103 scoped access proof -----------------------------------------------------------------


async def test_tc103_in_scope_read_is_proven_with_its_basis():
    fake = _fake(_meta("X", ("ROOT",)))
    proof = await prove_scoped_read(fake, IDENT, 0, CORPUS, "X", NARROW, "OBS-1")
    assert proof.status is AccessProof.PROVEN and proof.code == "READ_IN_CORPUS"
    assert proof.basis is not None
    assert (proof.basis.scopes, proof.basis.root_folder_ids, proof.basis.observation_id) == (
        ("drive.file",), ("ROOT",), "OBS-1")
    assert "get_file_meta" in fake.call_log


async def test_tc103_out_of_corpus_read_is_denied_and_carries_no_basis():
    fake = _fake(_meta("X", ("OTHER",)), _meta("OTHER", ()))
    proof = await prove_scoped_read(fake, IDENT, 0, CORPUS, "X", NARROW, "OBS-1")
    assert (proof.status, proof.code, proof.basis) == (AccessProof.DENIED, "OUT_OF_CORPUS", None)


async def test_tc103_empty_corpus_and_unresolved_file_prove_nothing():
    fake = _fake(_meta("X", ("GONE",)))
    empty = CorpusDeclaration("account:acc-1", None, ())
    p1 = await prove_scoped_read(fake, IDENT, 0, empty, "X", NARROW, "OBS-1")
    assert (p1.status, p1.code, p1.basis) == (AccessProof.NOT_PROVEN, "EMPTY_CORPUS", None)
    assert fake.call_count == 0
    p2 = await prove_scoped_read(fake, IDENT, 0, CORPUS, "X", NARROW, "OBS-1")
    assert (p2.status, p2.basis) == (AccessProof.NOT_PROVEN, None)
    p3 = await prove_scoped_read(fake, IDENT, 0, CORPUS, "MISSING", NARROW, "OBS-1")
    assert p3.status is AccessProof.NOT_PROVEN


async def test_tc103_unaccepted_scope_set_never_proves_even_for_a_readable_file():
    fake = _fake(_meta("X", ("ROOT",)))
    for scopes in (("drive",), ("drive.readonly",), ("https://x/drive.file",), ("drive.file", "drive")):
        proof = await prove_scoped_read(fake, IDENT, 0, CORPUS, "X", scopes, "OBS-1")
        assert proof.status is AccessProof.DENIED and proof.basis is None
    assert fake.call_count == 0
    ok = await prove_scoped_read(fake, IDENT, 0, CORPUS, "X", ("drive",), "OBS-1", ("BROAD_ACCEPTED",))
    assert ok.status is AccessProof.PROVEN  # accepted risk proceeds; it is still not isolation


async def test_tc103_stale_epoch_and_auth_failure_do_not_prove():
    fake = _fake(_meta("X", ("ROOT",)), scope_epoch=3)
    assert (await prove_scoped_read(fake, IDENT, 2, CORPUS, "X", NARROW, "O")).status is AccessProof.NOT_PROVEN
    assert (await prove_scoped_read(fake, IDENT, 3, CORPUS, "X", NARROW, "O")).status is AccessProof.PROVEN


@pytest.mark.parametrize("obs", [None, "", StrSub("O"), "O\x00", "O" * 5000, 5, " O"], ids=_ID)
async def test_hostile_observation_ids_are_refused_without_a_call(obs):
    fake = _fake(_meta("X", ("ROOT",)))
    p = await prove_scoped_read(fake, IDENT, 0, CORPUS, "X", NARROW, obs)
    n = await observe_new_child_access(fake, IDENT, 0, CORPUS, "X", NARROW, obs)
    assert (p.status, p.code) == (AccessProof.NOT_PROVEN, "INPUT_INVALID")
    assert (n.status, n.code) == (AccessProof.NOT_PROVEN, "INPUT_INVALID")
    assert fake.call_count == 0


async def test_hostile_scope_inputs_to_the_proof_functions_do_not_raise():
    fake = _fake(_meta("X", ("ROOT",)))
    for bad in HOSTILE_NAMES:
        p = await prove_scoped_read(fake, IDENT, 0, CORPUS, "X", bad, "O")
        n = await observe_new_child_access(fake, IDENT, 0, CORPUS, "X", bad, "O")
        assert p.status is not AccessProof.PROVEN and n.status is not AccessProof.PROVEN


# --- TC104 new child access --------------------------------------------------------------------


async def test_tc104_new_child_readable_after_grant_is_proven_only_from_the_observation():
    fake = FakeDrivePort()
    fake.set_file(_meta("CHILD", ("ROOT",)), new_child=True)
    obs = await observe_new_child_access(fake, IDENT, 0, CORPUS, "CHILD", NARROW, "OBS-9")
    assert (obs.status, obs.code) == (AccessProof.PROVEN, "CHILD_READABLE")
    assert obs.basis is not None and obs.basis.observation_id == "OBS-9"
    assert fake.call_log == ("get_file_meta",)


async def test_tc104_fake_that_hides_new_children_is_not_proven_and_names_why():
    fake = FakeDrivePort()
    fake.set_file(_meta("CHILD", ("ROOT",)), new_child=True)
    fake.hide_new_children = True
    obs = await observe_new_child_access(fake, IDENT, 0, CORPUS, "CHILD", NARROW, "OBS-9")
    assert (obs.status, obs.code, obs.basis) == (AccessProof.NOT_PROVEN, "CHILD_HIDDEN", None)


async def test_tc104_forbidden_child_is_denied_and_other_failures_are_not_proven():
    fake = FakeDrivePort()
    fake.set_file(_meta("CHILD", ("ROOT",)), new_child=True)
    fake.force_provider_response("get_file_meta", 403, "text must not leak")
    denied = await observe_new_child_access(fake, IDENT, 0, CORPUS, "CHILD", NARROW, "O")
    assert (denied.status, denied.code) == (AccessProof.DENIED, "CHILD_FORBIDDEN")
    fake.force_error("get_file_meta", DriveErrorCode.TRANSIENT)
    failed = await observe_new_child_access(fake, IDENT, 0, CORPUS, "CHILD", NARROW, "O")
    assert (failed.status, failed.code) == (AccessProof.NOT_PROVEN, "OBSERVATION_FAILED")


async def test_tc104_child_outside_the_corpus_or_with_empty_corpus_proves_nothing():
    fake = FakeDrivePort()
    fake.set_file(_meta("CHILD", ("OTHER",)), new_child=True)
    fake.set_file(_meta("OTHER", ()))
    out = await observe_new_child_access(fake, IDENT, 0, CORPUS, "CHILD", NARROW, "O")
    assert (out.status, out.code) == (AccessProof.NOT_PROVEN, "CHILD_OUTSIDE_CORPUS")
    empty = CorpusDeclaration("account:acc-1", None, ())
    none = await observe_new_child_access(fake, IDENT, 0, empty, "CHILD", NARROW, "O")
    assert (none.status, none.code) == (AccessProof.NOT_PROVEN, "EMPTY_CORPUS")


async def test_tc104_nothing_is_assumed_without_the_observation_and_broad_grant_needs_label():
    fake = FakeDrivePort()  # the child was never scripted: no assumption of access
    obs = await observe_new_child_access(fake, IDENT, 0, CORPUS, "CHILD", NARROW, "O")
    assert obs.status is AccessProof.NOT_PROVEN
    fake.set_file(_meta("CHILD", ("ROOT",)), new_child=True)
    broad = await observe_new_child_access(fake, IDENT, 0, CORPUS, "CHILD", ("drive",), "O")
    assert (broad.status, broad.code) == (AccessProof.DENIED, "SCOPE_NOT_ACCEPTED")


# --- boundary of this module -------------------------------------------------------------------


def test_scope_module_has_no_forbidden_imports_and_no_google_url():
    src = Path(drive_scope.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
            if node.level:
                imported.add("." * node.level + (node.module or ""))
    forbidden = {"httpx", "requests", "socket", "subprocess", "urllib", "os", "sqlite3", "aiohttp"}
    assert not (imported & forbidden)
    assert not any("release1" in m.lower() or "pdcc" in m.lower() for m in imported)
    assert "drive_http" not in " ".join(imported)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "googleapis" not in node.value and "://" not in node.value
