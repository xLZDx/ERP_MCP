"""S7/E3 (TC109): revision tracking, HISTORICAL PASS, read-only history availability. Offline."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import drive_revisions
from business_ai_gateway.phase2.drive_changes import EvidenceCandidate
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_port import (
    DriveErrorCode,
    DrivePortIdentity,
    FileMeta,
    RevisionMeta,
)
from business_ai_gateway.phase2.drive_revisions import (
    HistoryCoverage,
    HistoryStatus,
    ObservationOutcome,
    RecordResult,
    RevisionState,
    RevisionTracker,
    list_history,
)

IDENT = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")
GUID = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"


class StrSub(str):
    def __eq__(self, other):  # hostile: equal to anything
        return True

    __hash__ = str.__hash__


def _meta(fid: str = "F1") -> FileMeta:
    return FileMeta(fid, "Doc.pdf", "application/pdf", ("P",), False, None)


# --- TC109: new revision -> UNATTESTED candidate, old PASS historical ------------------------------


def test_tc109_new_revision_is_unattested_and_old_pass_is_historical():
    t = RevisionTracker(IDENT)
    first = t.observe("F1", "rev1", "c1")
    assert first.outcome is ObservationOutcome.FIRST_SEEN
    assert first.candidate == EvidenceCandidate("conn-1", "F1", "rev1", "c1")
    assert t.record_attested("F1", "rev1") is RecordResult.RECORDED
    assert t.latest_verdict("F1").state is RevisionState.PASS_CURRENT

    second = t.observe("F1", "rev2", "c2")
    assert second.outcome is ObservationOutcome.NEW_REVISION
    assert second.candidate is not None
    assert second.candidate.revision_id == "rev2"
    assert second.candidate.status == "UNATTESTED"
    assert second.historical_revision_ids == ("rev1",)

    old = t.verdict("F1", "rev1")
    assert old.state is RevisionState.PASS_HISTORICAL
    assert old.applies_to_revision == "rev1"
    assert old.is_latest is False
    latest = t.latest_verdict("F1")
    assert latest.state is RevisionState.UNATTESTED
    assert latest.applies_to_revision is None
    assert latest.is_latest is True
    assert t.verdict("F1", "rev2").state is RevisionState.UNATTESTED

    # only a new, independent attestation of rev2 makes the latest PASS; rev1 stays historical
    assert t.record_attested("F1", "rev2") is RecordResult.RECORDED
    assert t.latest_verdict("F1").state is RevisionState.PASS_CURRENT
    assert t.verdict("F1", "rev1").state is RevisionState.PASS_HISTORICAL


def test_unattested_old_revision_is_not_reported_historical_pass():
    t = RevisionTracker(IDENT)
    t.observe("F1", "rev1", "c1")
    second = t.observe("F1", "rev2", "c2")
    assert second.historical_revision_ids == ()
    assert t.verdict("F1", "rev1").state is RevisionState.UNATTESTED


def test_duplicate_and_older_redelivery_create_no_candidate_and_never_become_latest():
    t = RevisionTracker(IDENT)
    t.observe("F1", "rev1", "c1")
    t.observe("F1", "rev2", "c2")
    dup = t.observe("F1", "rev2", "c3")
    assert dup.outcome is ObservationOutcome.DUPLICATE and dup.candidate is None
    old = t.observe("F1", "rev1", "c4")
    assert old.outcome is ObservationOutcome.OUT_OF_ORDER and old.candidate is None
    assert t.verdict("F1", "rev2").is_latest is True
    assert t.verdict("F1", "rev1").is_latest is False


def test_attestation_mark_needs_a_known_revision_and_is_per_file():
    t = RevisionTracker(IDENT)
    t.observe("F1", "rev1", "c1")
    t.observe("F2", "rev1", "c2")
    assert t.record_attested("F1", "nope") is RecordResult.UNKNOWN_REVISION
    assert t.record_attested("NOFILE", "rev1") is RecordResult.UNKNOWN_REVISION
    assert t.record_attested("F1", "rev1") is RecordResult.RECORDED
    assert t.verdict("F2", "rev1").state is RevisionState.UNATTESTED
    assert t.latest_verdict("NOFILE").state is RevisionState.UNKNOWN


# --- S6b lessons: exact types, byte-exact ids, hostile input never raises --------------------------

HOSTILE = [
    None, 1, True, b"x", ["x"], {"a": 1}, object(), "", " x", "x ", "a b", "a\x00b", "a\nb",
    "a\u200bb", "x" * 5000, StrSub("rev1"),
]


@pytest.mark.parametrize("bad", HOSTILE)
def test_hostile_input_is_refused_without_raising(bad):
    t = RevisionTracker(IDENT)
    t.observe("F1", "rev1", "c1")
    assert t.observe(bad, "rev2", "c2").outcome is ObservationOutcome.REFUSED
    assert t.observe("F1", bad, "c2").outcome is ObservationOutcome.REFUSED
    assert t.observe("F1", "rev2", bad).outcome is ObservationOutcome.REFUSED
    assert t.record_attested(bad, "rev1") is RecordResult.INVALID_INPUT
    assert t.record_attested("F1", bad) is RecordResult.INVALID_INPUT
    assert t.verdict(bad, "rev1").state is RevisionState.UNKNOWN
    assert t.verdict("F1", bad).state is RevisionState.UNKNOWN
    assert t.latest_verdict(bad).state is RevisionState.UNKNOWN
    # state untouched by every refusal: rev2 was never recorded
    assert t.latest_verdict("F1").applies_to_revision is None
    assert t.verdict("F1", "rev1").is_latest is True


def test_ids_are_preserved_byte_exact_and_never_folded():
    t = RevisionTracker(IDENT)
    r1 = t.observe(GUID, "Rev-A", "c1")
    assert r1.candidate is not None
    assert r1.candidate.file_id == GUID  # GUID-shaped Drive id is NOT canonicalised
    assert r1.candidate.revision_id == "Rev-A"
    # a differently cased revision id is a different revision, i.e. a new revision, not a duplicate
    assert t.observe(GUID, "rev-a", "c2").outcome is ObservationOutcome.NEW_REVISION
    # the lower-case spelling of the file id is another file
    assert t.observe(GUID.lower(), "Rev-A", "c3").outcome is ObservationOutcome.FIRST_SEEN


def test_trackers_of_two_namespaces_do_not_share_state():
    other = RevisionTracker(DrivePortIdentity("drive:D1", "tenant-1", "conn-2"))
    t = RevisionTracker(IDENT)
    t.observe("F1", "rev1", "c1")
    t.record_attested("F1", "rev1")
    assert other.observe("F1", "rev1", "c1").candidate == EvidenceCandidate("conn-2", "F1", "rev1", "c1")
    assert other.verdict("F1", "rev1").state is RevisionState.UNATTESTED


def test_tracker_bounds_are_a_fixed_refusal(monkeypatch):
    monkeypatch.setattr(drive_revisions, "MAX_TRACKED_FILES", 1)
    monkeypatch.setattr(drive_revisions, "MAX_REVISIONS_PER_FILE", 2)
    t = RevisionTracker(IDENT)
    t.observe("F1", "r1", "c1")
    assert t.observe("F2", "r1", "c2").reason == "TRACKER_FULL"
    t.observe("F1", "r2", "c3")
    refused = t.observe("F1", "r3", "c4")
    assert refused.outcome is ObservationOutcome.REFUSED and refused.reason == "TRACKER_FULL"
    assert t.latest_verdict("F1").applies_to_revision is None
    assert t.verdict("F1", "r2").is_latest is True


def test_constructor_refuses_a_non_identity():
    with pytest.raises(ValueError, match="DRIVE_IDENTITY_INVALID"):
        RevisionTracker("account:x")  # type: ignore[arg-type]


# --- history availability (read-only port) ---------------------------------------------------------


async def test_history_listed_through_read_only_call():
    fake = FakeDrivePort()
    fake.set_file(_meta())
    fake.set_revisions("F1", (RevisionMeta("rev1"), RevisionMeta("rev2")))
    res = await list_history(fake, IDENT, 0, "F1")
    assert res.status is HistoryStatus.AVAILABLE
    assert res.coverage is HistoryCoverage.LISTED
    assert res.revision_ids == ("rev1", "rev2")
    assert fake.call_log == ("list_revisions",)


async def test_history_forbidden_is_unavailable_current_only_and_makes_no_other_call():
    fake = FakeDrivePort()
    fake.set_file(_meta())
    fake.history_forbidden = True
    res = await list_history(fake, IDENT, 0, "F1")
    assert (res.status, res.coverage) == (HistoryStatus.HISTORY_UNAVAILABLE, HistoryCoverage.CURRENT_ONLY)
    assert res.reason == "HISTORY_UNAVAILABLE"
    assert res.revision_ids == ()
    assert fake.call_log == ("list_revisions",)  # no write/permission/keepForever exists on the fake either
    fake2 = FakeDrivePort()
    fake2.set_file(_meta())
    fake2.force_provider_response("list_revisions", 403, "insufficientFilePermissions: raise rights")
    res2 = await list_history(fake2, IDENT, 0, "F1")
    assert res2 == res
    assert "rights" not in repr(res2)


async def test_missing_or_empty_revision_list_is_history_unavailable():
    fake = FakeDrivePort()
    fake.set_file(_meta())  # no revisions scripted -> ()
    res = await list_history(fake, IDENT, 0, "F1")
    assert (res.status, res.coverage) == (HistoryStatus.HISTORY_UNAVAILABLE, HistoryCoverage.CURRENT_ONLY)


async def test_history_other_port_errors_are_fixed_codes():
    fake = FakeDrivePort()
    fake.set_file(_meta())
    assert (await list_history(fake, IDENT, 0, "UNKNOWN")).status is HistoryStatus.NOT_FOUND
    for code in (DriveErrorCode.INVALID_GRANT, DriveErrorCode.AUTH_REQUIRED, DriveErrorCode.RATE_LIMITED):
        fake.force_error("list_revisions", code)
        res = await list_history(fake, IDENT, 0, "F1")
        assert res.status is HistoryStatus.CHECK_FAILED
        assert res.reason == code.value
        assert res.revision_ids == ()
        assert res.coverage is HistoryCoverage.NONE
    res = await list_history(fake, IDENT, 7, "F1")  # stale epoch
    assert res.reason == "SCOPE_EPOCH_STALE"


class _BrokenPort:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    async def list_revisions(self, identity, scope_epoch, file_id):
        if self.behaviour == "raise":
            raise RuntimeError("secret-token-123 leaked")
        return self.behaviour


async def test_port_bugs_fail_closed_and_never_echo():
    res = await list_history(_BrokenPort("raise"), IDENT, 0, "F1")  # type: ignore[arg-type]
    assert res.status is HistoryStatus.CHECK_FAILED and res.reason == "TRANSIENT"
    assert "secret" not in repr(res)
    dup = (RevisionMeta("r1"), RevisionMeta("r1"))
    assert (await list_history(_BrokenPort(dup), IDENT, 0, "F1")).reason == "REVISION_LIST_INVALID"  # type: ignore[arg-type]
    junk = (RevisionMeta("r1"), "r2")
    assert (await list_history(_BrokenPort(junk), IDENT, 0, "F1")).reason == "REVISION_LIST_INVALID"  # type: ignore[arg-type]
    assert (await list_history(_BrokenPort(["r1"]), IDENT, 0, "F1")).reason == "REVISION_LIST_INVALID"  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", HOSTILE)
async def test_history_hostile_args_refused_with_zero_port_calls(bad):
    fake = FakeDrivePort()
    fake.set_file(_meta())
    epoch_case = [] if type(bad) is int else [(IDENT, bad, "F1")]  # a plain int is a legal epoch
    for args in ((IDENT, 0, bad), (bad, 0, "F1"), *epoch_case):
        res = await list_history(fake, *args)  # type: ignore[arg-type]
        assert res.status is HistoryStatus.CHECK_FAILED
    assert fake.call_count == 0
    assert (await list_history(fake, IDENT, True, "F1")).status is HistoryStatus.CHECK_FAILED
    assert fake.call_count == 0


# --- no write / permission / keepForever path (AST) ------------------------------------------------

_SRC = Path(drive_revisions.__file__)
_FORBIDDEN_WORDS = (
    "permission", "keepforever", "keep_forever", "write", "delete", "create", "update", "patch",
    "grant", "elevate", "download", "export", "upload", "insert", "share",
)


def test_module_has_no_write_path_and_only_calls_list_revisions_on_the_port():
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    port_calls = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "port"
    }
    assert port_calls == {"list_revisions"}
    names = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.name.lower() for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not [w for w in _FORBIDDEN_WORDS for n in names if w in n]
    strings = [n.value.lower() for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    # reason/result codes (not docstrings) never suggest a right change
    codes = [s for s in strings if s.isupper() or s.replace("_", "").isalpha() and "_" in s]
    assert not [w for w in ("permission", "keepforever", "elevate", "writer") for c in codes if w in c]


def test_module_imports_are_offline_only():
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(("." * n.level) + (n.module or ""))
    forbidden = {"httpx", "requests", "socket", "subprocess", "urllib", "aiohttp", "os", "sqlite3"}
    assert not (mods & forbidden)
    assert not [m for m in mods if "drive_http" in m or "business_ai_gateway.phase1" in m or "pdcc" in m.lower()]
