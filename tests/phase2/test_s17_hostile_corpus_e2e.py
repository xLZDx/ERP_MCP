"""S17 hostile-document corpus at the parser process boundary.

Every workbook is constructed in memory; no external file, network target, or 1C endpoint is used.
"""
from __future__ import annotations

import io
import multiprocessing
import socket
import struct
import warnings
import zipfile

import pytest

from business_ai_gateway.phase2.intake_extraction import ExtractionState, UploadFormat, extract_upload
from business_ai_gateway.phase2.safe_parser import ParseLimits, Status, parse_csv, parse_workbook, run_isolated

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES = (
    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>{extra}</Types>'
)
SECRET_FORMULA = "S17_SECRET_FORMULA(A1)"


def _xlsx(*, sheet_state: str = "visible", row_hidden: str | None = None,
          column_hidden: str | None = None, sheet_xml: bytes | None = None,
          extra: dict[str, bytes] | None = None, relationship: str = "",
          type_extra: str = "") -> bytes:
    row_attrs = "" if row_hidden is None else f' hidden="{row_hidden}"'
    col_xml = "" if column_hidden is None else f'<cols><col min="1" max="1" hidden="{column_hidden}"/></cols>'
    worksheet = sheet_xml or (
        f'<worksheet xmlns="{MAIN}">{col_xml}<sheetData><row r="1"{row_attrs}>'
        '<c r="A1"><v>42</v></c></row></sheetData></worksheet>'
    ).encode()
    workbook = (
        f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets><sheet name="Data" '
        f'sheetId="1" state="{sheet_state}" r:id="rId1"/></sheets></workbook>'
    ).encode()
    members = {
        "[Content_Types].xml": CONTENT_TYPES.format(extra=type_extra).encode(),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
            f'Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>{relationship}</Relationships>'
        ).encode(),
        "xl/worksheets/sheet1.xml": worksheet,
    }
    members.update(extra or {})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for name, value in members.items():
            archive.writestr(name, value)
    return output.getvalue()


def _mark_encrypted(data: bytes) -> bytes:
    out = bytearray(data)
    local = out.find(b"PK\x03\x04")
    central = out.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    for start, offset in ((local, 6), (central, 8)):
        flags = struct.unpack_from("<H", out, start + offset)[0]
        struct.pack_into("<H", out, start + offset, flags | 1)
    return bytes(out)


def _assert_denied(data: bytes, code: str, *, limits: ParseLimits = ParseLimits()) -> None:
    result = parse_workbook(data, limits=limits)
    assert result.status is Status.DENIED
    assert result.code == code
    assert result.sheets == ()


def test_H01_clean_csv_and_xlsx_produce_nonempty_review_only_values():
    csv_data = b"invoice_number,amount\nINV-S17-01,12.40\n"
    xlsx_data = _xlsx()
    for data, source_format in ((csv_data, UploadFormat.CSV), (xlsx_data, UploadFormat.XLSX)):
        result = extract_upload(data, source_format)
        assert result.state is ExtractionState.REVIEW_REQUIRED
        assert result.values
        assert result.source_sha256
        assert all(value.provenance.source_sha256 == result.source_sha256 for value in result.values)
        assert all(value.provenance.row_number > 0 and value.provenance.column_number > 0
                   for value in result.values)
        assert result.proposal_allowed is False


def test_H02_formula_text_is_not_returned_or_evaluated():
    sheet = (
        f'<worksheet xmlns="{MAIN}"><sheetData><row r="1"><c r="A1"><f>{SECRET_FORMULA}</f>'
        '<v>42</v></c></row></sheetData></worksheet>'
    ).encode()
    result = extract_upload(_xlsx(sheet_xml=sheet), UploadFormat.XLSX)
    assert result.state is ExtractionState.REVIEW_REQUIRED
    assert [value.text for value in result.values] == ["42"]
    assert SECRET_FORMULA not in repr(result)
    assert result.proposal_allowed is False


