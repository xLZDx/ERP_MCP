"""CREATE_DRAFT executor for the clone-only S14 qualification (fake-COM tested, not wired anywhere).

``execute_create_draft`` creates one new document object from a reviewed document manager, sets the
reviewed header and single-row line properties, stamps the change-id / manifest-hash markers and
calls the plain write exactly once. Destinations come only from a caller-built
``DraftDestinationSet`` (never from payload data). Refusals carry stable codes; messages never
contain values, identifiers, the connection string or COM error text, and no COM object stays
reachable from a raised refusal. Posting is never called. Run it on the STA worker; it does no
logging.

Value types: ``value_type`` enforcement (string versus number versus enumeration) is a concern of
the reviewed binding set. The executor assigns values as given and only refuses ``None``.
"""
from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

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
_NEW_OBJECT = "NewObject"  # connector method building 1C values
_STRING = "String"  # connector method turning a 1C value into canonical text

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ExecutorRefusal(Exception):
    """Stable-code refusal; the message is the code only."""

    def __init__(self, code: str, outcome_unknown: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown

    def __reduce__(self):
        return (ExecutorRefusal, (self.code, self.outcome_unknown))


def _refusal(code: str, outcome_unknown: bool = False) -> ExecutorRefusal:
    return ExecutorRefusal(code, outcome_unknown).with_traceback(None)


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
    markers, total) must be pairwise distinct.
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
        names = ([n for _, n in self.header_properties] + [n for n, _ in self.constants] + [n for _, n in self.line_properties]
                 + [self.change_id_attribute, self.manifest_attribute, self.total_property])
        if len(names) != len(set(names)):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")

    def all_paths(self) -> frozenset[str]:
        return frozenset(p for p, _ in self.header_properties + self.line_properties)


@dataclass(frozen=True, slots=True)
class ExecutorResult:
    document_ref: str
    document_total_text: str


def _guarded(code: str, outcome_unknown: bool, call):
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
        raise _refusal(code, outcome_unknown)


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
        return value

    return _guarded("COM_ENUM_VALUE_NOT_FOUND", False, lookup)


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
        document_date: datetime.datetime
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
    if type(document_date) is not datetime.datetime or document_date.tzinfo is not None:
        raise _refusal("COM_EXECUTOR_DOCUMENT_DATE_INVALID")
    if not _canonical_uuid(change_id):
        raise _refusal("COM_MARKER_INVALID")
    if type(manifest_sha256) is not str or _HEX64.fullmatch(manifest_sha256) is None:
        raise _refusal("COM_MARKER_INVALID")

    by_path = {v.property_path: v for v in values}
    catalog_of = dict(destinations.references)
    enum_of = dict(destinations.enumerations)
    resolved: dict[str, object] | None = {}
    document = row = mode = None
    try:
        # 1. Resolve references first (in value order); no document object exists yet.
        for v in values:
            catalog = catalog_of.get(v.property_path)
            if catalog is not None:
                resolved[v.property_path] = _resolve_reference(connection, catalog, v.value)
            elif v.property_path in enum_of:
                resolved[v.property_path] = _resolve_enumeration(
                    connection, enum_of[v.property_path], v.value)

        def final(path: str) -> object:
            return resolved[path] if path in resolved else by_path[path].value

        # 2. Create the object, set header, add one row and set it, then the markers.
        def create() -> object:
            manager = getattr(getattr(connection, _DOCUMENTS), destinations.document_manager)
            return getattr(manager, _CREATE_DOCUMENT)()

        document = _guarded("COM_DOCUMENT_CREATE_FAILED", False, create)

        def set_header() -> None:
            setattr(document, _DOC_DATE, document_date)
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
            section = getattr(stored, destinations.line_section)
            if getattr(section, _COUNT)() != 1:
                return False
            line_row = getattr(section, _GET_ROW)(0)
            for owner, properties in ((stored, destinations.header_properties),
                                      (line_row, destinations.line_properties)):
                for path, name in properties:
                    expected = by_path[path].value
                    if path in catalog_of:
                        stored_value = getattr(owner, name)
                        if stored_value is None:
                            return False
                        actual = getattr(connection, _STRING)(
                            getattr(stored_value, _UNIQUE_ID)())
                    elif path in enum_of:
                        stored_value = getattr(owner, name)
                        if stored_value is None:
                            return False
                        actual = getattr(connection, _XML_STRING)(stored_value)
                    else:
                        continue
                    if type(actual) is not str or actual != expected:
                        return False
            return True

        # 3. The write method is fetched and called inside the unknown-outcome boundary; the
        #    stored state is read back through a fresh object obtained from the new reference.
        def write_and_read_back() -> tuple[str, str, bool]:
            write = getattr(document, _WRITE)
            write(mode)
            new_ref = getattr(document, _REF)
            text = getattr(connection, _STRING)(getattr(new_ref, _UNIQUE_ID)())
            if not _canonical_uuid(text):
                raise ValueError
            stored = getattr(new_ref, _GET_OBJECT)()
            if stored is None:
                raise ValueError
            total = _total_text(getattr(stored, destinations.total_property))
            return text, total, stored_matches(stored)

        ref_id, total, matches = _guarded(
            "COM_WRITE_OUTCOME_UNKNOWN", True, write_and_read_back)
        if not matches:
            raise _refusal("COM_WRITTEN_READBACK_MISMATCH", True)
        return ExecutorResult(document_ref=ref_id, document_total_text=total)
    finally:
        resolved = document = row = mode = None
