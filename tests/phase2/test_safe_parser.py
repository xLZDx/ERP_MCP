"""R2-US-027 / REQ17 safe values-only parser tests (TC079, TC080, TC081).

All fixtures are built in memory; nothing binary is committed.
"""
from __future__ import annotations

import io
import itertools
import multiprocessing
import struct
import warnings
import zipfile

import pytest

from business_ai_gateway.phase2 import safe_parser as sp
from business_ai_gateway.phase2.safe_parser import (
    ParseLimits,
    Status,
    parse_csv,
    parse_workbook,
    run_isolated,
)

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKGREL = "http://schemas.openxmlformats.org/package/2006/relationships"
MARK = "SECRETMARK"
FORMULA = "SECRETFORMULA(A1)"

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    "{extra}</Types>"
)


def _sheet_xml(rows: str) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}">'
        f"<sheetData>{rows}</sheetData></worksheet>"
    ).encode()


def make_xlsx(
    sheets: list[tuple[str, str]],
    shared: list[str] | None = None,
    extra: dict[str, bytes] | None = None,
    overrides: dict[str, bytes] | None = None,
    types_extra: str = "",
    rels_extra: str = "",
) -> bytes:
    members: dict[str, bytes] = {
        "[Content_Types].xml": CONTENT_TYPES.format(extra=types_extra).encode(),
    }
    wb_sheets = ""
    rels = ""
    for i, (name, rows) in enumerate(sheets, start=1):
        wb_sheets += f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
        rels += (
            f'<Relationship Id="rId{i}" Type="{RELNS}/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
        )
        members[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(rows)
    if shared is not None:
        items = "".join(f"<si><t>{s}</t></si>" for s in shared)
        members["xl/sharedStrings.xml"] = (
            f'<sst xmlns="{MAIN}">{items}</sst>'.encode()
        )
        rels += (
            f'<Relationship Id="rIdS" Type="{RELNS}/sharedStrings" '
            'Target="sharedStrings.xml"/>'
        )
    members["xl/workbook.xml"] = (
        f'<workbook xmlns="{MAIN}" xmlns:r="{RELNS}"><sheets>{wb_sheets}</sheets></workbook>'
    ).encode()
    members["xl/_rels/workbook.xml.rels"] = (
        f'<Relationships xmlns="{PKGREL}">{rels}{rels_extra}</Relationships>'
    ).encode()
    members.update(extra or {})
    members.update(overrides or {})
    return zip_bytes(members)


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, blob in members.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.filename = name  # bypass os.sep normalisation
            zf.writestr(info, blob)
    return buf.getvalue()


def patch_directory(data: bytes, name: str, offset: int, fmt: str, value: int) -> bytes:
    """Patch a field of the central-directory header of member ``name``."""
    raw = name.encode()
    pos = -1
    while True:
        pos = data.find(b"PK\x01\x02", pos + 1)
        assert pos >= 0, "member not found"
        if data[pos + 46 : pos + 46 + len(raw)] == raw:
            break
    out = bytearray(data)
    out[pos + offset : pos + offset + struct.calcsize(fmt)] = struct.pack(fmt, value)
    return bytes(out)


NORMAL_ROWS = (
    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>1.10</v></c></row>'
    f'<row r="2"><c r="A2"><f>{FORMULA}</f><v>42</v></c><c r="B2"><f>{FORMULA}</f></c></row>'
    '<row r="3"><c r="A3" t="inlineStr"><is><t>inline</t></is></c></row>'
)


def normal_book() -> bytes:
    return make_xlsx(
        [("First", NORMAL_ROWS), ("Second", '<row r="1"><c r="A1"><v>7</v></c></row>')],
        shared=["shared text"],
    )


def assert_denied(result: sp.ParseResult, code: str) -> None:
    assert result.status is Status.DENIED
    assert result.code == code
    assert result.sheets == ()
    assert MARK not in repr(result)


def assert_bound(result: sp.ParseResult, code: str) -> None:
    assert result.status is Status.BOUND_EXCEEDED
    assert result.code == code
    assert result.sheets == ()


# --- TC079 -----------------------------------------------------------------

def test_tc079_normal_workbook_values_only():
    result = parse_workbook(normal_book())
    assert result.status is Status.OK
    assert result.code == "OK"
    assert [s.name for s in result.sheets] == ["First", "Second"]
    assert result.sheets[0].rows == (
        ("shared text", "1.10"),  # number kept as literal text, no float
        ("42", None),  # cached value / no cache -> None
        ("inline",),
    )
    assert result.sheets[1].rows == (("7",),)
    assert result.stats.formula_cells == 2
    assert "SECRETFORMULA" not in repr(result)


def test_tc079_sparse_rows_and_columns_are_positioned():
    rows = '<row r="2"><c r="C2"><v>x</v></c></row><row r="4"><c r="A4"><v>y</v></c></row>'
    result = parse_workbook(make_xlsx([("S", rows)]))
    assert result.status is Status.OK
    assert result.sheets[0].rows == ((), (None, None, "x"), (), ("y",))


def test_tc079_bytearray_input_is_accepted():
    assert parse_workbook(bytearray(normal_book())).status is Status.OK


# --- TC080 -----------------------------------------------------------------

DOCTYPE_LOL = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "SECRETMARK">'
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">]>'
    b"<worksheet><sheetData><row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>&lol2;</t></is></c></row></sheetData></worksheet>"
)
XXE = (
    b'<?xml version="1.0"?><!DOCTYPE s [<!ENTITY xxe SYSTEM "file:///SECRETMARK">]>'
    b"<sst><si><t>&xxe;</t></si></sst>"
)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (make_xlsx([("S", NORMAL_ROWS)], extra={"xl/vbaProject.bin": b"SECRETMARK"}), sp.MACRO_PRESENT),
        (make_xlsx([("S", NORMAL_ROWS)], extra={"xl/vbaProjectSignature.bin": b"x"}), sp.MACRO_PRESENT),
        (make_xlsx([("S", NORMAL_ROWS)], extra={"xl/other.bin": b"x"}), sp.MACRO_PRESENT),
        (
            make_xlsx(
                [("S", NORMAL_ROWS)],
                types_extra='<Override PartName="/xl/workbook.xml" ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/>',
            ),
            sp.MACRO_PRESENT,
        ),
        (make_xlsx([("S", NORMAL_ROWS)], overrides={"xl/worksheets/sheet1.xml": DOCTYPE_LOL}), sp.XML_DTD_OR_ENTITY),
        (make_xlsx([("S", NORMAL_ROWS)], shared=["a"], overrides={"xl/sharedStrings.xml": XXE}), sp.XML_DTD_OR_ENTITY),
        (
            make_xlsx(
                [("S", NORMAL_ROWS)],
                overrides={"xl/worksheets/sheet1.xml": DOCTYPE_LOL.replace(b"<!DOCTYPE", b"<!doctype")},
            ),
            sp.XML_DTD_OR_ENTITY,
        ),
        (
            make_xlsx(
                [("S", NORMAL_ROWS)],
                rels_extra='<Relationship Id="rIdX" Type="http://x/hyperlink" Target="http://SECRETMARK" TargetMode="External"/>',
            ),
            sp.EXTERNAL_LINK,
        ),
        (make_xlsx([("S", NORMAL_ROWS)], extra={"xl/externalLinks/externalLink1.xml": b"<x/>"}), sp.EXTERNAL_LINK),
        (make_xlsx([("S", NORMAL_ROWS)], extra={"xl/embeddings/oleObject1.bin": b"x"}), sp.EXTERNAL_LINK),
        (
            make_xlsx(
                [("S", NORMAL_ROWS)],
                rels_extra=f'<Relationship Id="rIdO" Type="{RELNS}/oleObject" Target="o.dat"/>',
            ),
            sp.EXTERNAL_LINK,
        ),
        (
            make_xlsx([("S", '<row r="1"><c r="A1"><v>1</v></c></row><ddeLink/>')]),
            sp.EXTERNAL_LINK,
        ),
        (b"not a zip SECRETMARK", sp.NOT_A_ZIP),
        (b"", sp.NOT_A_ZIP),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"SECRETMARK", sp.UNSUPPORTED_FORMAT),
        (zip_bytes({"hello.txt": b"x"}), sp.UNSUPPORTED_FORMAT),
        (
            make_xlsx([("S", NORMAL_ROWS)], overrides={"xl/worksheets/sheet1.xml": b"<worksheet><sheetData>SECRETMARK"}),
            sp.MALFORMED_XML,
        ),
        (
            make_xlsx([("S", NORMAL_ROWS)], overrides={"xl/worksheets/sheet1.xml": "<w>SECRETMARK</w>".encode("utf-16")}),
            sp.MALFORMED_XML,
        ),
    ],
)
def test_tc080_hostile_input_denied_with_fixed_code(data, code):
    assert_denied(parse_workbook(data), code)


