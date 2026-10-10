"""S7/E1: read-only DrivePort contract, value types and the scripted fake. Pure, no I/O."""
from __future__ import annotations

import ast
import pickle
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import drive_fake, drive_port
from business_ai_gateway.phase2.drive_changes import DriveChange, DriveChangeKind
from business_ai_gateway.phase2.drive_fake import FakeDrivePort
from business_ai_gateway.phase2.drive_port import (
    ChangesPage,
    DriveErrorCode,
    DrivePort,
    DrivePortError,
    DrivePortIdentity,
    FileMeta,
    RevisionMeta,
    StartToken,
)

GUID = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"
IDENT = DrivePortIdentity("account:acc-1", "tenant-1", "conn-1")


def _change(cid: str = "c1", fid: str = "F1") -> DriveChange:
    return DriveChange(cid, fid, "r1", DriveChangeKind.UPSERT)


def _meta(fid: str = "F1", **kw) -> FileMeta:
    base = {"file_id": fid, "name": "My File.pdf", "mime_type": "application/pdf",
            "parents": ("P1",), "trashed": False, "drive_id": None}
    base.update(kw)
    return FileMeta(**base)


class StrSub(str):
    pass


class IntSub(int):
    pass


class TupleSub(tuple):
    pass


# --- value types ---------------------------------------------------------------------------------


@pytest.mark.parametrize("ns", ["account:x", "drive:Ab-_1"])
def test_identity_accepts_both_namespaces_and_preserves_id_exactly(ns):
    ident = DrivePortIdentity(ns, "t", "c")
    assert ident.namespace == ns
    assert ident.namespace_id == ns.split(":", 1)[1]
    assert ident.kind == ns.split(":", 1)[0]


@pytest.mark.parametrize("ns", [
    "", "account:", "drive:", "user:x", "Account:x", " account:x", "account:x ", "account: x",
    "account:x\x00", "account:\u200bx", StrSub("account:x"), None, 5, b"account:x", "a" * 2000,
])
def test_identity_refuses_bad_namespace_with_fixed_code(ns):
    with pytest.raises(ValueError) as exc:
        DrivePortIdentity(ns, "t", "c")
    assert str(exc.value) == "DRIVE_NAMESPACE_INVALID"


@pytest.mark.parametrize("bad", ["", " t", "t ", "t\x00", StrSub("t"), None, 1, "x" * 5000])
def test_identity_refuses_bad_tenant_and_connection(bad):
    with pytest.raises(ValueError, match="^DRIVE_IDENTITY_INVALID$"):
        DrivePortIdentity("account:a", bad, "c")
    with pytest.raises(ValueError, match="^DRIVE_IDENTITY_INVALID$"):
        DrivePortIdentity("account:a", "t", bad)


def test_identity_canonicalises_only_guid_shaped_tenant_and_connection():
    ident = DrivePortIdentity("account:" + GUID, "{" + GUID + "}", GUID.replace("-", ""))
    canon = GUID.lower()
    assert ident.tenant == canon and ident.connection_id == canon
    # namespace id is a Drive id: never canonicalised, case kept
    assert ident.namespace == "account:" + GUID
    # non-GUID text keeps its case
    assert DrivePortIdentity("drive:D", "TenantA", "ConnB").tenant == "TenantA"


def test_error_message_never_contains_offending_value():
    with pytest.raises(ValueError) as exc:
        DrivePortIdentity("account:a", "SECRET-VALUE\x00", "c")
    assert "SECRET" not in str(exc.value) and "SECRET" not in repr(exc.value)


def test_start_token_exact_and_byte_preserved():
    tok = "  Mixed/Case+Token=  "
    with pytest.raises(ValueError):
        StartToken(tok)  # whitespace is refused, never trimmed
    assert StartToken("Mixed/Case+Token=").token == "Mixed/Case+Token="
    for bad in ("", StrSub("x"), None, 7, "a\x00b", "z" * 2000):
        with pytest.raises(ValueError, match="^DRIVE_PAGE_TOKEN_INVALID$"):
            StartToken(bad)


