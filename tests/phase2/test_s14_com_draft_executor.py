"""Functional acceptance for the S14 CREATE_DRAFT executor on hand-written STRICT FAKE COM objects.

No real 1C, COM, database or docker. The fakes reject every attribute name outside an explicit
schema, so a drifting executor fails instead of silently passing. Run with:
    pytest -p no:cacheprovider -q tests/phase2/test_s14_com_draft_executor.py
"""
from __future__ import annotations

import copy
import dataclasses
import datetime
import gc
import pickle
import weakref
from decimal import Decimal
from functools import partial
from typing import ClassVar

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
CP = "22222222-2222-4222-8222-22222222222c"
ITEM = "33333333-3333-4333-8333-33333333333d"
OTHER_CATALOG_ELEMENT = "44444444-4444-4444-8444-44444444444e"
DOC_ID = "99999999-9999-4999-8999-99999999999a"
CHANGE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
MANIFEST = "ab" * 32
SECRET = "SECRET-COM-ERROR-TEXT-XYZZY"
NUMBER = "SECRET-NUMBER-777"
QTY = "5550.555"
CONN_STRING = "Srvr=SECRET-HOST;Ref=SECRET-BASE"

# Real Russian posting member names the fake document must never be asked for.
POST_NAMES = {
    "\u041f\u0440\u043e\u0432\u0435\u0441\u0442\u0438",  # Post
    ("\u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c\u041f\u0440\u043e\u0432\u0435\u0434\u0435"
     "\u043d\u0438\u0435"),  # UndoPosting
    "Post", "Posting", "Unpost",
}


class FakeUuid:
    """What connection.NewObject returns (a CDispatch-like 1C UUID); str() is garbage."""

    def __init__(self, text):
        self.text = text

    def __str__(self):
        return "<COMObject garbage>"


class FakeDocUuid(FakeUuid):
    pass


ZERO_UUID = "00000000-0000-0000-0000-000000000000"


class FakeEnumValue:
    def __init__(self, name):
        self.name = name


EMPTY_ENUM = FakeEnumValue("")


class FakeDate:
    """Opaque 1C date built by the TypeDescription cast (14 digits YYYYMMDDHHMMSS)."""

    def __init__(self, text14):
        self.text14 = text14

    @property
    def xml(self):
        t = self.text14
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}T{t[8:10]}:{t[10:12]}:{t[12:14]}"


EMPTY_DATE = FakeDate("01000101000000")  # what 1C stores when a date cannot be taken
ZERO_DATE = FakeDate("00010101000000")


class FakeTypeDesc:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        if name == ex._CAST_VALUE:
            def cast(text14):
                conn = self._conn
                if type(text14) is not str or len(text14) != 14 or not text14.isdigit():
                    raise ValueError("cast needs 14 digits")
                if text14 in conn.date_build_fail_on:
                    raise RuntimeError(SECRET)
                conn.date_builds.append(text14)
                if text14 in conn.date_cast_empty_on:
                    return EMPTY_DATE
                return text14 if conn.date_as_text else FakeDate(text14)
            return cast
        raise AttributeError(name)


class FakeRef:
    """Catalog reference; exists=False models the real phantom (non-empty, mark False)."""

    def __init__(self, conn, key, exists=True, marked=False, track=False):
        self._conn, self.key, self._exists, self._marked = conn, key, exists, marked
        if track:
            conn.created.append(weakref.ref(self))
            conn.tracked_refs += 1

    def __getattr__(self, name):
        if name == ex._GET_OBJECT:
            def get_object():
                self._conn.log.append(("get_object", self.key))
                return object() if self._exists else None
            return get_object
        if name == ex._IS_EMPTY:
            return lambda: False
        if name == ex._UNIQUE_ID:
            return lambda: FakeDocUuid(self.key)
        if name == ex._DELETION_MARK:
            self._conn.log.append(("read_mark", self.key))
            return self._marked
        raise AttributeError(name)


class FakeEmptyRef(FakeRef):
    def __init__(self, conn):
        super().__init__(conn, ZERO_UUID)


class FakeStoredRow:
    REFS: ClassVar[set[str]] = {"Item"}

    def __init__(self, conn, attrs):
        self._conn, self._attrs = conn, attrs

    def __getattr__(self, name):
        if name in self._attrs:
            return self._attrs[name]
        if name in self.REFS:
            return FakeEmptyRef(self._conn)
        if name in ENUM_PROPS:
            return EMPTY_ENUM
        raise AttributeError(name)


class FakeStoredSection:
    def __init__(self, conn, rows):
        self._conn, self._rows = conn, rows

    def __getattr__(self, name):
        if name == ex._COUNT:
            return lambda: self._conn.row_count_override or len(self._rows)
        if name == ex._GET_ROW:
            return lambda index: FakeStoredRow(self._conn, self._rows[index])
        raise AttributeError(name)


class FakeStored:
    """The document as stored in the base (what Ref.GetObject() returns)."""

    REFS: ClassVar[set[str]] = {"Org", "Cp"}

    def __init__(self, conn, attrs, rows):
        self._conn, self._attrs, self._rows = conn, attrs, rows
        conn.created.append(weakref.ref(self))

    def __getattr__(self, name):
        conn = self._conn
        if name == "Lines":
            return FakeStoredSection(conn, self._rows)
        if name == "TotalProp":
            if conn.fail_readback == "total":
                raise RuntimeError(SECRET)
            return conn.total
        if conn.fail_readback == "stored" and name == "Org":
            raise RuntimeError(SECRET)
        if name == ex._POSTED:
            return conn.stored_posted
        if name == ex._DELETION_MARK:
            return conn.stored_marked
        if name in self._attrs:
            return self._attrs[name]
        if name in self.REFS:
            return FakeEmptyRef(conn)
        if name in ENUM_PROPS:
            return EMPTY_ENUM
        raise AttributeError(name)


class FakeDocRef:
    def __init__(self, doc):
        self._doc = doc

    def __getattr__(self, name):
        conn = self._doc._conn
        if name == ex._UNIQUE_ID:
            def uid():
                if conn.fail_readback == "ref":
                    raise RuntimeError(SECRET)
                return FakeDocUuid(DOC_ID)
            return uid
        if name == ex._GET_OBJECT:
            def get_object():
                if conn.stored_none:
                    return None
                return self._doc._stored
            return get_object
        raise AttributeError(name)


NUMERIC_PROPS = {"Qty", "Price", "Amount", "VatAmount"}
# What real 1C stores when it silently drops a value it cannot take (empty / zero / false).
COERCED = {"Number": "", "Qty": 0, "Price": 0, "Amount": 0, "VatAmount": 0, "InclVat": False,
           ex._DOC_DATE: None, "SupplierDate": EMPTY_DATE, "LineDate": EMPTY_DATE}
DATE_PROPS = {ex._DOC_DATE, "SupplierDate", "LineDate"}


def _store(conn, attrs, overrides):
    stored = {}
    for name, value in attrs.items():
        if name in conn.silent_coerce:
            value = COERCED[name]
        # Mimic real 1C: a text string assigned to an enumeration property stores EMPTY silently.
        elif name in ENUM_PROPS and type(value) is not FakeEnumValue:
            value = EMPTY_ENUM
        elif name in NUMERIC_PROPS and type(value) is str:
            value = float(value)  # numbers assigned as text are stored as numbers
        elif name in DATE_PROPS:
            if type(value) is not FakeDate:
                value = EMPTY_DATE  # text assigned to a date is stored as the empty date
            elif name == ex._DOC_DATE:
                # the configuration adjusts the time of day of the document's own date
                value = FakeDate(value.text14[:8] + conn.own_time)
        stored[name] = value
    stored.update(overrides)
    return stored


