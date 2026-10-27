"""Pure functional acceptance for S14 ephemeral COM payload value binding.

These tests exercise only Python payload/manifests: no COM, database, lane or business data.
Run with: uv run pytest -q tests/phase2/test_s14_com_ephemeral_value_binding.py
"""
from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError

import pytest

from business_ai_gateway.phase2.change.evidence import canonical_json_bytes
from business_ai_gateway.phase2.change.proposal import (
    DraftPayload,
    DuplicateOverride,
    Line,
    payload_digest,
)
from erp_mcp_private_writer.com_manifest import (
    ComOperationManifest,
    ComValueAssignment,
    MappedPropertyAssignment,
    PayloadPropertyBinding,
    PreparedComManifest,
    assignments_from_approved_payload,
    com_values_from_approved_payload,
)


def _payload(*, lines: tuple[Line, ...] | None = None, expected_target_version: str | None = None
            ) -> DraftPayload:
    return DraftPayload(
        organization_ref="org-7",
        counterparty_ref="party-12",
        contract_ref="contract-4",
        supplier_document_number="supplier-2026-42",
        supplier_document_date="2026-10-25",
        currency="MDL",
        lines=lines if lines is not None else (
            Line(item_ref="item-9", quantity="2", price="15.5", vat_rate_code="20", amount="31"),
        ),
        comment="approved payload value",
        duplicate_override=DuplicateOverride("prior-change-1", "operator approved duplicate"),
        expected_target_version=expected_target_version,
    )


def _bindings() -> tuple[PayloadPropertyBinding, ...]:
    source_paths = (
        "organization_ref",
        "counterparty_ref",
        "contract_ref",
        "supplier_document_number",
        "supplier_document_date",
        "currency",
        "lines[0].item_ref",
        "lines[0].quantity",
        "lines[0].price",
        "lines[0].vat_rate_code",
        "lines[0].amount",
        "comment",
    )
    return tuple(
        PayloadPropertyBinding(path, f"Document.{path.replace('.', '_').replace('[0]', '')}",
                               "SetValue", "String")
        for path in source_paths
    )


def _value_digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes({"value": value})).hexdigest()


def _extract(payload: DraftPayload, bindings: tuple[PayloadPropertyBinding, ...]):
    return com_values_from_approved_payload(
        payload,
        bindings,
        approved_payload_digest=payload_digest(payload, None),
        target_version=None,
    )


def test_s14_exact_approved_leaf_values_and_canonical_digests() -> None:
    payload = _payload()
    bindings = _bindings()
    assignments = _extract(payload, bindings)

    expected = (
        ("org-7", "organization_ref"),
        ("party-12", "counterparty_ref"),
        ("contract-4", "contract_ref"),
        ("supplier-2026-42", "supplier_document_number"),
        ("2026-10-25", "supplier_document_date"),
        ("MDL", "currency"),
        ("item-9", "lines[0].item_ref"),
        ("2", "lines[0].quantity"),
        ("15.5", "lines[0].price"),
        ("20", "lines[0].vat_rate_code"),
        ("31", "lines[0].amount"),
        ("approved payload value", "comment"),
    )
    assert tuple((item.value, binding.payload_path)
                 for item, binding in zip(assignments, bindings, strict=True)) == expected
    for item, (value, _path) in zip(assignments, expected, strict=True):
        assert item.value_sha256 == _value_digest(value)