def test_changes_page_exactly_one_token():
    assert ChangesPage((), next_page_token="N").new_start_page_token is None
    assert ChangesPage((), new_start_page_token="S").next_page_token is None
    for kw in ({}, {"next_page_token": "N", "new_start_page_token": "S"}):
        with pytest.raises(ValueError, match="^PAGE_CONTINUATION_XOR_NEW_START_REQUIRED$"):
            ChangesPage((), **kw)
    # an empty string is not "absent": refused as an invalid token
    with pytest.raises(ValueError, match="^DRIVE_PAGE_TOKEN_INVALID$"):
        ChangesPage((), next_page_token="")


@pytest.mark.parametrize("changes", [
    [_change()], TupleSub((_change(),)), (object(),), (_change(cid=""),), (_change(fid=""),),
    (DriveChange("c", "f", None, "UPSERT"),), None,
])
def test_changes_page_refuses_bad_changes(changes):
    with pytest.raises(ValueError, match="^DRIVE_CHANGES_INVALID$"):
        ChangesPage(changes, next_page_token="N")


def test_changes_page_keeps_token_bytes_and_adapts_to_drive_page():
    page = ChangesPage((_change(),), next_page_token="aB/c==")
    dp = page.to_drive_page("Req-Token")
    assert dp.requested_page_token == "Req-Token" and dp.next_page_token == "aB/c=="
    assert dp.changes == page.changes
    with pytest.raises(ValueError):
        page.to_drive_page("")


def test_file_meta_valid_and_exact():
    m = _meta(shortcut_target="T1", head_revision_id="R9", drive_id="D1", trashed=True)
    assert (m.file_id, m.name, m.parents, m.trashed, m.shortcut_target, m.head_revision_id) == (
        "F1", "My File.pdf", ("P1",), True, "T1", "R9")
    # case-sensitive, GUID-shaped Drive ids stay as given
    assert _meta(fid=GUID).file_id == GUID


@pytest.mark.parametrize("kw", [
    {"file_id": ""}, {"file_id": StrSub("F")}, {"file_id": " F"}, {"name": ""}, {"name": "a\x00b"},
    {"name": "a\nb"}, {"name": StrSub("n")}, {"mime_type": None}, {"parents": ["P"]},
    {"parents": TupleSub(("P",))}, {"parents": ("",)}, {"parents": (StrSub("P"),)},
    {"trashed": 1}, {"trashed": None}, {"drive_id": ""}, {"shortcut_target": " x"},
    {"head_revision_id": 5}, {"parents": ("P",) * 20_000},
])
def test_file_meta_refuses_hostile_values(kw):
    with pytest.raises(ValueError, match="^DRIVE_FILE_META_INVALID$"):
        _meta(**kw)


def test_revision_meta_flattens_to_utc_and_refuses_naive_and_subclass():
    est = timezone(timedelta(hours=-5))
    r = RevisionMeta("rev1", datetime(2026, 1, 1, 7, 0, tzinfo=est))
    assert r.modified_time == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert r.modified_time.utcoffset() == timedelta(0)
    assert RevisionMeta("rev1").modified_time is None

    class DT(datetime):
        pass

    for bad in (datetime(2026, 1, 1), DT(  # noqa: DTZ001 - naive on purpose
2026, 1, 1, tzinfo=UTC), "2026-01-01", 5):
        with pytest.raises(ValueError, match="^DRIVE_REVISION_INVALID$"):
            RevisionMeta("rev1", bad)
    for bad_id in ("", StrSub("r"), None, "r\x00"):
        with pytest.raises(ValueError, match="^DRIVE_REVISION_INVALID$"):
            RevisionMeta(bad_id)