class FakeRow:
    ALLOWED: ClassVar[set[str]] = {
        "Item", "Qty", "Price", "Amount", "VatAmount", "VatRate", "LineDate"}

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_attrs", {})
        conn.created.append(weakref.ref(self))

    def __setattr__(self, name, value):
        if name not in self.ALLOWED:
            raise AttributeError(name)
        if isinstance(value, datetime.date):
            raise TypeError("a Python datetime must never be assigned")
        self._attrs[name] = value
        self._conn.log.append(("row_set", name, value))


class FakeSection:
    def __init__(self, doc):
        self._doc = doc

    def __getattr__(self, name):
        if name == ex._ADD_ROW:
            def add():
                conn = self._doc._conn
                conn.log.append(("add_row",))
                row = FakeRow(conn)
                self._doc._rows.append(row)
                return row
            return add
        raise AttributeError(name)


class FakeDoc:
    SETTABLE: ClassVar[set[str]] = {
        "Org", "Cp", "Number", "Kind", "InclVat", "Marker", "Hash", "SupplierDate",
        ex._DOC_DATE}

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_attrs", {})
        object.__setattr__(self, "_rows", [])
        object.__setattr__(self, "_stored", None)
        conn.created.append(weakref.ref(self))

    def __setattr__(self, name, value):
        self._conn.doc_names.add(name)
        if name not in self.SETTABLE:
            raise AttributeError(name)
        if isinstance(value, datetime.date):
            raise TypeError("a Python datetime must never be assigned")
        if name == "Marker" and self._conn.fail_marker:
            raise RuntimeError(SECRET)
        if name == "Org" and self._conn.fail_header:
            raise RuntimeError(SECRET)
        self._attrs[name] = value
        self._conn.log.append(("hdr_set", name, value))

    def __getattr__(self, name):
        conn = self._conn
        conn.doc_names.add(name)
        if name in POST_NAMES:
            pytest.fail("posting must never be reached")
        if name == "Lines":
            return FakeSection(self)
        if name == ex._WRITE:
            if conn.missing_write:
                raise AttributeError(name)

            def write(mode):
                conn.log.append(("write", mode))
                conn.write_calls += 1
                if ex._DOC_DATE not in self._attrs:
                    raise RuntimeError("Failed to save")  # real 1C behavior without a date
                if conn.fail_write:
                    raise conn.fail_write(SECRET + CONN_STRING + NUMBER)
                header = _store(conn, self._attrs, conn.override_header)
                rows = [_store(conn, r._attrs, conn.override_row) for r in self._rows]
                object.__setattr__(self, "_stored", FakeStored(conn, header, rows))
            return write
        if name == ex._REF:
            return FakeDocRef(self)
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
            def get_ref(guid):
                if type(guid) is not FakeUuid:
                    raise TypeError("GetRef needs a 1C UUID object")
                self._conn.log.append(("lookup", self._name, guid.text))
                if guid.text in self._conn.boom:
                    raise RuntimeError(SECRET)
                factory = self._conn.catalog_data.get((self._name, guid.text))
                if factory is not None:
                    return factory()
                # unknown GUID or an element of another catalog: non-empty phantom reference
                return FakeRef(self._conn, guid.text, exists=False, track=True)
            return get_ref
        raise AttributeError(name)


class _Namespace:
    def __init__(self, factory, allowed):
        self._factory, self._allowed = factory, allowed

    def __getattr__(self, name):
        if name not in self._allowed:
            raise AttributeError(name)
        return self._factory(name)


class _Permissive:
    """A dispatch-like namespace that resolves any name."""

    def __init__(self, factory):
        self._factory = factory

    def __getattr__(self, name):
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


ENUM_PROPS = {"Kind", "VatRate"}
ENUM_MEMBERS = {"Kinds": {"Purchase", "Return"}, "VatRates": {"Vat0", "Vat10", "Vat20"}}


class FakeConnection:
    def __init__(self):
        self.log = []
        self.created = []
        self.doc_names = set()
        self.write_calls = 0
        self.boom = set()
        self.enum_boom = set()
        self.fail_create = self.fail_header = self.fail_marker = False
        self.fail_write = None  # exception class raised by the write call
        self.fail_readback = None
        self.missing_write = False
        self.stored_none = False
        self.enum_as_str = False  # the enumeration lookup hands out plain text
        self.override_header = {}
        self.override_row = {}
        self.row_count_override = None
        self.string_override = None
        self.silent_coerce = set()
        self.date_builds = []
        self.date_as_text = False  # the cast "returns" plain text: the silent-empty mistake
        self.date_build_fail_on = set()
        self.own_time = "070000"
        self.xml_override = None
        self.total = 123.45
        self.modes = _WriteModes()
        self._enum_values = {}
        self.tracked_refs = 0
        self.xml_raise = None
        self.stored_posted = False
        self.stored_marked = False
        self.enum_dispatch_any = False  # an enumeration namespace that resolves any name
        self.date_cast_empty_on = set()
        # factories: every lookup creates a fresh tracked reference (held only by its user)
        self.catalog_data = {
            ("Orgs", ORG): partial(FakeRef, self, ORG, track=True),
            ("Cps", CP): partial(FakeRef, self, CP, track=True),
            ("Items", ITEM): partial(FakeRef, self, ITEM, track=True),
        }

    def enum_value(self, enum_name, member):
        if member in self.enum_boom:
            raise RuntimeError(SECRET)
        if self.enum_dispatch_any and member not in ENUM_MEMBERS.get(enum_name, ()):
            return FakeEnumValue("Other")
        if self.enum_as_str:
            return member
        return self._enum_values.setdefault((enum_name, member), FakeEnumValue(member))

    def NewObject(self, type_name, text):
        if type_name == ex._TYPE_DESCRIPTION:
            if text != ex._DATE_TYPE:
                raise AttributeError(text)
            return FakeTypeDesc(self)
        if type_name != ex._UNIQUE_ID:
            raise AttributeError(type_name)
        self.log.append(("new_object", text))
        return FakeUuid(text)

    def String(self, value):
        if type(value) is not FakeDocUuid:
            raise TypeError("String needs a 1C value")
        if self.string_override is not None:
            return self.string_override
        return value.text

    def XMLString(self, value):
        if type(value) not in (FakeEnumValue, FakeDate):
            raise TypeError("XMLString needs an enumeration or date value")
        if self.xml_raise is not None and self.write_calls:
            raise self.xml_raise
        if self.xml_override is not None and self.write_calls:
            return self.xml_override  # only the post-write read-back is overridden
        return value.xml if type(value) is FakeDate else value.name

    def __getattr__(self, name):
        if name == ex._DOCUMENTS:
            return _Namespace(lambda n: FakeDocManager(self), {"Receipt"})
        if name == ex._CATALOGS:
            return _Namespace(lambda n: FakeCatalogManager(self, n), {"Orgs", "Cps", "Items"})
        if name == ex._ENUMERATIONS and self.enum_dispatch_any:
            return _Permissive(lambda e: _Permissive(lambda m: self.enum_value(e, m)))
        if name == ex._ENUMERATIONS:
            return _Namespace(
                lambda e: _Namespace(lambda m: self.enum_value(e, m), ENUM_MEMBERS[e]),
                set(ENUM_MEMBERS))
        if name == ex._XML_STRING:
            return self.XMLString
        if name == ex._WRITE_MODE_ENUM:
            return self.modes
        raise AttributeError(name)

    def __repr__(self):
        return CONN_STRING


HEADER = (("h.org", "Org"), ("h.cp", "Cp"), ("h.number", "Number"), ("h.kind", "Kind"),
          ("h.sdate", "SupplierDate"))
LINE = (("l.item", "Item"), ("l.qty", "Qty"), ("l.price", "Price"), ("l.amount", "Amount"),
        ("l.vat_amount", "VatAmount"), ("l.vat", "VatRate"), ("l.ldate", "LineDate"))
