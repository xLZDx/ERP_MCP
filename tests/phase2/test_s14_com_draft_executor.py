"""Functional acceptance for the S14 CREATE_DRAFT executor on hand-written FAKE COM objects only.

No real 1C, COM, database or docker. Run with:
    pytest -p no:cacheprovider -q tests/phase2/test_s14_com_draft_executor.py
"""
from __future__ import annotations

import dataclasses

import pytest

import erp_mcp_private_writer.com_draft_executor as ex
from erp_mcp_private_writer.com_draft_executor import (
    DraftDestinationSet,
    ExecutorRefusal,
    ExecutorResult,
    execute_create_draft,
)
from erp_mcp_private_writer.com_manifest import ComValueAssignment

ORG = "1111111a-1111-4111-8111-11111111111b"
CP = "22222222-2222-4222-8222-222222222222"
ITEM = "33333333-3333-4333-8333-333333333333"
DOC_ID = "99999999-9999-4999-8999-999999999999"
CHANGE_ID = "c" * 36
MANIFEST = "ab" * 32
SECRET = "SECRET-COM-ERROR-TEXT-XYZZY"
NUMBER = "SECRET-NUMBER-777"
QTY = "SECRET-QTY-555"
CONN_STRING = "Srvr=SECRET-HOST;Ref=SECRET-BASE"


class FakeRef:
    def __init__(self, log, key, empty=False, marked=False):
        self._log, self.key, self._empty, self._marked = log, key, empty, marked

    def __getattr__(self, name):
        if name == ex._IS_EMPTY:
            return lambda: self._empty
        if name == ex._DELETION_MARK:
            self._log.append(("read_mark", self.key))
            return self._marked
        raise AttributeError(name)


class FakeDocRef:
    def __init__(self, doc):
        self._doc = doc

    def __getattr__(self, name):
        if name == ex._UNIQUE_ID:
            def uid():
                if self._doc._fail_readback == "ref":
                    raise RuntimeError(SECRET)
                return DOC_ID
            return uid
        raise AttributeError(name)


class FakeRow:
    def __init__(self, log):
        object.__setattr__(self, "_log", log)

    def __setattr__(self, name, value):
        self._log.append(("row_set", name, value))


class FakeSection:
    def __init__(self, doc):
        self._doc = doc

    def __getattr__(self, name):
        if name == ex._ADD_ROW:
            def add():
                self._doc._log.append(("add_row",))
                object.__setattr__(self._doc, "_rows", self._doc._rows + 1)
                return FakeRow(self._doc._log)
            return add
        raise AttributeError(name)


class FakeDoc:
    def __init__(self, conn):
        d = object.__setattr__
        d(self, "_conn", conn)
        d(self, "_log", conn.log)
        d(self, "_rows", 0)
        d(self, "_fail_readback", conn.fail_readback)

    def __setattr__(self, name, value):
        if name == "Marker" and self._conn.fail_marker:
            raise RuntimeError(SECRET)
        if name == "Org" and self._conn.fail_header:
            raise RuntimeError(SECRET)
        self._log.append(("hdr_set", name, value))

    def __getattr__(self, name):
        if name == "Lines":
            return FakeSection(self)
        if name == ex._WRITE:
            def write(mode):
                self._log.append(("write", mode))
                self._conn.write_calls += 1
                if self._conn.fail_write:
                    raise RuntimeError(SECRET + CONN_STRING + NUMBER)
            return write
        if name == ex._REF:
            return FakeDocRef(self)
        if name == "TotalProp":
            if self._fail_readback == "total":
                raise RuntimeError(SECRET)
            return "123.45"
        if name in ("Post", "Posting", "Unpost"):
            pytest.fail("posting must never be reached")
        raise AttributeError(name)


class FakeDocManager:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        if name == ex._CREATE_DOCUMENT:
            def create():
                self._conn.log.append(("create",))
                if self._conn.fail_create:
                    raise RuntimeError(SECRET)
                return FakeDoc(self._conn)
            return create
        raise AttributeError(name)