def test_value_types_are_frozen_and_slotted():
    for obj in (IDENT, StartToken("t"), ChangesPage((), next_page_token="n"), _meta(), RevisionMeta("r")):
        assert not hasattr(obj, "__dict__")
        with pytest.raises((AttributeError, TypeError)):  # slots+frozen quirk raises TypeError on 3.14
            obj.zzz = 1
    with pytest.raises(AttributeError):
        StartToken("t").token = "u"


# --- errors --------------------------------------------------------------------------------------


def test_error_codes_are_exactly_the_fixed_set():
    assert {c.value for c in DriveErrorCode} == {
        "AUTH_REQUIRED", "INVALID_GRANT", "FORBIDDEN_HISTORY", "NOT_FOUND", "RATE_LIMITED",
        "TRANSIENT", "SCOPE_EPOCH_STALE"}


def test_port_error_carries_only_code_and_survives_pickle():
    err = DrivePortError(DriveErrorCode.RATE_LIMITED)
    assert err.code is DriveErrorCode.RATE_LIMITED and str(err) == "RATE_LIMITED"
    assert err.args == ("RATE_LIMITED",)
    again = pickle.loads(pickle.dumps(err))
    assert again.code is DriveErrorCode.RATE_LIMITED
    # a hostile code never leaks and never raises: fixed TRANSIENT
    for bad in ("token=SECRET", None, StrSub("NOT_FOUND"), "NOT_FOUND"):
        e = DrivePortError(bad)
        assert e.code is DriveErrorCode.TRANSIENT and "SECRET" not in str(e) and str(e) == "TRANSIENT"


# --- fake behaviour ------------------------------------------------------------------------------


def _fake() -> FakeDrivePort:
    f = FakeDrivePort(scope_epoch=3, start_page_token="START-A")
    f.script_page("START-A", (_change("c1", "F1"),), next_page_token="P2")
    f.script_page("P2", (_change("c2", "F2"),), new_start_page_token="START-B")
    f.set_file(_meta("F1", shortcut_target="F2", head_revision_id="R2"))
    f.set_file(_meta("F2", drive_id="D1"))
    f.set_revisions("F1", (RevisionMeta("R1"), RevisionMeta("R2")))
    return f


async def test_fake_satisfies_port_and_walks_pages_with_exact_tokens():
    f = _fake()
    port: DrivePort = f
    assert (await port.get_start_page_token(IDENT, 3)).token == "START-A"
    p1 = await port.list_changes(IDENT, 3, "START-A")
    assert p1.next_page_token == "P2" and p1.new_start_page_token is None
    p2 = await port.list_changes(IDENT, 3, "P2")
    assert p2.new_start_page_token == "START-B" and p2.next_page_token is None
    meta = await port.get_file_meta(IDENT, 3, "F1")
    assert meta.shortcut_target == "F2" and meta.parents == ("P1",)
    assert [r.revision_id for r in await port.list_revisions(IDENT, 3, "F1")] == ["R1", "R2"]
    assert await port.list_revisions(IDENT, 3, "F2") == ()


async def test_call_log_records_order_counts_and_failed_calls():
    f = _fake()
    await f.get_start_page_token(IDENT, 3)
    await f.list_changes(IDENT, 3, "START-A")
    with pytest.raises(DrivePortError):
        await f.list_changes(IDENT, 3, "unknown")
    await f.get_file_meta(IDENT, 3, "F1")
    assert f.call_log == ("get_start_page_token", "list_changes", "list_changes", "get_file_meta")
    assert f.call_count == 4 and f.count("list_changes") == 2 and f.count("list_revisions") == 0
    assert isinstance(f.call_log, tuple)


async def test_unknown_token_file_and_case_variant_are_not_found():
    f = _fake()
    for coro in (f.list_changes(IDENT, 3, "start-a"), f.get_file_meta(IDENT, 3, "f1"),
                 f.list_revisions(IDENT, 3, "nope")):
        with pytest.raises(DrivePortError) as exc:
            await coro
        assert exc.value.code is DriveErrorCode.NOT_FOUND  # ids are case-exact