DATE = datetime.datetime(2026, 10, 27)  # noqa: DTZ001 - naive by contract

DESTINATIONS = DraftDestinationSet(
    document_manager="Receipt",
    header_properties=HEADER,
    line_section="Lines",
    line_properties=LINE,
    references=(("h.org", "Orgs"), ("h.cp", "Cps"), ("l.item", "Items")),
    change_id_attribute="Marker",
    manifest_attribute="Hash",
    total_property="TotalProp",
    enumerations=(("h.kind", "Kinds"), ("l.vat", "VatRates")),
    constants=(("InclVat", True),),
    dates=("h.sdate", "l.ldate"),
)


def make_values(**overrides):
    base = {"h.org": ORG, "h.cp": CP, "h.number": NUMBER, "h.kind": "Purchase",
            "l.item": ITEM, "l.qty": QTY, "l.price": "10.50", "l.amount": "21.00",
            "l.vat_amount": "3.50", "l.vat": "Vat20", "h.sdate": "2026-10-20",
            "l.ldate": "2026-10-21"}
    base.update(overrides)
    return tuple(ComValueAssignment(p, "SetValue", "String", v) for p, v in base.items())


def run(conn, values=None, destinations=DESTINATIONS, change_id=CHANGE_ID, manifest=MANIFEST,
        document_date=DATE):
    return execute_create_draft(
        conn, make_values() if values is None else values, destinations,
        change_id=change_id, manifest_sha256=manifest, document_date=document_date)


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
    # per reference: new_object, lookup, get_object, read_mark; then create, date, header,
    # constant, row, markers, one write
    assert kinds == ["new_object", "lookup", "get_object", "read_mark"] * 3 + [
        "create", *["hdr_set"] * 7, "add_row", *["row_set"] * 7, "hdr_set", "hdr_set", "write"]
    hdr = [e for e in conn.log if e[0] == "hdr_set"]
    assert [h[1] for h in hdr] == [ex._DOC_DATE, "Org", "Cp", "Number", "Kind", "SupplierDate",
                                   "InclVat", "Marker", "Hash"]
    assert type(hdr[0][2]) is FakeDate and hdr[0][2].text14 == "20261027000000"
    assert type(hdr[5][2]) is FakeDate and hdr[5][2].text14 == "20261020000000"
    assert type(hdr[1][2]) is FakeRef and hdr[1][2].key == ORG
    assert type(hdr[2][2]) is FakeRef and hdr[2][2].key == CP
    assert hdr[3][2] == NUMBER
    assert type(hdr[4][2]) is FakeEnumValue and hdr[4][2].name == "Purchase"
    assert hdr[6][2] is True
    assert (hdr[7][2], hdr[8][2]) == (CHANGE_ID, MANIFEST)
    rows = [e for e in conn.log if e[0] == "row_set"]
    assert [r[1] for r in rows] == ["Item", "Qty", "Price", "Amount", "VatAmount", "VatRate",
                                    "LineDate"]
    assert type(rows[6][2]) is FakeDate and rows[6][2].text14 == "20261021000000"
    assert type(rows[0][2]) is FakeRef and rows[0][2].key == ITEM
    assert rows[1][2] == QTY
    assert (rows[2][2], rows[3][2], rows[4][2]) == ("10.50", "21.00", "3.50")
    assert type(rows[5][2]) is FakeEnumValue and rows[5][2].name == "Vat20"
    assert conn.write_calls == 1
    assert conn.log[-1] == ("write", conn.modes.PLAIN)
    assert conn.log[-1][1] is not conn.modes.POSTING
    assert sum(1 for e in conn.log if e[0] == "add_row") == 1


def test_document_is_asked_for_exactly_the_expected_names():
    conn = FakeConnection()
    run(conn)
    assert conn.doc_names == {ex._DOC_DATE, "Org", "Cp", "Number", "Kind", "SupplierDate",
                              "InclVat", "Marker",
                              "Hash", "Lines", ex._WRITE, ex._REF}
    assert not conn.doc_names & POST_NAMES


def test_result_repr_has_no_values():
    assert NUMBER not in repr(run(FakeConnection()))


@pytest.mark.parametrize("bad", [
    ORG.upper(), "not-a-guid", "", "{" + ORG + "}", ORG.replace("-", ""), ORG + " ", None, 5,
])
def test_reference_not_guid_refused_before_create(bad):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"h.org": bad}))
    # None is refused earlier as an invalid value; everything else is not a canonical GUID
    expected = "COM_EXECUTOR_VALUE_INVALID" if bad is None else "COM_REFERENCE_NOT_GUID"
    assert info.value.code == expected
    assert info.value.outcome_unknown is False
    assert conn.write_calls == 0
    assert ("create",) not in conn.log
    assert_clean(info.value, extra=("not-a-guid",))


def test_reference_unknown_guid_is_phantom_and_refused():
    conn = FakeConnection()
    del conn.catalog_data[("Cps", CP)]
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_REFERENCE_NOT_FOUND", False)
    assert ("get_object", CP) in conn.log
    assert ("read_mark", CP) not in conn.log
    assert conn.write_calls == 0 and ("create",) not in conn.log
    assert_clean(info.value)


def test_reference_from_another_catalog_is_phantom_and_refused():
    conn = FakeConnection()
    conn.catalog_data[("Items", OTHER_CATALOG_ELEMENT)] = partial(
        FakeRef, conn, OTHER_CATALOG_ELEMENT, track=True)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"h.cp": OTHER_CATALOG_ELEMENT}))  # looked up in "Cps"
    assert info.value.code == "COM_REFERENCE_NOT_FOUND"
    assert conn.write_calls == 0


def test_str_guid_passed_to_getref_would_raise_in_the_strict_fake():
    conn = FakeConnection()
    manager = getattr(conn, ex._CATALOGS).Orgs
    with pytest.raises(TypeError):
        getattr(manager, ex._GET_REF)(ORG)
    assert run(conn).document_ref == DOC_ID  # executor builds the UUID object itself


def test_reference_deletion_marked():
    conn = FakeConnection()
    conn.catalog_data[("Items", ITEM)] = partial(FakeRef, conn, ITEM, marked=True, track=True)
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
    conn.catalog_data[("Cps", ORG)] = partial(FakeRef, conn, ORG, track=True)
    run(conn, make_values(**{"h.cp": ORG}))
    assert ("lookup", "Orgs", ORG) in conn.log
    assert ("lookup", "Cps", ORG) in conn.log
    assert sum(1 for e in conn.log if e[0] == "new_object" and e[1] == ORG) == 2
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


@pytest.mark.parametrize("path", ["h.org", "h.number", "l.qty"])
def test_none_value_refused_before_com(path):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{path: None}))
    assert (info.value.code, info.value.outcome_unknown) == ("COM_EXECUTOR_VALUE_INVALID", False)
    assert conn.log == []
    assert_clean(info.value)


@pytest.mark.parametrize("value", [True, 0, 7, ""])
def test_other_value_types_are_passed_through(value):
    conn = FakeConnection()
    run(conn, make_values(**{"h.number": value}))
    number_sets = [e for e in conn.log if e[:2] == ("hdr_set", "Number")]
    assert number_sets[0][2] == value and type(number_sets[0][2]) is type(value)


@pytest.mark.parametrize("change_id", [
    "c" * 36, CHANGE_ID.upper(), CHANGE_ID[:-1], CHANGE_ID + "0", "", None,
    "{" + CHANGE_ID + "}", CHANGE_ID.replace("-", ""),
])
def test_change_id_must_be_canonical_lowercase_uuid_before_com(change_id):
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


