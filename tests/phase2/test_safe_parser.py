"""R2-US-027 / REQ17 safe values-only parser tests (TC079, TC080, TC081).

All fixtures are built in memory; nothing binary is committed.
"""
from __future__ import annotations

import array
import base64
import io
import itertools
import json
import multiprocessing
import random
import struct
import sys
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
        (make_xlsx([("S", NORMAL_ROWS)], extra={"xl/other.bin": b"x"}), sp.UNSUPPORTED_FORMAT),
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


def _pad(n: int, seed: int = 1) -> bytes:
    """Deterministic, barely compressible, NUL-free XML-ish member of about n bytes."""
    raw = random.Random(seed).randbytes(n * 3 // 4 + 1)
    return b"<a>" + base64.b64encode(raw)[:n] + b"</a>"


def test_tc080_lying_directory_size_is_a_crc_failure():
    """A directory size smaller than the real stream truncates the read; CRC fails."""
    body = b"<a>" + b"abcdefgh" * 1000 + b"</a>"
    data = make_xlsx([("S", NORMAL_ROWS)], extra={"xl/pad.xml": body})
    lying = patch_directory(data, "xl/pad.xml", 24, "<I", 10)
    assert_denied(parse_workbook(lying), sp.NOT_A_ZIP)


def test_tc080_members_each_under_member_cap_but_over_total_cap():
    extra = {f"xl/pad{i}.xml": _pad(1500, i) for i in range(4)}
    data = make_xlsx([("S", NORMAL_ROWS)], shared=["x"], extra=extra)
    tight = ParseLimits(max_member_uncompressed=2000, max_total_uncompressed=5000)
    assert_denied(parse_workbook(data, limits=tight), sp.ZIP_BOMB_RATIO)
    loose = ParseLimits(max_member_uncompressed=2000)  # default 50 MB total
    assert parse_workbook(data, limits=loose).status is Status.OK


def test_tc080_member_count_at_limit_passes_and_one_over_denied():
    extra = {f"xl/extra{i}.xml": b"<a/>" for i in range(6)}
    data = make_xlsx([("S", NORMAL_ROWS)], shared=["x"], extra=extra)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        count = len(zf.namelist())
    assert_denied(parse_workbook(data, limits=ParseLimits(max_members=count - 1)), sp.TOO_MANY_MEMBERS)
    assert parse_workbook(data, limits=ParseLimits(max_members=count)).status is Status.OK


def test_tc080_member_size_at_limit_passes_and_one_over_denied():
    pad = _pad(1200)
    data = make_xlsx([("S", NORMAL_ROWS)], shared=["x"], extra={"xl/pad.xml": pad})
    assert_denied(
        parse_workbook(data, limits=ParseLimits(max_member_uncompressed=len(pad) - 1)),
        sp.MEMBER_TOO_LARGE,
    )
    assert parse_workbook(data, limits=ParseLimits(max_member_uncompressed=len(pad))).status is Status.OK


def test_tc080_backslash_member_name_denied_on_every_platform():
    data = make_xlsx([("S", NORMAL_ROWS)], extra={r"xl\evil.xml": b"<a/>"})
    assert_denied(parse_workbook(data), sp.PATH_TRAVERSAL_MEMBER)


def test_tc080_printer_settings_bin_is_harmless_other_bin_unsupported():
    ok = make_xlsx([("S", NORMAL_ROWS)], shared=["x"], extra={"xl/printerSettings/printerSettings1.bin": b"x"})
    assert parse_workbook(ok).status is Status.OK
    bad = make_xlsx([("S", NORMAL_ROWS)], extra={"xl/printerSettings/vbaProject.bin": b"x"})
    assert_denied(parse_workbook(bad), sp.MACRO_PRESENT)


@pytest.mark.parametrize(
    "ctype",
    [
        "application/vnd.openxmlformats-officedocument.oleObject",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.externalLink+xml",
        "application/vnd.ms-office.activeX+xml",
    ],
)
def test_tc080_external_content_types_denied(ctype):
    extra = f'<Override PartName="/xl/x.xml" ContentType="{ctype}"/>'
    assert_denied(parse_workbook(make_xlsx([("S", NORMAL_ROWS)], types_extra=extra)), sp.EXTERNAL_LINK)


@pytest.mark.parametrize("name", sorted(sp._FORBIDDEN_ELEMENTS))
def test_tc080_forbidden_elements_denied(name):
    data = make_xlsx([("S", f'<row r="1"><c r="A1"><v>1</v></c></row><{name}/>')])
    assert_denied(parse_workbook(data), sp.EXTERNAL_LINK)


def test_tc080_workbook_external_reference_denied():
    wb = (
        f'<workbook xmlns="{MAIN}" xmlns:r="{RELNS}"><sheets><sheet name="S" sheetId="1" r:id="rId1"/>'
        '</sheets><externalReferences><externalReference r:id="rId9"/></externalReferences></workbook>'
    ).encode()
    data = make_xlsx([("S", NORMAL_ROWS)], overrides={"xl/workbook.xml": wb})
    assert_denied(parse_workbook(data), sp.EXTERNAL_LINK)


def test_tc080_vbaproject_relationship_type_denied():
    extra = f'<Relationship Id="rIdV" Type="{RELNS}/vbaProject" Target="vbaProject.bin"/>'
    assert_denied(parse_workbook(make_xlsx([("S", NORMAL_ROWS)], rels_extra=extra)), sp.MACRO_PRESENT)


@pytest.mark.parametrize("target", ["../../evil.xml", "/../evil.xml"])
def test_tc080_relationship_target_traversal_denied(target):
    rels = (
        f'<Relationships xmlns="{PKGREL}"><Relationship Id="rId1" Type="{RELNS}/worksheet" '
        f'Target="{target}"/></Relationships>'
    ).encode()
    data = make_xlsx([("S", NORMAL_ROWS)], overrides={"xl/_rels/workbook.xml.rels": rels})
    assert_denied(parse_workbook(data), sp.PATH_TRAVERSAL_MEMBER)


def test_tc080_duplicate_relationship_id_and_two_shared_string_parts_denied():
    dup = f'<Relationship Id="rId1" Type="{RELNS}/hyperlink" Target="x"/>'
    assert_denied(parse_workbook(make_xlsx([("S", NORMAL_ROWS)], rels_extra=dup)), sp.MALFORMED_XML)
    second = f'<Relationship Id="rIdT" Type="{RELNS}/sharedStrings" Target="sharedStrings.xml"/>'
    two = make_xlsx([("S", NORMAL_ROWS)], shared=["a"], rels_extra=second)
    assert_denied(parse_workbook(two), sp.MALFORMED_XML)


def test_tc080_attribute_namespace_collision_denied():
    rows = '<row xmlns:a="urn:x" r="1" a:r="2"><c r="A1"><v>1</v></c></row>'
    assert_denied(parse_workbook(make_xlsx([("S", rows)])), sp.MALFORMED_XML)

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


# --- structure / bounds added in the S5 fix batch ---------------------------

def _cell_row(n: int) -> str:
    return f'<row r="{n}"><c r="A{n}"><v>1</v></c></row>'


def _dup_part_book(count: int, rows: str) -> bytes:
    sheets = "".join(f'<sheet name="D{i}" sheetId="{i}" r:id="rId{i}"/>' for i in range(1, count + 1))
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="{RELNS}/worksheet" Target="worksheets/sheet1.xml"/>'
        for i in range(1, count + 1)
    )
    wb = f'<workbook xmlns="{MAIN}" xmlns:r="{RELNS}"><sheets>{sheets}</sheets></workbook>'.encode()
    rel_xml = f'<Relationships xmlns="{PKGREL}">{rels}</Relationships>'.encode()
    return make_xlsx(
        [("S", rows)], overrides={"xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rel_xml}
    )


def test_tc081_same_part_referenced_by_many_sheets_is_denied():
    sparse = _cell_row(100_000)
    assert parse_workbook(_dup_part_book(1, sparse)).status is Status.OK  # positive control
    for count in (2, 64):
        assert_denied(parse_workbook(_dup_part_book(count, sparse)), sp.MALFORMED_XML)
    assert_bound(parse_workbook(_dup_part_book(3000, sparse)), sp.BOUND_SHEETS)


def test_tc081_sheet_count_cap():
    data = make_xlsx([(f"S{i}", _cell_row(1)) for i in range(65)])
    assert_bound(parse_workbook(data), sp.BOUND_SHEETS)  # default max_sheets=64
    assert parse_workbook(data, limits=ParseLimits(max_sheets=65)).status is Status.OK


def test_tc081_row_cap_is_across_all_sheets():
    data = make_xlsx([("A", _cell_row(6)), ("B", _cell_row(6))])
    assert_bound(parse_workbook(data, limits=ParseLimits(max_rows=10)), sp.BOUND_ROWS)
    assert parse_workbook(data, limits=ParseLimits(max_rows=12)).status is Status.OK


def test_tc081_padding_rows_count_against_max_cells():
    data = make_xlsx([("S", _cell_row(500))])  # 499 padding rows + 1 cell
    assert_bound(parse_workbook(data, limits=ParseLimits(max_cells=100)), sp.BOUND_CELLS)
    assert parse_workbook(data, limits=ParseLimits(max_cells=500)).status is Status.OK


def test_tc081_xml_node_budget():
    cells = "".join(f"<c><v>{i}</v></c>" for i in range(6000))  # about 12000 elements
    data = make_xlsx([("S", f'<row r="1">{cells}</row>')])
    assert_bound(parse_workbook(data, limits=ParseLimits(max_cells=1)), sp.BOUND_XML_NODES)
    assert parse_workbook(data, limits=ParseLimits(max_cells=10_000)).status is Status.OK


@pytest.mark.parametrize(
    "rows",
    [
        _cell_row(2) + _cell_row(1),  # backwards rows
        _cell_row(2) + _cell_row(2),  # repeated rows
        '<row r="1"><c r="B1"><v>1</v></c><c r="A1"><v>2</v></c></row>',  # backwards columns
        '<row r="1"><c r="A1"><v>1</v></c><c r="A1"><v>2</v></c></row>',  # repeated cell
        '<row r="1"><c r="A2"><v>1</v></c></row>',  # cell row differs from enclosing row
        '<row r="' + "9" * 5000 + '"><c><v>1</v></c></row>',  # huge digit string
    ],
)
def test_tc080_inconsistent_row_and_cell_addresses_denied(rows):
    assert_denied(parse_workbook(make_xlsx([("S", rows)])), sp.MALFORMED_XML)


@pytest.mark.parametrize("index", ["5", "-1", "9" * 5000, "x"])
def test_tc080_shared_string_index_out_of_range_denied(index):
    rows = f'<row r="1"><c r="A1" t="s"><v>{index}</v></c></row>'
    assert_denied(parse_workbook(make_xlsx([("S", rows)], shared=["a"])), sp.MALFORMED_XML)


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
@pytest.mark.parametrize("name", ["max_ratio", "deadline_seconds"])
def test_limits_reject_non_finite_numbers(name, bad):
    with pytest.raises(ValueError):
        ParseLimits(**{name: bad})


def test_memoryview_size_is_measured_in_bytes():
    view = memoryview(array.array("I", [0] * 10))  # 10 items, 40 bytes
    assert_bound(parse_workbook(view, limits=ParseLimits(max_input_bytes=20)), sp.BOUND_INPUT_BYTES)


def test_clock_failure_is_a_fixed_code_not_an_exception():
    def broken() -> float:
        raise ZeroDivisionError

    assert_denied(parse_workbook(normal_book(), clock=broken), sp.PARSE_FAILED)


def test_injected_memory_error_maps_to_bound_memory(monkeypatch):
    def boom(*_a, **_k):
        raise MemoryError

    monkeypatch.setattr(sp, "_workbook_sheets", boom)
    assert_bound(parse_workbook(normal_book()), sp.BOUND_MEMORY)
    monkeypatch.setattr(sp, "_parse_csv", boom)
    assert_bound(parse_csv(b"a\n"), sp.BOUND_MEMORY)


def test_unexpected_internal_error_maps_to_parse_failed(monkeypatch):
    def boom(*_a, **_k):
        raise KeyError(MARK)

    monkeypatch.setattr(sp, "_workbook_sheets", boom)
    assert_denied(parse_workbook(normal_book()), sp.PARSE_FAILED)


# --- more CSV --------------------------------------------------------------

def test_csv_field_larger_than_csv_module_limit_is_a_size_bound():
    data = b'"' + b"a" * 200_000 + b'"\n'
    limits = ParseLimits(max_cell_chars=1_000_000)
    assert_bound(parse_csv(data, limits=limits), sp.BOUND_CELL_CHARS)


def test_csv_empty_input_is_ok_and_has_no_rows():
    result = parse_csv(b"")
    assert result.status is Status.OK
    assert result.sheets == (sp.SheetValues("csv", ()),)
    assert result.stats.rows == 0


# --- more isolation (real child processes) ------------------------------------

_STATS = {
    "members": 0, "uncompressed_bytes": 0, "rows": 1, "cells": 2,
    "formula_cells": 0, "leading_formula_chars": 0,
}


def _doc(**override):
    doc = {
        "status": "OK", "code": "OK",
        "sheets": [{"name": "s", "rows": [["a", None]]}], "stats": dict(_STATS),
    }
    doc.update(override)
    return json.dumps(doc).encode()


def _echo_child(conn, data, _limits, _memory):
    """Test child: sends the 'workbook bytes' it was given verbatim as its answer."""
    conn.send_bytes(data)
    conn.close()


def _exit_child(_conn, _data, _limits, _memory):
    import os

    os._exit(3)


def test_run_isolated_well_formed_child_answer_is_rebuilt():
    result = run_isolated(_doc(), timeout_s=120.0, _child_target=_echo_child)
    assert result.status is Status.OK
    assert result.sheets == (sp.SheetValues("s", (("a", None),)),)
    assert result.stats.cells == 2


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfe garbage \x00",
        b"not json at all",
        b'{"status": "OK"}',  # wrong shape
        b"[]",
        _doc(status="WAT"),  # unknown enum
        _doc(code="MADE_UP"),
        _doc(code="MACRO_PRESENT"),  # status OK with a denial code
        _doc(stats={**_STATS, "rows": True}),  # bool is not a count
        _doc(stats={**_STATS, "extra": 1}),  # unknown field
        _doc(sheets=[{"name": "s", "rows": [[1]]}]),  # non-string cell
        _doc(unexpected=1),
    ],
)
def test_run_isolated_hostile_child_answer_is_child_aborted(payload):
    result = run_isolated(payload, timeout_s=120.0, _child_target=_echo_child)
    assert_bound(result, sp.CHILD_ABORTED)


