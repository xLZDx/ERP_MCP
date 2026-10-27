"""CREATE_DRAFT executor for the clone-only S14 qualification (fake-COM tested, not wired anywhere).

``execute_create_draft`` creates one new document object from a reviewed document manager, sets the
reviewed header and single-row line properties, stamps the change-id / manifest-hash markers and
calls the plain write exactly once. Destinations come only from a caller-built
``DraftDestinationSet`` (never from payload data). Refusals carry stable codes; messages never
contain values, identifiers, the connection string or COM error text. Posting is never called. Run
it on the STA worker; it does no logging.

Refusal hygiene: a refusal has no ``__cause__`` / ``__context__`` and the executor clears its own
locals that hold COM objects, ids or amounts when it exits (the tests prove this for the fake
objects created inside the call). The traceback frames, however, still reference the ``connection``
and ``values`` arguments, so the CALLER must drop the traceback (``exc.with_traceback(None)``)
before handing a refusal to another thread.

Dates: a Python datetime or ISO text must never be assigned (measured on the clone: ISO text is
stored as the empty date, and a Python datetime is converted with a shift). Every date, including
the document's own date, is built by 1C through a ``TypeDescription("Date")`` cast of a 14-digit
``YYYYMMDDHHMMSS`` text, the built value is checked with ``XMLString`` BEFORE the document is
created (``YYYY-MM-DDT00:00:00`` for dates, the assigned ``YYYY-MM-DDTHH:MM:SS`` for the document
date), and the 1C value is assigned. Date destinations must read back exactly
``YYYY-MM-DDT00:00:00``. The document's own date is compared by calendar day only (first 10
characters): the configuration controls its time of day on write. Measured on the clone: for
assigned times 00:00:00, 01:00:00, 04:30:00, 05:00:00, 12:00:00 and 23:59:59 the stored time was
always 07:00:00 and the calendar day was always kept (no midnight crossing).

Read-back: after the write the stored document is fetched afresh and EVERY assigned value is
compared, by destination type, with no cross-type equivalence:

* references: by identifier text; enumerations: by member name; dates: by ``XMLString`` text;
* paths listed in ``DraftDestinationSet.numbers``: the payload value is canonical decimal TEXT and
  the stored value must be an int, float or Decimal (never bool, str or None) that is finite and
  numerically equal (``Decimal(expected) == Decimal(stored)``);
* every other plain path (identity / free text): the payload value must be a str and the stored
  value must be exactly a str equal to it (leading zeros kept, no stripping, no coercion; a stored
  None or number never equals any text, including the empty text);
* constants: a bool must come back as the same bool, an int numerically, a str exactly;
* both markers, the row count, and that the stored document is neither posted nor marked for
  deletion. Only paths listed in the reviewed
``DraftDestinationSet.unverified_paths`` are skipped, and the result lists them. The total is
returned; it is compared only when the caller passes ``expected_total``. A read-back cannot prove
an assignment whose value equals the platform default (False, 0, empty text): such a field needs a
reviewed non-default value or must be listed in ``unverified_paths``.

Post-write failures: once the canonical document reference is known, every later failure carries
``document_ref``. KeyboardInterrupt / SystemExit raised in the post-write phase are converted into
the unknown-outcome refusal, so the caller must check for a pending interrupt afterwards. The
executor has no pre-write duplicate guard: a retry after ``outcome_unknown`` must first search for
a document by the change-id marker.

Measured to WORK on the clone in a real run: row access (``Count()`` / ``Get(0)``), the row count,
and the enumeration name read (``XMLString``). Not yet measured: the behavior of this executor
under the narrow (least-privilege) role.

Value types: ``value_type`` enforcement (string versus number versus enumeration) is a concern of
the reviewed binding set. A plain value must be a str; on a ``numbers`` path it must be canonical
decimal text. Anything else, including ``None``, numbers and date objects, is refused before COM
access.
"""
from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from functools import partial