async def test_scope_epoch_mismatch_raises_stale_on_every_method_and_recovers_when_epoch_matches():
    f = _fake()
    calls = (
        lambda e: f.get_start_page_token(IDENT, e),
        lambda e: f.list_changes(IDENT, e, "START-A"),
        lambda e: f.get_file_meta(IDENT, e, "F1"),
        lambda e: f.list_revisions(IDENT, e, "F1"),
    )
    for call in calls:
        with pytest.raises(DrivePortError) as exc:
            await call(2)
        assert exc.value.code is DriveErrorCode.SCOPE_EPOCH_STALE
    f.set_scope_epoch(4)  # revoke/re-consent bumps the epoch: old epoch is stale, new one works
    with pytest.raises(DrivePortError) as exc:
        await f.get_start_page_token(IDENT, 3)
    assert exc.value.code is DriveErrorCode.SCOPE_EPOCH_STALE
    assert (await f.get_start_page_token(IDENT, 4)).token == "START-A"


@pytest.mark.parametrize("epoch", [True, IntSub(3), "3", None, -1, 3.0, 2**70])
async def test_hostile_epoch_is_stale_never_another_exception(epoch):
    f = _fake()
    with pytest.raises(DrivePortError) as exc:
        await f.get_start_page_token(IDENT, epoch)
    assert exc.value.code is DriveErrorCode.SCOPE_EPOCH_STALE


@pytest.mark.parametrize("ident", [None, "account:a", object(), ("account:a", "t", "c")])
async def test_hostile_identity_is_auth_required(ident):
    f = _fake()
    with pytest.raises(DrivePortError) as exc:
        await f.list_changes(ident, 3, "START-A")
    assert exc.value.code is DriveErrorCode.AUTH_REQUIRED


@pytest.mark.parametrize("tok", ["", None, 5, StrSub("START-A"), "START-A\x00", "x" * 5000, [], b"START-A"])
async def test_hostile_tokens_and_file_ids_are_not_found(tok):
    f = _fake()
    for call in (f.list_changes, f.get_file_meta, f.list_revisions):
        with pytest.raises(DrivePortError) as exc:
            await call(IDENT, 3, tok)
        assert exc.value.code is DriveErrorCode.NOT_FOUND


@pytest.mark.parametrize("code", list(DriveErrorCode))
async def test_forced_error_maps_to_fixed_code_once_then_recovers(code):
    f = _fake()
    f.force_error("get_file_meta", code)
    with pytest.raises(DrivePortError) as exc:
        await f.get_file_meta(IDENT, 3, "F1")
    assert exc.value.code is code and str(exc.value) == code.value
    assert (await f.get_file_meta(IDENT, 3, "F1")).file_id == "F1"
    assert f.count("get_file_meta") == 2


async def test_forced_error_after_and_unbounded_times():
    f = _fake()
    f.force_error("list_changes", DriveErrorCode.TRANSIENT, times=None, after=1)
    await f.list_changes(IDENT, 3, "START-A")  # first call skipped
    for _ in range(3):
        with pytest.raises(DrivePortError) as exc:
            await f.list_changes(IDENT, 3, "START-A")
        assert exc.value.code is DriveErrorCode.TRANSIENT
    await f.get_start_page_token(IDENT, 3)  # other methods unaffected
    f.clear_forced_errors()
    await f.list_changes(IDENT, 3, "START-A")