@pytest.mark.parametrize(
    "name",
    ["../SECRETMARK.xml", "xl/../../SECRETMARK.xml", "/SECRETMARK.xml", "C:/SECRETMARK.xml", "..\\SECRETMARK.xml"],
)
def test_tc080_path_traversal_member_denied(name):
    data = make_xlsx([("S", NORMAL_ROWS)], extra={name: b"x"})
    assert_denied(parse_workbook(data), sp.PATH_TRAVERSAL_MEMBER)


def test_tc080_duplicate_member_names_denied():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        zf.writestr("xl/workbook.xml", b"<a/>")
        zf.writestr("xl/workbook.xml", b"<b/>")
    assert_denied(parse_workbook(buf.getvalue()), sp.PATH_TRAVERSAL_MEMBER)


def test_tc080_case_variant_duplicate_denied():
    data = zip_bytes({"xl/workbook.xml": b"<a/>", "XL/Workbook.xml": b"<b/>"})
    assert_denied(parse_workbook(data), sp.PATH_TRAVERSAL_MEMBER)


def test_tc080_encrypted_flag_denied():
    data = patch_directory(normal_book(), "xl/workbook.xml", 8, "<H", 0x1 | 0x8)
    assert_denied(parse_workbook(data), sp.ENCRYPTED_MEMBER)