@pytest.mark.parametrize("error", [RuntimeError, KeyboardInterrupt, SystemExit, GeneratorExit])
def test_write_exception_is_outcome_unknown_and_leaks_nothing(error):
    conn = FakeConnection()
    conn.fail_write = error
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert conn.write_calls == 1
    assert_clean(info.value)


def test_write_method_lookup_failure_is_inside_unknown_boundary():
    conn = FakeConnection()
    conn.missing_write = True
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert conn.write_calls == 0


@pytest.mark.parametrize("which", ["ref", "total"])
def test_readback_failure_is_outcome_unknown(which):
    conn = FakeConnection()
    conn.fail_readback = which
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert conn.write_calls == 1
    assert_clean(info.value)


@pytest.mark.parametrize("text", [DOC_ID.upper(), "garbage", "", DOC_ID.replace("-", "")])
def test_readback_ref_text_must_be_canonical_uuid(text):
    conn = FakeConnection()
    conn.string_override = text
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert conn.write_calls == 1


@pytest.mark.parametrize("total,expected", [
    (123.45, "123.45"), (5, "5"), (Decimal("1E+2"), "100"), (1e-05, "0.00001"),
    (Decimal("0.10"), "0.10"), (0, "0"), (-3.5, "-3.5"),
])
def test_total_is_returned_without_exponent(total, expected):
    conn = FakeConnection()
    conn.total = total
    result = run(conn)
    assert result.document_total_text == expected
    assert "e" not in result.document_total_text.lower()


@pytest.mark.parametrize("total", [
    True, False, "12.5", None, float("nan"), float("inf"), Decimal("NaN"), b"1", [1],
])
def test_total_of_other_types_is_outcome_unknown(total):
    conn = FakeConnection()
    conn.total = total
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert conn.write_calls == 1


@pytest.mark.parametrize("scenario", [
    lambda c: c.boom.add(ORG),
    lambda c: setattr(c, "fail_header", True),
    lambda c: setattr(c, "fail_write", RuntimeError),
    lambda c: setattr(c, "fail_readback", "ref"),
    lambda c: c.catalog_data.pop(("Orgs", ORG)),
])
def test_no_refusal_message_contains_values(scenario):
    conn = FakeConnection()
    scenario(conn)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert_clean(info.value)


@pytest.mark.parametrize("make", [
    lambda: ExecutorRefusal("COM_WRITE_OUTCOME_UNKNOWN", True),
    lambda: ExecutorRefusal("COM_REFERENCE_NOT_FOUND", False),
    lambda: ExecutorRefusal("COM_WRITTEN_READBACK_MISMATCH", True, DOC_ID),
])
def test_refusal_survives_copy_and_pickle(make):
    original = make()
    clones = [pickle.loads(pickle.dumps(original)), copy.copy(original),
              copy.deepcopy(original)]
    for clone in clones:
        assert type(clone) is ExecutorRefusal
        assert (clone.code, clone.outcome_unknown) == (original.code, original.outcome_unknown)
        assert clone.document_ref == original.document_ref
        assert str(clone) == original.code
        assert clone.args == (original.code,)
        assert DOC_ID not in str(clone) + repr(clone)


def _failing_scenarios():
    def write_fails(c):
        c.fail_write = RuntimeError

    def phantom(c):
        del c.catalog_data[("Items", ITEM)]

    def header_fails(c):
        c.fail_header = True

    def readback_fails(c):
        c.fail_readback = "total"

    def mismatch(c):
        c.silent_coerce = {"Number"}

    return [write_fails, phantom, header_fails, readback_fails, mismatch]


@pytest.mark.parametrize("scenario", _failing_scenarios())
def test_refusal_traceback_keeps_no_com_object_alive(scenario):
    conn = FakeConnection()
    scenario(conn)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    conn.log.clear()  # the log records assigned values and would keep references alive
    gc.collect()
    assert conn.tracked_refs > 0  # resolved catalog references were created and are tracked
    assert conn.created, "the scenario must have created trackable fake COM objects"
    alive = [r for r in conn.created if r() is not None]
    assert alive == []
    # the refusal itself is still held here, so any frame it references is still alive
    assert info.value.__traceback__ is not None
    # no frame below the test keeps a document id or an amount in a local variable
    frame_tb = info.value.__traceback__.tb_next
    while frame_tb is not None:
        for local in frame_tb.tb_frame.f_locals.values():
            assert local not in (DOC_ID, "123.45")
        frame_tb = frame_tb.tb_next


def test_posting_is_never_reached_on_happy_path():
    conn = FakeConnection()
    run(conn)
    assert all(e[0] != "write" or e[1] is conn.modes.PLAIN for e in conn.log)


@pytest.mark.parametrize("kwargs", [
    {"document_manager": ""},
    {"header_properties": ()},
    {"header_properties": (*HEADER, ("h.org", "Org2"))},
    {"line_properties": (*LINE, ("h.org", "X"))},
    {"references": (("missing.path", "Orgs"),)},
    {"references": (("h.org", "Orgs"), ("h.org", "Cps"))},
    {"change_id_attribute": " "},
    # enumerations
    {"enumerations": (("missing.path", "Kinds"),)},
    {"enumerations": (("h.kind", "Kinds"), ("h.kind", "Kinds2"))},
    {"enumerations": (("h.org", "Kinds"),)},  # also a reference
    {"enumerations": (("h.kind", ""),)},
    {"enumerations": (("h.kind", 5),)},
    # constants
    {"constants": (("InclVat", None),)},
    {"constants": (("InclVat", 1.5),)},
    {"constants": (("InclVat", [1]),)},
    {"constants": (("", True),)},
    {"constants": (("InclVat", True), ("InclVat", False))},
    {"constants": ("InclVat",)},
], ids=lambda kw: next(iter(kw)) + "=" + str(next(iter(kw.values())))[-30:])
def test_destination_set_rejects_invalid_shapes(kwargs):
    with pytest.raises(ValueError) as info:
        dataclasses.replace(DESTINATIONS, **kwargs)
    assert str(info.value) == "COM_EXECUTOR_DESTINATIONS_INVALID"


@pytest.mark.parametrize("kwargs", [
    {"header_properties": (("h.org", "Org"), ("h.cp", "Org"), *HEADER[2:])},
    {"line_properties": (("l.item", "Org"), *LINE[1:])},
    {"line_properties": (LINE[0], ("l.qty", "Item"), *LINE[2:])},
    {"line_properties": (*LINE[:5], ("l.vat", "Kind"), LINE[6])},
    {"line_properties": (*LINE[:5], ("l.vat", "Qty"), LINE[6])},
    {"line_properties": (*LINE[:6], ("l.ldate", "Item"))},
    {"line_properties": (*LINE[:6], ("l.ldate", "SupplierDate"))},
    {"change_id_attribute": "Org"},
    {"change_id_attribute": "Item"},
    {"manifest_attribute": "Marker"},
    {"manifest_attribute": "Qty"},
    {"total_property": "Org"},
    {"total_property": "Item"},
    {"total_property": "Marker"},
    {"total_property": "Hash"},
    {"constants": (("Org", True),)},
    {"constants": (("Item", True),)},
    {"constants": (("Marker", True),)},
    {"constants": (("Hash", True),)},
    {"constants": (("TotalProp", True),)},
], ids=lambda kw: next(iter(kw)) + "=" + str(next(iter(kw.values())))[-24:])
def test_destination_set_rejects_colliding_property_names(kwargs):
    with pytest.raises(ValueError) as info:
        dataclasses.replace(DESTINATIONS, **kwargs)
    assert str(info.value) == "COM_EXECUTOR_DESTINATIONS_INVALID"


def test_destination_set_with_no_enumerations_or_constants_is_valid():
    dest = dataclasses.replace(
        DESTINATIONS,
        header_properties=HEADER[:3], line_properties=LINE[:2], enumerations=(), constants=(),
        dates=())
    assert dest.enumerations == () and dest.constants == ()