def test_run_isolated_child_exit_without_answer_is_child_aborted():
    result = run_isolated(b"x", timeout_s=120.0, _child_target=_exit_child)
    assert_bound(result, sp.CHILD_ABORTED)
    assert multiprocessing.active_children() == []


def test_run_isolated_hostile_workbook_is_denied_with_exact_code():
    data = make_xlsx([("S", NORMAL_ROWS)], extra={"xl/vbaProject.bin": b"x"})
    assert_denied(run_isolated(data, timeout_s=120.0), sp.MACRO_PRESENT)


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "1"])
def test_run_isolated_bad_memory_argument_is_invalid_input(bad):
    result = run_isolated(b"x", memory_bytes=bad)  # type: ignore[arg-type]
    assert (result.status, result.code) == (Status.DENIED, sp.INVALID_INPUT)


def test_run_isolated_spawn_failure_closes_both_pipe_ends(monkeypatch):
    real = multiprocessing.get_context("spawn")
    ends = []

    class FailingProcess:
        def __init__(self, *_a, **_k):
            pass

        def start(self):
            raise BrokenPipeError

        def close(self):
            pass

    class FakeContext:
        Process = FailingProcess

        @staticmethod
        def Pipe(duplex):
            pair = real.Pipe(duplex=duplex)
            ends.extend(pair)
            return pair

    monkeypatch.setattr(sp.multiprocessing, "get_context", lambda _method: FakeContext())
    assert_bound(run_isolated(b"x"), sp.CHILD_ABORTED)
    assert len(ends) == 2
    assert all(end.closed for end in ends)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="RLIMIT_AS does not exist on Windows: the child memory bound is NOT enforced "
    "there and is reported NOT_RUN",
)
def test_run_isolated_memory_limit_posix_only():
    result = run_isolated(normal_book(), timeout_s=120.0, memory_bytes=64 << 20)
    assert result.code in (sp.BOUND_MEMORY, sp.CHILD_ABORTED)


