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
* XML members are screened on raw bytes for DOCTYPE / ENTITY before any
  parser sees them; expat additionally refuses DTD/entity declarations.

Known limits (documented, not hidden):
* ``run_isolated`` enforces the wall-clock timeout everywhere. The address
  space bound is applied in the child only where ``resource.RLIMIT_AS``
  exists (POSIX). On Windows the memory bound is NOT enforced across the
  process boundary; input / member / node limits are the protection there.
* The raw DOCTYPE/ENTITY scan also rejects the literal text ``<!DOCTYPE`` or
  ``<!ENTITY`` inside CDATA (conservative false positive).
* The per-member ratio check only applies to members of at least 4096 bytes.
"""
from __future__ import annotations

import csv
import io
import multiprocessing
import re
import time
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
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

    def __post_init__(self) -> None:
        for name in (
            "max_input_bytes", "max_members", "max_member_uncompressed",
            "max_total_uncompressed", "max_rows", "max_cells",
            "max_cell_chars", "max_xml_depth",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive int")
        for name in ("max_ratio", "deadline_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
                raise ValueError(f"{name} must be a positive number")


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
BOUND_DEADLINE = "BOUND_DEADLINE"
BOUND_MEMORY = "BOUND_MEMORY"
TIMEOUT = "TIMEOUT"
CHILD_ABORTED = "CHILD_ABORTED"


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

    def freeze(self) -> ParseStats:
        return ParseStats(
            self.members, self.uncompressed, self.rows, self.cells,
            self.formula_cells, self.leading,
        )


class _Node:
    __slots__ = ("attrs", "children", "size", "tag", "text")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node] = []
        self.text: list[str] = []
        self.size = 0

    def joined(self) -> str:
        return "".join(self.text)

    def child(self, tag: str) -> _Node | None:
        for node in self.children:
            if node.tag == tag:
                return node
        return None


def _local(name: str) -> str:
    return name.rpartition(" ")[2]


_FORBIDDEN_ELEMENTS = frozenset(
    {"ddeLink", "oleLink", "oleLinks", "oleObject", "oleObjects",
     "externalReference", "externalReferences", "externalBook"}
)


def _screen_xml(raw: bytes) -> None:
    if b"\x00" in raw:  # UTF-16/32 would hide a DOCTYPE from the byte scan
        raise _Deny(MALFORMED_XML)
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise _Deny(XML_DTD_OR_ENTITY)


def _parse_xml(raw: bytes, limits: ParseLimits, budget: _Budget) -> _Node:
    """Parse already-screened XML into a small tree with hard budgets."""
    _screen_xml(raw)
    root = _Node("", {})
    stack = [root]
    count = 0
    node_budget = limits.max_cells * 8 + 10_000

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal count
        count += 1
        if len(stack) > limits.max_xml_depth:
            raise _Bound(BOUND_XML_DEPTH)
        if count > node_budget:
            raise _Bound(BOUND_XML_NODES)
        if count % 256 == 0:
            budget.check()
        tag = _local(name)
        if tag in _FORBIDDEN_ELEMENTS:
            raise _Deny(EXTERNAL_LINK)
        node = _Node(tag, {_local(k): v for k, v in attrs.items()})
        stack[-1].children.append(node)
        stack.append(node)

    def end(_name: str) -> None:
        stack.pop()

    def chars(data: str) -> None:
        node = stack[-1]
        node.size += len(data)
        if node.size > limits.max_cell_chars:
            raise _Bound(BOUND_CELL_CHARS)
        node.text.append(data)

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
_MIN_RATIO_SIZE = 4096


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


def _check_directory(zf: zipfile.ZipFile, data_len: int, limits: ParseLimits) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > limits.max_members:
        raise _Deny(TOO_MANY_MEMBERS)
    seen: set[str] = set()
    for info in infos:
        _check_name(info.filename, seen)
    total = 0
    for info in infos:
        low = info.filename.lower()
        if info.flag_bits & 0x1:
            raise _Deny(ENCRYPTED_MEMBER)
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise _Deny(UNSUPPORTED_FORMAT)
        if "vbaproject" in low:
            raise _Deny(MACRO_PRESENT)
        if low.startswith(("xl/externallinks/", "xl/embeddings/")) or any(
            part in low for part in _EXTERNAL_NAME_PARTS
        ):
            raise _Deny(EXTERNAL_LINK)
        if low.endswith(".bin"):
            raise _Deny(MACRO_PRESENT)
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
    """Read at most limit+1 bytes so a lying directory cannot bypass the cap."""
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
        if "macroenabled" in ctype or "vbaproject" in ctype:
            raise _Deny(MACRO_PRESENT)
        if "oleobject" in ctype or "externallink" in ctype:
            raise _Deny(EXTERNAL_LINK)


def _relationships(root: _Node) -> dict[str, tuple[str, str]]:
    rels: dict[str, tuple[str, str]] = {}
    for node in root.children:
        if node.attrs.get("TargetMode", "").lower() == "external":
            raise _Deny(EXTERNAL_LINK)
        rtype = node.attrs.get("Type", "").lower()
        if rtype.endswith("/vbaproject"):
            raise _Deny(MACRO_PRESENT)
        if rtype.endswith(("/oleobject", "/externallink", "/externallinkpath")):
            raise _Deny(EXTERNAL_LINK)
        rels[node.attrs.get("Id", "")] = (rtype, node.attrs.get("Target", ""))
    return rels


def _resolve(base_dir: str, target: str) -> str:
    joined = target[1:] if target.startswith("/") else f"{base_dir}/{target}"
    path = normpath(joined)
    if path.startswith(("..", "/")):
        raise _Deny(PATH_TRAVERSAL_MEMBER)
    return path


_CELL_REF = re.compile(r"([A-Z]{1,3})[0-9]{1,7}")


def _column(ref: str) -> int:
    match = _CELL_REF.fullmatch(ref)
    if match is None:
        raise _Deny(MALFORMED_XML)
    col = 0
    for ch in match.group(1):
        col = col * 26 + (ord(ch) - 64)
    if col > 16_384:
        raise _Deny(MALFORMED_XML)
    return col - 1


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
            if not value.isascii() or not value.isdigit() or int(value) >= len(sst):
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
    data = root.child("sheetData")
    rows: list[tuple[str | None, ...]] = []
    if data is None:
        return ()
    last = 0
    for row in data.children:
        if row.tag != "row":
            continue
        budget.check()
        raw_r = row.attrs.get("r")
        if raw_r is None:
            number = last + 1
        elif raw_r.isascii() and raw_r.isdigit():
            number = int(raw_r)
        else:
            raise _Deny(MALFORMED_XML)
        if number <= last:
            raise _Deny(MALFORMED_XML)
        if number > limits.max_rows:
            raise _Bound(BOUND_ROWS)
        sparse: dict[int, str | None] = {}
        nxt = 0
        for cell in row.children:
            if cell.tag != "c":
                continue
            ref = cell.attrs.get("r")
            col = _column(ref) if ref is not None else nxt
            nxt = col + 1
            sparse[col] = _cell_value(cell, sst, limits, counters)
        width = max(sparse) + 1 if sparse else 0
        counters.cells += width
        if counters.cells > limits.max_cells:
            raise _Bound(BOUND_CELLS)
        rows.extend(() for _ in range(number - 1 - last))
        rows.append(tuple(sparse.get(i) for i in range(width)))
        last = number
    counters.rows += len(rows)
    return tuple(rows)


def _parse_workbook(data: bytes, limits: ParseLimits, clock: Callable[[], float]) -> ParseResult:
    counters = _Counters()
    budget = _Budget(limits, clock)
    try:
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
            if len(blob) >= _MIN_RATIO_SIZE and len(blob) / max(info.compress_size, 1) > limits.max_ratio:
                raise _Deny(ZIP_BOMB_RATIO)
            _screen_xml(blob)
            cache[info.filename] = blob
        for name, blob in cache.items():
            if name.lower().endswith(".rels"):
                _relationships(_parse_xml(blob, limits, budget))
        if "[Content_Types].xml" not in cache:
            raise _Deny(UNSUPPORTED_FORMAT)
        _check_content_types(_parse_xml(cache["[Content_Types].xml"], limits, budget))
        if "xl/workbook.xml" not in cache:
            raise _Deny(UNSUPPORTED_FORMAT)
        rels: dict[str, tuple[str, str]] = {}
        if "xl/_rels/workbook.xml.rels" in cache:
            rels = _relationships(_parse_xml(cache["xl/_rels/workbook.xml.rels"], limits, budget))
        sst: list[str] = []
        for rtype, target in rels.values():
            if rtype.endswith("/sharedstrings"):
                part = _resolve("xl", target)
                if part not in cache:
                    raise _Deny(MALFORMED_XML)
                tree = _parse_xml(cache[part], limits, budget)
                for si in tree.children:
                    budget.check()
                    text = _text(si)
                    if len(text) > limits.max_cell_chars:
                        raise _Bound(BOUND_CELL_CHARS)
                    sst.append(text)
        book = _parse_xml(cache["xl/workbook.xml"], limits, budget)
        listing = book.child("sheets")
        out: list[SheetValues] = []
        for sheet in listing.children if listing is not None else ():
            rid = sheet.attrs.get("id", "")
            if rid not in rels or not rels[rid][0].endswith("/worksheet"):
                raise _Deny(MALFORMED_XML)
            part = _resolve("xl", rels[rid][1])
            if part not in cache or part not in by_name:
                raise _Deny(MALFORMED_XML)
            tree = _parse_xml(cache[part], limits, budget)
            rows = _sheet_rows(tree, sst, limits, budget, counters)
            out.append(SheetValues(sheet.attrs.get("name", ""), rows))
        return tuple(out)


def _validate(data: object, limits: object, clock: object) -> ParseResult | bytes:
    if not isinstance(limits, ParseLimits) or not callable(clock):
        return ParseResult(Status.DENIED, INVALID_INPUT)
    if not isinstance(data, bytes | bytearray | memoryview):
        return ParseResult(Status.DENIED, INVALID_INPUT)
    if len(data) > limits.max_input_bytes:
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


def _child_main(conn: object, data: bytes, limits: ParseLimits, memory_bytes: int) -> None:
    try:
        try:
            import resource  # POSIX only

            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except (ImportError, ValueError, OSError):
            pass  # not enforced on this platform
        result = parse_workbook(data, limits=limits)
    except MemoryError:
        result = ParseResult(Status.BOUND_EXCEEDED, BOUND_MEMORY)
    conn.send(result)  # type: ignore[attr-defined]
    conn.close()  # type: ignore[attr-defined]


def run_isolated(
    data: bytes,
    *,
    limits: ParseLimits = ParseLimits(),  # noqa: B008 - frozen dataclass
    timeout_s: float = 10.0,
    memory_bytes: int = _DEFAULT_CHILD_MEMORY,
) -> ParseResult:
    """Run parse_workbook in a spawned child with a wall-clock timeout.

    The child is killed and reaped on timeout (code TIMEOUT). The timeout
    includes interpreter start-up. Memory bound: RLIMIT_AS in the child on
    POSIX only; NOT enforced on Windows.
    """
    checked = _validate(data, limits, time.monotonic)
    if isinstance(checked, ParseResult):
        return checked
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, int | float)
        or not timeout_s > 0
        or isinstance(memory_bytes, bool)
        or not isinstance(memory_bytes, int)
        or memory_bytes <= 0
    ):
        return ParseResult(Status.DENIED, INVALID_INPUT)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child_main, args=(child, checked, limits, memory_bytes), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(timeout_s):
            return ParseResult(Status.BOUND_EXCEEDED, TIMEOUT)
        try:
            received = parent.recv()
        except (EOFError, OSError):
            return ParseResult(Status.BOUND_EXCEEDED, CHILD_ABORTED)
        if not isinstance(received, ParseResult):
            return ParseResult(Status.DENIED, PARSE_FAILED)
        return replace(received)
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(5.0)
        parent.close()
