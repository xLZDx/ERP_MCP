"""Canonical, value-minimizing S12 manifests for a future qualified COM mapping.

This module derives assignment values from an approved payload using caller-supplied reviewed
crosswalk bindings. It neither discovers 1C metadata nor authenticates the mapping/configuration,
enters COM, or authorizes a write. A deployment must supply bindings from its qualified clone
crosswalk before a writer can use these values.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from business_ai_gateway.phase2.change.evidence import canonical_json_bytes
from business_ai_gateway.phase2.change.proposal import (
    DraftPayload,
    DuplicateOverride,
    Line,
    payload_digest,
    payload_to_dict,
)

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_PROPERTY_MANIFEST_PREFIX = b"ERP_MCP_R2:S12:MAPPED-PROPERTY-MANIFEST:v1\n"
_OPERATION_MANIFEST_PREFIX = b"ERP_MCP_R2:S12:COM-OPERATION-MANIFEST:v1\n"
_OPERATIONS = frozenset(("CREATE_DRAFT", "POST", "UNPOST"))
_DRAFT_PAYLOAD_FIELDS = frozenset({
    "organization_ref", "counterparty_ref", "contract_ref", "supplier_document_number",
    "supplier_document_date", "currency", "lines", "comment", "duplicate_override",
    "expected_target_version",
})
_DRAFT_LINE_FIELDS = frozenset({"item_ref", "quantity", "price", "vat_rate_code", "amount"})
_DUPLICATE_OVERRIDE_FIELDS = frozenset({"duplicate_of_change_or_ref", "justification"})


def _manifest_text(value: object, code: str) -> None:
    if (type(value) is not str or not value or value != value.strip()
            or len(value) > 512 or any(not c.isprintable() for c in value)):
        raise ValueError(code)


@dataclass(frozen=True, slots=True)
class MappedPropertyAssignment:
    """One ordered property/section change, retaining only its canonical value digest."""

    property_path: str
    assignment_kind: str
    value_type: str
    value_sha256: str

    def __post_init__(self) -> None:
        _manifest_text(self.property_path, "COM_PROPERTY_PATH_INVALID")
        _manifest_text(self.assignment_kind, "COM_ASSIGNMENT_KIND_INVALID")
        _manifest_text(self.value_type, "COM_PROPERTY_TYPE_INVALID")
        if type(self.value_sha256) is not str or _HEX64.fullmatch(self.value_sha256) is None:
            raise ValueError("COM_PROPERTY_VALUE_DIGEST_INVALID")

    @classmethod
    def from_value(cls, property_path: str, assignment_kind: str, value_type: str, value: Any
                   ) -> MappedPropertyAssignment:
        """Build a value digest under S12 canonical JSON rules; floats/custom values are rejected."""
        try:
            value_digest = hashlib.sha256(canonical_json_bytes({"value": value})).hexdigest()
        except (TypeError, ValueError):
            raise ValueError("COM_PROPERTY_VALUE_NOT_CANONICAL") from None
        return cls(property_path, assignment_kind, value_type, value_digest)

    def to_manifest_record(self) -> dict[str, str]:
        return {
            "property_path": self.property_path,
            "assignment_kind": self.assignment_kind,
            "value_type": self.value_type,
            "value_sha256": self.value_sha256,
        }


@dataclass(frozen=True, slots=True)
class ComValueAssignment:
    """Ephemeral exact value for a COM call; its representation and equality omit the value."""

    property_path: str
    assignment_kind: str
    value_type: str
    value: str | bool | int | None = field(repr=False, compare=False)
    value_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _manifest_text(self.property_path, "COM_PROPERTY_PATH_INVALID")
        _manifest_text(self.assignment_kind, "COM_ASSIGNMENT_KIND_INVALID")
        _manifest_text(self.value_type, "COM_PROPERTY_TYPE_INVALID")
        # DraftPayload leaves are immutable JSON scalars. Reject direct construction with
        # containers so the captured digest cannot drift before the ephemeral COM call.
        if self.value is not None and type(self.value) not in (str, bool, int):
            raise ValueError("COM_PROPERTY_VALUE_NOT_CANONICAL")
        try:
            digest = hashlib.sha256(canonical_json_bytes({"value": self.value})).hexdigest()
        except (TypeError, ValueError):
            raise ValueError("COM_PROPERTY_VALUE_NOT_CANONICAL") from None
        object.__setattr__(self, "value_sha256", digest)


@dataclass(frozen=True, slots=True)
class PayloadPropertyBinding:
    """One reviewed 1C destination bound to one source field in the approved payload."""

    payload_path: str
    property_path: str
    assignment_kind: str
    value_type: str

    def __post_init__(self) -> None:
        _manifest_text(self.payload_path, "COM_PAYLOAD_PATH_INVALID")
        _manifest_text(self.property_path, "COM_PROPERTY_PATH_INVALID")
        _manifest_text(self.assignment_kind, "COM_ASSIGNMENT_KIND_INVALID")
        _manifest_text(self.value_type, "COM_PROPERTY_TYPE_INVALID")


def _payload_leaf_values(value: object, path: str = "") -> dict[str, object]:
    """Flatten only the canonical payload's built-in containers; never evaluate a path string."""
    if type(value) is dict:
        flattened: dict[str, object] = {}
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError("COM_PAYLOAD_SHAPE_INVALID")
            child_path = f"{path}.{key}" if path else key
            flattened.update(_payload_leaf_values(child, child_path))
        return flattened
    if type(value) is list:
        flattened = {}
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            flattened.update(_payload_leaf_values(child, child_path))
        return flattened
    if not path:
        raise ValueError("COM_PAYLOAD_SHAPE_INVALID")
    return {path: value}