@pytest.mark.parametrize(("status", "text", "code"), [
    (400, "invalid_grant: Token has been expired or revoked.", DriveErrorCode.INVALID_GRANT),
    (401, "invalid_grant", DriveErrorCode.INVALID_GRANT),
    (401, "unauthorized", DriveErrorCode.AUTH_REQUIRED),
    (403, "insufficientFilePermissions", DriveErrorCode.FORBIDDEN_HISTORY),
    (404, "File not found: F1", DriveErrorCode.NOT_FOUND),
    (429, "rateLimitExceeded", DriveErrorCode.RATE_LIMITED),
    (500, "backendError", DriveErrorCode.TRANSIENT),
    (400, "other", DriveErrorCode.TRANSIENT),
])
async def test_provider_response_text_is_never_echoed(status, text, code):
    f = _fake()
    f.force_provider_response("list_changes", status, text + " access_token=SECRET-TOKEN")
    with pytest.raises(DrivePortError) as exc:
        await f.list_changes(IDENT, 3, "START-A")
    err = exc.value
    assert err.code is code
    blob = f"{err!s}|{err!r}|{err.args}"
    assert "SECRET" not in blob and "access_token" not in blob and text not in blob
    assert err.__cause__ is None and err.__context__ is None


async def test_history_forbidden_and_hide_new_children():
    f = _fake()
    f.history_forbidden = True
    with pytest.raises(DrivePortError) as exc:
        await f.list_revisions(IDENT, 3, "F1")
    assert exc.value.code is DriveErrorCode.FORBIDDEN_HISTORY
    assert (await f.get_file_meta(IDENT, 3, "F1")).file_id == "F1"  # current metadata still readable

    f.set_file(_meta("NEW"), new_child=True)
    f.script_page("PN", (_change("c9", "NEW"), _change("c8", "F1")), new_start_page_token="S9")
    assert (await f.get_file_meta(IDENT, 3, "NEW")).file_id == "NEW"  # default: visible
    f.hide_new_children = True
    with pytest.raises(DrivePortError) as exc:
        await f.get_file_meta(IDENT, 3, "NEW")
    assert exc.value.code is DriveErrorCode.NOT_FOUND
    page = await f.list_changes(IDENT, 3, "PN")
    assert [c.file_id for c in page.changes] == ["F1"] and page.new_start_page_token == "S9"
    assert (await f.get_file_meta(IDENT, 3, "F1")).file_id == "F1"  # older files unaffected


async def test_hook_after_n_calls_scripts_changes_between_calls_and_fires_once():
    f = _fake()
    seen: list[int] = []

    def hook(fake: FakeDrivePort) -> None:
        seen.append(fake.call_count)
        fake.script_page("START-A", (_change("c1", "F1"), _change("late", "FLATE")), next_page_token="P2")

    f.run_after_calls(2, hook)
    first = await f.list_changes(IDENT, 3, "START-A")
    assert [c.change_id for c in first.changes] == ["c1"]
    await f.get_start_page_token(IDENT, 3)  # 2nd call completes, hook fires after it
    assert seen == [2]
    second = await f.list_changes(IDENT, 3, "START-A")
    assert [c.change_id for c in second.changes] == ["c1", "late"]
    await f.get_start_page_token(IDENT, 3)
    assert seen == [2]


async def test_hook_fires_even_when_the_nth_call_fails():
    f = _fake()
    fired: list[bool] = []
    f.run_after_calls(1, lambda _f: fired.append(True))
    with pytest.raises(DrivePortError):
        await f.list_changes(IDENT, 99, "START-A")
    assert fired == [True]


def test_scripting_api_refuses_hostile_input_with_fixed_codes():
    f = FakeDrivePort()
    with pytest.raises(ValueError, match="^DRIVE_PAGE_TOKEN_INVALID$"):
        f.script_page("", (), next_page_token="x")
    with pytest.raises(ValueError, match="^PAGE_CONTINUATION_XOR_NEW_START_REQUIRED$"):
        f.script_page("T", ())
    with pytest.raises(ValueError, match="^DRIVE_FILE_META_INVALID$"):
        f.set_file("not a FileMeta")
    with pytest.raises(ValueError, match="^FORCED_ERROR_INVALID$"):
        f.force_error("delete_file", DriveErrorCode.TRANSIENT)
    with pytest.raises(ValueError, match="^FORCED_ERROR_INVALID$"):
        f.force_error("list_changes", "TRANSIENT")
    with pytest.raises(ValueError, match="^HOOK_INVALID$"):
        f.run_after_calls(0, print)
    with pytest.raises(ValueError, match="^SCOPE_EPOCH_INVALID$"):
        FakeDrivePort(scope_epoch=True)