# --- second batch: canonical attributes, text budget, active parts ----------

def test_tc080_foreign_namespace_security_attribute_denied():
    rel = (
        f'<Relationship xmlns:x="urn:x" Id="rIdX" Type="{RELNS}/hyperlink" Target="t.xml" '
        'x:TargetMode="External"/>'
    )
    assert_denied(parse_workbook(make_xlsx([("S", NORMAL_ROWS)], shared=["x"], rels_extra=rel)), sp.MALFORMED_XML)


def test_tc080_duplicate_local_attribute_denied():
    rel = (
        f'<Relationship xmlns:x="urn:x" Id="rIdX" Type="{RELNS}/hyperlink" Target="a.xml" '
        'x:Target="b.xml"/>'
    )
    assert_denied(parse_workbook(make_xlsx([("S", NORMAL_ROWS)], shared=["x"], rels_extra=rel)), sp.MALFORMED_XML)


def test_tc080_wrong_namespace_worksheet_is_unsupported():
    sheet = b'<worksheet xmlns="urn:evil"><sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>'
    data = make_xlsx([("S", NORMAL_ROWS)], shared=["x"], overrides={"xl/worksheets/sheet1.xml": sheet})
    assert_denied(parse_workbook(data), sp.UNSUPPORTED_FORMAT)