def test_tc080_zip_bomb_high_ratio_denied():
    bomb = make_xlsx([("S", NORMAL_ROWS)], extra={"xl/media/pad.xml": b"\x00" * 3_000_000})
    assert_denied(parse_workbook(bomb), sp.ZIP_BOMB_RATIO)


def test_tc080_total_uncompressed_cap_denied():
    data = make_xlsx([("S", NORMAL_ROWS)], extra={"xl/pad.xml": b"<a>" + b"x" * 5000 + b"</a>"})
    limits = ParseLimits(max_total_uncompressed=2000, max_member_uncompressed=2000)
    assert parse_workbook(data, limits=limits).status is Status.DENIED


def test_tc080_member_too_large_denied():
    data = make_xlsx([("S", NORMAL_ROWS)], extra={"xl/pad.xml": b"<a>" + bytes(range(256)) * 20 + b"</a>"})
    result = parse_workbook(data, limits=ParseLimits(max_member_uncompressed=1000))
    assert_denied(result, sp.MEMBER_TOO_LARGE)


def test_tc080_too_many_members_denied():
    extra = {f"xl/extra{i}.xml": b"<a/>" for i in range(10)}
    result = parse_workbook(make_xlsx([("S", NORMAL_ROWS)], extra=extra), limits=ParseLimits(max_members=5))
    assert_denied(result, sp.TOO_MANY_MEMBERS)


def test_tc080_lying_directory_size_cannot_bypass_the_limit():
    body = b"<a>" + b"abcdefgh" * 1000 + b"</a>"
    data = make_xlsx([("S", NORMAL_ROWS)], extra={"xl/pad.xml": body})
    lying = patch_directory(data, "xl/pad.xml", 24, "<I", 10)
    result = parse_workbook(lying)
    assert result.status is Status.DENIED
    assert result.code == sp.NOT_A_ZIP  # truncated stream fails the CRC check
    assert result.sheets == ()


def test_tc080_bounded_reader_reads_at_most_limit_plus_one():
    blob = zip_bytes({"xl/pad.xml": b"x" * 5000})
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        info = zf.infolist()[0]
        assert len(sp._read_member(zf, info, 5000)) == 5000
        with pytest.raises(sp._Deny) as err:
            sp._read_member(zf, info, 100)
        assert err.value.code == sp.MEMBER_TOO_LARGE


# --- TC081 -----------------------------------------------------------------

def _wide_book(n_cells: int) -> bytes:
    cells = "".join(f'<c r="{chr(65 + i)}1"><v>1</v></c>' for i in range(n_cells))
    return make_xlsx([("S", f'<row r="1">{cells}</row>')])


@pytest.mark.parametrize(
    ("data", "tight", "loose", "code"),
    [
        (
            make_xlsx([("S", '<row r="10"><c r="A10"><v>1</v></c></row>')]),
            ParseLimits(max_rows=5),
            ParseLimits(max_rows=10),
            sp.BOUND_ROWS,
        ),
        (_wide_book(3), ParseLimits(max_cells=2), ParseLimits(max_cells=3), sp.BOUND_CELLS),
        (
            make_xlsx([("S", '<row r="1"><c r="A1" t="inlineStr"><is><t>' + "z" * 50 + "</t></is></c></row>")]),
            ParseLimits(max_cell_chars=10),
            ParseLimits(max_cell_chars=50),
            sp.BOUND_CELL_CHARS,
        ),
        (normal_book(), ParseLimits(max_xml_depth=4), ParseLimits(max_xml_depth=8), sp.BOUND_XML_DEPTH),
    ],
)
def test_tc081_each_bound_fails_and_larger_limit_passes(data, tight, loose, code):
    assert_bound(parse_workbook(data, limits=tight), code)
    assert parse_workbook(data, limits=loose).status is Status.OK


def test_tc081_sparse_wide_row_counts_padding_cells():
    data = make_xlsx([("S", '<row r="1"><c r="XFD1"><v>1</v></c></row>')])
    assert_bound(parse_workbook(data, limits=ParseLimits(max_cells=1000)), sp.BOUND_CELLS)