class FakeCatalogManager:
    def __init__(self, conn, name):
        self._conn, self._name = conn, name

    def __getattr__(self, name):
        if name == ex._GET_REF:
            def get_ref(text):
                self._conn.log.append(("lookup", self._name, text))
                if text in self._conn.boom:
                    raise RuntimeError(SECRET)
                return self._conn.catalog_data.get(
                    (self._name, text), FakeRef(self._conn.log, text, empty=True))
            return get_ref
        raise AttributeError(name)


class _Namespace:
    def __init__(self, factory, allowed):
        self._factory, self._allowed = factory, allowed

    def __getattr__(self, name):
        if name not in self._allowed:
            raise AttributeError(name)
        return self._factory(name)


class _WriteModes:
    PLAIN = object()
    POSTING = object()

    def __getattr__(self, name):
        if name == ex._WRITE_MODE_PLAIN:
            return self.PLAIN
        if name == "Posting":
            return self.POSTING
        raise AttributeError(name)


class FakeConnection:
    def __init__(self):
        self.log = []
        self.write_calls = 0
        self.boom = set()
        self.fail_create = self.fail_header = self.fail_marker = False
        self.fail_write = False
        self.fail_readback = None
        self.modes = _WriteModes()
        self.catalog_data = {
            ("Orgs", ORG): FakeRef(self.log, ORG),
            ("Cps", CP): FakeRef(self.log, CP),
            ("Items", ITEM): FakeRef(self.log, ITEM),
        }

    def __getattr__(self, name):
        if name == ex._DOCUMENTS:
            return _Namespace(lambda n: FakeDocManager(self), {"Receipt"})
        if name == ex._CATALOGS:
            return _Namespace(lambda n: FakeCatalogManager(self, n), {"Orgs", "Cps", "Items"})
        if name == ex._WRITE_MODE_ENUM:
            return self.modes
        raise AttributeError(name)

    def __repr__(self):
        return CONN_STRING


DESTINATIONS = DraftDestinationSet(
    document_manager="Receipt",
    header_properties=(("h.org", "Org"), ("h.cp", "Cp"), ("h.number", "Number")),
    line_section="Lines",
    line_properties=(("l.item", "Item"), ("l.qty", "Qty")),
    references=(("h.org", "Orgs"), ("h.cp", "Cps"), ("l.item", "Items")),
    change_id_attribute="Marker",
    manifest_attribute="Hash",
    total_property="TotalProp",
)


def make_values(**overrides):
    base = {"h.org": ORG, "h.cp": CP, "h.number": NUMBER, "l.item": ITEM, "l.qty": QTY}
    base.update(overrides)
    return tuple(ComValueAssignment(p, "SetValue", "String", v) for p, v in base.items())


def run(conn, values=None, destinations=DESTINATIONS, change_id=CHANGE_ID, manifest=MANIFEST):
    return execute_create_draft(
        conn, make_values() if values is None else values, destinations,
        change_id=change_id, manifest_sha256=manifest)