def test_destination_set_accepts_int_and_str_constants():
    dataclasses.replace(DESTINATIONS, constants=(("InclVat", True), ("Flag", 3), ("Tag", "x")))


# ---- document date -------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "2026-10-27", datetime.date(2026, 10, 27), None, 20261027,
    datetime.datetime(2026, 10, 27, tzinfo=datetime.UTC),
])
def test_document_date_wrong_type_refused_before_com(bad):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, document_date=bad)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_EXECUTOR_DOCUMENT_DATE_INVALID", False)
    assert conn.log == [] and conn.write_calls == 0
    assert_clean(info.value)


def test_document_date_is_required_keyword():
    with pytest.raises(TypeError):
        execute_create_draft(FakeConnection(), make_values(), DESTINATIONS,
                             change_id=CHANGE_ID, manifest_sha256=MANIFEST)


def test_document_date_is_set_first_after_creation_and_is_stored():
    conn = FakeConnection()
    run(conn, document_date=datetime.datetime(2026, 1, 2, 3, 4, 5))  # noqa: DTZ001
    index = [e[0] for e in conn.log].index("create")
    first = conn.log[index + 1]
    assert first[:2] == ("hdr_set", ex._DOC_DATE)
    assert type(first[2]) is FakeDate and first[2].text14 == "20260102030405"


def test_the_fake_document_without_a_date_fails_on_write():
    conn = FakeConnection()
    doc = getattr(conn, ex._DOCUMENTS).Receipt
    doc = getattr(doc, ex._CREATE_DOCUMENT)()
    with pytest.raises(RuntimeError):
        getattr(doc, ex._WRITE)(conn.modes.PLAIN)


# ---- constants -----------------------------------------------------------------------------

def test_constant_is_set_on_the_header_before_the_row_and_the_write():
    conn = FakeConnection()
    run(conn)
    names = [e[1] if e[0] == "hdr_set" else e[0] for e in conn.log]
    assert names.index("InclVat") > names.index("Kind")
    assert names.index("InclVat") < names.index("add_row") < names.index("write")
    assert [e[2] for e in conn.log if e[:2] == ("hdr_set", "InclVat")] == [True]


def test_constant_value_is_taken_from_the_reviewed_set():
    conn = FakeConnection()
    dest = dataclasses.replace(DESTINATIONS, constants=(("InclVat", False),))
    run(conn, destinations=dest)
    assert [e[2] for e in conn.log if e[:2] == ("hdr_set", "InclVat")] == [False]


# ---- enumerations --------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["Nope", "", " Vat20", 5, True, "Vat20\n"])
def test_enum_missing_or_invalid_member_refused_before_create(value):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"l.vat": value}))
    assert (info.value.code, info.value.outcome_unknown) == ("COM_ENUM_VALUE_NOT_FOUND", False)
    assert ("create",) not in conn.log and conn.write_calls == 0
    assert_clean(info.value)


def test_enum_unknown_enumeration_name_refused():
    conn = FakeConnection()
    dest = dataclasses.replace(
        DESTINATIONS, enumerations=(("h.kind", "NoSuchEnum"), ("l.vat", "VatRates")))
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, destinations=dest)
    assert info.value.code == "COM_ENUM_VALUE_NOT_FOUND"
    assert conn.write_calls == 0 and ("create",) not in conn.log


def test_enum_member_from_another_enumeration_refused():
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"h.kind": "Vat20"}))
    assert info.value.code == "COM_ENUM_VALUE_NOT_FOUND"


def test_enum_lookup_exception_is_a_clean_refusal():
    conn = FakeConnection()
    conn.enum_boom.add("Vat10")
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"l.vat": "Vat10"}))
    assert (info.value.code, info.value.outcome_unknown) == ("COM_ENUM_VALUE_NOT_FOUND", False)
    assert_clean(info.value)


def test_enumeration_is_assigned_as_an_object_and_read_back_by_name():
    conn = FakeConnection()
    run(conn, make_values(**{"l.vat": "Vat10", "h.kind": "Return"}))
    assigned = {e[1]: e[2] for e in conn.log if e[0] in ("hdr_set", "row_set")}
    assert type(assigned["VatRate"]) is FakeEnumValue and assigned["VatRate"].name == "Vat10"
    assert type(assigned["Kind"]) is FakeEnumValue and assigned["Kind"].name == "Return"


def test_the_fake_mimics_silent_empty_enumeration_for_text():
    conn = FakeConnection()
    doc = getattr(conn, ex._DOCUMENTS).Receipt
    doc = getattr(doc, ex._CREATE_DOCUMENT)()
    setattr(doc, ex._DOC_DATE, FakeDate("20261027000000"))
    doc.Kind = "Purchase"  # text instead of the enumeration object: no error
    getattr(doc, ex._WRITE)(conn.modes.PLAIN)
    stored = getattr(getattr(doc, ex._REF), ex._GET_OBJECT)()
    assert stored.Kind is EMPTY_ENUM


def test_text_valued_enumeration_is_refused_before_create():
    conn = FakeConnection()
    conn.enum_as_str = True  # the lookup hands out text: XMLString of it is not a member name
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_ENUM_VALUE_NOT_FOUND", False)
    assert ("create",) not in conn.log and conn.write_calls == 0
    assert_clean(info.value)


# ---- read-back of the stored object -----------------------------------------------------------

def test_happy_readback_compares_without_mismatch():
    conn = FakeConnection()
    assert run(conn).document_ref == DOC_ID


@pytest.mark.parametrize("header,row,count", [
    ({"Org": "OTHER_REF"}, {}, None),
    ({"Cp": "EMPTY_REF"}, {}, None),
    ({"Org": "EMPTY_REF"}, {}, None),
    ({"Org": None}, {}, None),
    ({"Kind": "EMPTY_ENUM"}, {}, None),
    ({"Kind": "OTHER_ENUM"}, {}, None),
    ({"Marker": "00000000-0000-4000-8000-000000000000"}, {}, None),
    ({"Marker": None}, {}, None),
    ({"Hash": "ff" * 32}, {}, None),
    ({}, {"Item": "OTHER_REF"}, None),
    ({}, {"Item": "EMPTY_REF"}, None),
    ({}, {"VatRate": "EMPTY_ENUM"}, None),
    ({}, {"VatRate": "OTHER_ENUM"}, None),
    ({}, {}, 2),
], ids=lambda v: str(v))
def test_readback_mismatch_is_unknown_outcome(header, row, count):
    conn = FakeConnection()

    def make(spec):
        out = {}
        for key, kind in spec.items():
            if kind == "OTHER_REF":
                out[key] = FakeRef(conn, OTHER_CATALOG_ELEMENT)
            elif kind == "EMPTY_REF":
                out[key] = FakeEmptyRef(conn)
            elif kind == "EMPTY_ENUM":
                out[key] = EMPTY_ENUM
            elif kind == "OTHER_ENUM":
                out[key] = FakeEnumValue("Return" if key == "Kind" else "Vat0")
            else:
                out[key] = kind
        return out

    conn.override_header = make(header)
    conn.override_row = make(row)
    conn.row_count_override = count
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_WRITTEN_READBACK_MISMATCH", True)
    assert conn.write_calls == 1
    assert_clean(info.value)


def test_readback_object_missing_is_outcome_unknown():
    conn = FakeConnection()
    conn.stored_none = True
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)


def test_readback_comparison_error_stays_unknown_not_mismatch():
    conn = FakeConnection()
    conn.fail_readback = "stored"
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert_clean(info.value)


def test_total_comes_from_the_stored_object_and_is_not_compared():
    conn = FakeConnection()
    conn.total = 999
    assert run(conn).document_total_text == "999"


# ---- F1: every assigned value is verified on the stored object ---------------------------------