from .com_manifest import ComValueAssignment

__all__ = [
    "DraftDestinationSet",
    "ExecutorRefusal",
    "ExecutorResult",
    "execute_create_draft",
]

# 1C names, written as unicode escapes to keep the source ASCII.
_DOCUMENTS = "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b"  # Documents
_CATALOGS = "\u0421\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0438"  # Catalogs
_CREATE_DOCUMENT = (  # CreateDocument
    "\u0421\u043e\u0437\u0434\u0430\u0442\u044c\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442")
_ADD_ROW = "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c"  # Add (tabular section row)
_WRITE = "\u0417\u0430\u043f\u0438\u0441\u0430\u0442\u044c"  # Write
_GET_REF = (  # GetRef (catalog manager, takes a 1C UUID object)
    "\u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c\u0421\u0441\u044b\u043b\u043a\u0443")
_GET_OBJECT = (  # GetObject (None for a phantom reference)
    "\u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c\u041e\u0431\u044a\u0435\u043a\u0442")
_IS_EMPTY = "\u041f\u0443\u0441\u0442\u0430\u044f"  # IsEmpty (reference)
_DELETION_MARK = (  # DeletionMark
    "\u041f\u043e\u043c\u0435\u0442\u043a\u0430\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u044f")
_REF = "\u0421\u0441\u044b\u043b\u043a\u0430"  # Ref (document reference property)
_UNIQUE_ID = (  # UUID: both the 1C type name (NewObject) and the reference method
    "\u0423\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0439"
    "\u0418\u0434\u0435\u043d\u0442\u0438\u0444\u0438\u043a\u0430\u0442\u043e\u0440")
_WRITE_MODE_ENUM = (  # DocumentWriteMode
    "\u0420\u0435\u0436\u0438\u043c\u0417\u0430\u043f\u0438\u0441\u0438"
    "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430")
_WRITE_MODE_PLAIN = "\u0417\u0430\u043f\u0438\u0441\u044c"  # Write (plain mode, not Posting)
_DOCUMENT_TOTAL = (  # DocumentAmount
    "\u0421\u0443\u043c\u043c\u0430\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430")
_ENUMERATIONS = "\u041f\u0435\u0440\u0435\u0447\u0438\u0441\u043b\u0435\u043d\u0438\u044f"  # Enumerations
_DOC_DATE = "\u0414\u0430\u0442\u0430"  # Date (the document's own date)
_COUNT = "\u041a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e"  # Count (tabular section)
_GET_ROW = "\u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c"  # Get (tabular section row by index)
_XML_STRING = "XML\u0421\u0442\u0440\u043e\u043a\u0430"  # XMLString (enumeration value name)
_TYPE_DESCRIPTION = "\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435\u0422\u0438\u043f\u043e\u0432"  # TypeDescription (builds 1C values)
_DATE_TYPE = "\u0414\u0430\u0442\u0430"  # Date (type name given to the type description)
_CAST_VALUE = "\u041f\u0440\u0438\u0432\u0435\u0441\u0442\u0438\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435"  # AdjustValue / cast text to the described type
_POSTED = "\u041f\u0440\u043e\u0432\u0435\u0434\u0435\u043d"  # Posted
_NUMBER = "\u041d\u043e\u043c\u0435\u0440"  # Number (document number, assigned by the platform)
_NEW_OBJECT = "NewObject"  # connector method building 1C values
_STRING = "String"  # connector method turning a 1C value into canonical text

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL_TEXT = re.compile(r"-?[0-9]+(\.[0-9]+)?\Z")
_ISO_DATE_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_DIGITS14_SHAPE = re.compile(r"[0-9]{14}\Z")
# 1C names the platform owns; a destination may not use them (compared case-insensitively).
_RESERVED_NAMES = frozenset(n.casefold() for n in (
    _DOC_DATE, _REF, _POSTED, _DELETION_MARK, _NUMBER))