@pytest.mark.parametrize("literal", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\t=1+1", "\r=1+1"])
def test_H03_csv_formula_prefixes_remain_literal_review_data(literal: str):
    csv_bytes = (f'"{literal}"\n' if "\r" in literal else literal + "\n").encode()
    result = parse_csv(csv_bytes)
    assert result.status is Status.OK
    assert result.sheets[0].rows == ((literal,),)
    assert result.stats.leading_formula_chars == 1
    extracted = extract_upload(csv_bytes, UploadFormat.CSV)
    assert extracted.state is ExtractionState.REVIEW_REQUIRED
    assert extracted.values[0].text == literal
    assert extracted.proposal_allowed is False


def test_H04_external_relationship_is_denied_before_any_fetch():
    link = (f'<Relationship Id="rId2" Type="{REL}/hyperlink" '
            'Target="https://invalid.example/resource" TargetMode="External"/>')
    _assert_denied(_xlsx(relationship=link), "EXTERNAL_LINK")


@pytest.mark.parametrize("name", ["xl/vbaProject.bin", "xl/macrosheets/sheet1.xml"])
def test_H05_macro_parts_are_denied(name: str):
    _assert_denied(_xlsx(extra={name: b"not executable"}), "MACRO_PRESENT")


def test_H06_traversal_member_is_denied_without_disk_extraction():
    _assert_denied(_xlsx(extra={"../outside.txt": b"sentinel"}), "PATH_TRAVERSAL_MEMBER")


def test_H07_encrypted_member_is_denied():
    _assert_denied(_mark_encrypted(_xlsx()), "ENCRYPTED_MEMBER")


def test_H08a_member_size_bound_is_enforced():
    result = parse_workbook(_xlsx(), limits=ParseLimits(max_member_uncompressed=16))
    assert result.status is Status.DENIED
    assert result.code == "MEMBER_TOO_LARGE"
    assert result.sheets == ()


def test_H08b_total_decompression_bound_is_enforced():
    result = parse_workbook(_xlsx(), limits=ParseLimits(max_total_uncompressed=16))
    assert result.status is Status.DENIED
    assert result.code == "ZIP_BOMB_RATIO"
    assert result.sheets == ()


def test_H09_malformed_xml_returns_fixed_denial_without_partial_sheets():
    result = parse_workbook(_xlsx(sheet_xml=b"<worksheet><sheetData><broken></worksheet>"))
    assert result.status is Status.DENIED
    assert result.code in {"MALFORMED_XML", "PARSE_FAILED"}
    assert result.sheets == ()
    assert b"broken" not in repr(result).encode()


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"sheet_state": "hidden"}, "HIDDEN_CONTENT"),
        ({"sheet_state": "veryHidden"}, "HIDDEN_CONTENT"),
        ({"row_hidden": "1"}, "HIDDEN_CONTENT"),
        ({"column_hidden": "true"}, "HIDDEN_CONTENT"),
        ({"row_hidden": "perhaps"}, "MALFORMED_XML"),
        ({"column_hidden": "perhaps"}, "MALFORMED_XML"),
    ],
)
def test_H10_hidden_or_malformed_visibility_has_no_partial_output(kwargs, expected):
    _assert_denied(_xlsx(**kwargs), expected)


def test_H12_external_link_does_not_reach_local_canary_or_modify_sentinel(tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    original = b"unchanged S17 sentinel\n"
    sentinel.write_bytes(original)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        link = (f'<Relationship Id="rId2" Type="{REL}/hyperlink" '
                f'Target="http://127.0.0.1:{port}/canary" TargetMode="External"/>')
        result = run_isolated(_xlsx(relationship=link), timeout_s=30.0)
        assert result.status is Status.DENIED
        assert result.code == "EXTERNAL_LINK"
        assert result.sheets == ()
        try:
            connection, _ = listener.accept()
        except BlockingIOError:
            pass
        else:
            connection.close()
            pytest.fail("parser followed the external relationship to the local canary")
        assert not multiprocessing.active_children(), "parser child remained alive after completion"
        assert sentinel.read_bytes() == original
    finally:
        listener.close()