def test_tc081_input_bytes_bound():
    data = normal_book()
    assert_bound(parse_workbook(data, limits=ParseLimits(max_input_bytes=100)), sp.BOUND_INPUT_BYTES)
    assert parse_workbook(data, limits=ParseLimits(max_input_bytes=len(data))).status is Status.OK


def test_tc081_deadline_with_injected_clock():
    data = normal_book()
    ticks = itertools.count()
    slow = parse_workbook(data, limits=ParseLimits(deadline_seconds=0.5), clock=lambda: float(next(ticks)))
    assert_bound(slow, sp.BOUND_DEADLINE)
    fast = parse_workbook(data, limits=ParseLimits(deadline_seconds=0.5), clock=lambda: 0.0)
    assert fast.status is Status.OK


# --- input validation ------------------------------------------------------

@pytest.mark.parametrize("bad", [None, "text", 5, ["a"], {"a": 1}])
def test_wrong_data_types_get_fixed_code(bad):
    for fn in (parse_workbook, parse_csv):
        result = fn(bad)
        assert (result.status, result.code, result.sheets) == (Status.DENIED, sp.INVALID_INPUT, ())


def test_wrong_limits_type_gets_fixed_code():
    result = parse_workbook(b"x", limits="loose")  # type: ignore[arg-type]
    assert (result.status, result.code) == (Status.DENIED, sp.INVALID_INPUT)


@pytest.mark.parametrize(
    "kwargs",
    [{"max_rows": 0}, {"max_cells": -1}, {"max_ratio": 0}, {"deadline_seconds": 0}, {"max_xml_depth": True}, {"max_cell_chars": 1.5}],
)
def test_limits_are_validated_positive(kwargs):
    with pytest.raises(ValueError):
        ParseLimits(**kwargs)


# --- CSV -------------------------------------------------------------------

def test_csv_values_only_and_formula_chars_counted_not_stripped():
    result = parse_csv(b"a,b\r\n=SUM(A1),+1\r\n@x,-2\r\n")
    assert result.status is Status.OK
    assert result.sheets[0].rows == (("a", "b"), ("=SUM(A1)", "+1"), ("@x", "-2"))
    assert result.stats.leading_formula_chars == 4
    assert result.stats.rows == 3


def test_csv_bom_and_quotes():
    result = parse_csv(b'\xef\xbb\xbf"a,1","b""c"\n')
    assert result.sheets[0].rows == (("a,1", 'b"c'),)


@pytest.mark.parametrize(
    ("data", "code"),
    [(b"a,\xff\n", sp.CSV_NOT_UTF8), (b"a,b\x00\n", sp.CSV_NUL_BYTE), (b'"a"b,c\n', sp.CSV_MALFORMED)],
)
def test_csv_denials(data, code):
    assert_denied(parse_csv(data), code)


@pytest.mark.parametrize(
    ("data", "tight", "loose", "code"),
    [
        (b"a\nb\nc\n", ParseLimits(max_rows=2), ParseLimits(max_rows=3), sp.BOUND_ROWS),
        (b"a,b,c\n", ParseLimits(max_cells=2), ParseLimits(max_cells=3), sp.BOUND_CELLS),
        (b"abcdefghij\n", ParseLimits(max_cell_chars=5), ParseLimits(max_cell_chars=10), sp.BOUND_CELL_CHARS),
        (b"abc\n", ParseLimits(max_input_bytes=2), ParseLimits(max_input_bytes=4), sp.BOUND_INPUT_BYTES),
    ],
)
def test_csv_bounds_and_positive_controls(data, tight, loose, code):
    assert_bound(parse_csv(data, limits=tight), code)
    assert parse_csv(data, limits=loose).status is Status.OK


def test_csv_deadline_with_injected_clock():
    ticks = itertools.count()
    result = parse_csv(b"a\n", limits=ParseLimits(deadline_seconds=0.5), clock=lambda: float(next(ticks)))
    assert_bound(result, sp.BOUND_DEADLINE)


# --- isolation (real child processes) ---------------------------------------

def test_run_isolated_normal_case_matches_in_process():
    data = normal_book()
    result = run_isolated(data, timeout_s=120.0)
    assert result == parse_workbook(data)


def test_run_isolated_timeout_kills_and_reaps_child():
    result = run_isolated(normal_book(), timeout_s=0.001)
    assert_bound(result, sp.TIMEOUT)
    assert multiprocessing.active_children() == []


def test_run_isolated_bad_arguments_get_fixed_codes():
    assert run_isolated("x").code == sp.INVALID_INPUT  # type: ignore[arg-type]
    assert run_isolated(b"x", timeout_s=0).code == sp.INVALID_INPUT
    assert_bound(run_isolated(b"x" * 20, limits=ParseLimits(max_input_bytes=10)), sp.BOUND_INPUT_BYTES)
