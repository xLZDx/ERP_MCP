"""Functional acceptance for the reviewed closed VAT table (legacy 1C ``СтавкиНДС`` value names).

No COM, database, lane or business data. Run with:
    pytest -p no:cacheprovider -q tests/phase2/test_s14_com_vat_table.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from business_ai_gateway.phase2.change.evidence import canonical_json_bytes
from business_ai_gateway.phase2.change.proposal import (
    DraftPayload,
    DuplicateOverride,
    Line,
    payload_digest,
    payload_to_dict,
)
from erp_mcp_private_writer.com_manifest import (
    PayloadPropertyBinding,
    assignments_from_approved_payload,
    com_values_from_write_port_payload,
)
from erp_mcp_private_writer.com_vat_table import VAT_RATE_CODE_TO_ENUM_VALUE, vat_rate_binding

ARTIFACT = (Path(__file__).resolve().parents[2]
            / "docs" / "phase2" / "artifacts" / "CT14_VAT_ENUMERATION_SEMANTICS_2026-10-27.json")
VAT_PATH = "lines[0].vat_rate_code"

# Literal expectations, independent of the module under test.
EXPECTED = {"VAT0": "НДС0", "VAT10": "НДС_10", "VAT20": "НДС18"}
EXPECTED_SYNONYM = {"VAT0": "0%", "VAT10": "10%", "VAT20": "20%"}


def _artifact_values() -> dict[str, str]:
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert data["enumeration"] == "СтавкиНДС"
    return {item["name"]: item["synonym"] for item in data["values"]}


def _payload(vat: str = "VAT20") -> DraftPayload:
    return DraftPayload(
        organization_ref="org-7",
        counterparty_ref="party-12",
        contract_ref="contract-4",
        supplier_document_number="supplier-2026-42",
        supplier_document_date="2026-10-25",
        currency="MDL",
        lines=(Line(item_ref="item-9", quantity="2", price="15.5", vat_rate_code=vat,
                    amount="31", vat_amount="5.17"),),
        comment="approved payload value",
        duplicate_override=DuplicateOverride("prior-change-1", "operator approved duplicate"),
        expected_target_version=None,
    )


_SOURCE_PATHS = (
    "organization_ref", "counterparty_ref", "contract_ref", "supplier_document_number",
    "supplier_document_date", "currency", "lines[0].item_ref", "lines[0].quantity",
    "lines[0].price", VAT_PATH, "lines[0].amount", "lines[0].vat_amount", "comment",
)


def _dest(path: str) -> str:
    return f"Document.{path.replace('.', '_').replace('[0]', '')}"


def _bindings() -> tuple[PayloadPropertyBinding, ...]:
    return tuple(
        vat_rate_binding(path, _dest(path)) if path == VAT_PATH
        else PayloadPropertyBinding(path, _dest(path), "SetValue", "String")
        for path in _SOURCE_PATHS
    )


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes({"value": value})).hexdigest()


def _vat_index() -> int:
    return _SOURCE_PATHS.index(VAT_PATH)


# (1) table content ---------------------------------------------------------------------------


def test_table_has_exactly_the_three_reviewed_entries() -> None:
    assert type(VAT_RATE_CODE_TO_ENUM_VALUE) is tuple
    assert len(VAT_RATE_CODE_TO_ENUM_VALUE) == 3
    assert dict(VAT_RATE_CODE_TO_ENUM_VALUE) == EXPECTED
    assert set(VAT_RATE_CODE_TO_ENUM_VALUE) == set(EXPECTED.items())


@pytest.mark.parametrize("code", sorted(EXPECTED))
def test_target_is_exact_unicode_and_its_synonym_is_the_intended_rate(code: str) -> None:
    target = dict(VAT_RATE_CODE_TO_ENUM_VALUE)[code]
    assert target == EXPECTED[code]
    # Cyrillic, not Latin look-alikes: the exact code points matter for the 1C enumeration lookup.
    assert target.encode("utf-8") == EXPECTED[code].encode("utf-8")
    assert target.startswith("НДС")  # Cyrillic N, D, S
    synonyms = _artifact_values()
    assert synonyms[target] == EXPECTED_SYNONYM[code]


def test_legacy_name_traps_are_not_targets() -> None:
    targets = {target for _, target in VAT_RATE_CODE_TO_ENUM_VALUE}
    synonyms = _artifact_values()
    assert synonyms["НДС10"] == "8%"
    assert "НДС10" not in targets
    assert synonyms["НДС20"].startswith("(не используется)")
    assert "НДС20" not in targets
    # No target may be an unused or advance-payment value.
    for target in targets:
        assert "не используется" not in synonyms[target]
        assert "Авансы" not in synonyms[target]


# (4) every named enumeration value exists in the artifact ------------------------------------


def test_every_target_exists_in_artifact_values() -> None:
    names = _artifact_values()
    for _, target in VAT_RATE_CODE_TO_ENUM_VALUE:
        assert target in names


# (2) binding behaviour -----------------------------------------------------------------------


def test_vat_rate_binding_shape() -> None:
    binding = vat_rate_binding(VAT_PATH, "Document.Vat")
    assert type(binding) is PayloadPropertyBinding
    assert binding.payload_path == VAT_PATH
    assert binding.property_path == "Document.Vat"
    assert binding.value_map == VAT_RATE_CODE_TO_ENUM_VALUE


@pytest.mark.parametrize("code", sorted(EXPECTED))
def test_binding_translates_each_code(code: str) -> None:
    assert vat_rate_binding(VAT_PATH, "Document.Vat").translate(code) == EXPECTED[code]


@pytest.mark.parametrize("bad", ["VAT18", "20", "vat20", "", "НДС18", "НДС_10", "НДС0", "VAT20 ", "VAT5"])
def test_binding_refuses_everything_outside_the_table(bad: str) -> None:
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        vat_rate_binding(VAT_PATH, "Document.Vat").translate(bad)


@pytest.mark.parametrize("bad", [20, None, True, b"VAT20"])
def test_binding_refuses_non_string(bad: object) -> None:
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        vat_rate_binding(VAT_PATH, "Document.Vat").translate(bad)


# (3) end to end through the write-port path --------------------------------------------------


@pytest.mark.parametrize("code", sorted(EXPECTED))
def test_write_port_value_is_translated_and_digest_matches_manifest(code: str) -> None:
    payload = _payload(code)
    bindings = _bindings()
    values = com_values_from_write_port_payload(
        payload_to_dict(payload), bindings, approved_payload_digest=payload_digest(payload, None))
    vat = values[_vat_index()]
    assert vat.value == EXPECTED[code]
    assert vat.value_sha256 == _digest(EXPECTED[code])
    assert vat.value_sha256 != _digest(code)
    manifest = assignments_from_approved_payload(payload, bindings)
    assert manifest[_vat_index()].value_sha256 == vat.value_sha256
    assert [m.value_sha256 for m in manifest] == [v.value_sha256 for v in values]
    # Neighbours are untouched.
    assert values[0].value == "org-7"
    assert values[_SOURCE_PATHS.index("lines[0].vat_amount")].value == "5.17"


def test_vat20_ephemeral_value_is_legacy_name_nds18() -> None:
    payload = _payload("VAT20")
    values = com_values_from_write_port_payload(
        payload_to_dict(payload), _bindings(), approved_payload_digest=payload_digest(payload, None))
    assert values[_vat_index()].value == "НДС18"


@pytest.mark.parametrize("code", ["VAT18", "20", "vat20", "НДС18", "V" * 32])
def test_unknown_vat_code_is_refused_before_any_value_is_returned(code: str) -> None:
    payload = _payload(code)
    raw = payload_to_dict(payload)
    digest = payload_digest(payload, None)
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        com_values_from_write_port_payload(raw, _bindings(), approved_payload_digest=digest)
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        assignments_from_approved_payload(payload, _bindings())


def test_empty_code_never_reaches_a_value() -> None:
    with pytest.raises(ValueError):
        Line(item_ref="item-9", quantity="2", price="15.5", vat_rate_code="",
             amount="31", vat_amount="5.17")
    raw = payload_to_dict(_payload("VAT20"))
    raw["lines"][0]["vat_rate_code"] = ""
    with pytest.raises(ValueError):
        com_values_from_write_port_payload(
            raw, _bindings(), approved_payload_digest=payload_digest(_payload("VAT20"), None))