def assert_clean(exc, *, extra=()):
    blob = " ".join([str(exc), repr(exc), repr(exc.__cause__), repr(exc.args)])
    for secret in (SECRET, NUMBER, QTY, ORG, CP, ITEM, CONN_STRING, "SECRET-HOST", *extra):
        assert secret not in blob
    assert str(exc) == exc.code
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_happy_path_order_and_single_plain_write():
    conn = FakeConnection()
    result = run(conn)
    assert result == ExecutorResult(document_ref=DOC_ID, document_total_text="123.45")
    kinds = [e[0] for e in conn.log]
    # references first (3 lookups + 3 mark reads), then create, header, row, markers, one write
    assert kinds == ["lookup", "read_mark", "lookup", "read_mark", "lookup", "read_mark",
                     "create", "hdr_set", "hdr_set", "hdr_set", "add_row", "row_set", "row_set",
                     "hdr_set", "hdr_set", "write"]
    hdr = [e for e in conn.log if e[0] == "hdr_set"]
    assert [h[1] for h in hdr] == ["Org", "Cp", "Number", "Marker", "Hash"]
    assert hdr[0][2] is conn.catalog_data[("Orgs", ORG)]
    assert hdr[1][2] is conn.catalog_data[("Cps", CP)]
    assert hdr[2][2] == NUMBER
    assert (hdr[3][2], hdr[4][2]) == (CHANGE_ID, MANIFEST)
    rows = [e for e in conn.log if e[0] == "row_set"]
    assert [r[1] for r in rows] == ["Item", "Qty"]
    assert rows[0][2] is conn.catalog_data[("Items", ITEM)]
    assert rows[1][2] == QTY
    assert conn.write_calls == 1
    assert conn.log[-1] == ("write", conn.modes.PLAIN)
    assert conn.log[-1][1] is not conn.modes.POSTING
    assert sum(1 for e in conn.log if e[0] == "add_row") == 1


def test_result_repr_has_no_values():
    assert NUMBER not in repr(run(FakeConnection()))


@pytest.mark.parametrize("bad", [
    ORG.upper(), "not-a-guid", "", "{" + ORG + "}", ORG.replace("-", ""), ORG + " ", None, 5,
])
def test_reference_not_guid_refused_before_create(bad):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"h.org": bad}))
    assert info.value.code == "COM_REFERENCE_NOT_GUID"
    assert info.value.outcome_unknown is False
    assert conn.write_calls == 0
    assert ("create",) not in conn.log
    assert_clean(info.value, extra=("not-a-guid",))


def test_reference_not_found():
    conn = FakeConnection()
    del conn.catalog_data[("Cps", CP)]
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_REFERENCE_NOT_FOUND", False)
    assert conn.write_calls == 0 and ("create",) not in conn.log
    assert_clean(info.value)


def test_reference_in_wrong_catalog_is_not_found():
    conn = FakeConnection()
    conn.catalog_data[("Cps", CP)] = FakeRef(conn.log, CP, empty=True)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert info.value.code == "COM_REFERENCE_NOT_FOUND"


def test_reference_deletion_marked():
    conn = FakeConnection()
    conn.catalog_data[("Items", ITEM)] = FakeRef(conn.log, ITEM, marked=True)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_REFERENCE_DELETION_MARKED", False)
    assert conn.write_calls == 0 and ("create",) not in conn.log
    assert_clean(info.value)


def test_reference_lookup_com_exception_is_not_outcome_unknown():
    conn = FakeConnection()
    conn.boom.add(CP)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_REFERENCE_LOOKUP_FAILED", False)
    assert conn.write_calls == 0
    assert_clean(info.value)


def test_duplicate_guid_in_two_references_is_looked_up_each_time():
    conn = FakeConnection()
    conn.catalog_data[("Cps", ORG)] = FakeRef(conn.log, ORG)
    run(conn, make_values(**{"h.cp": ORG}))
    assert [e for e in conn.log if e[0] == "lookup"].count(("lookup", "Orgs", ORG)) == 1
    assert ("lookup", "Cps", ORG) in conn.log
    assert conn.write_calls == 1


def test_duplicate_value_paths_refused():
    conn = FakeConnection()
    values = make_values() + (make_values()[0],)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, values)
    assert info.value.code == "COM_EXECUTOR_DESTINATION_MISMATCH"
    assert conn.log == []


def test_destination_mismatch_extra_value_before_com():
    conn = FakeConnection()
    values = make_values() + (ComValueAssignment("h.extra", "SetValue", "String", NUMBER),)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, values)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_EXECUTOR_DESTINATION_MISMATCH", False)
    assert conn.log == [] and conn.write_calls == 0
    assert_clean(info.value)


def test_destination_mismatch_missing_value_before_com():
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values()[:-1])
    assert info.value.code == "COM_EXECUTOR_DESTINATION_MISMATCH"
    assert conn.log == []