def test_s14_control_only_paths_are_excluded_from_ephemeral_values_and_manifest() -> None:
    payload = _payload()
    bindings = _bindings()
    values = _extract(payload, bindings)
    assert all("duplicate_override" not in item.property_path for item in values)
    assert all("expected_target_version" not in item.property_path for item in values)
    assert all(item.value not in ("prior-change-1", "operator approved duplicate") for item in values)

    digest_only = assignments_from_approved_payload(payload, bindings)
    assert all(type(item) is MappedPropertyAssignment for item in digest_only)
    assert all(not hasattr(item, "value") for item in digest_only)
    assert all(set(item.to_manifest_record()) == {
        "property_path", "assignment_kind", "value_type", "value_sha256",
    } for item in digest_only)
    manifest = PreparedComManifest.from_approved_payload(
        ComOperationManifest("CREATE_DRAFT", "CreateDocument", "WRITE", None, None),
        "SetValue",
        payload,
        bindings,
        approved_payload_digest=payload_digest(payload, None),
        target_version=None,
    )
    rendered = repr(manifest)
    assert "approved payload value" not in rendered
    assert "prior-change-1" not in rendered
    assert "operator approved duplicate" not in rendered
    assert all(not hasattr(item, "value") for item in manifest.assignments)


def test_s14_requires_exact_one_line_leaf_and_destination_coverage() -> None:
    payload = _payload()
    bindings = _bindings()

    with pytest.raises(ValueError, match="^COM_PAYLOAD_SHAPE_NOT_QUALIFIED$"):
        _extract(_payload(lines=(payload.lines[0], payload.lines[0])), bindings)

    duplicate_source = (bindings[0], bindings[0], *bindings[2:])
    with pytest.raises(ValueError, match="^COM_PAYLOAD_BINDING_COVERAGE_INVALID$"):
        _extract(payload, duplicate_source)

    duplicate_destination = (
        bindings[0],
        PayloadPropertyBinding(bindings[1].payload_path, bindings[0].property_path,
                               bindings[1].assignment_kind, bindings[1].value_type),
        *bindings[2:],
    )
    with pytest.raises(ValueError, match="^COM_PAYLOAD_BINDING_COVERAGE_INVALID$"):
        _extract(payload, duplicate_destination)

    with pytest.raises(ValueError, match="^COM_PAYLOAD_BINDING_COVERAGE_INVALID$"):
        _extract(payload, bindings[:-1])

    extra_source = bindings + (
        PayloadPropertyBinding("unexpected.leaf", "Document.Unexpected", "SetValue", "String"),
    )
    with pytest.raises(ValueError, match="^COM_PAYLOAD_BINDING_COVERAGE_INVALID$"):
        _extract(payload, extra_source)


def test_s14_changed_approved_digest_and_create_preimage_refuse() -> None:
    payload = _payload()
    bindings = _bindings()
    with pytest.raises(ValueError, match="^COM_APPROVED_PAYLOAD_DIGEST_MISMATCH$"):
        com_values_from_approved_payload(
            payload,
            bindings,
            approved_payload_digest="0" * 64,
            target_version=None,
        )

    embedded_preimage = _payload(expected_target_version="version-7")
    with pytest.raises(ValueError, match="^COM_CREATE_DRAFT_PREIMAGE_INVALID$"):
        com_values_from_approved_payload(
            embedded_preimage,
            _bindings(),
            approved_payload_digest=payload_digest(embedded_preimage, None),
            target_version=None,
        )
    with pytest.raises(ValueError, match="^COM_CREATE_DRAFT_PREIMAGE_INVALID$"):
        com_values_from_approved_payload(
            payload,
            bindings,
            approved_payload_digest=payload_digest(payload, "version-7"),
            target_version="version-7",
        )


def test_s14_com_value_assignment_is_frozen_scalar_only_and_redacted() -> None:
    for scalar in ("sensitive leaf", True, 17, None):
        assignment = ComValueAssignment("Document.Value", "SetValue", "Scalar", scalar)
        assert assignment.value is scalar or assignment.value == scalar
        assert assignment.value_sha256 == _value_digest(scalar)
        assert "sensitive leaf" not in repr(assignment)
        with pytest.raises(FrozenInstanceError):
            assignment.value = "changed"  # type: ignore[misc]

    for mutable in ([], {}, {"nested": [1]}):
        with pytest.raises(ValueError, match="^COM_PROPERTY_VALUE_NOT_CANONICAL$"):
            ComValueAssignment("Document.Value", "SetValue", "Scalar", mutable)  # type: ignore[arg-type]
