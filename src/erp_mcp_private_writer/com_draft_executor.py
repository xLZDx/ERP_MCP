"""CREATE_DRAFT executor for the clone-only S14 qualification (fake-COM tested, not wired anywhere).

``execute_create_draft`` creates one new document object from a reviewed document manager, sets the
reviewed header and single-row line properties, stamps the change-id / manifest-hash markers and
calls the plain write exactly once. Destinations come only from a caller-built
``DraftDestinationSet`` (never from payload data). Refusals carry stable codes; messages never
contain values, identifiers, the connection string or COM error text. Posting is never called.
Run it on the STA worker; it does no logging.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from .com_manifest import ComValueAssignment

__all__ = [
    "DraftDestinationSet",
    "ExecutorRefusal",
    "ExecutorResult",
    "execute_create_draft",
]

# 1C names, written as unicode escapes to keep the source ASCII.
_DOCUMENTS = "Документы"  # Documents
_CATALOGS = "Справочники"  # Catalogs
_CREATE_DOCUMENT = (  # CreateDocument
    "СоздатьДокумент")
_ADD_ROW = "Добавить"  # Add (tabular section row)
_WRITE = "Записать"  # Write
_GET_REF = (  # GetRef (catalog manager, by unique identifier)
    "ПолучитьСсылку")
_IS_EMPTY = "Пустая"  # IsEmpty (reference)
_DELETION_MARK = (  # DeletionMark
    "ПометкаУдаления")
_REF = "Ссылка"  # Ref (document reference property)
_UNIQUE_ID = (  # UUID (reference method)
    "Уникальный"
    "Идентификатор")
_WRITE_MODE_ENUM = (  # DocumentWriteMode
    "РежимЗаписи"
    "Документа")
_WRITE_MODE_PLAIN = "Запись"  # Write (plain mode, not Posting)
_DOCUMENT_TOTAL = (  # DocumentAmount
    "СуммаДокумента")

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ExecutorRefusal(Exception):
    """Stable-code refusal; the message is the code only."""

    def __init__(self, code: str, outcome_unknown: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown


def _name_ok(value: object) -> bool:
    return (type(value) is str and bool(value) and value == value.strip()
            and len(value) <= 128 and all(c.isprintable() for c in value))


def _pairs_ok(value: object) -> bool:
    return (type(value) is tuple and bool(value)
            and all(type(p) is tuple and len(p) == 2 and _name_ok(p[0]) and _name_ok(p[1])
                    for p in value))


@dataclass(frozen=True, slots=True)
class DraftDestinationSet:
    """Reviewed destinations keyed by binding ``property_path``.

    ``header_properties`` / ``line_properties``: ((property_path, 1C property name), ...), set in
    the given order. ``references``: ((property_path, expected catalog manager name), ...); each
    path must also be a header or line destination.
    """

    document_manager: str
    header_properties: tuple[tuple[str, str], ...]
    line_section: str
    line_properties: tuple[tuple[str, str], ...]
    references: tuple[tuple[str, str], ...]
    change_id_attribute: str
    manifest_attribute: str
    total_property: str = _DOCUMENT_TOTAL

    def __post_init__(self) -> None:
        if not (_name_ok(self.document_manager) and _name_ok(self.line_section)
                and _name_ok(self.change_id_attribute) and _name_ok(self.manifest_attribute)
                and _name_ok(self.total_property)
                and _pairs_ok(self.header_properties) and _pairs_ok(self.line_properties)
                and (self.references == () or _pairs_ok(self.references))):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        paths = [p for p, _ in self.header_properties] + [p for p, _ in self.line_properties]
        if len(paths) != len(set(paths)):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")
        ref_paths = [p for p, _ in self.references]
        if len(ref_paths) != len(set(ref_paths)) or not set(ref_paths) <= set(paths):
            raise ValueError("COM_EXECUTOR_DESTINATIONS_INVALID")

    def all_paths(self) -> frozenset[str]:
        return frozenset(p for p, _ in self.header_properties + self.line_properties)


@dataclass(frozen=True, slots=True)
class ExecutorResult:
    document_ref: str
    document_total_text: str


def _guarded(code: str, outcome_unknown: bool, call):
    """Run ``call``; on any exception raise a refusal outside the handler (no context kept)."""
    try:
        return call()
    except Exception:  # noqa: BLE001 - COM error classes are opaque; text is never kept
        failed = True
    if failed:
        raise ExecutorRefusal(code, outcome_unknown)


def _resolve_reference(connection: object, catalog_name: str, raw: object) -> object:
    if type(raw) is not str:
        raise ExecutorRefusal("COM_REFERENCE_NOT_GUID")
    try:
        canonical = str(uuid.UUID(raw))
    except ValueError:
        canonical = None
    if canonical is None or canonical != raw:
        raise ExecutorRefusal("COM_REFERENCE_NOT_GUID")

    def lookup() -> tuple[object, object, object]:
        manager = getattr(getattr(connection, _CATALOGS), catalog_name)
        found = getattr(manager, _GET_REF)(raw)
        empty = getattr(found, _IS_EMPTY)()
        marked = getattr(found, _DELETION_MARK) if empty is False else None
        return found, empty, marked

    found, empty, marked = _guarded("COM_REFERENCE_LOOKUP_FAILED", False, lookup)
    if empty is not False:
        raise ExecutorRefusal("COM_REFERENCE_NOT_FOUND")
    if marked is not False:
        raise ExecutorRefusal("COM_REFERENCE_DELETION_MARKED")
    return found


def execute_create_draft(
        connection: object, values: tuple[ComValueAssignment, ...],
        destinations: DraftDestinationSet, *, change_id: str, manifest_sha256: str
        ) -> ExecutorResult:
    """Create and plainly write one draft document; see module docstring for the error contract."""
    if type(destinations) is not DraftDestinationSet:
        raise ExecutorRefusal("COM_EXECUTOR_DESTINATION_MISMATCH")
    if (type(values) is not tuple
            or any(type(v) is not ComValueAssignment for v in values)):
        raise ExecutorRefusal("COM_EXECUTOR_DESTINATION_MISMATCH")
    paths = [v.property_path for v in values]
    if len(paths) != len(set(paths)) or set(paths) != destinations.all_paths():
        raise ExecutorRefusal("COM_EXECUTOR_DESTINATION_MISMATCH")
    if type(change_id) is not str or len(change_id) != 36:
        raise ExecutorRefusal("COM_MARKER_INVALID")
    if type(manifest_sha256) is not str or _HEX64.fullmatch(manifest_sha256) is None:
        raise ExecutorRefusal("COM_MARKER_INVALID")

    by_path = {v.property_path: v for v in values}
    catalog_of = dict(destinations.references)

    # 1. Resolve references first (in value order); no document object exists yet.
    resolved: dict[str, object] = {}
    for v in values:
        catalog = catalog_of.get(v.property_path)
        if catalog is not None:
            resolved[v.property_path] = _resolve_reference(connection, catalog, v.value)

    def final(path: str) -> object:
        return resolved[path] if path in resolved else by_path[path].value

    # 2. Create the object, set header, add one row and set it, then the markers.
    def create() -> object:
        manager = getattr(getattr(connection, _DOCUMENTS), destinations.document_manager)
        return getattr(manager, _CREATE_DOCUMENT)()

    document = _guarded("COM_DOCUMENT_CREATE_FAILED", False, create)

    def set_header() -> None:
        for path, name in destinations.header_properties:
            setattr(document, name, final(path))

    _guarded("COM_HEADER_SET_FAILED", False, set_header)

    def set_line() -> None:
        row = getattr(getattr(document, destinations.line_section), _ADD_ROW)()
        for path, name in destinations.line_properties:
            setattr(row, name, final(path))

    _guarded("COM_LINE_SET_FAILED", False, set_line)

    def set_markers() -> None:
        setattr(document, destinations.change_id_attribute, change_id)
        setattr(document, destinations.manifest_attribute, manifest_sha256)

    _guarded("COM_MARKER_SET_FAILED", False, set_markers)

    def prepare_write() -> tuple[object, object]:
        mode = getattr(getattr(connection, _WRITE_MODE_ENUM), _WRITE_MODE_PLAIN)
        return getattr(document, _WRITE), mode

    write, mode = _guarded("COM_WRITE_MODE_UNAVAILABLE", False, prepare_write)

    # 3. From here on the outcome is unknown on any failure.
    def write_and_read_back() -> tuple[str, str]:
        write(mode)
        ref_id = str(getattr(getattr(document, _REF), _UNIQUE_ID)())
        total = str(getattr(document, destinations.total_property))
        if not ref_id or not total:
            raise ValueError
        return ref_id, total

    ref_id, total = _guarded("COM_WRITE_OUTCOME_UNKNOWN", True, write_and_read_back)
    return ExecutorResult(document_ref=ref_id, document_total_text=total)