SILENT_FIELDS = ["Number", "Qty", "Price", "Amount", "VatAmount", "InclVat", ex._DOC_DATE,
                 "SupplierDate", "LineDate"]


@pytest.mark.parametrize("field", SILENT_FIELDS)
def test_silent_coercion_of_any_plain_field_is_a_mismatch(field):
    conn = FakeConnection()
    conn.silent_coerce = {field}
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_WRITTEN_READBACK_MISMATCH", True)
    assert info.value.document_ref == DOC_ID
    assert conn.write_calls == 1
    assert_clean(info.value)


@pytest.mark.parametrize("header,row", [
    ({"Number": "other"}, {}),
    ({"Number": ""}, {}),
    ({"Number": None}, {}),
    ({"Number": 5}, {}),
    ({"InclVat": False}, {}),
    ({"InclVat": 1}, {}),
    ({"InclVat": "True"}, {}),
    ({"InclVat": None}, {}),
    ({ex._DOC_DATE: FakeDate("20261028070000")}, {}),
    ({ex._DOC_DATE: None}, {}),
    ({ex._DOC_DATE: EMPTY_DATE}, {}),
    ({ex._DOC_DATE: ZERO_DATE}, {}),
    ({"SupplierDate": FakeDate("20261021000000")}, {}),
    ({"SupplierDate": FakeDate("20261020070000")}, {}),
    ({"SupplierDate": EMPTY_DATE}, {}),
    ({"SupplierDate": ZERO_DATE}, {}),
    ({"SupplierDate": None}, {}),
    ({}, {"LineDate": FakeDate("20261022000000")}),
    ({}, {"LineDate": EMPTY_DATE}),
    ({}, {"LineDate": None}),
    ({}, {"Qty": 1.0}),
    ({}, {"Qty": 0}),
    ({}, {"Qty": None}),
    ({}, {"Qty": "5550.555x"}),
    ({}, {"Price": 10.51}),
    ({}, {"Price": ""}),
    ({}, {"Amount": 21.01}),
    ({}, {"Amount": "21.0"}),  # text is never coerced: stored text must equal exactly
    ({}, {"VatAmount": None}),
    ({}, {"VatAmount": 3.51}),
    ({}, {"VatAmount": True}),
], ids=lambda v: str(v)[:40])
def test_stored_value_overrides_are_mismatches(header, row):
    conn = FakeConnection()
    conn.override_header = header
    conn.override_row = row
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_WRITTEN_READBACK_MISMATCH", True)
    assert info.value.document_ref == DOC_ID
    assert_clean(info.value)


@pytest.mark.parametrize("header,row", [
    ({}, {"Price": Decimal("10.5")}),
    ({}, {"Amount": 21}),
    ({}, {"Amount": Decimal(21)}),
    ({}, {"VatAmount": 3.5}),
    ({}, {"Qty": Decimal("5550.5550")}),
    ({"Number": NUMBER}, {}),
])
def test_equal_numbers_in_other_representations_are_accepted(header, row):
    conn = FakeConnection()
    conn.override_header = header
    conn.override_row = row
    assert run(conn).document_ref == DOC_ID


def test_enumeration_name_read_must_be_text():
    conn = FakeConnection()
    conn.xml_override = 5
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_WRITTEN_READBACK_MISMATCH", True)


def test_enumeration_name_read_must_equal_the_member():
    conn = FakeConnection()
    conn.xml_override = "Other"
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert info.value.code == "COM_WRITTEN_READBACK_MISMATCH"


# ---- unverified_paths -------------------------------------------------------------------------

def test_unverified_path_is_skipped_only_when_reviewed():
    conn = FakeConnection()
    conn.silent_coerce = {"Number"}
    with pytest.raises(ExecutorRefusal):
        run(conn)
    conn = FakeConnection()
    conn.silent_coerce = {"Number"}
    dest = dataclasses.replace(DESTINATIONS, unverified_paths=("h.number",))
    assert run(conn, destinations=dest).document_ref == DOC_ID


def test_unverified_paths_default_is_empty():
    assert DESTINATIONS.unverified_paths == ()


@pytest.mark.parametrize("paths", [
    ("missing.path",), ("h.number", "h.number"), ("h.org",), ("h.kind",), ("l.vat",), (5,),
    ["h.number"], ("",),
])
def test_unverified_paths_validation(paths):
    with pytest.raises(ValueError) as info:
        dataclasses.replace(DESTINATIONS, unverified_paths=paths)
    assert str(info.value) == "COM_EXECUTOR_DESTINATIONS_INVALID"


# ---- document_ref on the refusal ---------------------------------------------------------------

def test_mismatch_carries_only_the_document_ref_and_keeps_it_out_of_the_text():
    conn = FakeConnection()
    conn.silent_coerce = {"Qty"}
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    exc = info.value
    assert exc.document_ref == DOC_ID
    assert exc.args == ("COM_WRITTEN_READBACK_MISMATCH",)
    assert DOC_ID not in str(exc) + repr(exc) + repr(exc.args)
    assert_clean(exc)
    clone = pickle.loads(pickle.dumps(exc))
    assert clone.document_ref == DOC_ID and clone.outcome_unknown is True


@pytest.mark.parametrize("prepare,code", [
    (lambda c: setattr(c, "fail_write", RuntimeError), "COM_WRITE_OUTCOME_UNKNOWN"),
    (lambda c: c.boom.add(CP), "COM_REFERENCE_LOOKUP_FAILED"),
    (lambda c: setattr(c, "fail_header", True), "COM_HEADER_SET_FAILED"),
])
def test_document_ref_is_none_for_every_other_code(prepare, code):
    conn = FakeConnection()
    prepare(conn)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert info.value.code == code
    assert info.value.document_ref is None


def test_precondition_refusals_have_no_document_ref():
    with pytest.raises(ExecutorRefusal) as info:
        run(FakeConnection(), change_id="x")
    assert info.value.document_ref is None


# ---- dates ------------------------------------------------------------------------------------

def test_dates_are_built_by_the_conversion_and_no_python_datetime_is_assigned():
    conn = FakeConnection()
    run(conn, document_date=datetime.datetime(2026, 10, 27, 12, 34, 56, 789))  # noqa: DTZ001
    assert sorted(conn.date_builds) == ["20261020000000", "20261021000000", "20261027123456"]
    for entry in conn.log:
        for value in entry[1:]:
            assert not isinstance(value, datetime.date)
    assigned = {e[1]: e[2] for e in conn.log if e[0] in ("hdr_set", "row_set")}
    assert all(type(assigned[n]) is FakeDate for n in (ex._DOC_DATE, "SupplierDate", "LineDate"))


@pytest.mark.parametrize("text", ["2026-02-28", "2024-02-29", "1999-12-31", "2026-01-01"])
def test_valid_date_texts_are_accepted_and_read_back(text):
    conn = FakeConnection()
    run(conn, make_values(**{"h.sdate": text}))
    assert text.replace("-", "") + "000000" in conn.date_builds


@pytest.mark.parametrize("text", [
    "2026-13-01", "2026-10-32", "2026-02-30", "2023-02-29", "20261027", "2026-1-5",
    " 2026-10-27", "2026-10-27 ", "2026-10-27T00:00:00", "", "10/27/2026", "2026-10-27\n",
    5, True, "0001-01-01", "0100-01-01",
])
def test_invalid_date_texts_are_refused_before_com(text):
    conn = FakeConnection()
    for path in ("h.sdate", "l.ldate"):
        with pytest.raises(ExecutorRefusal) as info:
            run(conn, make_values(**{path: text}))
        assert (info.value.code, info.value.outcome_unknown) == (
            "COM_EXECUTOR_VALUE_INVALID", False)
        assert conn.log == [] and conn.date_builds == []
        assert_clean(info.value, extra=(str(text),) if text else ())