async def test_returned_values_are_immutable_snapshots():
    f = _fake()
    meta = await f.get_file_meta(IDENT, 3, "F1")
    with pytest.raises(AttributeError):
        meta.name = "other"
    f.set_file(_meta("F1", name="Renamed"))
    assert meta.name == "My File.pdf"
    assert (await f.get_file_meta(IDENT, 3, "F1")).name == "Renamed"


# --- static structure ----------------------------------------------------------------------------

_FORBIDDEN_PARTS = ("write", "permission", "keep_forever", "keepforever", "create", "update",
                    "delete", "trash", "upload", "copy", "share", "revoke", "grant", "set_")
_FORBIDDEN_IMPORTS = ("httpx", "requests", "socket", "subprocess", "urllib", "http", "sqlite3",
                      "psycopg", "asyncpg", "aiohttp", "os", "pathlib", "business_ai_gateway.phase2.drive_http")


def _tree(mod) -> ast.Module:
    return ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))


def _imports(tree: ast.Module, pkg: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names.append(("." * node.level) + base)
            names += [f"{('.' * node.level) + base}.{a.name}" for a in node.names]
    return names


@pytest.mark.parametrize("mod", [drive_port, drive_fake])
def test_modules_import_nothing_forbidden(mod):
    names = _imports(_tree(mod), mod.__name__)
    assert names, "scan must see imports"
    for name in names:
        bare = name.lstrip(".")
        root = bare.split(".")[0]
        assert root not in _FORBIDDEN_IMPORTS, name
        assert bare not in _FORBIDDEN_IMPORTS, name
        assert "drive_http" not in bare, name
        low = bare.lower()
        assert "pdcc" not in low and "release1" not in low and "release_1" not in low, name
        # relative imports may only reach sibling phase2 modules
        if name.startswith("."):
            assert name.startswith(".") and not name.startswith(".."), name
    # absolute imports must be stdlib or this very package's phase2 modules
    for name in names:
        if not name.startswith("."):
            assert name.split(".")[0] in {"__future__", "unicodedata", "dataclasses", "datetime", "enum",
                                         "typing", "collections"}, name


def _port_methods(tree: ast.Module, cls: str) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    raise AssertionError(cls)


def test_port_protocol_has_exactly_the_four_read_methods():
    assert _port_methods(_tree(drive_port), "DrivePort") == [
        "get_start_page_token", "list_changes", "get_file_meta", "list_revisions"]
    public = {n for n in vars(DrivePort) if not n.startswith("_")}
    assert public == {"get_start_page_token", "list_changes", "get_file_meta", "list_revisions"}


def test_no_write_permission_or_keep_forever_method_anywhere():
    names: list[str] = []
    for mod in (drive_port, drive_fake):
        for node in ast.walk(_tree(mod)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(node.name)
    assert "get_file_meta" in names and "list_revisions" in names
    for name in names:
        if name.startswith("_"):
            continue
        low = name.lower()
        for part in _FORBIDDEN_PARTS:
            if part == "set_":
                continue  # fake scripting setters are test support, checked separately below
            assert part not in low, name
    # the fake's only port-facing coroutines are the four reads; everything else is scripting/observation
    fake_async = [n.name for n in ast.walk(_tree(drive_fake)) if isinstance(n, ast.AsyncFunctionDef)]
    assert fake_async == ["get_start_page_token", "list_changes", "get_file_meta", "list_revisions"]
    # the live fake object exposes no such attributes either
    for attr in dir(FakeDrivePort):
        low = attr.lower()
        assert not any(p in low for p in ("write", "permission", "keepforever", "keep_forever", "upload",
                                          "delete", "trash", "create", "update", "share")), attr