def test_tc080_wrong_namespace_row_is_unsupported():
    sheet = (
        f'<worksheet xmlns="{MAIN}"><sheetData><row xmlns="urn:evil" r="1"><c r="A1"><v>1</v></c></row>'
        "</sheetData></worksheet>"
    ).encode()
    data = make_xlsx([("S", NORMAL_ROWS)], shared=["x"], overrides={"xl/worksheets/sheet1.xml": sheet})
    assert_denied(parse_workbook(data), sp.UNSUPPORTED_FORMAT)


def test_tc081_total_text_budget_across_cells():
    text = base64.b64encode(random.Random(5).randbytes(24_576)).decode()  # 32,768 chars
    text = text[:32_767]
    rows = "".join(f'<row r="{i}"><c r="A{i}" t="s"><v>0</v></c></row>' for i in range(1, 161))
    data = make_xlsx([("S", rows)], shared=[text])
    assert_bound(parse_workbook(data), sp.BOUND_TOTAL_TEXT)  # 160 * 32,767 > 5,000,000
    assert parse_workbook(data, limits=ParseLimits(max_total_text_chars=6_000_000)).status is Status.OK
    assert_bound(parse_csv(b"abcdef\n", limits=ParseLimits(max_total_text_chars=5)), sp.BOUND_TOTAL_TEXT)