@pytest.mark.parametrize("bad", [
    datetime.datetime(1, 1, 1),  # noqa: DTZ001
    datetime.datetime(100, 1, 1, 5),  # noqa: DTZ001
])
def test_empty_date_calendar_day_is_refused_as_document_date(bad):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, document_date=bad)
    assert info.value.code == "COM_EXECUTOR_DOCUMENT_DATE_INVALID"
    assert conn.log == []


def test_strict_fake_rejects_python_datetimes():
    conn = FakeConnection()
    doc = getattr(conn, ex._DOCUMENTS).Receipt
    doc = getattr(doc, ex._CREATE_DOCUMENT)()
    with pytest.raises(TypeError):
        setattr(doc, ex._DOC_DATE, DATE)
    with pytest.raises(TypeError):
        doc.SupplierDate = datetime.date(2026, 10, 20)
    row = getattr(doc.Lines, ex._ADD_ROW)()
    with pytest.raises(TypeError):
        row.LineDate = DATE


def test_the_fake_stores_the_empty_date_for_text():
    conn = FakeConnection()
    doc = getattr(conn, ex._DOCUMENTS).Receipt
    doc = getattr(doc, ex._CREATE_DOCUMENT)()
    setattr(doc, ex._DOC_DATE, FakeDate("20261027000000"))
    doc.SupplierDate = "2026-10-27"  # ISO text: no error, stored empty
    getattr(doc, ex._WRITE)(conn.modes.PLAIN)
    stored = getattr(getattr(doc, ex._REF), ex._GET_OBJECT)()
    assert stored.SupplierDate is EMPTY_DATE


def test_conversion_returning_text_is_refused_before_create():
    conn = FakeConnection()
    conn.date_as_text = True  # the cast "returns" text: XMLString of it is not a 1C date
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_HEADER_SET_FAILED", False)
    assert ("create",) not in conn.log and conn.write_calls == 0
    assert_clean(info.value)


def test_document_date_time_of_day_difference_is_accepted_but_the_day_is_checked():
    conn = FakeConnection()
    conn.own_time = "123456"  # the configuration moved the time of day: same day is fine
    assert run(conn).document_ref == DOC_ID
    conn = FakeConnection()
    conn.override_header = {ex._DOC_DATE: FakeDate("20261026070000")}
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert info.value.code == "COM_WRITTEN_READBACK_MISMATCH"


def test_date_destination_with_a_time_of_day_is_a_mismatch():
    conn = FakeConnection()
    conn.override_row = {"LineDate": FakeDate("20261021000001")}
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert info.value.code == "COM_WRITTEN_READBACK_MISMATCH"


def test_stored_date_text_must_be_text():
    conn = FakeConnection()
    conn.xml_override = 20261027
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert info.value.code == "COM_WRITTEN_READBACK_MISMATCH"


@pytest.mark.parametrize("fail_digits,code", [
    ("20261027000000", "COM_HEADER_SET_FAILED"),
    ("20261020000000", "COM_HEADER_SET_FAILED"),
    ("20261021000000", "COM_LINE_SET_FAILED"),
])
def test_date_build_failure_maps_to_the_set_codes(fail_digits, code):
    conn = FakeConnection()
    conn.date_build_fail_on = {fail_digits}
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (code, False)
    assert conn.write_calls == 0
    assert_clean(info.value)


def test_broken_date_build_is_a_set_failure():
    conn = FakeConnection()
    conn.date_builds = None  # the fake cast would fail on append: stands for a broken build
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert info.value.code == "COM_HEADER_SET_FAILED"
    assert conn.write_calls == 0


def test_unverified_date_path_is_not_compared():
    conn = FakeConnection()
    conn.override_header = {"SupplierDate": EMPTY_DATE}
    with pytest.raises(ExecutorRefusal):
        run(conn)
    dest = dataclasses.replace(
        DESTINATIONS, dates=("l.ldate",), unverified_paths=("h.sdate",))
    conn = FakeConnection()
    conn.override_header = {"SupplierDate": EMPTY_DATE}
    # the value is a plain (unverified) value now and must not be date-shaped
    values = make_values(**{"h.sdate": "free text"})
    assert run(conn, values, destinations=dest).document_ref == DOC_ID


@pytest.mark.parametrize("dates", [
    ("missing.path",), ("h.sdate", "h.sdate"), ("h.org",), ("h.kind",), ("",), (5,),
    ["h.sdate"],
])
def test_dates_validation(dates):
    with pytest.raises(ValueError) as info:
        dataclasses.replace(DESTINATIONS, dates=dates)
    assert str(info.value) == "COM_EXECUTOR_DESTINATIONS_INVALID"


def test_dates_may_not_overlap_unverified_paths():
    with pytest.raises(ValueError) as info:
        dataclasses.replace(DESTINATIONS, unverified_paths=("h.sdate",))
    assert str(info.value) == "COM_EXECUTOR_DESTINATIONS_INVALID"


def test_dates_default_is_empty():
    dest = DraftDestinationSet(
        document_manager="Receipt", header_properties=HEADER[:3], line_section="Lines",
        line_properties=LINE[:2], references=(), change_id_attribute="Marker",
        manifest_attribute="Hash")
    assert dest.dates == ()


# ---- plain value types, unverified paths, result ----------------------------------------------

@pytest.mark.parametrize("bad", [
    datetime.datetime(2026, 10, 27),  # noqa: DTZ001
    datetime.date(2026, 10, 27), float("inf"), float("nan"), Decimal("NaN"), Decimal("Infinity"),
    ["x"], b"x", object(),
])
def test_plain_value_of_a_disallowed_type_is_refused_before_com(bad):
    conn = FakeConnection()
    values = list(make_values())
    index = [v.property_path for v in values].index("h.number")
    object.__setattr__(values[index], "value", bad)  # bypass the manifest type guard
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, tuple(values))
    assert (info.value.code, info.value.outcome_unknown) == ("COM_EXECUTOR_VALUE_INVALID", False)
    assert conn.log == []
    assert_clean(info.value)


@pytest.mark.parametrize("good", [1.5, Decimal("2.50"), 7, True, "text"])
def test_plain_value_of_an_allowed_type_is_assigned(good):
    conn = FakeConnection()
    values = list(make_values())
    index = [v.property_path for v in values].index("h.number")
    object.__setattr__(values[index], "value", good)
    run(conn, tuple(values))
    number = [e for e in conn.log if e[:2] == ("hdr_set", "Number")]
    assert number[0][2] == good and type(number[0][2]) is type(good)


@pytest.mark.parametrize("text", ["2026-10-27", "20261027123456", "00000000000000"])
def test_unverified_path_refuses_date_shaped_values(text):
    conn = FakeConnection()
    dest = dataclasses.replace(DESTINATIONS, unverified_paths=("h.number",))
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"h.number": text}), destinations=dest)
    assert info.value.code == "COM_EXECUTOR_VALUE_INVALID"
    assert conn.log == []


def test_verified_path_may_hold_date_shaped_text_but_unverified_other_text_is_fine():
    conn = FakeConnection()
    run(conn, make_values(**{"h.number": "2026-10-27"}))  # verified: compared exactly
    conn = FakeConnection()
    conn.silent_coerce = {"Number"}
    dest = dataclasses.replace(DESTINATIONS, unverified_paths=("h.number",))
    result = run(conn, destinations=dest)
    assert result.unverified_paths == ("h.number",)


def test_result_lists_no_unverified_paths_by_default():
    assert run(FakeConnection()).unverified_paths == ()


# ---- document time of day -----------------------------------------------------------------