class ExecutorRefusal(Exception):
    """Stable-code refusal; the message is the code only."""

    def __init__(self, code: str, outcome_unknown: bool = False,
                 document_ref: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown
        # Canonical UUID text of the written draft (never a business value); set only for
        # COM_WRITTEN_READBACK_MISMATCH so the caller can find the document. Not in str/args.
        self.document_ref = document_ref

    def __reduce__(self):
        return (ExecutorRefusal, (self.code, self.outcome_unknown, self.document_ref))


def _refusal(code: str, outcome_unknown: bool = False,
             document_ref: str | None = None) -> ExecutorRefusal:
    return ExecutorRefusal(code, outcome_unknown, document_ref).with_traceback(None)


def _name_ok(value: object) -> bool:
    return (type(value) is str and bool(value) and value == value.strip()
            and len(value) <= 128 and all(c.isprintable() for c in value))


def _pairs_ok(value: object) -> bool:
    return (type(value) is tuple and bool(value)
            and all(type(p) is tuple and len(p) == 2 and _name_ok(p[0]) and _name_ok(p[1])
                    for p in value))


def _constants_ok(value: object) -> bool:
    return (type(value) is tuple
            and all(type(p) is tuple and len(p) == 2 and _name_ok(p[0])
                    and type(p[1]) in (bool, int, str) for p in value))


def _canonical_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class DraftDestinationSet:
    """Reviewed destinations keyed by binding ``property_path``.

    ``header_properties`` / ``line_properties``: ((property_path, 1C property name), ...), set in
    the given order. ``references``: ((property_path, expected catalog manager name), ...); each
    path must also be a header or line destination. ``enumerations``: ((property_path,
    enumeration name), ...) with the same rules; the payload value is the enumeration member name
    and the executor assigns the enumeration object (never text). ``constants``:
    ((header 1C property name, bool|int|str), ...) reviewed constants set on the header, for
    example the "amount includes VAT" flag. All 1C property names (header, line, constants, both
    markers, total) must be pairwise distinct. ``unverified_paths``: reviewed property paths of
    plain (non-reference, non-enumeration) values that the read-back deliberately does NOT
    compare; it exists only for a field that cannot be read back and defaults to empty.
    ``dates``: property paths (header or line) whose payload value is an ISO date text
    ``YYYY-MM-DD``; they are built into 1C dates (never assigned as text) and read back as
    ``YYYY-MM-DDT00:00:00``. Unique, and disjoint from references, enumerations and
    ``unverified_paths``. ``numbers``: header or line paths whose payload value is canonical
    decimal text and whose stored value is compared numerically (unique, plain paths only:
    disjoint from references, enumerations, dates and ``unverified_paths``). Every other plain
    path is identity / free text and is compared as exact text.
    """

    document_manager: str
    header_properties: tuple[tuple[str, str], ...]
    line_section: str
    line_properties: tuple[tuple[str, str], ...]
    references: tuple[tuple[str, str], ...]
    change_id_attribute: str
    manifest_attribute: str
    total_property: str = _DOCUMENT_TOTAL
    enumerations: tuple[tuple[str, str], ...] = ()
    constants: tuple[tuple[str, bool | int | str], ...] = ()
    unverified_paths: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (_name_ok(self.document_manager) and _name_ok(self.line_section)
                and _name_ok(self.change_id_attribute) and _name_ok(self.manifest_attribute)
                and _name_ok(self.total_property)
                and _pairs_ok(self.header_properties) and _pairs_ok(self.line_properties)
                and (self.references == () or _pairs_ok(self.references))
                and (self.enumerations == () or _pairs_ok(self.enumerations))
                and _constants_ok(self.constants)):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        paths = [p for p, _ in self.header_properties] + [p for p, _ in self.line_properties]
        if len(paths) != len(set(paths)):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        ref_paths = [p for p, _ in self.references]
        if len(ref_paths) != len(set(ref_paths)) or not set(ref_paths) <= set(paths):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        enum_paths = [p for p, _ in self.enumerations]
        if (len(enum_paths) != len(set(enum_paths)) or not set(enum_paths) <= set(paths)
                or set(enum_paths) & set(ref_paths)):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        skipped = self.unverified_paths
        if (type(skipped) is not tuple or not all(_name_ok(x) for x in skipped)
                or len(skipped) != len(set(skipped)) or not set(skipped) <= set(paths)
                or set(skipped) & (set(ref_paths) | set(enum_paths))):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        date_paths = self.dates
        if (type(date_paths) is not tuple or not all(_name_ok(x) for x in date_paths)
                or len(date_paths) != len(set(date_paths)) or not set(date_paths) <= set(paths)
                or set(date_paths) & (set(ref_paths) | set(enum_paths) | set(skipped))):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        number_paths = self.numbers
        if (type(number_paths) is not tuple or not all(_name_ok(x) for x in number_paths)
                or len(number_paths) != len(set(number_paths))
                or not set(number_paths) <= set(paths)
                or set(number_paths) & (set(ref_paths) | set(enum_paths) | set(skipped)
                                        | set(date_paths))):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        names = ([n for _, n in self.header_properties] + [n for n, _ in self.constants]
                 + [n for _, n in self.line_properties]
                 + [self.change_id_attribute, self.manifest_attribute, self.total_property])
        folded = [n.casefold() for n in names]
        if len(folded) != len(set(folded)) or set(folded) & _RESERVED_NAMES:
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")

    def all_paths(self) -> frozenset[str]:
        return frozenset(p for p, _ in self.header_properties + self.line_properties)


@dataclass(frozen=True, slots=True)
class ExecutorResult:
    document_ref: str
    document_total_text: str
    # Reviewed paths the read-back did not verify (partial verification is visible to the caller).
    unverified_paths: tuple[str, ...] = ()


def _guarded(code: str, outcome_unknown: bool, call, document_ref: str | None = None):
    """Run ``call``; on any failure raise a refusal outside the handler (no context kept).

    With ``outcome_unknown`` the handler also catches BaseException: after the write boundary
    nothing may escape except the unknown-outcome refusal.
    """
    try:
        return call()
    except BaseException as caught:
        if not outcome_unknown and not isinstance(caught, Exception):
            raise
        failed = True
    if failed:
        refusal = _refusal(code, outcome_unknown, document_ref)
        document_ref = call = None  # the frame must not keep the id or the closure
        try:
            raise refusal
        finally:
            refusal = None


def _resolve_reference(connection: object, catalog_name: str, raw: object) -> object:
    if not _canonical_uuid(raw):
        raise _refusal("COM_REFERENCE_NOT_GUID")
    found = None
    ok = False
    try:
        def lookup() -> tuple[object, bool, object, object]:
            guid = getattr(connection, _NEW_OBJECT)(_UNIQUE_ID, raw)
            manager = getattr(getattr(connection, _CATALOGS), catalog_name)
            ref = getattr(manager, _GET_REF)(guid)
            exists = getattr(ref, _GET_OBJECT)() is not None
            empty = getattr(ref, _IS_EMPTY)() if exists else None
            marked = getattr(ref, _DELETION_MARK) if exists and empty is False else None
            return ref, exists, empty, marked

        found, exists, empty, marked = _guarded("COM_REFERENCE_LOOKUP_FAILED", False, lookup)
        if not exists or empty is not False:
            raise _refusal("COM_REFERENCE_NOT_FOUND")
        if marked is not False:
            raise _refusal("COM_REFERENCE_DELETION_MARKED")
        ok = True
        return found
    finally:
        if not ok:
            found = None


def _resolve_enumeration(connection: object, enum_name: str, member: object) -> object:
    if not _name_ok(member):
        raise _refusal("COM_ENUM_VALUE_NOT_FOUND")

    def lookup() -> object:
        value = getattr(getattr(getattr(connection, _ENUMERATIONS), enum_name), member)
        if value is None:
            raise ValueError
        name = getattr(connection, _XML_STRING)(value)
        if type(name) is not str or name != member:
            raise ValueError  # a dispatch object may resolve any name; only the real member passes
        return value

    return _guarded("COM_ENUM_VALUE_NOT_FOUND", False, lookup)


_EMPTY_DATE_DAYS = frozenset({"0001-01-01", "0100-01-01"})


def _date_text_ok(value: object) -> bool:
    """Strict ``YYYY-MM-DD`` that round-trips and is not an empty-date calendar day."""
    if type(value) is not str:
        return False
    try:
        return (datetime.date.fromisoformat(value).isoformat() == value
                and value not in _EMPTY_DATE_DAYS)
    except ValueError:
        return False


def _digits14(year: int, month: int, day: int, hour: int = 0, minute: int = 0,
              second: int = 0) -> str:
    return f"{year:04d}{month:02d}{day:02d}{hour:02d}{minute:02d}{second:02d}"


def _build_date(connection: object, digits: str, expected_xml: str) -> object:
    """Build a 1C date through the TypeDescription cast and verify it before it is used."""
    description = getattr(connection, _NEW_OBJECT)(_TYPE_DESCRIPTION, _DATE_TYPE)
    built = getattr(description, _CAST_VALUE)(digits)
    if built is None:
        raise ValueError
    text = getattr(connection, _XML_STRING)(built)
    if type(text) is not str or text != expected_xml:
        raise ValueError
    return built


def _decimal_of(value: object) -> Decimal | None:
    if type(value) is float:
        number = Decimal(repr(value))
    elif type(value) is int:
        number = Decimal(value)
    elif type(value) is Decimal:
        number = value
    else:
        return None
    return number if number.is_finite() else None


def _number_equal(expected_text: str, stored: object) -> bool:
    """Numeric comparison: the stored value must be an int, float or Decimal (never bool/str)."""
    if type(stored) not in (int, float, Decimal):
        return False
    found = _decimal_of(stored)
    return found is not None and found == Decimal(expected_text)


def _text_equal(expected: str, stored: object) -> bool:
    """Exact text comparison: no stripping, no coercion, None and numbers never equal text."""
    return type(stored) is str and stored == expected


def _total_text(value: object) -> str:
    if type(value) is float:
        number = Decimal(repr(value))
    elif type(value) is int:
        number = Decimal(value)
    elif type(value) is Decimal:
        number = value
    else:
        raise ValueError
    if not number.is_finite():
        raise ValueError
    return format(number, "f")


def execute_create_draft(
        connection: object, values: tuple[ComValueAssignment, ...],
        destinations: DraftDestinationSet, *, change_id: str, manifest_sha256: str,
        document_date: datetime.datetime, expected_total: str | None = None
        ) -> ExecutorResult:
    """Create and plainly write one draft document; see module docstring for the error contract."""
    if type(destinations) is not DraftDestinationSet:
        raise _refusal("COM_EXECUTOR_DESTINATION_MISMATCH")
    if (type(values) is not tuple
            or any(type(v) is not ComValueAssignment for v in values)):
        raise _refusal("COM_EXECUTOR_DESTINATION_MISMATCH")
    paths = [v.property_path for v in values]
    if len(paths) != len(set(paths)) or set(paths) != destinations.all_paths():
        raise _refusal("COM_EXECUTOR_DESTINATION_MISMATCH")
    if any(v.value is None for v in values):
        raise _refusal("COM_EXECUTOR_VALUE_INVALID")
    date_paths = frozenset(destinations.dates)
    catalog_of = dict(destinations.references)
    enum_of = dict(destinations.enumerations)
    skipped_paths = frozenset(destinations.unverified_paths)
    number_paths = frozenset(destinations.numbers)
    for v in values:
        path, value = v.property_path, v.value
        if path in date_paths:
            ok = _date_text_ok(value)
        elif path in catalog_of:
            ok = True  # a bad reference is refused by the GUID rule
        elif path in enum_of:
            ok = type(value) is not str or not value.startswith("_")
        elif path in number_paths:
            ok = type(value) is str and _DECIMAL_TEXT.fullmatch(value) is not None
        else:
            ok = type(value) is str
            if ok and path in skipped_paths:
                ok = (_ISO_DATE_SHAPE.fullmatch(value) is None
                      and _DIGITS14_SHAPE.fullmatch(value) is None)
        if not ok:
            raise _refusal("COM_EXECUTOR_VALUE_INVALID")
    if expected_total is not None and (
            type(expected_total) is not str or _DECIMAL_TEXT.fullmatch(expected_total) is None):
        raise _refusal("COM_EXECUTOR_VALUE_INVALID")
    if (type(document_date) is not datetime.datetime or document_date.tzinfo is not None
            or document_date.date().isoformat() in _EMPTY_DATE_DAYS):
        raise _refusal("COM_EXECUTOR_DOCUMENT_DATE_INVALID")
    if not _canonical_uuid(change_id):
        raise _refusal("COM_MARKER_INVALID")
    if type(manifest_sha256) is not str or _HEX64.fullmatch(manifest_sha256) is None:
        raise _refusal("COM_MARKER_INVALID")

    by_path = {v.property_path: v for v in values}
    line_paths = frozenset(p for p, _ in destinations.line_properties)
    resolved: dict[str, object] | None = {}
    document = row = mode = ref_id = total = new_ref = own_date = None
    own_digits = _digits14(document_date.year, document_date.month, document_date.day,
                           document_date.hour, document_date.minute, document_date.second)
    own_day = document_date.date().isoformat()
    own_xml = document_date.replace(microsecond=0).isoformat()
    try:
        # 1. Resolve references first (in value order); no document object exists yet.
        for v in values:
            catalog = catalog_of.get(v.property_path)
            if catalog is not None:
                resolved[v.property_path] = _resolve_reference(connection, catalog, v.value)
            elif v.property_path in enum_of:
                resolved[v.property_path] = _resolve_enumeration(
                    connection, enum_of[v.property_path], v.value)
            elif v.property_path in date_paths:
                code = ("COM_LINE_SET_FAILED" if v.property_path in line_paths
                        else "COM_HEADER_SET_FAILED")
                resolved[v.property_path] = _guarded(code, False, partial(
                    _build_date, connection, v.value.replace("-", "") + "000000",
                    v.value + "T00:00:00"))
        own_date = _guarded("COM_HEADER_SET_FAILED", False,
                            partial(_build_date, connection, own_digits, own_xml))

        def final(path: str) -> object:
            return resolved[path] if path in resolved else by_path[path].value

        # 2. Create the object, set header, add one row and set it, then the markers.
        def create() -> object:
            manager = getattr(getattr(connection, _DOCUMENTS), destinations.document_manager)
            return getattr(manager, _CREATE_DOCUMENT)()

        document = _guarded("COM_DOCUMENT_CREATE_FAILED", False, create)

        def set_header() -> None:
            setattr(document, _DOC_DATE, own_date)
            for path, name in destinations.header_properties:
                setattr(document, name, final(path))
            for name, constant in destinations.constants:
                setattr(document, name, constant)

        _guarded("COM_HEADER_SET_FAILED", False, set_header)

        def set_line() -> None:
            nonlocal row
            row = getattr(getattr(document, destinations.line_section), _ADD_ROW)()
            for path, name in destinations.line_properties:
                setattr(row, name, final(path))

        _guarded("COM_LINE_SET_FAILED", False, set_line)

        def set_markers() -> None:
            setattr(document, destinations.change_id_attribute, change_id)
            setattr(document, destinations.manifest_attribute, manifest_sha256)

        _guarded("COM_MARKER_SET_FAILED", False, set_markers)

        def fetch_mode() -> object:
            return getattr(getattr(connection, _WRITE_MODE_ENUM), _WRITE_MODE_PLAIN)

        mode = _guarded("COM_WRITE_MODE_UNAVAILABLE", False, fetch_mode)

        def stored_matches(stored: object) -> bool:
            if (getattr(stored, destinations.change_id_attribute) != change_id
                    or getattr(stored, destinations.manifest_attribute) != manifest_sha256):
                return False
            if getattr(stored, _POSTED) is not False or getattr(stored, _DELETION_MARK) is not False:
                return False
            stored_date = getattr(stored, _DOC_DATE)
            if stored_date is None:
                return False
            own_text = getattr(connection, _XML_STRING)(stored_date)
            if type(own_text) is not str or own_text[:10] != own_day:
                return False
            for name, constant in destinations.constants:
                stored_constant = getattr(stored, name)
                if type(constant) is bool:
                    if stored_constant is not constant:
                        return False
                elif type(constant) is int:
                    if not _number_equal(str(constant), stored_constant):
                        return False
                elif not _text_equal(constant, stored_constant):
                    return False
            section = getattr(stored, destinations.line_section)
            if getattr(section, _COUNT)() != 1:
                return False
            line_row = getattr(section, _GET_ROW)(0)
            for owner, properties in ((stored, destinations.header_properties),
                                      (line_row, destinations.line_properties)):
                for path, name in properties:
                    if path in skipped_paths:
                        continue
                    expected = by_path[path].value
                    stored_value = getattr(owner, name)
                    if path in catalog_of:
                        if stored_value is None:
                            return False
                        actual = getattr(connection, _STRING)(
                            getattr(stored_value, _UNIQUE_ID)())
                    elif path in enum_of:
                        if stored_value is None:
                            return False
                        actual = getattr(connection, _XML_STRING)(stored_value)
                    elif path in date_paths:
                        if stored_value is None:
                            return False
                        actual = getattr(connection, _XML_STRING)(stored_value)
                        expected = expected + "T00:00:00"
                    elif path in number_paths:
                        if not _number_equal(expected, stored_value):
                            return False
                        continue
                    else:
                        if not _text_equal(expected, stored_value):
                            return False
                        continue
                    if type(actual) is not str or actual != expected:
                        return False
            return True

        # 3. The write method is fetched and called inside the unknown-outcome boundary. Once the
        #    canonical reference is known, later failures carry it. The stored state is read back
        #    through a fresh object obtained from the new reference.
        def write_and_get_ref() -> str:
            nonlocal new_ref
            write = getattr(document, _WRITE)
            write(mode)
            new_ref = getattr(document, _REF)
            text = getattr(connection, _STRING)(getattr(new_ref, _UNIQUE_ID)())
            if not _canonical_uuid(text):
                raise ValueError
            return text

        ref_id = _guarded("COM_WRITE_OUTCOME_UNKNOWN", True, write_and_get_ref)

        def read_back() -> tuple[str, bool]:
            stored = getattr(new_ref, _GET_OBJECT)()
            if stored is None:
                raise ValueError
            total_text = _total_text(getattr(stored, destinations.total_property))
            ok = stored_matches(stored)
            if ok and expected_total is not None:
                ok = Decimal(total_text) == Decimal(expected_total)
            return total_text, ok

        total, matches = _guarded("COM_WRITE_OUTCOME_UNKNOWN", True, read_back, ref_id)
        if not matches:
            raise _refusal("COM_WRITTEN_READBACK_MISMATCH", True, ref_id)
        return ExecutorResult(document_ref=ref_id, document_total_text=total,
                              unverified_paths=destinations.unverified_paths)
    finally:
        resolved = document = row = mode = ref_id = total = new_ref = own_date = None
