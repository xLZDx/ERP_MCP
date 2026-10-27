"""Pure functional acceptance for the optional PayloadPropertyBinding closed value map.

No COM, database, lane or business data. Run with:
    pytest -p no:cacheprovider -q tests/phase2/test_s14_com_value_map.py
"""
from __future__ import annotations

import hashlib

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
    com_values_from_approved_payload,
    com_values_from_write_port_payload,
)

VAT_PATH = "lines[0].vat_rate_code"
VAT_MAP = (("VAT20", "НДС20"), ("VAT0", "НДС0"), ("VAT10", "НДС10"))


def _payload(vat: str = "VAT20") -> DraftPayload:
    return DraftPayload(
        organization_ref="org-7",
        counterparty_ref="party-12",
        contract_ref="contract-4",
        supplier_document_number="supplier-2026-42",
        supplier_document_date="2026-10-25",
        currency="MDL",
        lines=(Line(item_ref="item-9", quantity="2", price="15.5", vat_rate_code=vat, amount="31"),),
        comment="approved payload value",
        duplicate_override=DuplicateOverride("prior-change-1", "operator approved duplicate"),
        expected_target_version=None,
    )


_SOURCE_PATHS = (
    "organization_ref", "counterparty_ref", "contract_ref", "supplier_document_number",
    "supplier_document_date", "currency", "lines[0].item_ref", "lines[0].quantity",
    "lines[0].price", VAT_PATH, "lines[0].amount", "comment",
)


def _bindings(value_map=VAT_MAP) -> tuple[PayloadPropertyBinding, ...]:
    return tuple(
        PayloadPropertyBinding(
            path, f"Document.{path.replace('.', '_').replace('[0]', '')}", "SetValue", "String",
            value_map if path == VAT_PATH else None)
        for path in _SOURCE_PATHS
    )


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes({"value": value})).hexdigest()


def _extract(payload: DraftPayload, bindings):
    return com_values_from_approved_payload(
        payload, bindings, approved_payload_digest=payload_digest(payload, None), target_version=None)


def _vat_index() -> int:
    return _SOURCE_PATHS.index(VAT_PATH)


@pytest.mark.parametrize("code,expected", [("VAT20", "НДС20"), ("VAT0", "НДС0"), ("VAT10", "НДС10")])
def test_mapped_vat_code_is_translated_in_ephemeral_value(code: str, expected: str) -> None:
    values = _extract(_payload(code), _bindings())
    vat = values[_vat_index()]
    assert vat.property_path == "Document.lines_vat_rate_code"
    assert vat.value == expected
    assert vat.value != code
    assert vat.value_sha256 == _digest(expected)
    # Unmapped neighbours keep their approved payload value untouched.
    assert values[0].value == "org-7"
    assert values[_SOURCE_PATHS.index("lines[0].amount")].value == "31"


def test_write_port_path_uses_translated_value() -> None:
    payload = _payload("VAT10")
    values = com_values_from_write_port_payload(
        payload_to_dict(payload), _bindings(), approved_payload_digest=payload_digest(payload, None))
    assert values[_vat_index()].value == "НДС10"


@pytest.mark.parametrize("code", ["VAT20", "VAT0", "VAT10"])
def test_manifest_digest_matches_ephemeral_digest_of_translated_value(code: str) -> None:
    payload = _payload(code)
    bindings = _bindings()
    manifest = assignments_from_approved_payload(payload, bindings)
    values = _extract(payload, bindings)
    translated = dict(VAT_MAP)[code]
    assert manifest[_vat_index()].value_sha256 == values[_vat_index()].value_sha256 == _digest(translated)
    # The manifest must not carry the untranslated payload code digest.
    assert manifest[_vat_index()].value_sha256 != _digest(code)
    assert [m.value_sha256 for m in manifest] == [v.value_sha256 for v in values]


@pytest.mark.parametrize("code", ["VAT18", "20", "vat20", "VAT200"])
def test_unmapped_code_is_refused_before_any_value_is_returned(code: str) -> None:
    payload = _payload(code)
    bindings = _bindings()
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        _extract(payload, bindings)
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        assignments_from_approved_payload(payload, bindings)
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        com_values_from_write_port_payload(
            payload_to_dict(payload), bindings, approved_payload_digest=payload_digest(payload, None))