@pytest.mark.parametrize("moment", [
    datetime.datetime(2026, 10, 27, 0, 0, 0),  # noqa: DTZ001
    datetime.datetime(2026, 10, 27, 23, 59, 59),  # noqa: DTZ001
    datetime.datetime(2026, 10, 27, 4, 30, 0),  # noqa: DTZ001
    datetime.datetime(2026, 10, 27, 12, 0, 0),  # noqa: DTZ001
])
def test_document_time_of_day_is_free_but_day_is_kept(moment):
    conn = FakeConnection()  # the fake always stores 07:00:00 on the same day
    run(conn, document_date=moment)
    assert moment.strftime("%Y%m%d%H%M%S") in conn.date_builds


def test_built_dates_are_verified_before_create():
    for digits, code in (("20261021000000", "COM_LINE_SET_FAILED"),
                         ("20261020000000", "COM_HEADER_SET_FAILED"),
                         ("20261027000000", "COM_HEADER_SET_FAILED")):
        conn = FakeConnection()
        conn.date_cast_empty_on = {digits}
        with pytest.raises(ExecutorRefusal) as info:
            run(conn)
        assert (info.value.code, info.value.outcome_unknown) == (code, False)
        assert ("create",) not in conn.log and conn.write_calls == 0
        assert_clean(info.value)


# ---- enumeration member names -------------------------------------------------------------

@pytest.mark.parametrize("member", ["_x", "__class__", "__doc__", "_Vat20"])
def test_enumeration_member_names_starting_with_underscore_are_refused(member):
    conn = FakeConnection()
    conn.enum_dispatch_any = True
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"l.vat": member}))
    assert (info.value.code, info.value.outcome_unknown) == ("COM_EXECUTOR_VALUE_INVALID", False)
    assert conn.log == []


def test_dispatch_namespace_resolving_any_name_is_caught_by_the_name_check():
    conn = FakeConnection()
    conn.enum_dispatch_any = True
    with pytest.raises(ExecutorRefusal) as info:
        run(conn, make_values(**{"l.vat": "NoSuchMember"}))
    assert (info.value.code, info.value.outcome_unknown) == ("COM_ENUM_VALUE_NOT_FOUND", False)
    assert ("create",) not in conn.log


def test_dispatch_namespace_with_real_members_still_works():
    conn = FakeConnection()
    conn.enum_dispatch_any = True
    assert run(conn).document_ref == DOC_ID


# ---- failures after the document reference is known -------------------------------------------

@pytest.mark.parametrize("prepare", [
    lambda c: setattr(c, "stored_none", True),
    lambda c: setattr(c, "total", "not a number"),
    lambda c: setattr(c, "fail_readback", "stored"),
    lambda c: setattr(c, "fail_readback", "total"),
])
def test_failures_after_the_reference_is_known_carry_document_ref(prepare):
    conn = FakeConnection()
    prepare(conn)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert info.value.document_ref == DOC_ID
    assert info.value.args == ("COM_WRITE_OUTCOME_UNKNOWN",)
    assert_clean(info.value)


@pytest.mark.parametrize("prepare", [
    lambda c: setattr(c, "fail_write", RuntimeError),
    lambda c: setattr(c, "fail_readback", "ref"),
    lambda c: setattr(c, "string_override", "garbage"),
    lambda c: setattr(c, "missing_write", True),
])
def test_failures_before_the_reference_is_known_have_no_document_ref(prepare):
    conn = FakeConnection()
    prepare(conn)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert info.value.code == "COM_WRITE_OUTCOME_UNKNOWN"
    assert info.value.document_ref is None


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_interrupt_after_the_reference_is_known_is_the_unknown_refusal_with_ref(error):
    conn = FakeConnection()
    conn.xml_raise = error  # raised by the read-back after the write
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_WRITE_OUTCOME_UNKNOWN", True)
    assert info.value.document_ref == DOC_ID


# ---- posted / deletion mark / expected total -----------------------------------------------------

@pytest.mark.parametrize("attr,value", [
    ("stored_posted", True), ("stored_posted", None), ("stored_posted", 0),
    ("stored_marked", True), ("stored_marked", None), ("stored_marked", 1),
])
def test_posted_or_deletion_marked_stored_document_is_a_mismatch(attr, value):
    conn = FakeConnection()
    setattr(conn, attr, value)
    with pytest.raises(ExecutorRefusal) as info:
        run(conn)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_WRITTEN_READBACK_MISMATCH", True)
    assert info.value.document_ref == DOC_ID
    assert_clean(info.value)


@pytest.mark.parametrize("expected", ["123.45", "123.450", "0123.45"])
def test_expected_total_matching_numerically_is_accepted(expected):
    conn = FakeConnection()
    assert run_with_total(conn, expected).document_total_text == "123.45"


def run_with_total(conn, expected):
    return execute_create_draft(
        conn, make_values(), DESTINATIONS, change_id=CHANGE_ID, manifest_sha256=MANIFEST,
        document_date=DATE, expected_total=expected)


@pytest.mark.parametrize("expected", ["123.46", "124", "-123.45", "0"])
def test_expected_total_mismatch_is_a_readback_mismatch(expected):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run_with_total(conn, expected)
    assert (info.value.code, info.value.outcome_unknown) == (
        "COM_WRITTEN_READBACK_MISMATCH", True)
    assert info.value.document_ref == DOC_ID


@pytest.mark.parametrize("expected", ["1e2", " 1", "1 ", "", "abc", "1,5", 5, "NaN", "1.", ".5",
                                      "+1", "Infinity", b"1"])
def test_invalid_expected_total_is_refused_before_com(expected):
    conn = FakeConnection()
    with pytest.raises(ExecutorRefusal) as info:
        run_with_total(conn, expected)
    assert (info.value.code, info.value.outcome_unknown) == ("COM_EXECUTOR_VALUE_INVALID", False)
    assert conn.log == []


def test_total_is_not_compared_without_expected_total():
    conn = FakeConnection()
    conn.total = 999
    assert run(conn).document_total_text == "999"


# ---- property names: case-insensitive uniqueness and reserved names --------------------------

@pytest.mark.parametrize("kwargs", [
    {"change_id_attribute": "org"},
    {"change_id_attribute": "ORG"},
    {"manifest_attribute": "kind"},
    {"total_property": "ITEM"},
    {"constants": (("inclvat", True), ("INCLVAT", False))},
    {"constants": (("org", True),)},
    {"line_properties": (("l.item", "item"), ("l.qty", "ITEM"), *LINE[2:])},
    {"header_properties": (("h.org", "Org"), ("h.cp", "oRG"), *HEADER[2:])},
])
def test_property_names_are_unique_case_insensitively(kwargs):
    with pytest.raises(ValueError) as info:
        dataclasses.replace(DESTINATIONS, **kwargs)
    assert str(info.value) == "COM_EXECUTOR_DESTINATIONS_INVALID"


RESERVED = [ex._DOC_DATE, ex._REF, ex._POSTED, ex._DELETION_MARK, ex._NUMBER]


@pytest.mark.parametrize("name", RESERVED + [r.upper() for r in RESERVED])
@pytest.mark.parametrize("position", [
    "header", "line", "constant", "change_id", "manifest", "total"])
def test_reserved_platform_names_are_refused(position, name):
    if position == "header":
        kwargs = {"header_properties": (("h.org", name), *HEADER[1:])}
    elif position == "line":
        kwargs = {"line_properties": (("l.item", name), *LINE[1:])}
    elif position == "constant":
        kwargs = {"constants": ((name, True),)}
    elif position == "change_id":
        kwargs = {"change_id_attribute": name}
    elif position == "manifest":
        kwargs = {"manifest_attribute": name}
    else:
        kwargs = {"total_property": name}
    with pytest.raises(ValueError) as info:
        dataclasses.replace(DESTINATIONS, **kwargs)
    assert str(info.value) == "COM_EXECUTOR_DESTINATIONS_INVALID"