def test_limits_total_text_must_be_positive():
    with pytest.raises(ValueError):
        ParseLimits(max_total_text_chars=0)


def _stepping_clock(step: float):
    ticks = itertools.count()
    return lambda: next(ticks) * step


def test_deadline_is_checked_per_shared_string_and_per_cell():
    limits = ParseLimits(deadline_seconds=5.0)  # trips after about 500 clock reads
    strings = make_xlsx([("S", _cell_row(1))], shared=[str(i) for i in range(2000)])
    assert_bound(parse_workbook(strings, limits=limits, clock=_stepping_clock(0.01)), sp.BOUND_DEADLINE)
    assert parse_workbook(strings, limits=limits, clock=lambda: 0.0).status is Status.OK
    cells = "".join(f'<c r="{_col(i)}1"><v>1</v></c>' for i in range(2000))
    wide = make_xlsx([("S", f'<row r="1">{cells}</row>')])
    assert_bound(parse_workbook(wide, limits=limits, clock=_stepping_clock(0.01)), sp.BOUND_DEADLINE)
    assert parse_workbook(wide, limits=limits, clock=lambda: 0.0).status is Status.OK


def _col(i: int) -> str:
    name = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        name = chr(65 + rem) + name
    return name


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"xl/connections.xml": b"<connections/>"}, sp.EXTERNAL_LINK),
        ({"xl/queryTables/queryTable1.xml": b"<q/>"}, sp.EXTERNAL_LINK),
        ({"xl/webextensions/webextension1.xml": b"<w/>"}, sp.EXTERNAL_LINK),
        ({"customUI/customUI.xml": b"<c/>"}, sp.MACRO_PRESENT),
        ({"xl/macrosheets/sheet1.xml": b"<m/>"}, sp.MACRO_PRESENT),  # not listed in <sheets>
    ],
)
def test_tc080_active_or_external_parts_denied(extra, code):
    assert_denied(parse_workbook(make_xlsx([("S", NORMAL_ROWS)], shared=["x"], extra=extra)), code)