_CONTROL_ONLY_PAYLOAD_PATHS = frozenset({"duplicate_override", "expected_target_version"})


def _is_control_only_payload_path(path: str) -> bool:
    return any(path == root or path.startswith(root + ".")
               for root in _CONTROL_ONLY_PAYLOAD_PATHS)


def _has_exact_dict_keys(value: object, expected: frozenset[str]) -> bool:
    """Compare JSON object fields only after excluding custom key/hash behavior."""
    return (type(value) is dict
            and all(type(key) is str for key in value)
            and set(value) == expected)


def _bound_payload_values(
        payload: DraftPayload, bindings: tuple[PayloadPropertyBinding, ...]
        ) -> tuple[tuple[PayloadPropertyBinding, object], ...]:
    if type(payload) is not DraftPayload:
        raise ValueError("COM_APPROVED_PAYLOAD_INVALID")
    if len(payload.lines) != 1:
        raise ValueError("COM_PAYLOAD_SHAPE_NOT_QUALIFIED")
    if (type(bindings) is not tuple
            or any(type(binding) is not PayloadPropertyBinding for binding in bindings)):
        raise ValueError("COM_PAYLOAD_BINDINGS_INVALID")

    values = _payload_leaf_values(payload_to_dict(payload))
    required_paths = {path for path in values if not _is_control_only_payload_path(path)}
    bound_paths = [binding.payload_path for binding in bindings]
    destination_paths = [binding.property_path for binding in bindings]
    if (len(bound_paths) != len(set(bound_paths))
            or len(destination_paths) != len(set(destination_paths))
            or set(bound_paths) != required_paths):
        raise ValueError("COM_PAYLOAD_BINDING_COVERAGE_INVALID")

    return tuple((binding, values[binding.payload_path]) for binding in bindings)