def test_values_must_be_tuple_of_assignments():
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, list(make_values()))
    assert info.value.code == "COM_EXECUTOR_DESTINATION_MISMATCH"
    with pytest.raises(ExecutorRefusal):
        run(conn, ("x",) * 5)
    assert conn.log == []


def test_destinations_must_be_the_reviewed_type():
    with pytest.raises(ExecutorRefusal) as info:
        run(FakeConnection(), destinations=object())
    assert info.value.code == "COM_EXECUTOR_DESTINATION_MISMATCH"


@pytest.mark.parametrize("change_id", ["c" * 35, "c" * 37, "", None])
def test_change_id_length_checked_before_com(change_id):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, change_id=change_id)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_MARKER_INVALID", False)
    assert conn.log == []


@pytest.mark.parametrize("manifest", ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "", None])
def test_manifest_hash_checked_before_com(manifest):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, manifest=manifest)
    assert info.value.code == "COM_MARKER_INVALID"
    assert conn.log == []


@pytest.mark.parametrize("flag,code", [
    ("fail_create", "COM_DOCUMENT_CREATE_FAILED"),
    ("fail_header", "COM_HEADER_SET_FAILED"),
    ("fail_marker", "COM_MARKER_SET_FAILED"),
])
def test_failures_before_write_leave_zero_writes(flag, code):
    conn = FakeConnection()
    setattr(conn, flag, True)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (code, False)
    assert conn.write_calls == 0
    assert_clean(info.value)


def test_unknown_document_manager_refused_before_write():
    conn = FakeConnection()
    dest = dataclasses.replace(DESTINATIONS, document_manager="Other")
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, destinations=dest)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_DOCUMENT_CREATE_FAILED", False)
    assert conn.write_calls == 0


def test_line_failure_before_write():
    conn = FakeConnection()
    dest = dataclasses.replace(DESTINATIONS, line_section="NoSuchSection")
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, destinations=dest)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_LINE_SET_FAILED", False)
    assert conn.write_calls == 0


def test_write_mode_unavailable_before_write():
    conn = FakeConnection()
    conn.modes = object()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_WRITE_MODE_UNAVAILABLE", False)
    assert conn.write_calls == 0


def test_write_exception_is_outcome_unknown_and_leaks_nothing():
    conn = FakeConnection()
    conn.fail_write = True
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert conn.write_calls == 1
    assert_clean(info.value)


@pytest.mark.parametrize("which", ["ref", "total"])
def test_readback_failure_is_outcome_unknown(which):
    conn = FakeConnection()
    conn.fail_readback = which
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert conn.write_calls == 1
    assert_clean(info.value)


@pytest.mark.parametrize("scenario", [
    lambda c: c.boom.add(ORG),
    lambda c: setattr(c, "fail_header", True),
    lambda c: setattr(c, "fail_write", True),
    lambda c: setattr(c, "fail_readback", "ref"),
    lambda c: c.catalog_data.pop(("Orgs", ORG)),
])
def test_no_refusal_message_contains_values(scenario):
    conn = FakeConnection()
    scenario(conn)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert_clean(info.value)


def test_posting_is_never_reached_on_happy_path():
    conn = FakeConnection()
    run(conn)
    assert all(e[0] != "write" or e[1] is conn.modes.PLAIN for e in conn.log)


@pytest.mark.parametrize("kwargs", [
    {"document_manager": ""},
    {"header_properties": ()},
    {"header_properties": (("h.org", "Org"), ("h.org", "Org2"))},
    {"line_properties": (("h.org", "X"),)},
    {"references": (("missing.path", "Orgs"),)},
    {"references": (("h.org", "Orgs"), ("h.org", "Cps"))},
    {"change_id_attribute": " "},
])
def test_destination_set_rejects_invalid_shapes(kwargs):
    with pytest.raises(ValueError) as info:
        dataclasses.replace(DESTINATIONS, **kwargs)
    assert str(info.value) == "COM_EXECUTOR_DESTINATIONS_INVALID"