@pytest.mark.parametrize(
    ("ctype", "code"),
    [
        ("application/vnd.ms-excel.macrosheet+xml", sp.MACRO_PRESENT),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.connections+xml", sp.EXTERNAL_LINK),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.queryTable+xml", sp.EXTERNAL_LINK),
    ],
)
def test_tc080_active_content_types_denied(ctype, code):
    extra = f'<Override PartName="/xl/x.xml" ContentType="{ctype}"/>'
    data = make_xlsx([("S", NORMAL_ROWS)], shared=["x"], types_extra=extra)
    assert_denied(parse_workbook(data), code)


@pytest.mark.parametrize(
    ("rtype", "code"),
    [
        ("http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet", sp.MACRO_PRESENT),
        ("http://schemas.microsoft.com/office/2006/relationships/ui/extensibility", sp.MACRO_PRESENT),
        (f"{RELNS}/connections", sp.EXTERNAL_LINK),
        (f"{RELNS}/queryTable", sp.EXTERNAL_LINK),
    ],
)
def test_tc080_active_relationship_types_denied(rtype, code):
    rel = f'<Relationship Id="rIdX" Type="{rtype}" Target="t.xml"/>'
    assert_denied(parse_workbook(make_xlsx([("S", NORMAL_ROWS)], shared=["x"], rels_extra=rel)), code)


@pytest.mark.parametrize(
    "source",
    ['type="external" connectionId="1"', 'type="consolidation"', 'type="worksheet" connectionId="2"'],
)
def test_tc080_external_pivot_cache_denied(source):
    cache = f'<pivotCacheDefinition xmlns="{MAIN}"><cacheSource {source}/></pivotCacheDefinition>'.encode()
    data = make_xlsx(
        [("S", NORMAL_ROWS)], shared=["x"], extra={"xl/pivotCache/pivotCacheDefinition1.xml": cache}
    )
    assert_denied(parse_workbook(data), sp.EXTERNAL_LINK)


def test_tc080_worksheet_pivot_cache_is_allowed():
    cache = f'<pivotCacheDefinition xmlns="{MAIN}"><cacheSource type="worksheet"/></pivotCacheDefinition>'.encode()
    data = make_xlsx(
        [("S", NORMAL_ROWS)], shared=["x"], extra={"xl/pivotCache/pivotCacheDefinition1.xml": cache}
    )
    assert parse_workbook(data).status is Status.OK


def test_tc080_entry_count_is_checked_before_zipfile_builds_entries(monkeypatch):
    data = make_xlsx([("S", NORMAL_ROWS)], shared=["x"], extra={f"xl/e{i}.xml": b"<a/>" for i in range(10)})

    def must_not_build(*_a, **_k):
        raise RuntimeError("zipfile must not be consulted")

    monkeypatch.setattr(sp.zipfile, "ZipFile", must_not_build)
    assert_denied(parse_workbook(data, limits=ParseLimits(max_members=5)), sp.TOO_MANY_MEMBERS)


def _env_child(conn, _data, _limits, _memory):
    import os

    seen = os.environ.get("SAFE_PARSER_TEST_SECRET", "absent")
    conn.send_bytes(_doc(sheets=[{"name": seen, "rows": []}]))
    conn.close()


def test_run_isolated_child_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("SAFE_PARSER_TEST_SECRET", "hunter2")
    result = run_isolated(b"x", timeout_s=120.0, _child_target=_env_child)
    assert result.sheets[0].name == "absent"
    assert sp.os.environ["SAFE_PARSER_TEST_SECRET"] == "hunter2"  # parent restored


@pytest.mark.parametrize("error", [BrokenPipeError, AssertionError])
def test_run_isolated_start_failure_is_child_aborted(monkeypatch, error):
    real = multiprocessing.get_context("spawn")

    class FailingProcess:
        def __init__(self, *_a, **_k):
            pass

        def start(self):
            raise error("daemonic processes are not allowed to have children")

        def close(self):
            pass

    class FakeContext:
        Process = FailingProcess

        @staticmethod
        def Pipe(duplex):
            return real.Pipe(duplex=duplex)

    monkeypatch.setattr(sp.multiprocessing, "get_context", lambda _method: FakeContext())
    assert_bound(run_isolated(b"x"), sp.CHILD_ABORTED)