def draft_payload_from_write_port(value: object) -> DraftPayload:
    """Rebuild the typed CREATE_DRAFT payload from the write-port JSON shape.

    ``PrivateWriterService`` receives the canonical payload as a dictionary, while the COM value
    extractor intentionally accepts only the validated ``DraftPayload`` model. This strict
    inverse of ``payload_to_dict`` keeps that boundary explicit and rejects extra or missing
    fields before any crosswalk lookup or COM entry. It does not validate a 1C destination map.
    """
    if not _has_exact_dict_keys(value, _DRAFT_PAYLOAD_FIELDS):
        raise ValueError("COM_APPROVED_PAYLOAD_INVALID")
    raw_lines = value.get("lines")
    if type(raw_lines) is not list:
        raise ValueError("COM_APPROVED_PAYLOAD_INVALID")
    lines: list[Line] = []
    try:
        for raw_line in raw_lines:
            if not _has_exact_dict_keys(raw_line, _DRAFT_LINE_FIELDS):
                raise ValueError
            lines.append(Line(
                item_ref=raw_line["item_ref"],
                quantity=raw_line["quantity"],
                price=raw_line["price"],
                vat_rate_code=raw_line["vat_rate_code"],
                amount=raw_line["amount"],
            ))

        raw_override = value["duplicate_override"]
        if raw_override is None:
            duplicate_override = None
        else:
            if not _has_exact_dict_keys(raw_override, _DUPLICATE_OVERRIDE_FIELDS):
                raise ValueError
            duplicate_override = DuplicateOverride(
                duplicate_of_change_or_ref=raw_override["duplicate_of_change_or_ref"],
                justification=raw_override["justification"],
            )

        return DraftPayload(
            organization_ref=value["organization_ref"],
            counterparty_ref=value["counterparty_ref"],
            contract_ref=value["contract_ref"],
            supplier_document_number=value["supplier_document_number"],
            supplier_document_date=value["supplier_document_date"],
            currency=value["currency"],
            lines=tuple(lines),
            comment=value["comment"],
            duplicate_override=duplicate_override,
            expected_target_version=value["expected_target_version"],
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("COM_APPROVED_PAYLOAD_INVALID") from None


def assignments_from_approved_payload(
        payload: DraftPayload, bindings: tuple[PayloadPropertyBinding, ...]
        ) -> tuple[MappedPropertyAssignment, ...]:
    """Build the digest-only record for every approved business leaf.

    ``duplicate_override`` and ``expected_target_version`` are authorization/concurrency inputs,
    not 1C document properties. Destination names still require a separately reviewed clone
    crosswalk; this function neither discovers metadata nor authorizes or invokes COM.
    """
    assignments = []
    for binding, value in _bound_payload_values(payload, bindings):
        assignments.append(MappedPropertyAssignment.from_value(
            binding.property_path,
            binding.assignment_kind,
            binding.value_type,
            value,
        ))
    return tuple(assignments)


def com_values_from_approved_payload(
        payload: DraftPayload, bindings: tuple[PayloadPropertyBinding, ...], *,
        approved_payload_digest: str, target_version: str | None
        ) -> tuple[ComValueAssignment, ...]:
    """Return values for immediate COM use after the approved digest and mapping are rechecked.

    Callers must keep the returned tuple local to the COM invocation and must never log, persist,
    or include its values in receipt/checkpoint data. The separate manifest remains digest-only.
    """
    if (type(approved_payload_digest) is not str
            or _HEX64.fullmatch(approved_payload_digest) is None):
        raise ValueError("COM_APPROVED_PAYLOAD_DIGEST_INVALID")
    if type(payload) is not DraftPayload:
        raise ValueError("COM_APPROVED_PAYLOAD_INVALID")
    if (target_version is not None or payload.expected_target_version is not None):
        raise ValueError("COM_CREATE_DRAFT_PREIMAGE_INVALID")
    try:
        actual_digest = payload_digest(payload, target_version)
    except (TypeError, ValueError):
        raise ValueError("COM_APPROVED_PAYLOAD_INVALID") from None
    if actual_digest != approved_payload_digest:
        raise ValueError("COM_APPROVED_PAYLOAD_DIGEST_MISMATCH")
    return tuple(
        ComValueAssignment(
            binding.property_path,
            binding.assignment_kind,
            binding.value_type,
            value,
        )
        for binding, value in _bound_payload_values(payload, bindings)
    )


def com_values_from_write_port_payload(
        payload: object, bindings: tuple[PayloadPropertyBinding, ...], *,
        approved_payload_digest: str
        ) -> tuple[ComValueAssignment, ...]:
    """Build ephemeral CREATE_DRAFT values from the exact dictionary passed to the write port."""
    typed_payload = draft_payload_from_write_port(payload)
    return com_values_from_approved_payload(
        typed_payload,
        bindings,
        approved_payload_digest=approved_payload_digest,
        target_version=None,
    )


def mapped_property_manifest_sha256(
        assignments: tuple[MappedPropertyAssignment, ...], *, write_mode: str,
        property_setting_method: str) -> str:
    """Hash ordered changes plus the write/property method, including tabular-section changes."""
    if (type(assignments) is not tuple
            or any(type(item) is not MappedPropertyAssignment for item in assignments)):
        raise ValueError("COM_PROPERTY_ASSIGNMENTS_INVALID")
    _manifest_text(write_mode, "COM_WRITE_MODE_INVALID")
    _manifest_text(property_setting_method, "COM_PROPERTY_METHOD_INVALID")
    body = {
        "write_mode": write_mode,
        "property_setting_method": property_setting_method,
        "assignments": [item.to_manifest_record() for item in assignments],
    }
    return hashlib.sha256(_PROPERTY_MANIFEST_PREFIX + canonical_json_bytes(body)).hexdigest()


@dataclass(frozen=True, slots=True)
class ComOperationManifest:
    """Exact operation boundary fields bound by a DispatchReceipt's S12 operation digest."""

    operation_kind: str
    method: str
    write_mode: str
    target_ref: str | None
    expected_version: str | None

    def __post_init__(self) -> None:
        if type(self.operation_kind) is not str or self.operation_kind not in _OPERATIONS:
            raise ValueError("COM_OPERATION_KIND_INVALID")
        _manifest_text(self.method, "COM_METHOD_INVALID")
        _manifest_text(self.write_mode, "COM_WRITE_MODE_INVALID")
        if self.operation_kind == "CREATE_DRAFT":
            if self.target_ref is not None or self.expected_version is not None:
                raise ValueError("COM_CREATE_DRAFT_PREIMAGE_INVALID")
        elif (self.target_ref is None or self.expected_version is None):
            raise ValueError("COM_OPERATION_PREIMAGE_REQUIRED")
        else:
            _manifest_text(self.target_ref, "COM_TARGET_INVALID")
            _manifest_text(self.expected_version, "COM_EXPECTED_VERSION_INVALID")

    def sha256(self) -> str:
        """Return the domain-separated digest; the method is descriptive and is never invoked here."""
        body = {
            "operation_kind": self.operation_kind,
            "method": self.method,
            "write_mode": self.write_mode,
            "target_ref": self.target_ref,
            "expected_version": self.expected_version,
        }
        return hashlib.sha256(_OPERATION_MANIFEST_PREFIX + canonical_json_bytes(body)).hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class PreparedComManifest:
    """Keep property and operation digests on one payload-derived immutable boundary."""

    operation: ComOperationManifest
    property_setting_method: str
    assignments: tuple[MappedPropertyAssignment, ...]

    def __init__(self, operation: ComOperationManifest, property_setting_method: str,
                 payload: DraftPayload | None,
                 bindings: tuple[PayloadPropertyBinding, ...], *,
                 approved_payload_digest: str, target_version: str | None) -> None:
        if type(operation) is not ComOperationManifest:
            raise ValueError("COM_OPERATION_MANIFEST_INVALID")
        _manifest_text(property_setting_method, "COM_PROPERTY_METHOD_INVALID")
        if type(approved_payload_digest) is not str or _HEX64.fullmatch(
                approved_payload_digest) is None:
            raise ValueError("COM_APPROVED_PAYLOAD_DIGEST_INVALID")
        if operation.operation_kind == "CREATE_DRAFT":
            if (type(payload) is not DraftPayload or target_version is not None
                    or payload.expected_target_version is not None):
                raise ValueError("COM_CREATE_DRAFT_PREIMAGE_INVALID")
        elif (target_version != operation.expected_version or payload is not None
              or type(bindings) is not tuple or bindings):
            raise ValueError("COM_OPERATION_PREIMAGE_INVALID")
        try:
            actual_payload_digest = payload_digest(payload, target_version)
        except (TypeError, ValueError):
            raise ValueError("COM_APPROVED_PAYLOAD_INVALID") from None
        if actual_payload_digest != approved_payload_digest:
            raise ValueError("COM_APPROVED_PAYLOAD_DIGEST_MISMATCH")
        if operation.operation_kind == "CREATE_DRAFT":
            assignments = assignments_from_approved_payload(payload, bindings)
        else:
            assignments = ()
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "property_setting_method", property_setting_method)
        object.__setattr__(self, "assignments", assignments)

    @classmethod
    def from_approved_payload(
            cls, operation: ComOperationManifest, property_setting_method: str,
            payload: DraftPayload | None,
            bindings: tuple[PayloadPropertyBinding, ...], *,
            approved_payload_digest: str, target_version: str | None
            ) -> PreparedComManifest:
        """Require the coordinator's approved digest and target preimage at every operation."""
        return cls(
            operation,
            property_setting_method,
            payload,
            bindings,
            approved_payload_digest=approved_payload_digest,
            target_version=target_version,
        )

    def property_manifest_sha256(self) -> str:
        """Compute assignments with the same write mode committed by the operation manifest."""
        return mapped_property_manifest_sha256(
            self.assignments,
            write_mode=self.operation.write_mode,
            property_setting_method=self.property_setting_method,
        )

    def operation_manifest_sha256(self) -> str:
        return self.operation.sha256()


__all__ = [
    "ComOperationManifest",
    "ComValueAssignment",
    "MappedPropertyAssignment",
    "PayloadPropertyBinding",
    "PreparedComManifest",
    "assignments_from_approved_payload",
    "com_values_from_approved_payload",
    "com_values_from_write_port_payload",
    "draft_payload_from_write_port",
    "mapped_property_manifest_sha256",
]
