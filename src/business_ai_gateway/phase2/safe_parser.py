"""Phase 2 values-only reader for untrusted XLSX / CSV files (R2-US-027, REQ17).

Pure stdlib, no I/O beyond the in-memory bytes handed in, no network.

Contract:
* Values only. Formulas are never evaluated and the formula text is never
  returned; a formula cell yields its cached ``<v>`` text or ``None``.
* Numbers are returned as the literal text found in the file (no float
  round-trip); dates are not guessed (the serial number text is returned).
* Hostile content is DENIED with a fixed code. Resource bounds produce
  BOUND_EXCEEDED with a bound code. Neither ever returns partial sheets and
  neither echoes file content (names, text, exception messages).
* XML members are screened on raw bytes for DOCTYPE / ENTITY exactly once
  (when the member is read) before any parser sees them; expat additionally
  refuses DTD/entity declarations.
* ``run_isolated`` never unpickles child output: the child sends a bounded
  JSON document and the parent rebuilds the result with strict type checks.

Known limits (documented, not hidden):
* ``run_isolated`` enforces the wall-clock timeout everywhere. The address
  space bound is applied in the child only where ``resource.RLIMIT_AS``
  exists (POSIX). On Windows the memory bound is NOT enforced across the
  process boundary (NOT_RUN there); input / member / node / row / cell limits
  are the protection on that platform.
* The XML node budget is ``min(max_cells * 8 + 10000, member_bytes // 3 +
  100)`` because an element needs at least 4 bytes; nodes use ``__slots__``
  and lazily created containers. It bounds allocation, it is not a memory cap.
* The raw DOCTYPE/ENTITY scan also rejects the literal text ``<!DOCTYPE`` or
  ``<!ENTITY`` inside CDATA (conservative false positive).
* The per-member ratio check only applies to members of at least 4096 bytes.
* Rows are bounded across all sheets of a workbook; padding rows implied by a
  sparse ``r`` attribute are counted against ``max_cells``; the summed length
  of every returned value is bounded by ``max_total_text_chars``.
* ``DENIED``/``OK`` here means "values were (not) extracted safely"; it does
  NOT mean the file is safe to open in Office. Relationships with an external
  TargetMode (including hyperlinks) are denied outright, and nothing is ever
  followed or fetched.
* The central-directory entry count is compared with ``max_members`` from the
  raw end-of-central-directory record before any per-entry object is built;
  ZIP64 archives (count field 0xFFFF) fall back to ``zipfile`` and keep the
  residual cost of building their entry list.
* ``run_isolated`` is a crash / timeout boundary, NOT a sandbox: the child
  runs with the caller's privileges (only the environment is scrubbed).
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import math
import multiprocessing
import os
import re
import threading
import time
import zipfile
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, fields
from enum import StrEnum
from posixpath import normpath
from xml.parsers import expat


class Status(StrEnum):
    OK = "OK"
    DENIED = "DENIED"
    BOUND_EXCEEDED = "BOUND_EXCEEDED"


@dataclass(frozen=True)
class ParseLimits:
    max_input_bytes: int = 5_000_000
    max_members: int = 200
    max_member_uncompressed: int = 20_000_000
    max_total_uncompressed: int = 50_000_000
    max_ratio: float = 100.0
    max_rows: int = 100_000
    max_cells: int = 1_000_000
    max_cell_chars: int = 32_767
    deadline_seconds: float = 5.0
    max_xml_depth: int = 64
    max_sheets: int = 64
    max_total_text_chars: int = 5_000_000

    def __post_init__(self) -> None:
        for name in (
            "max_input_bytes", "max_members", "max_member_uncompressed",
            "max_total_uncompressed", "max_rows", "max_cells",
            "max_cell_chars", "max_xml_depth", "max_sheets", "max_total_text_chars",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive int")
        for name in ("max_ratio", "deadline_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or not value > 0
            ):
                raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class ParseStats:
    members: int = 0
    uncompressed_bytes: int = 0
    rows: int = 0
    cells: int = 0
    formula_cells: int = 0
    leading_formula_chars: int = 0  # CSV only; values are NOT stripped


@dataclass(frozen=True)
class SheetValues:
    name: str
    rows: tuple[tuple[str | None, ...], ...]


@dataclass(frozen=True)
class ParseResult:
    status: Status
    code: str
    sheets: tuple[SheetValues, ...] = field(default=())
    stats: ParseStats = field(default_factory=ParseStats)


# Fixed codes (never carry content).
NOT_A_ZIP = "NOT_A_ZIP"
ENCRYPTED_MEMBER = "ENCRYPTED_MEMBER"
MACRO_PRESENT = "MACRO_PRESENT"
EXTERNAL_LINK = "EXTERNAL_LINK"
XML_DTD_OR_ENTITY = "XML_DTD_OR_ENTITY"
ZIP_BOMB_RATIO = "ZIP_BOMB_RATIO"
TOO_MANY_MEMBERS = "TOO_MANY_MEMBERS"
MEMBER_TOO_LARGE = "MEMBER_TOO_LARGE"
PATH_TRAVERSAL_MEMBER = "PATH_TRAVERSAL_MEMBER"
MALFORMED_XML = "MALFORMED_XML"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
INVALID_INPUT = "INVALID_INPUT"
PARSE_FAILED = "PARSE_FAILED"
CSV_NOT_UTF8 = "CSV_NOT_UTF8"
CSV_NUL_BYTE = "CSV_NUL_BYTE"
CSV_MALFORMED = "CSV_MALFORMED"
BOUND_INPUT_BYTES = "BOUND_INPUT_BYTES"
BOUND_ROWS = "BOUND_ROWS"
BOUND_CELLS = "BOUND_CELLS"
BOUND_CELL_CHARS = "BOUND_CELL_CHARS"
BOUND_XML_DEPTH = "BOUND_XML_DEPTH"
BOUND_XML_NODES = "BOUND_XML_NODES"
BOUND_SHEETS = "BOUND_SHEETS"
BOUND_TOTAL_TEXT = "BOUND_TOTAL_TEXT"
BOUND_DEADLINE = "BOUND_DEADLINE"
BOUND_MEMORY = "BOUND_MEMORY"
TIMEOUT = "TIMEOUT"
CHILD_ABORTED = "CHILD_ABORTED"

_KNOWN_CODES = frozenset({
    "OK", NOT_A_ZIP, ENCRYPTED_MEMBER, MACRO_PRESENT, EXTERNAL_LINK, XML_DTD_OR_ENTITY,
    ZIP_BOMB_RATIO, TOO_MANY_MEMBERS, MEMBER_TOO_LARGE, PATH_TRAVERSAL_MEMBER,
    MALFORMED_XML, UNSUPPORTED_FORMAT, INVALID_INPUT, PARSE_FAILED, CSV_NOT_UTF8,
    CSV_NUL_BYTE, CSV_MALFORMED, BOUND_INPUT_BYTES, BOUND_ROWS, BOUND_CELLS,
    BOUND_CELL_CHARS, BOUND_XML_DEPTH, BOUND_XML_NODES, BOUND_SHEETS, BOUND_TOTAL_TEXT, BOUND_DEADLINE,
    BOUND_MEMORY, TIMEOUT, CHILD_ABORTED,
})


class _Deny(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Bound(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Budget:
    def __init__(self, limits: ParseLimits, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._deadline = limits.deadline_seconds
        self._start = clock()

    def check(self) -> None:
        if self._clock() - self._start > self._deadline:
            raise _Bound(BOUND_DEADLINE)


class _Counters:
    def __init__(self) -> None:
        self.members = 0
        self.uncompressed = 0
        self.rows = 0
        self.cells = 0
        self.formula_cells = 0
        self.leading = 0
        self.text = 0  # summed length of every returned value

    def freeze(self) -> ParseStats:
        return ParseStats(
            self.members, self.uncompressed, self.rows, self.cells,
            self.formula_cells, self.leading,
        )


_NO_ATTRS: dict[str, str] = {}  # shared, never mutated
_NO_KIDS: tuple[_Node, ...] = ()


class _Node:
    """Tree node; child / text containers are created only when needed."""

    __slots__ = ("attrs", "kids", "ns", "parts", "size", "tag")

    def __init__(self, tag: str, attrs: dict[str, str], ns: str = "") -> None:
        self.tag = tag
        self.ns = ns
        self.attrs = attrs
        self.kids: list[_Node] | None = None
        self.parts: list[str] | None = None
        self.size = 0

    @property
    def children(self) -> list[_Node] | tuple[_Node, ...]:
        return self.kids if self.kids is not None else _NO_KIDS

    def joined(self) -> str:
        return "".join(self.parts) if self.parts else ""

    def child(self, tag: str) -> _Node | None:
        for node in self.children:
            if node.tag == tag:
                return node
        return None


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_SECURITY_ATTRS = frozenset(
    {"Type", "Target", "TargetMode", "ContentType", "PartName", "Extension", "Id", "id"}
)


_FORBIDDEN_ELEMENTS = frozenset(
    {"ddeLink", "oleLink", "oleLinks", "oleObject", "oleObjects",
     "externalReference", "externalReferences", "externalBook"}
)


def _screen_xml(raw: bytes) -> None:
    """Raw-byte DOCTYPE/ENTITY screen; callers run it once per member."""
    if b"\x00" in raw:  # UTF-16/32 would hide a DOCTYPE from the byte scan
        raise _Deny(MALFORMED_XML)
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise _Deny(XML_DTD_OR_ENTITY)


def _parse_xml(raw: bytes, limits: ParseLimits, budget: _Budget) -> _Node:
    """Parse already-screened XML into a small tree with hard budgets."""
    root = _Node("", _NO_ATTRS)
    stack = [root]
    count = 0
    node_budget = min(limits.max_cells * 8 + 10_000, len(raw) // 3 + 100)

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal count
        count += 1
        if len(stack) > limits.max_xml_depth:
            raise _Bound(BOUND_XML_DEPTH)
        if count > node_budget:
            raise _Bound(BOUND_XML_NODES)
        if count % 256 == 0:
            budget.check()
        ns, _, tag = name.rpartition(" ")
        if tag in _FORBIDDEN_ELEMENTS:
            raise _Deny(EXTERNAL_LINK)
        local_attrs = _NO_ATTRS
        if attrs:
            local_attrs = {}
            for key, val in attrs.items():
                key_ns, _, key_local = key.rpartition(" ")
                # security-relevant attributes are accepted only unqualified
                # (or r:id in the relationships namespace); a collision after
                # namespace stripping would let the last one win.
                if key_local in local_attrs or (
                    key_ns and key_ns != _REL_NS and key_local in _SECURITY_ATTRS
                ):
                    raise _Deny(MALFORMED_XML)
                local_attrs[key_local] = val
        node = _Node(tag, local_attrs, ns)
        parent = stack[-1]
        if parent.kids is None:
            parent.kids = [node]
        else:
            parent.kids.append(node)
        stack.append(node)

    def end(_name: str) -> None:
        stack.pop()

    def chars(data: str) -> None:
        node = stack[-1]
        node.size += len(data)
        if node.size > limits.max_cell_chars:
            raise _Bound(BOUND_CELL_CHARS)
        if node.parts is None:
            node.parts = [data]
        else:
            node.parts.append(data)

    def refuse(*_args: object) -> None:
        raise _Deny(XML_DTD_OR_ENTITY)

    parser = expat.ParserCreate(namespace_separator=" ")
    parser.buffer_text = True
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    try:
        parser.Parse(raw, True)
    except expat.ExpatError:
        raise _Deny(MALFORMED_XML) from None
    return root.children[0] if root.children else root


def _text(node: _Node) -> str:
    """Concatenate text of <t> descendants, skipping phonetic runs."""
    if node.tag == "rPh":
        return ""
    if node.tag == "t":
        return node.joined()
    return "".join(_text(child) for child in node.children)


# --- zip layer -------------------------------------------------------------

_XML_SUFFIXES = (".xml", ".rels")
_EXTERNAL_NAME_PARTS = ("oleobject", "/activex/", "externallink")
_EXTERNAL_PREFIXES = (
    "xl/externallinks/", "xl/embeddings/", "xl/connections", "xl/querytables/",
    "xl/webextensions/",
)
_MACRO_NAME_PARTS = ("vbaproject", "macrosheet", "customui/")
_EXTERNAL_TYPE_PARTS = ("connections", "querytable", "webextension")
_MACRO_TYPE_PARTS = ("macrosheet", "ui/extensibility", "customui")
_MIN_RATIO_SIZE = 4096
_PRINTER_SETTINGS_PREFIX = "xl/printersettings/"


def _check_name(name: str, seen: set[str]) -> None:
    parts = name.split("/")
    if (
        not name
        or name.startswith(("/", "\\"))
        or "\\" in name
        or "\x00" in name
        or (len(name) > 1 and name[1] == ":")
        or ".." in parts
    ):
        raise _Deny(PATH_TRAVERSAL_MEMBER)
    key = name.casefold()
    if key in seen:
        raise _Deny(PATH_TRAVERSAL_MEMBER)
    seen.add(key)


def _check_entry_count(data: bytes, limits: ParseLimits) -> None:
    """Compare the EOCD entry count with max_members before zipfile builds entries."""
    pos = data.rfind(b"PK\x05\x06", max(0, len(data) - 22 - 65_535))
    if pos < 0 or pos + 12 > len(data):
        return  # let zipfile classify it
    total = int.from_bytes(data[pos + 10 : pos + 12], "little")
    if total != 0xFFFF and total > limits.max_members:  # 0xFFFF = ZIP64 marker
        raise _Deny(TOO_MANY_MEMBERS)


def _check_directory(zf: zipfile.ZipFile, data_len: int, limits: ParseLimits) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > limits.max_members:
        raise _Deny(TOO_MANY_MEMBERS)
    seen: set[str] = set()
    for info in infos:
        # zipfile rewrites os.sep to "/" on Windows; judge the raw name so every
        # platform sees the same thing.
        if "\\" in info.orig_filename:
            raise _Deny(PATH_TRAVERSAL_MEMBER)
        _check_name(info.filename, seen)
    total = 0
    for info in infos:
        low = info.filename.lower()
        if info.flag_bits & 0x1:
            raise _Deny(ENCRYPTED_MEMBER)
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise _Deny(UNSUPPORTED_FORMAT)
        if any(part in low for part in _MACRO_NAME_PARTS) or low.startswith("customui"):
            raise _Deny(MACRO_PRESENT)
        if low.startswith(_EXTERNAL_PREFIXES) or any(
            part in low for part in _EXTERNAL_NAME_PARTS
        ):
            raise _Deny(EXTERNAL_LINK)
        if low.endswith(".bin") and not low.startswith(_PRINTER_SETTINGS_PREFIX):
            raise _Deny(UNSUPPORTED_FORMAT)
        if info.file_size > limits.max_member_uncompressed:
            raise _Deny(MEMBER_TOO_LARGE)
        if info.file_size >= _MIN_RATIO_SIZE and (
            info.file_size / max(info.compress_size, 1) > limits.max_ratio
        ):
            raise _Deny(ZIP_BOMB_RATIO)
        total += info.file_size
    if total > limits.max_total_uncompressed or total / max(data_len, 1) > limits.max_ratio:
        raise _Deny(ZIP_BOMB_RATIO)
    return infos


def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """Read at most limit+1 bytes so a lying directory cannot bypass the cap.

    A decoded blob can never be larger than the directory size that already
    passed the ratio check, so no second ratio check is needed here.
    """
    try:
        with zf.open(info) as handle:
            blob = handle.read(limit + 1)
    except (
        zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error,
        EOFError, NotImplementedError, RuntimeError, OSError,
    ):
        raise _Deny(NOT_A_ZIP) from None
    if len(blob) > limit:
        raise _Deny(MEMBER_TOO_LARGE)
    return blob


def _check_content_types(root: _Node) -> None:
    for node in root.children:
        ctype = node.attrs.get("ContentType", "").lower()
        if "macroenabled" in ctype or "vbaproject" in ctype or "macrosheet" in ctype:
            raise _Deny(MACRO_PRESENT)
        if (
            "oleobject" in ctype or "externallink" in ctype or "activex" in ctype
            or any(part in ctype for part in _EXTERNAL_TYPE_PARTS)
        ):
            raise _Deny(EXTERNAL_LINK)


def _relationships(root: _Node) -> dict[str, tuple[str, str]]:
    rels: dict[str, tuple[str, str]] = {}
    for node in root.children:
        if node.attrs.get("TargetMode", "").lower() == "external":
            raise _Deny(EXTERNAL_LINK)
        rtype = node.attrs.get("Type", "").lower()
        if rtype.endswith("/vbaproject") or any(part in rtype for part in _MACRO_TYPE_PARTS):
            raise _Deny(MACRO_PRESENT)
        if (
            rtype.endswith(("/oleobject", "/externallink", "/externallinkpath"))
            or "activex" in rtype
            or any(part in rtype for part in _EXTERNAL_TYPE_PARTS)
        ):
            raise _Deny(EXTERNAL_LINK)
        rid = node.attrs.get("Id", "")
        if rid in rels:
            raise _Deny(MALFORMED_XML)
        rels[rid] = (rtype, node.attrs.get("Target", ""))
    return rels


def _check_pivot_cache(root: _Node) -> None:
    source = root.child("cacheSource")
    if source is not None and (
        source.attrs.get("type", "worksheet") != "worksheet" or "connectionId" in source.attrs
    ):
        raise _Deny(EXTERNAL_LINK)


def _resolve(base_dir: str, target: str) -> str:
    joined = target[1:] if target.startswith("/") else f"{base_dir}/{target}"
    path = normpath(joined)
    if path.startswith(("..", "/")):
        raise _Deny(PATH_TRAVERSAL_MEMBER)
    return path


_CELL_REF = re.compile(r"([A-Z]{1,3})([0-9]{1,7})")


def _cell_ref(ref: str) -> tuple[int, int]:
    """Return (zero-based column, row number) of an A1 reference."""
    match = _CELL_REF.fullmatch(ref)
    if match is None:
        raise _Deny(MALFORMED_XML)
    col = 0
    for ch in match.group(1):
        col = col * 26 + (ord(ch) - 64)
    if col > 16_384:
        raise _Deny(MALFORMED_XML)
    return col - 1, int(match.group(2))


def _cell_value(cell: _Node, sst: list[str], limits: ParseLimits, counters: _Counters) -> str | None:
    if cell.child("f") is not None:
        counters.formula_cells += 1
    kind = cell.attrs.get("t", "n")
    value: str | None
    if kind == "inlineStr":
        inline = cell.child("is")
        value = _text(inline) if inline is not None else None
    else:
        v = cell.child("v")
        value = v.joined() if v is not None else None
        if kind == "s" and value is not None:
            # length guard first: int() of a huge digit string raises ValueError
            if len(value) > 10 or not value.isascii() or not value.isdigit() or int(value) >= len(sst):
                raise _Deny(MALFORMED_XML)
            value = sst[int(value)]
    if value is not None and len(value) > limits.max_cell_chars:
        raise _Bound(BOUND_CELL_CHARS)
    return value


def _sheet_rows(
    root: _Node, sst: list[str], limits: ParseLimits, budget: _Budget, counters: _Counters
) -> tuple[tuple[str | None, ...], ...]:
    if root.tag != "worksheet":
        raise _Deny(MALFORMED_XML)
    if root.ns != _MAIN_NS:
        raise _Deny(UNSUPPORTED_FORMAT)
    data = root.child("sheetData")
    rows: list[tuple[str | None, ...]] = []
    if data is None:
        return ()
    if data.ns != _MAIN_NS:
        raise _Deny(UNSUPPORTED_FORMAT)
    base_rows = counters.rows  # rows already produced by earlier sheets
    last = 0
    for row in data.children:
        if row.tag != "row":
            continue
        if row.ns != _MAIN_NS:
            raise _Deny(UNSUPPORTED_FORMAT)
        budget.check()
        raw_r = row.attrs.get("r")
        if raw_r is None:
            number = last + 1
        elif raw_r.isascii() and raw_r.isdigit() and len(raw_r) <= 9:
            number = int(raw_r)
        else:
            raise _Deny(MALFORMED_XML)
        if number <= last:
            raise _Deny(MALFORMED_XML)
        if base_rows + number > limits.max_rows:
            raise _Bound(BOUND_ROWS)
        sparse: dict[int, str | None] = {}
        nxt = 0
        for cell in row.children:
            if cell.tag != "c":
                continue
            if cell.ns != _MAIN_NS:
                raise _Deny(UNSUPPORTED_FORMAT)
            budget.check()
            ref = cell.attrs.get("r")
            if ref is None:
                col = nxt
            else:
                col, ref_row = _cell_ref(ref)
                if ref_row != number:
                    raise _Deny(MALFORMED_XML)
            if col < nxt:  # backwards or repeated column
                raise _Deny(MALFORMED_XML)
            nxt = col + 1
            value = _cell_value(cell, sst, limits, counters)
            if value is not None:
                counters.text += len(value)
                if counters.text > limits.max_total_text_chars:
                    raise _Bound(BOUND_TOTAL_TEXT)
            sparse[col] = value
        width = max(sparse) + 1 if sparse else 0
        gap = number - 1 - last
        counters.cells += gap + width  # padding rows are not free
        if counters.cells > limits.max_cells:
            raise _Bound(BOUND_CELLS)
        rows.extend(() for _ in range(gap))
        rows.append(tuple(sparse.get(i) for i in range(width)))
        last = number
    counters.rows += len(rows)
    return tuple(rows)


def _parse_workbook(data: bytes, limits: ParseLimits, clock: Callable[[], float]) -> ParseResult:
    counters = _Counters()
    try:
        budget = _Budget(limits, clock)
        sheets = _workbook_sheets(data, limits, budget, counters)
    except _Deny as exc:
        return ParseResult(Status.DENIED, exc.code, (), counters.freeze())
    except _Bound as exc:
        return ParseResult(Status.BOUND_EXCEEDED, exc.code, (), counters.freeze())
    except RecursionError:
        return ParseResult(Status.BOUND_EXCEEDED, BOUND_XML_DEPTH, (), counters.freeze())
    except MemoryError:
        return ParseResult(Status.BOUND_EXCEEDED, BOUND_MEMORY, (), counters.freeze())
    except Exception:  # noqa: BLE001 - fixed code, no content echoed
        return ParseResult(Status.DENIED, PARSE_FAILED, (), counters.freeze())
    return ParseResult(Status.OK, "OK", sheets, counters.freeze())


def _workbook_sheets(
    data: bytes, limits: ParseLimits, budget: _Budget, counters: _Counters
) -> tuple[SheetValues, ...]:
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise _Deny(UNSUPPORTED_FORMAT)
    _check_entry_count(data, limits)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, EOFError, OSError, ValueError):
        raise _Deny(NOT_A_ZIP) from None
    with zf:
        infos = _check_directory(zf, len(data), limits)
        counters.members = len(infos)
        by_name = {info.filename: info for info in infos}
        cache: dict[str, bytes] = {}
        remaining = limits.max_total_uncompressed
        for info in infos:
            budget.check()
            if info.is_dir() or not info.filename.lower().endswith(_XML_SUFFIXES):
                continue
            blob = _read_member(zf, info, min(limits.max_member_uncompressed, remaining))
            remaining -= len(blob)
            counters.uncompressed += len(blob)
            _screen_xml(blob)  # the only DTD screen; _parse_xml trusts it
            cache[info.filename] = blob
        for name, blob in cache.items():
            low = name.lower()
            if low.endswith(".rels"):
                _relationships(_parse_xml(blob, limits, budget))
            elif low.startswith("xl/pivotcache/pivotcachedefinition"):
                _check_pivot_cache(_parse_xml(blob, limits, budget))
        if "[Content_Types].xml" not in cache:
            raise _Deny(UNSUPPORTED_FORMAT)
        _check_content_types(_parse_xml(cache["[Content_Types].xml"], limits, budget))
        if "xl/workbook.xml" not in cache:
            raise _Deny(UNSUPPORTED_FORMAT)
        rels: dict[str, tuple[str, str]] = {}
        if "xl/_rels/workbook.xml.rels" in cache:
            rels = _relationships(_parse_xml(cache["xl/_rels/workbook.xml.rels"], limits, budget))
        sst: list[str] = []
        sst_parts = [target for rtype, target in rels.values() if rtype.endswith("/sharedstrings")]
        if len(sst_parts) > 1:
            raise _Deny(MALFORMED_XML)
        for target in sst_parts:
            part = _resolve("xl", target)
            if part not in cache:
                raise _Deny(MALFORMED_XML)
            tree = _parse_xml(cache[part], limits, budget)
            for si in tree.children:
                budget.check()  # per item: a huge table must not outrun the deadline
                text = _text(si)
                if len(text) > limits.max_cell_chars:
                    raise _Bound(BOUND_CELL_CHARS)
                sst.append(text)
        book = _parse_xml(cache["xl/workbook.xml"], limits, budget)
        listing = book.child("sheets")
        entries = listing.children if listing is not None else ()
        if len(entries) > limits.max_sheets:
            raise _Bound(BOUND_SHEETS)
        out: list[SheetValues] = []
        used_parts: set[str] = set()
        for sheet in entries:
            budget.check()
            rid = sheet.attrs.get("id", "")
            if rid not in rels or not rels[rid][0].endswith("/worksheet"):
                raise _Deny(MALFORMED_XML)
            part = _resolve("xl", rels[rid][1])
            if part not in cache or part not in by_name:
                raise _Deny(MALFORMED_XML)
            if part in used_parts:  # one part must not be re-materialised per sheet
                raise _Deny(MALFORMED_XML)
            used_parts.add(part)
            tree = _parse_xml(cache[part], limits, budget)
            rows = _sheet_rows(tree, sst, limits, budget, counters)
            out.append(SheetValues(sheet.attrs.get("name", ""), rows))
        return tuple(out)


def _validate(data: object, limits: object, clock: object) -> ParseResult | bytes:
    if not isinstance(limits, ParseLimits) or not callable(clock):
        return ParseResult(Status.DENIED, INVALID_INPUT)
    if not isinstance(data, bytes | bytearray | memoryview):
        return ParseResult(Status.DENIED, INVALID_INPUT)
    size = data.nbytes if isinstance(data, memoryview) else len(data)
    if size > limits.max_input_bytes:
        return ParseResult(Status.BOUND_EXCEEDED, BOUND_INPUT_BYTES)
    return bytes(data)


def parse_workbook(
    data: bytes,
    *,
    limits: ParseLimits = ParseLimits(),  # noqa: B008 - frozen dataclass
    clock: Callable[[], float] = time.monotonic,
) -> ParseResult:
    """Read an untrusted XLSX as values only. Never raises on bad input."""
    checked = _validate(data, limits, clock)
    if isinstance(checked, ParseResult):
        return checked
    return _parse_workbook(checked, limits, clock)


# --- CSV -------------------------------------------------------------------

_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def parse_csv(
    data: bytes,
    *,
    limits: ParseLimits = ParseLimits(),  # noqa: B008 - frozen dataclass
    clock: Callable[[], float] = time.monotonic,
) -> ParseResult:
    """Read an untrusted CSV (strict UTF-8). Values are text, never interpreted."""
    checked = _validate(data, limits, clock)
    if isinstance(checked, ParseResult):
        return checked
    counters = _Counters()
    try:
        return _parse_csv(checked, limits, clock, counters)
    except _Bound as exc:
        return ParseResult(Status.BOUND_EXCEEDED, exc.code, (), counters.freeze())
    except _Deny as exc:
        return ParseResult(Status.DENIED, exc.code, (), counters.freeze())
    except MemoryError:
        return ParseResult(Status.BOUND_EXCEEDED, BOUND_MEMORY, (), counters.freeze())
    except Exception:  # noqa: BLE001 - fixed code, no content echoed
        return ParseResult(Status.DENIED, PARSE_FAILED, (), counters.freeze())


def _parse_csv(
    data: bytes, limits: ParseLimits, clock: Callable[[], float], counters: _Counters
) -> ParseResult:
    budget = _Budget(limits, clock)
    if b"\x00" in data:
        raise _Deny(CSV_NUL_BYTE)
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise _Deny(CSV_NOT_UTF8) from None
    rows: list[tuple[str | None, ...]] = []
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        for record in reader:
            if len(rows) % 256 == 0:
                budget.check()
            if len(rows) >= limits.max_rows:
                raise _Bound(BOUND_ROWS)
            counters.cells += len(record)
            if counters.cells > limits.max_cells:
                raise _Bound(BOUND_CELLS)
            for value in record:
                if len(value) > limits.max_cell_chars:
                    raise _Bound(BOUND_CELL_CHARS)
                counters.text += len(value)
                if counters.text > limits.max_total_text_chars:
                    raise _Bound(BOUND_TOTAL_TEXT)
                if value.startswith(_FORMULA_LEADS):
                    counters.leading += 1
            rows.append(tuple(record))
    except csv.Error as exc:
        # The csv module's own field-size cap is a size bound, not malformed input.
        if "field larger than field limit" in str(exc):
            raise _Bound(BOUND_CELL_CHARS) from None
        raise _Deny(CSV_MALFORMED) from None
    counters.rows = len(rows)
    return ParseResult(Status.OK, "OK", (SheetValues("csv", tuple(rows)),), counters.freeze())


# --- process isolation -----------------------------------------------------

_DEFAULT_CHILD_MEMORY = 1 << 30
_MAX_PAYLOAD = 64 << 20  # bytes the parent will accept from the child
_POLL_SLICE = 0.2


def _encode_result(result: ParseResult) -> bytes:
    doc = {
        "status": result.status.value,
        "code": result.code,
        "sheets": [
            {"name": sheet.name, "rows": [list(row) for row in sheet.rows]}
            for sheet in result.sheets
        ],
        "stats": {f.name: getattr(result.stats, f.name) for f in fields(ParseStats)},
    }
    return json.dumps(doc, separators=(",", ":")).encode("ascii")


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _build_result(doc: object) -> ParseResult:
    """Strictly rebuild a ParseResult; raise ValueError on any deviation."""
    if not isinstance(doc, dict) or set(doc) != {"status", "code", "sheets", "stats"}:
        raise ValueError("shape")
    status = Status(doc["status"])
    code = doc["code"]
    if not isinstance(code, str) or code not in _KNOWN_CODES:
        raise ValueError("code")
    if (status is Status.OK) != (code == "OK"):
        raise ValueError("status/code")
    names = [f.name for f in fields(ParseStats)]
    raw_stats = doc["stats"]
    if (
        not isinstance(raw_stats, dict)
        or set(raw_stats) != set(names)
        or not all(_is_count(v) for v in raw_stats.values())
    ):
        raise ValueError("stats")
    raw_sheets = doc["sheets"]
    if not isinstance(raw_sheets, list) or (status is not Status.OK and raw_sheets):
        raise ValueError("sheets")
    sheets: list[SheetValues] = []
    for raw in raw_sheets:
        if (
            not isinstance(raw, dict)
            or set(raw) != {"name", "rows"}
            or not isinstance(raw["name"], str)
            or not isinstance(raw["rows"], list)
        ):
            raise ValueError("sheet")
        rows: list[tuple[str | None, ...]] = []
        for row in raw["rows"]:
            if not isinstance(row, list) or not all(v is None or isinstance(v, str) for v in row):
                raise ValueError("row")
            rows.append(tuple(row))
        sheets.append(SheetValues(raw["name"], tuple(rows)))
    return ParseResult(status, code, tuple(sheets), ParseStats(**raw_stats))


def _decode_result(payload: bytes) -> ParseResult | None:
    try:
        return _build_result(json.loads(payload.decode("ascii")))
    except (ValueError, TypeError, RecursionError):
        return None


def _child_main(conn: object, data: bytes, limits: ParseLimits, memory_bytes: int) -> None:
    try:
        try:
            import resource  # POSIX only

            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except (ImportError, ValueError, OSError, OverflowError):
            pass  # not enforced on this platform / for this value
        payload = _encode_result(parse_workbook(data, limits=limits))
        if len(payload) > _MAX_PAYLOAD:
            payload = _encode_result(ParseResult(Status.BOUND_EXCEEDED, BOUND_MEMORY))
    except MemoryError:
        payload = _encode_result(ParseResult(Status.BOUND_EXCEEDED, BOUND_MEMORY))
    conn.send_bytes(payload)  # type: ignore[attr-defined]
    conn.close()  # type: ignore[attr-defined]


_ENV_KEEP = frozenset({
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "PATH", "PATHEXT", "COMSPEC",
    "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "HOME",
})
_ENV_LOCK = threading.Lock()


@contextlib.contextmanager
def _scrubbed_environment() -> Iterator[None]:
    """Start the child with only what spawn needs; restore the parent afterwards.

    KNOWN LIMIT: ``multiprocessing`` spawn inherits ``os.environ``, which is
    process-wide, so other threads still observe the removed variables while the
    child is being created (reads of a scrubbed name see it missing). What is
    guaranteed: kept variables are never touched; removal happens one key at a
    time inside the ``try`` so an interrupt at any point is undone in ``finally``;
    the restore uses ``setdefault`` so a value another thread wrote (or re-created)
    during the window is kept, never overwritten by the stale snapshot.
    """
    removed: dict[str, str] = {}
    with _ENV_LOCK:
        try:
            for key in list(os.environ):
                if key.upper() in _ENV_KEEP:
                    continue
                value = os.environ.pop(key, None)
                if value is not None:
                    removed[key] = value
            yield
        finally:
            for key, value in removed.items():
                os.environ.setdefault(key, value)


def _aborted() -> ParseResult:
    return ParseResult(Status.BOUND_EXCEEDED, CHILD_ABORTED)


def run_isolated(
    data: bytes,
    *,
    limits: ParseLimits = ParseLimits(),  # noqa: B008 - frozen dataclass
    timeout_s: float = 10.0,
    memory_bytes: int = _DEFAULT_CHILD_MEMORY,
    _child_target: Callable[..., None] = _child_main,
) -> ParseResult:
    """Run parse_workbook in a spawned child with a wall-clock timeout.

    The child is killed and reaped on timeout (code TIMEOUT). The timeout
    includes interpreter start-up and the parent never waits past it. The
    child sends bounded JSON (never pickle); anything that does not rebuild
    strictly yields CHILD_ABORTED. Memory bound: RLIMIT_AS in the child on
    POSIX only; NOT enforced on Windows.

    Windows uses ``spawn``: the calling program's ``__main__`` module must be
    import-safe (``if __name__ == "__main__":`` guard) or the child re-runs it.
    This is a crash / timeout boundary, NOT a sandbox: the child keeps the
    caller's OS privileges and only receives a scrubbed environment (no
    inherited secrets). Called from a daemonic process, where children are not
    allowed, it returns CHILD_ABORTED instead of raising.
    ``_child_target`` is a test seam; production callers leave the default.
    """
    checked = _validate(data, limits, time.monotonic)
    if isinstance(checked, ParseResult):
        return checked
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, int | float)
        or not math.isfinite(timeout_s)
        or not timeout_s > 0
        or isinstance(memory_bytes, bool)
        or not isinstance(memory_bytes, int)
        or memory_bytes <= 0
    ):
        return ParseResult(Status.DENIED, INVALID_INPUT)
    deadline = time.monotonic() + timeout_s
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child_target, args=(child, checked, limits, memory_bytes), daemon=True)
    started = False
    reader: threading.Thread | None = None
    try:
        try:
            with _scrubbed_environment():
                proc.start()
            started = True
        except (OSError, AssertionError):  # BrokenPipeError; daemonic caller
            return _aborted()
        child.close()
        # The whole reply (header AND body) is read by a helper thread so a child
        # that sends a partial frame and stalls cannot outlive the deadline: the
        # parent only waits for the thread until the deadline, then kills the child.
        box: list[bytes | None] = []

        def _read() -> None:
            try:
                box.append(parent.recv_bytes(_MAX_PAYLOAD))
            except Exception:  # noqa: BLE001 - EOF / broken pipe / oversize: no answer
                box.append(None)

        reader = threading.Thread(target=_read, name="safe-parser-reader", daemon=True)
        reader.start()
        reader.join(max(deadline - time.monotonic(), 0.0))
        if not box:
            return ParseResult(Status.BOUND_EXCEEDED, TIMEOUT)
        payload = box[0]
        if payload is None:
            return _aborted()
        return _decode_result(payload) or _aborted()
    finally:
        if started:
            if proc.is_alive():
                proc.kill()
            proc.join(5.0)
        if reader is not None:
            reader.join(2.0)  # the killed child's pipe end is gone, so recv returns
        for conn in (parent, child):
            if conn is parent and reader is not None and reader.is_alive():
                continue  # never close a handle another thread is blocked on
            try:
                conn.close()
            except OSError:
                pass
        try:
            proc.close()
        except ValueError:  # still running after kill+join: leave it to the daemon flag
            pass
