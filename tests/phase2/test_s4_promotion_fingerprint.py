"""Acceptance cases for the offline promotion-request-v1 canonical fingerprint."""

from dataclasses import replace

import pytest

from business_ai_gateway.phase2.promotion_fingerprint import (
    PromotionRequestFingerprintV1,
    promotion_request_fingerprint_bytes_v1,
    promotion_request_fingerprint_sha256_v1,
)


_TARGET = "00000000-0000-0000-0000-000000000001"
_ATTESTATION = "00000000-0000-0000-0000-000000000002"
_MAX_BIGINT = 9_223_372_036_854_775_807


def _promote(**changes: object) -> PromotionRequestFingerprintV1:
    values: dict[str, object] = {
        "tenant": "t",
        "source": "s",
        "company": "c",
        "model": "m",
        "operation": "promote",
        "requested_rollback_version": None,
        "expected_version": 0,
        "target_revision": _TARGET,
        "requester": "u",
        "approver": "v",
        "attestation": _ATTESTATION,
        "evidence_reference": "ref",
        "artifact_version": "version",
        "content_digest": "a" * 64,
    }
    values.update(changes)
    return PromotionRequestFingerprintV1(**values)  # type: ignore[arg-type]


def _independent_frame(value: str | None) -> bytes:
    """Implement the written wire rule in the test, not via the encoder under test."""
    if value is None:
        return b"0"
    raw = value.encode("utf-8")
    return b"1" + str(len(raw)).encode("ascii") + b":" + raw


def _reference_bytes(fields: tuple[str | None, ...]) -> bytes:
    return b"erp-mcp:promotion-request:v1\0" + b"".join(
        _independent_frame(field) for field in fields
    )


def test_promote_vector_uses_null_marker_and_matches_independent_sha256() -> None:
    request = _promote()
    fields = (
        "t", "s", "c", "m", "promote", None, "0", _TARGET, "u", "v",
        _ATTESTATION, "ref", "version", "a" * 64,
    )

    assert promotion_request_fingerprint_bytes_v1(request) == _reference_bytes(fields)
    assert promotion_request_fingerprint_sha256_v1(request) == (
        "f3f373edfe8377abd39fa25dc0e7f0d0f821f8bf146bbacb04e06d568b149c58"
    )


def test_rollback_vector_binds_utf8_delimiters_and_max_signed_bigint() -> None:
    request = _promote(
        model="m:é",
        operation="rollback",
        requested_rollback_version=1,
        expected_version=_MAX_BIGINT,
        evidence_reference="x:0:y",
        artifact_version="v:1",
        content_digest="b" * 64,
    )
    fields = (
        "t", "s", "c", "m:é", "rollback", "1", str(_MAX_BIGINT), _TARGET,
        "u", "v", _ATTESTATION, "x:0:y", "v:1", "b" * 64,
    )

    assert promotion_request_fingerprint_bytes_v1(request) == _reference_bytes(fields)
    assert promotion_request_fingerprint_sha256_v1(request) == (
        "99adccfdc14b532e6bcebd848ba1a2bfc14b2b59b38a0a0a78285d8b66551d1d"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant", "tenant-2"),
        ("source", "source-2"),
        ("company", "company-2"),
        ("model", "model-2"),
        ("target_revision", "00000000-0000-0000-0000-000000000003"),
        ("requester", "requester-2"),
        ("approver", "approver-2"),
        ("attestation", "00000000-0000-0000-0000-000000000003"),
        ("evidence_reference", "ref-2"),
        ("artifact_version", "version-2"),
        ("content_digest", "b" * 64),
    ],
)
def test_each_resolved_string_field_changes_fingerprint(field: str, value: str) -> None:
    original = _promote()
    changed = replace(original, **{field: value})

    assert promotion_request_fingerprint_sha256_v1(changed) != (
        promotion_request_fingerprint_sha256_v1(original)
    )


def test_operation_and_rollback_version_are_bound() -> None:
    promote = _promote(expected_version=2)
    rollback = replace(
        promote,
        operation="rollback",
        requested_rollback_version=1,
    )

    assert promotion_request_fingerprint_sha256_v1(rollback) != (
        promotion_request_fingerprint_sha256_v1(promote)
    )
    assert promotion_request_fingerprint_bytes_v1(rollback) != (
        promotion_request_fingerprint_bytes_v1(promote)
    )


def test_expected_version_is_bound() -> None:
    original = _promote(expected_version=4)
    changed = replace(original, expected_version=5)

    assert promotion_request_fingerprint_sha256_v1(changed) != (
        promotion_request_fingerprint_sha256_v1(original)
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"operation": "PROMOTE"},
        {"operation": "archive"},
        {"expected_version": True},
        {"expected_version": -1},
        {"expected_version": _MAX_BIGINT + 1},
        {"requested_rollback_version": 1},  # promote cannot carry rollback state
        {"target_revision": "00000000-0000-0000-0000-00000000000A"},
        {"target_revision": "00000000000000000000000000000001"},
        {"attestation": "00000000-0000-0000-0000-00000000000A"},
        {"content_digest": "A" * 64},
        {"content_digest": "a" * 63},
        {"tenant": ""},
        {"tenant": "tenant\0suffix"},
        {"tenant": "x" * 4097},
        {"tenant": "\ud800"},
    ],
)
def test_malformed_or_noncanonical_promotion_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _promote(**changes)


@pytest.mark.parametrize(
    "rollback_version,expected_version",
    [
        (None, 2),
        (0, 2),
        (1, 1),
        (2, 2),
        (True, 2),
        (_MAX_BIGINT + 1, _MAX_BIGINT),
    ],
)
def test_invalid_rollback_version_or_signed_bigint_is_rejected(
    rollback_version: int | None, expected_version: int
) -> None:
    with pytest.raises(ValueError):
        _promote(
            operation="rollback",
            requested_rollback_version=rollback_version,
            expected_version=expected_version,
        )