def test_empty_code_is_refused_by_payload_contract_and_by_map() -> None:
    # Payload contract: Line refuses an empty vat_rate_code, so it never reaches the map.
    with pytest.raises(ValueError):
        Line(item_ref="item-9", quantity="2", price="15.5", vat_rate_code="", amount="31")
    # The map itself also refuses it (defence in depth).
    binding = PayloadPropertyBinding(VAT_PATH, "Document.Vat", "SetValue", "String", VAT_MAP)
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        binding.translate("")


def test_33_character_code_is_refused_by_payload_contract_not_by_map() -> None:
    too_long = "V" * 33
    # Refused at payload construction (is_identity_text max 32), before any map is consulted.
    with pytest.raises(ValueError):
        Line(item_ref="item-9", quantity="2", price="15.5", vat_rate_code=too_long, amount="31")
    # A 32-character code is accepted by the contract and then refused by the map as unmapped.
    boundary = "V" * 32
    payload = _payload(boundary)
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        _extract(payload, _bindings())
    # If the 33-character code were smuggled to translate directly, the map still refuses it.
    binding = PayloadPropertyBinding(VAT_PATH, "Document.Vat", "SetValue", "String", VAT_MAP)
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        binding.translate(too_long)


@pytest.mark.parametrize("value", [20, True, None, b"VAT20", ("VAT20",)])
def test_translate_refuses_non_string_values(value: object) -> None:
    binding = PayloadPropertyBinding(VAT_PATH, "Document.Vat", "SetValue", "String", VAT_MAP)
    with pytest.raises(ValueError, match="^COM_VALUE_NOT_MAPPED$"):
        binding.translate(value)


@pytest.mark.parametrize("bad_map", [
    (),
    (("VAT20", "A"), ("VAT20", "B")),
    [("VAT20", "A")],
    (["VAT20", "A"],),
    (("VAT20", "A", "B"),),
    (("VAT20",),),
    (("VAT20", 20),),
    (("VAT20", None),),
    ((20, "A"),),
    (("VAT20", " A"),),
    (("VAT20", "A "),),
    ((" VAT20", "A"),),
    (("VAT20", ""),),
    (("", "A"),),
    (("VAT20", "A\n"),),
    "VAT20",
    {"VAT20": "A"},
])
def test_invalid_value_map_is_refused(bad_map: object) -> None:
    with pytest.raises(ValueError, match="^COM_VALUE_MAP_INVALID$"):
        PayloadPropertyBinding(VAT_PATH, "Document.Vat", "SetValue", "String", bad_map)  # type: ignore[arg-type]


def test_valid_map_is_accepted_and_translate_is_exact() -> None:
    binding = PayloadPropertyBinding(VAT_PATH, "Document.Vat", "SetValue", "String", VAT_MAP)
    assert [binding.translate(s) for s, _ in VAT_MAP] == [t for _, t in VAT_MAP]
    assert binding.translate("VAT20") == "НДС20"


def test_binding_without_value_map_behaves_as_before() -> None:
    plain = PayloadPropertyBinding("currency", "Document.currency", "SetValue", "String")
    assert plain.value_map is None
    for value in ("MDL", "", 5, None, True):
        assert plain.translate(value) is value

    payload = _payload("20")
    bindings = _bindings(value_map=None)
    values = _extract(payload, bindings)
    assert values[_vat_index()].value == "20"
    assert values[_vat_index()].value_sha256 == _digest("20")
    manifest = assignments_from_approved_payload(payload, bindings)
    assert manifest[_vat_index()].value_sha256 == _digest("20")
    # Any code is accepted without a map, including ones a map would refuse.
    assert _extract(_payload("VAT18"), bindings)[_vat_index()].value == "VAT18"
    # All other fields are still their exact approved values.
    assert [v.value for v in values] == [
        "org-7", "party-12", "contract-4", "supplier-2026-42", "2026-10-25", "MDL",
        "item-9", "2", "15.5", "20", "31", "approved payload value",
    ]


def test_map_does_not_change_coverage_rules() -> None:
    payload = _payload()
    with pytest.raises(ValueError, match="^COM_PAYLOAD_BINDING_COVERAGE_INVALID$"):
        _extract(payload, _bindings()[:-1])
