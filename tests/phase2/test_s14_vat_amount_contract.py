"""Focused contract tests for the required CREATE_DRAFT line field ``vat_amount``.

Pure Python: no COM, database or network.
Run with: .venv\\Scripts\\python.exe -m pytest -p no:cacheprovider -q tests/phase2/test_s14_vat_amount_contract.py
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from business_ai_gateway.phase2.change.evidence import canonical_json_bytes
from business_ai_gateway.phase2.change.proposal import (
    DraftPayload,
    Line,
    parse_writer_payload,
    payload_digest,
    payload_to_dict,
)
from business_ai_gateway.phase2.change import ChangeKind, Scope
from erp_mcp_private_writer.com_manifest import (
    ComOperationManifest,
    PayloadPropertyBinding,
    PreparedComManifest,
    com_values_from_approved_payload,
    draft_payload_from_write_port,
)

SCOPE = Scope("tenant-1", "company-1", "org-1", "base-1")

_PATHS = (
    "organization_ref", "counterparty_ref", "contract_ref", "supplier_document_number",
    "supplier_document_date", "currency", "lines[0].item_ref", "lines[0].quantity",
    "lines[0].price", "lines[0].vat_rate_code", "lines[0].amount", "lines[0].vat_amount", "comment",
)


def _raw(vat_amount: object = "3.5") -> dict:
    """Write-port / proposal-shaped CREATE_DRAFT payload (all values already canonical)."""
    return {
        "organization_ref": "org-1", "counterparty_ref": "cp-1", "contract_ref": "ct-1",
        "supplier_document_number": "N-1", "supplier_document_date": "2026-10-01", "currency": "RUB",
        "lines": [{"item_ref": "it-1", "quantity": "2", "price": "10.5", "vat_rate_code": "VAT20",
                   "amount": "21", "vat_amount": vat_amount}],
        "comment": "note",
    }


def _parse(raw: dict) -> object:
    return parse_writer_payload(raw, ChangeKind.CREATE_DRAFT, SCOPE)


def _typed(vat_amount: str = "3.5") -> DraftPayload:
    parsed = _parse(_raw(vat_amount))
    assert type(parsed) is DraftPayload, parsed
    return parsed


def _port_dict(payload: DraftPayload) -> dict:
    return copy.deepcopy(payload_to_dict(payload) | {"expected_target_version": None})


def _bindings(paths: tuple[str, ...] = _PATHS) -> tuple[PayloadPropertyBinding, ...]:
    return tuple(
        PayloadPropertyBinding(p, "Document." + p.replace(".", "_").replace("[0]", ""), "SetValue", "String")
        for p in paths)


def _value_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes({"value": value})).hexdigest()


# (a) digest binding -----------------------------------------------------------------------------------------------

def test_changing_only_vat_amount_changes_payload_digest() -> None:
    a, b = _typed("3.5"), _typed("3.6")
    assert payload_to_dict(a) == {**payload_to_dict(b), "lines": [{**payload_to_dict(b)["lines"][0],
                                                                   "vat_amount": "3.5"}]}
    assert payload_digest(a, None) != payload_digest(b, None)
    assert payload_digest(a, None) == payload_digest(_typed("3.5"), None)  # stable for equal input


def test_vat_amount_is_present_in_canonical_dict_line() -> None:
    assert payload_to_dict(_typed("0"))["lines"][0]["vat_amount"] == "0"


# (b) com_manifest binding -----------------------------------------------------------------------------------------

def test_binding_set_omitting_vat_amount_is_refused() -> None:
    payload = _typed()
    without = _bindings(tuple(p for p in _PATHS if p != "lines[0].vat_amount"))
    for fn in (com_values_from_approved_payload,):
        with pytest.raises(ValueError, match="^COM_PAYLOAD_BINDING_COVERAGE_INVALID$"):
            fn(payload, without, approved_payload_digest=payload_digest(payload, None), target_version=None)
    with pytest.raises(ValueError, match="^COM_PAYLOAD_BINDING_COVERAGE_INVALID$"):
        PreparedComManifest.from_approved_payload(
            ComOperationManifest("CREATE_DRAFT", "CreateDocument", "WRITE", None, None), "SetValue",
            payload, without, approved_payload_digest=payload_digest(payload, None), target_version=None)


def test_bound_vat_amount_value_equals_payload_text_and_digest_matches_manifest() -> None:
    payload = _typed("3.5")
    bindings = _bindings()
    digest = payload_digest(payload, None)
    values = com_values_from_approved_payload(payload, bindings, approved_payload_digest=digest,
                                              target_version=None)
    index = _PATHS.index("lines[0].vat_amount")
    assert values[index].value == "3.5" == payload.lines[0].vat_amount
    assert values[index].property_path == bindings[index].property_path
    manifest = PreparedComManifest.from_approved_payload(
        ComOperationManifest("CREATE_DRAFT", "CreateDocument", "WRITE", None, None), "SetValue",
        payload, bindings, approved_payload_digest=digest, target_version=None)
    assert values[index].value_sha256 == _value_digest("3.5") == manifest.assignments[index].value_sha256

    # A different vat_amount yields a different value digest at that position only.
    other = _typed("3.6")
    other_manifest = PreparedComManifest.from_approved_payload(
        ComOperationManifest("CREATE_DRAFT", "CreateDocument", "WRITE", None, None), "SetValue",
        other, bindings, approved_payload_digest=payload_digest(other, None), target_version=None)
    changed = [i for i, (x, y) in enumerate(zip(manifest.assignments, other_manifest.assignments, strict=True))
               if x.value_sha256 != y.value_sha256]
    assert changed == [index]


# (c) draft_payload_from_write_port --------------------------------------------------------------------------------

def test_write_port_round_trip_preserves_vat_amount_and_digest() -> None:
    payload = _typed("3.5")
    rebuilt = draft_payload_from_write_port(_port_dict(payload))
    assert rebuilt.lines[0].vat_amount == "3.5"
    assert payload_digest(rebuilt, None) == payload_digest(payload, None)


def test_write_port_refuses_line_missing_vat_amount() -> None:
    raw = _port_dict(_typed())
    del raw["lines"][0]["vat_amount"]
    with pytest.raises(ValueError, match="^COM_APPROVED_PAYLOAD_INVALID$"):
        draft_payload_from_write_port(raw)


def test_write_port_refuses_line_with_extra_key() -> None:
    raw = _port_dict(_typed())
    raw["lines"][0]["vat_base"] = "17.5"
    with pytest.raises(ValueError, match="^COM_APPROVED_PAYLOAD_INVALID$"):
        draft_payload_from_write_port(raw)


@pytest.mark.parametrize("bad", ["-1", 3.5, Decimal("3.5"), None, "1e2", "3.50", ""])
def test_write_port_refuses_non_canonical_vat_amount(bad: object) -> None:
    raw = _port_dict(_typed())
    raw["lines"][0]["vat_amount"] = bad
    with pytest.raises(ValueError, match="^COM_APPROVED_PAYLOAD_INVALID$"):
        draft_payload_from_write_port(raw)


# (d) canonicalization identical on typed and parse paths ----------------------------------------------------------

def test_canonicalization_same_on_typed_and_parse_paths() -> None:
    parsed = _typed("3.50")  # parse path canonicalizes
    assert parsed.lines[0].vat_amount == "3.5"
    typed = replace(parsed, lines=(Line("it-1", "2", "10.5", "VAT20", "21", "3.5"),))
    assert payload_digest(typed, None) == payload_digest(parsed, None)
    # The typed path accepts only the canonical form (no silent normalisation).
    with pytest.raises(ValueError, match="LINE_INVALID"):
        Line("it-1", "2", "10.5", "VAT20", "21", "3.50")
    # Same rule for every spelling that normalises to one canonical text.
    for spelled, canonical in (("0.00", "0"), ("0.000000", "0"), ("7.10", "7.1"), ("100", "100")):
        assert _typed(spelled).lines[0].vat_amount == canonical
        assert Line("it-1", "2", "10.5", "VAT20", "21", canonical).vat_amount == canonical


# (e) value domain -------------------------------------------------------------------------------------------------

def test_zero_is_accepted_on_both_paths() -> None:
    assert _typed("0").lines[0].vat_amount == "0"
    assert Line("it-1", "2", "10.5", "VAT20", "21", "0").vat_amount == "0"
    assert _typed("0.00").lines[0].vat_amount == "0"


def test_boundary_values_accepted() -> None:
    assert _typed("0.000001").lines[0].vat_amount == "0.000001"
    big = "9" * 18
    assert _typed(big).lines[0].vat_amount == big


_REJECTED = ["-1", "-0.01", "-0", 3.5, 0.0, Decimal("3.5"), Decimal(0), "1e3", "1E3", "3.5e0",
             "0.1234567", "3,5", " 3.5", "3.5 ", "NaN", "Infinity", "", "abc", None, True, 5, "+1", "01",
             ".5", "5.", "9" * 19]


@pytest.mark.parametrize("bad", _REJECTED, ids=repr)
def test_invalid_vat_amount_refused_by_parse_path(bad: object) -> None:
    result = _parse(_raw(bad))
    assert type(result) is not DraftPayload
    assert getattr(result, "code", None) is not None


@pytest.mark.parametrize("bad", _REJECTED, ids=repr)
def test_invalid_vat_amount_refused_by_typed_path(bad: object) -> None:
    with pytest.raises(ValueError, match="LINE_INVALID"):
        Line("it-1", "2", "10.5", "VAT20", "21", bad)  # type: ignore[arg-type]


def test_missing_and_extra_line_key_refused_by_parse_path() -> None:
    raw = _raw()
    del raw["lines"][0]["vat_amount"]
    assert type(_parse(raw)) is not DraftPayload
    raw = _raw()
    raw["lines"][0]["extra"] = "1"
    assert type(_parse(raw)) is not DraftPayload


# synthetic generator ----------------------------------------------------------------------------------------------

def test_synthetic_generator_payload_round_trips_through_real_parser() -> None:
    from business_ai_gateway.phase2.simulation.synthetic_data import SyntheticGenerator
    gen = SyntheticGenerator(11)
    # The writer parser qualifies only the single measured receipt shape (MEASURED_SHAPE_MAX_LINES == 1).
    for count in (1,):
        for payload in gen.payloads(40, lines=count):
            wire = payload_to_dict(payload)
            assert all("vat_amount" in line for line in wire["lines"])
            create_wire = {k: v for k, v in copy.deepcopy(wire).items() if k != "expected_target_version"}
            parsed = parse_writer_payload(create_wire, ChangeKind.CREATE_DRAFT,
                                          gen.scope(payload.organization_ref))
            assert type(parsed) is DraftPayload, parsed
            assert payload_to_dict(parsed) == wire
            assert payload_digest(parsed, None) == payload_digest(payload, None)
            assert all(Decimal(x.vat_amount) >= 0 for x in payload.lines)


def test_synthetic_generators_with_same_seed_are_identical_and_other_seed_differs() -> None:
    from business_ai_gateway.phase2.simulation.synthetic_data import SyntheticGenerator
    a = [payload_to_dict(p) for p in SyntheticGenerator(5).payloads(15, lines=2)]
    b = [payload_to_dict(p) for p in SyntheticGenerator(5).payloads(15, lines=2)]
    c = [payload_to_dict(p) for p in SyntheticGenerator(6).payloads(15, lines=2)]
    assert a == b
    assert a != c