# --- reply read under the deadline; environment scrub is non-clobbering -----------
def _partial_frame_child(conn, _data, _limits, _memory):
    """Stall mid-reply so the parent can only escape through its deadline.

    POSIX: a raw partial length-prefixed frame (header announces 64 bytes, 2
    follow), so ``recv_bytes`` blocks inside the body read.

    Windows: ``multiprocessing`` pipes are message-mode named pipes with no
    length header; one ``WriteFile`` is one COMPLETE message, so a "partial
    frame" cannot be produced there. Writing those 6 bytes would be delivered
    as a finished (undecodable) reply and the parent would answer
    CHILD_ABORTED as soon as the child got that far, racing the 1 s deadline
    against interpreter start-up (about 0.5-1.2 s with the venv launcher and
    test-module import). So on Windows the child sends nothing at all, which
    is a deterministic stall; see the next test for the short-message case.
    """
    import time

    if sys.platform != "win32":
        import os

        os.write(conn.fileno(), b"\x00\x00\x00\x40ab")
    time.sleep(60)


def _short_message_child(conn, _data, _limits, _memory):
    import _winapi
    import time

    _winapi.WriteFile(conn.fileno(), b"\x00\x00\x00\x40ab")
    time.sleep(60)


def test_run_isolated_stalled_partial_reply_times_out_and_kills_child():
    import time

    start = time.monotonic()
    result = run_isolated(b"x", timeout_s=1.0, _child_target=_partial_frame_child)
    elapsed = time.monotonic() - start
    assert_bound(result, sp.TIMEOUT)
    assert elapsed < 10.0
    assert multiprocessing.active_children() == []


@pytest.mark.skipif(sys.platform != "win32", reason="message-mode pipes are Windows-only")
def test_run_isolated_windows_short_message_is_child_aborted_not_timeout():
    # Root cause of the former flaky failure: on Windows a 6-byte WriteFile is a
    # whole message, so an undecodable reply is CHILD_ABORTED (fail-closed), not
    # a stalled read. Generous deadline: the child always answers well before it.
    result = run_isolated(b"x", timeout_s=60.0, _child_target=_short_message_child)
    assert_bound(result, sp.CHILD_ABORTED)
    assert multiprocessing.active_children() == []


def test_scrubbed_environment_keeps_concurrent_writes_and_restores_removed(monkeypatch):
    import threading

    monkeypatch.setenv("SP_TEST_SECRET", "hunter2")
    monkeypatch.setenv("SP_TEST_REWRITTEN", "old")
    monkeypatch.delenv("SP_TEST_NEW", raising=False)

    def writer():
        sp.os.environ["SP_TEST_NEW"] = "fresh"
        sp.os.environ["SP_TEST_REWRITTEN"] = "newer"

    with sp._scrubbed_environment():
        assert "SP_TEST_SECRET" not in sp.os.environ
        t = threading.Thread(target=writer)
        t.start()
        t.join()
    assert sp.os.environ["SP_TEST_SECRET"] == "hunter2"
    assert sp.os.environ["SP_TEST_NEW"] == "fresh"
    assert sp.os.environ["SP_TEST_REWRITTEN"] == "newer"
    monkeypatch.delenv("SP_TEST_NEW")


def test_scrubbed_environment_exception_leaves_environment_intact(monkeypatch):
    monkeypatch.setenv("SP_TEST_SECRET", "hunter2")
    before = dict(sp.os.environ)
    with pytest.raises(RuntimeError), sp._scrubbed_environment():
        assert "SP_TEST_SECRET" not in sp.os.environ
        raise RuntimeError("start failed")
    assert dict(sp.os.environ) == before


def test_scrubbed_environment_interrupt_during_removal_is_undone(monkeypatch):
    monkeypatch.setenv("SP_TEST_A", "1")
    monkeypatch.setenv("SP_TEST_B", "2")
    before = dict(sp.os.environ)
    real_pop = sp.os.environ.pop
    calls = {"n": 0}

    def flaky_pop(key, *default):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return real_pop(key, *default)

    with monkeypatch.context() as inner:
        inner.setattr(sp.os.environ, "pop", flaky_pop)
        with pytest.raises(KeyboardInterrupt), sp._scrubbed_environment():
            pass
    assert dict(sp.os.environ) == before
