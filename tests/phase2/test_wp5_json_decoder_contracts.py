"""WP5 decoder acceptance: bounded trust snapshots and signed evidence envelopes.

The tests are deterministic and offline. They do not load trust data, connect to PostgreSQL,
invoke COM, or establish runtime qualification.
"""
from __future__ import annotations

import builtins
import hashlib
import json
import time
import tracemalloc
import unittest
from unittest.mock import patch

from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidence,
    OutcomeEvidenceV2,
    OutcomeEvidenceV3,
    PostCompletionChallenge,
    PostCompletionReadAttestation,
    canonical_json_bytes,
    seal_record_fixture,
)
from erp_mcp_private_writer.postgres_evidence_trust import (
    EvidenceTrustSourceError,
    PostgresEvidenceTrustSource,
    _bounded_json_integer,
    _check_json_text_limits,
    _measure_json_value,
)
from erp_mcp_private_writer.production_evidence_verifier import (
    ProductionEvidenceVerificationError,
    ProductionEvidenceVerifier,
)


def _trust_payload(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "revision": "1",
        "loaded_at": "2026-10-26T00:00:00Z",
        "signers": [],
        "process_bindings": [],
        "oracle_artifacts": [],
        "outcome_version_floors": [],
    }
    value.update(updates)
    return value


def _attempt() -> DispatchAttempt:
    h = "a" * 64
    return DispatchAttempt.from_mapping({
        "tenant_id": "tenant-1", "company_id": "company-1",
        "organization_ref": "org-1", "base_fingerprint": h,
        "change_id": "123e4567-e89b-42d3-a456-426614174000",
        "claim_generation": 2, "dispatch_generation": 3,
        "dispatch_cas_id": "123e4567-e89b-42d3-a456-426614174002",
        "call_id": "123e4567-e89b-42d3-a456-426614174001",
        "operation_kind": "POST", "approval_digest": h, "auth_epoch": 4,
        "permit_id": "123e4567-e89b-42d3-a456-426614174006",
        "permit_digest": h, "expected_target_ref": "doc-42",
        "expected_pre_version": "v7", "writer_service_id": "writer-service",
        "writer_host_id": "writer-host",
        "writer_process_instance_id": "123e4567-e89b-42d3-a456-426614174004",
        "onec_session_instance_id": "123e4567-e89b-42d3-a456-426614174005",
    })


def _signed_receipt() -> DispatchReceipt:
    h = "a" * 64
    fields: dict[str, object] = {
        "receipt_version": "1", "tenant_id": "tenant-1", "company_id": "company-1",
        "organization_ref": "org-1", "base_fingerprint": h,
        "target_class": "qualified-receipt", "expected_target_ref": "doc-42",
        "expected_pre_version": "v7",
        "change_id": "123e4567-e89b-42d3-a456-426614174000",
        "request_id": "123e4567-e89b-42d3-a456-426614174000",
        "claim_generation": 2, "approval_digest_version": "2", "approval_digest": h,
        "auth_epoch": 4, "permit_id": "123e4567-e89b-42d3-a456-426614174006",
        "permit_digest": h, "receipt_id": "123e4567-e89b-42d3-a456-426614174003",
        "call_id": "123e4567-e89b-42d3-a456-426614174001", "dispatch_generation": 3,
        "dispatch_cas_id": "123e4567-e89b-42d3-a456-426614174002",
        "writer_service_id": "writer-service", "writer_host_id": "writer-host",
        "writer_process_instance_id": "123e4567-e89b-42d3-a456-426614174004",
        "onec_session_id": "session-1",
        "onec_session_instance_id": "123e4567-e89b-42d3-a456-426614174005",
        "operation_kind": "POST", "started_at": "2026-10-16T12:34:56.123456Z",
        "write_invocation_stage": "INVOKED", "call_returned": True,
        "returned_at": "2026-10-16T12:34:56.123456Z",
        "result_class": "CALL_RETURNED_SUCCESS", "returned_target_ref": "doc-42",
        "returned_version": "v8", "no_effect_evidence_digest": None,
        "error_family": None, "mapping_version": "map-v2",
        "configuration_fingerprint": h, "approved_payload_digest": h,
        "mapped_property_manifest_sha256": h, "COM_operation_manifest_sha256": h,
        "signer_key_id": "writer-key", "key_version": "key-v1",
        "signer_role": "writer_receipt", "algorithm": "Ed25519",
        "signed_payload_digest": h, "signature": "",
    }
    return seal_record_fixture(DispatchReceipt, fields, bytes(range(32)))  # type: ignore[return-value]


def _outcome_fields(*, uncertainty_size: int = 0) -> dict[str, object]:
    h = "a" * 64
    return {
        "evidence_version": "1", "tenant_id": "tenant-1", "company_id": "company-1",
        "organization_ref": "org-1", "base_fingerprint": h,
        "change_id": "123e4567-e89b-42d3-a456-426614174000",
        "claim_generation": 2, "call_id": "123e4567-e89b-42d3-a456-426614174001",
        "dispatch_receipt_id": "123e4567-e89b-42d3-a456-426614174003",
        "approval_digest": h, "verifier_service_id": "verifier-service",
        "verifier_host_id": "verifier-host", "signer_key_id": "verifier-key",
        "key_version": "key-v1", "algorithm": "Ed25519", "role": "verification_worker",
        "operation_kind": "POST", "observed_at": "2026-10-16T12:34:56.123456Z",
        "read_session_id": "read-session-1", "target_ref": "doc-42", "pre_version": "v7",
        "observed_version": "v8", "document_posting_state": "POSTED",
        "field_snapshot_digest": h, "lines_digest": h, "movement_multiset": (),
        "registrar": "doc-42", "register_catalogue_version": "catalogue-v1",
        "movement_count_by_register": {}, "movement_digest_by_register": {},
        "movement_multiset_digest": hashlib.sha256(b"[]").hexdigest(),
        "expected_effect_digest": h, "observed_effect_digest": h,
        "fields_match": True, "movements_match": True, "version_relation": "ADVANCED",
        "reader_health": "HEALTHY", "observation_complete": True,
        "effect_presence": "PRESENT", "effect_identity": "MATCH",
        "completion_proof_class": "WRITER_CALL_RETURNED", "attribution_result": "PROVEN",
        "attribution_evidence_ref": "audit-ref-1",
        "uncertainties": ("x" * uncertainty_size,) if uncertainty_size else (),
        "canonical_evidence_digest": h, "signature": "",
    }


def _signed_outcome(*, uncertainty_size: int = 0) -> OutcomeEvidence:
    return seal_record_fixture(
        OutcomeEvidence, _outcome_fields(uncertainty_size=uncertainty_size), bytes(range(1, 33)),
    )  # type: ignore[return-value]


def _signed_outcome_v2() -> OutcomeEvidenceV2:
    h = "a" * 64
    fields = _outcome_fields()
    fields.update({
        "evidence_version": "2", "document_shape_revision": "shape-v1",
        "configuration_fingerprint": h, "oracle_id": "oracle-1",
        "oracle_version": "v1", "oracle_digest": h,
        "expected_effect_schema_version": "effects-v1",
    })
    return seal_record_fixture(
        OutcomeEvidenceV2, fields, bytes(range(1, 33)),
    )  # type: ignore[return-value]


def _signed_outcome_v3() -> OutcomeEvidenceV3:
    h = "a" * 64
    fields = _outcome_fields()
    fields.update({
        "evidence_version": "3", "document_shape_revision": "shape-v1",
        "configuration_fingerprint": h, "oracle_id": "oracle-1",
        "oracle_version": "v1", "oracle_digest": h,
        "expected_effect_schema_version": "effects-v1",
        "completion_proof_digest": h,
        "post_completion_challenge_id": "123e4567-e89b-42d3-a456-426614174007",
        "verification_sequence": 1, "read_attestation_digest": h,
    })
    return seal_record_fixture(
        OutcomeEvidenceV3, fields, bytes(range(1, 33)),
    )  # type: ignore[return-value]


def _signed_completion_proof() -> CompletionProof:
    h = "a" * 64
    fields: dict[str, object] = {
        "proof_version": "1", "completion_proof_id": "123e4567-e89b-42d3-a456-426614174003",
        "tenant_id": "tenant-1", "company_id": "company-1", "organization_ref": "org-1",
        "base_fingerprint": h, "change_id": "123e4567-e89b-42d3-a456-426614174000",
        "claim_generation": 2, "dispatch_generation": 3,
        "dispatch_cas_id": "123e4567-e89b-42d3-a456-426614174002",
        "call_id": "123e4567-e89b-42d3-a456-426614174001", "operation_kind": "POST",
        "writer_process_instance_id": "123e4567-e89b-42d3-a456-426614174004",
        "onec_session_instance_id": "123e4567-e89b-42d3-a456-426614174005",
        "proof_class": "WRITER_CALL_RETURNED", "source_service_id": "writer-service",
        "source_host_id": "writer-host",
        "source_process_instance_id": "123e4567-e89b-42d3-a456-426614174004",
        "source_session_instance_id": "writer-local-session",
        "observed_session_instance_id": "123e4567-e89b-42d3-a456-426614174005",
        "evidence_ref": "completion-ref-1", "evidence_digest": h,
        "observed_at": "2026-10-16T12:34:56.123456Z", "signer_key_id": "writer-key",
        "key_version": "key-v1", "signer_role": "writer_receipt", "algorithm": "Ed25519",
        "canonical_evidence_digest": h, "signature": "",
    }
    return seal_record_fixture(CompletionProof, fields, bytes(range(32)))  # type: ignore[return-value]


def _signed_read_attestation() -> PostCompletionReadAttestation:
    h = "a" * 64
    fields: dict[str, object] = {
        "attestation_version": "1", "attestation_id": "123e4567-e89b-42d3-a456-426614174008",
        "tenant_id": "tenant-1", "company_id": "company-1", "organization_ref": "org-1",
        "base_fingerprint": h, "change_id": "123e4567-e89b-42d3-a456-426614174000",
        "claim_generation": 2, "dispatch_generation": 3,
        "dispatch_cas_id": "123e4567-e89b-42d3-a456-426614174002",
        "call_id": "123e4567-e89b-42d3-a456-426614174001",
        "challenge_id": "123e4567-e89b-42d3-a456-426614174007",
        "challenge_nonce_digest": h, "query_spec_digest": h, "query_request_digest": h,
        "source_response_digest": h, "outcome_observation_digest": h,
        "verification_sequence": 1,
        "process_instance_id": "123e4567-e89b-42d3-a456-426614174004",
        "attestor_service_id": "reader-service", "attestor_host_id": "reader-host",
        "completed_at": "2026-10-16T12:34:56.123456Z", "signer_key_id": "reader-key",
        "key_version": "key-v1", "signer_role": "read_attestor", "algorithm": "Ed25519",
        "canonical_attestation_digest": h, "signature": "",
    }
    return seal_record_fixture(
        PostCompletionReadAttestation, fields, bytes(range(3, 35)),
    )  # type: ignore[return-value]


def _challenge_fields(*, sequence_floor: int) -> dict[str, object]:
    h = "a" * 64
    return {
        "challenge_version": "1", "challenge_id": "123e4567-e89b-42d3-a456-426614174007",
        "tenant_id": "tenant-1", "company_id": "company-1", "organization_ref": "org-1",
        "base_fingerprint": h, "change_id": "123e4567-e89b-42d3-a456-426614174000",
        "claim_generation": 2, "dispatch_generation": 3,
        "dispatch_cas_id": "123e4567-e89b-42d3-a456-426614174002",
        "call_id": "123e4567-e89b-42d3-a456-426614174001",
        "completion_proof_digest": h, "verifier_service_id": "verifier-service",
        "verifier_host_id": "verifier-host", "verification_sequence_floor": sequence_floor,
        "challenge_nonce": h, "query_spec_digest": h,
        "read_attestor_service_id": "read-service", "read_attestor_host_id": "read-host",
        "issued_at": "2026-10-16T12:34:56.123456Z", "issuer_service_id": "issuer-service",
        "issuer_host_id": "issuer-host", "signer_key_id": "supervisor-key",
        "key_version": "key-v1", "signer_role": "completion_supervisor",
        "algorithm": "Ed25519", "canonical_challenge_digest": h, "signature": "",
    }


def _signed_challenge(*, sequence_floor: int) -> PostCompletionChallenge:
    return seal_record_fixture(
        PostCompletionChallenge, _challenge_fields(sequence_floor=sequence_floor), bytes(range(2, 34)),
    )  # type: ignore[return-value]


class TrustSnapshotDecoderAcceptance(unittest.TestCase):
    """Acceptance `WP5-JSON-DECODER-01`."""

    def assert_invalid_snapshot(self, value: object) -> None:
        with self.assertRaises(EvidenceTrustSourceError) as caught:
            PostgresEvidenceTrustSource._decode(value)
        self.assertEqual(caught.exception.code, "TRUST_SNAPSHOT_PAYLOAD_INVALID")

    def test_valid_closed_empty_snapshot_decodes(self) -> None:
        snapshot = PostgresEvidenceTrustSource._decode(json.dumps(_trust_payload()))
        self.assertEqual(snapshot.revision, "1")
        self.assertEqual(snapshot.signers, ())

    def test_duplicate_keys_constants_floats_and_overflow_are_stable_refusals(self) -> None:
        for payload in (
            '{"revision":"1","revision":"2"}',
            '{"revision":"1","loaded_at":"x","signers":[],"process_bindings":[],'
            '"oracle_artifacts":[],"outcome_version_floors":[],"loaded_\\u0061t":"x"}',
            '{"revision":"1","loaded_at":"2026-10-26T00:00:00Z","signers":[{"a":1,"a":2}],'
            '"process_bindings":[],"oracle_artifacts":[],"outcome_version_floors":[]}',
            '{"revision":"1","loaded_at":"2026-10-26T00:00:00Z","signers":[{"a":1,'
            '"\\u0061":2}],"process_bindings":[],"oracle_artifacts":[],"outcome_version_floors":[]}',
            '{"revision":"1","loaded_at":"2026-10-26T00:00:00Z","signers":[{"a":{"b":{"c":1,"c":2}}}],'
            '"process_bindings":[],"oracle_artifacts":[],"outcome_version_floors":[]}',
            '{"revision":"1","loaded_at":"2026-10-26T00:00:00Z","signers":[{"a":{"b":{"key":1,'
            '"\\u006b":2}}}],"process_bindings":[],"oracle_artifacts":[],"outcome_version_floors":[]}',
            json.dumps(_trust_payload())[:-1] + ',"extra":NaN}',
            json.dumps(_trust_payload())[:-1] + ',"extra":Infinity}',
            json.dumps(_trust_payload())[:-1] + ',"extra":-Infinity}',
            json.dumps(_trust_payload())[:-1] + ',"extra":1e999}',
            json.dumps(_trust_payload())[:-1] + ',"extra":1.25}',
            json.dumps(_trust_payload())[:-1] + ',"extra":1.0}',
            json.dumps(_trust_payload())[:-1] + ',"extra":1e0}',
            json.dumps(_trust_payload())[:-1] + ',"extra":true}',
            json.dumps(_trust_payload())[:-1] + ',"extra":2147483648}',
        ):
            with self.subTest(payload=payload[-24:]):
                self.assert_invalid_snapshot(payload)

    def test_malformed_json_and_escaped_surrogate_refuse_with_stable_error(self) -> None:
        valid = json.dumps(_trust_payload(), separators=(",", ":"))
        for payload in (
            valid[:-1],
            valid + "{}",
            valid[:-1] + ',"extra":1',
            '{"revision":"1","loaded_at":"x","signers":[{"name":"\\ud800"}],'
            '"process_bindings":[],"oracle_artifacts":[],"outcome_version_floors":[]}',
        ):
            with self.subTest(payload=payload[-32:]):
                self.assert_invalid_snapshot(payload)

        # A non-BMP scalar is valid Unicode in a schema-approved signer service identifier.
        signer = {
            "key_id": "writer-key", "key_version": "v1", "public_key_hex": "00" * 32,
            "signer_role": "writer_receipt", "service_id": "writer-😀", "host_id": "writer-host",
            "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z",
            "revoked_at": None, "allowed_scopes": [],
            "rotation_history": [{"key_id": "writer-key", "key_version": "v1"}],
        }
        accepted_scalar = PostgresEvidenceTrustSource._decode(
            json.dumps(_trust_payload(signers=[signer]), separators=(",", ":")))
        self.assertEqual(accepted_scalar.signers[0].service_id, "writer-😀")

    def test_driver_dictionary_compact_size_boundary_and_no_serialization_precheck(self) -> None:
        import erp_mcp_private_writer.postgres_evidence_trust as module

        limit = 8 * 1024 * 1024
        # No semantically valid closed snapshot can contain an 8 MiB scalar because each
        # decoded trust field has its own smaller domain bound. Exercise the driver-dict
        # compact representation bound directly, then prove an oversized dict is rejected
        # without first serializing it in the production decoder.
        exact = {"v": "x" * (limit - 8)}
        self.assertEqual(
            len(json.dumps(exact, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
            limit,
        )
        _measure_json_value(exact)
        with self.assertRaises(ValueError):
            _measure_json_value({"v": exact["v"] + "x"})

        over_limit = {**_trust_payload(), "extra": "x" * limit}
        with patch.object(module.json, "dumps", wraps=json.dumps) as dumps:
            self.assert_invalid_snapshot(over_limit)
            dumps.assert_not_called()

    def test_depth_byte_and_unicode_bounds_apply_to_text_and_driver_dicts(self) -> None:
        over_depth = "{" * 33 + "}" * 33
        self.assert_invalid_snapshot(over_depth)
        _check_json_text_limits("[" * 32 + "0" + "]" * 32)
        with self.assertRaises(ValueError):
            _check_json_text_limits("[" * 33 + "0" + "]" * 33)
        self.assert_invalid_snapshot(_trust_payload(revision="01"))
        self.assert_invalid_snapshot(_trust_payload(revision="1", extra="\ud800"))
        self.assert_invalid_snapshot({**_trust_payload(), "extra": "\udfff"})
        self.assert_invalid_snapshot({**_trust_payload(), "extra": 1.25})
        dictionary_with_surrogate_key = _trust_payload()
        dictionary_with_surrogate_key["\ud800"] = "value"
        self.assert_invalid_snapshot(dictionary_with_surrogate_key)
        self.assert_invalid_snapshot({**_trust_payload(), "extra": 2 ** 31})
        _measure_json_value({"minimum": -(2 ** 31), "maximum": 2 ** 31 - 1})
        for value in (-(2 ** 31) - 1, 2 ** 31):
            with self.subTest(driver_integer=value):
                with self.assertRaises(ValueError):
                    _measure_json_value({"value": value})
        self.assert_invalid_snapshot({**_trust_payload(), "extra": {"nested": 1}})
        deepest_valid_dictionary: object = 0
        for _ in range(31):
            deepest_valid_dictionary = {"nested": deepest_valid_dictionary}
        _measure_json_value({"extra": deepest_valid_dictionary})
        nested_dictionary: object = 0
        for _ in range(32):
            nested_dictionary = {"nested": nested_dictionary}
        with self.assertRaises(ValueError):
            _measure_json_value({"extra": nested_dictionary})
        self.assert_invalid_snapshot({**_trust_payload(), "extra": "x" * (8 * 1024 * 1024)})
        _measure_json_value({"v": "x" * (8 * 1024 * 1024 - 8)})
        with self.assertRaises(ValueError):
            _measure_json_value({"v": "x" * (8 * 1024 * 1024 - 7)})

        valid_text = json.dumps(_trust_payload(), separators=(",", ":"))
        at_byte_limit = valid_text + " " * (8 * 1024 * 1024 - len(valid_text))
        snapshot = PostgresEvidenceTrustSource._decode(at_byte_limit)
        self.assertEqual(snapshot.revision, "1")
        over_bytes = at_byte_limit + " "
        with self.assertRaises(ValueError):
            _check_json_text_limits(over_bytes)
        self.assert_invalid_snapshot(over_bytes)

    def test_text_byte_limit_counts_multibyte_utf8_exactly(self) -> None:
        byte_limit = 8 * 1024 * 1024
        # Quotes contribute two UTF-8 bytes; each U+00E9 contributes exactly two.
        accepted = '"' + "é" * ((byte_limit - 2) // 2) + '"'
        self.assertEqual(len(accepted.encode("utf-8")), byte_limit)
        _check_json_text_limits(accepted)

        rejected = accepted[:-1] + "é" + '"'
        with self.assertRaises(ValueError):
            _check_json_text_limits(rejected)

    def test_text_byte_count_rejects_actual_lone_surrogate(self) -> None:
        payload_with_surrogate_code_point = '"' + "\ud800" + '"'
        with self.assertRaises(UnicodeEncodeError):
            _check_json_text_limits(payload_with_surrogate_code_point)

    def test_signed_32_bit_integer_limits_are_exact(self) -> None:
        self.assertEqual(_bounded_json_integer("-2147483648"), -(2 ** 31))
        self.assertEqual(_bounded_json_integer("2147483647"), 2 ** 31 - 1)
        for token in ("-2147483649", "2147483648", "9" * 21):
            with self.subTest(token=token):
                with self.assertRaises(ValueError):
                    _bounded_json_integer(token)

    def test_one_million_json_values_pass_and_next_value_refuses_preparse(self) -> None:
        import erp_mcp_private_writer.postgres_evidence_trust as module

        at_limit = "[" + ",".join(["0"] * 999_999) + "]"
        over_limit = "[" + ",".join(["0"] * 1_000_000) + "]"
        _check_json_text_limits(at_limit)
        with self.assertRaises(ValueError):
            _check_json_text_limits(over_limit)

        original_loads = json.loads
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            self.assert_invalid_snapshot(at_limit)
            self.assertEqual(loads.call_count, 1)
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            self.assert_invalid_snapshot(over_limit)
            self.assertEqual(loads.call_count, 0)

    def test_one_million_driver_dictionary_values_are_rechecked_after_decode(self) -> None:
        import erp_mcp_private_writer.postgres_evidence_trust as module

        # root + seven field values (including the extra array) + array entries = 1,000,000.
        exact = {**_trust_payload(), "extra": [0] * 999_992}
        over = {**_trust_payload(), "extra": [0] * 999_993}
        original_measure = module._measure_json_value
        measured: list[int] = []

        def measure_and_record(document: object) -> None:
            original_measure(document)
            measured.append(len(document["extra"]))  # type: ignore[index]

        with patch.object(module, "_measure_json_value", side_effect=measure_and_record):
            # Exact shape bound reaches the later closed-schema check; one additional value
            # is refused by the post-decode resource recheck.
            self.assert_invalid_snapshot(exact)
            self.assertEqual(measured, [999_992])
            self.assert_invalid_snapshot(over)
            self.assertEqual(measured, [999_992])


class EvidenceEnvelopeDecoderAcceptance(unittest.IsolatedAsyncioTestCase):
    """Acceptance `WP5-VERIFIER-DECODE-01`."""

    def test_valid_canonical_receipt_parses_to_exact_supported_type(self) -> None:
        encoded = canonical_json_bytes(_signed_receipt().to_dict())
        parsed = ProductionEvidenceVerifier.parse_envelope(encoded)
        self.assertIs(type(parsed), DispatchReceipt)

    def test_valid_canonical_outcome_at_two_mib_ceiling_is_accepted(self) -> None:
        limit = 2 * 1024 * 1024
        base_record = _signed_outcome()
        base_size = len(canonical_json_bytes(base_record.to_dict()))
        uncertainty_size = limit - base_size - 2
        self.assertGreater(uncertainty_size, 0)
        record = _signed_outcome(uncertainty_size=uncertainty_size)
        encoded = canonical_json_bytes(record.to_dict())
        self.assertEqual(len(encoded), limit)
        parsed = ProductionEvidenceVerifier.parse_envelope(encoded)
        self.assertIs(type(parsed), OutcomeEvidence)

        over_record = _signed_outcome(uncertainty_size=uncertainty_size + 1)
        over_encoded = canonical_json_bytes(over_record.to_dict())
        self.assertEqual(len(over_encoded), limit + 1)
        with self.assertRaises(ProductionEvidenceVerificationError) as caught:
            ProductionEvidenceVerifier.parse_envelope(over_encoded)
        self.assertEqual(caught.exception.code, "EVIDENCE_ENVELOPE_INVALID")

    def test_signed_bigint_bounds_and_overlong_tokens_flow_through_parse_envelope(self) -> None:
        import erp_mcp_private_writer.production_evidence_verifier as module

        maximum = (2 ** 63) - 1
        max_record = _signed_challenge(sequence_floor=maximum)
        parsed = ProductionEvidenceVerifier.parse_envelope(
            canonical_json_bytes(max_record.to_dict()))
        self.assertIs(type(parsed), PostCompletionChallenge)
        self.assertEqual(parsed.verification_sequence_floor, maximum)

        minimum = -(2 ** 63)
        min_envelope = canonical_json_bytes(_challenge_fields(sequence_floor=minimum))
        parsed_integers: list[tuple[str, int]] = []
        original_parser = module._bounded_evidence_integer

        def record_integer(token: str) -> int:
            value = original_parser(token)
            parsed_integers.append((token, value))
            return value

        with patch.object(module, "_bounded_evidence_integer", side_effect=record_integer):
            with self.assertRaises(ProductionEvidenceVerificationError) as caught:
                ProductionEvidenceVerifier.parse_envelope(min_envelope)
        self.assertEqual(caught.exception.code, "EVIDENCE_ENVELOPE_INVALID")
        self.assertIn((str(minimum), minimum), parsed_integers)

        for token in (str(maximum + 1), "9" * 20):
            with self.subTest(token=token):
                fields = _challenge_fields(sequence_floor=0)
                encoded = canonical_json_bytes({**fields, "verification_sequence_floor": int(token)})
                with self.assertRaises(ProductionEvidenceVerificationError) as caught:
                    ProductionEvidenceVerifier.parse_envelope(encoded)
                self.assertEqual(caught.exception.code, "EVIDENCE_ENVELOPE_INVALID")

        overlong_fields = _challenge_fields(sequence_floor=0)
        overlong_envelope = canonical_json_bytes({
            **overlong_fields, "verification_sequence_floor": 10 ** 20,
        })
        overlong_token = str(10 ** 20)
        with patch.object(module, "int", wraps=builtins.int, create=True) as integer_constructor:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(overlong_envelope)
            constructed_tokens = [call.args[0] for call in integer_constructor.call_args_list
                                  if call.args]
            self.assertNotIn(overlong_token, constructed_tokens)

    def test_maximum_payload_decode_duration_and_peak_allocation(self) -> None:
        # Prepare maximum-sized inputs outside the measured operations.
        trust_prefix = json.dumps(_trust_payload(), separators=(",", ":"))
        trust_envelope = trust_prefix + " " * (8 * 1024 * 1024 - len(trust_prefix))
        base_outcome = _signed_outcome()
        base_size = len(canonical_json_bytes(base_outcome.to_dict()))
        evidence_limit = 2 * 1024 * 1024
        evidence_record = _signed_outcome(uncertainty_size=evidence_limit - base_size - 2)
        evidence_envelope = canonical_json_bytes(evidence_record.to_dict())
        self.assertEqual(len(trust_envelope.encode("utf-8")), 8 * 1024 * 1024)
        self.assertEqual(len(evidence_envelope), evidence_limit)

        measurements: list[tuple[str, float, int]] = []
        operations = (
            ("trust_snapshot_8mib", lambda: PostgresEvidenceTrustSource._decode(trust_envelope)),
            ("evidence_envelope_2mib", lambda: ProductionEvidenceVerifier.parse_envelope(
                evidence_envelope)),
        )
        for name, operation in operations:
            # Measure wall time without tracing overhead, then measure peak Python allocation
            # separately on the same prebuilt payload. No arbitrary allocation ceiling is implied.
            started = time.perf_counter()
            result = operation()
            elapsed = time.perf_counter() - started
            self.assertIsNotNone(result)

            tracemalloc.start()
            try:
                traced_result = operation()
                _, peak_bytes = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertIsNotNone(traced_result)
            measurements.append((name, elapsed, peak_bytes))
            print(
                f"WP5 decode measurement {name}: duration={elapsed:.6f}s, "
                f"traced_peak={peak_bytes} bytes"
            )
            self.assertLessEqual(elapsed, 3.0, f"{name} exceeded the default 3-second budget")

        self.assertEqual([item[0] for item in measurements], [
            "trust_snapshot_8mib", "evidence_envelope_2mib",
        ])

    async def test_invalid_envelope_refuses_before_trust_source_lookup(self) -> None:
        class Source:
            def __init__(self) -> None:
                self.calls = 0

            async def load_snapshot(self, request):
                self.calls += 1
                raise AssertionError("invalid envelope must not load trust data")

        source = Source()
        verifier = ProductionEvidenceVerifier(source)
        with self.assertRaises(ProductionEvidenceVerificationError) as caught:
            await verifier.verify(b'{"bad":NaN}', attempt=_attempt())
        self.assertEqual(caught.exception.code, "EVIDENCE_ENVELOPE_INVALID")
        self.assertEqual(source.calls, 0)

    def test_duplicate_keys_noncanonical_and_float_tokens_refuse(self) -> None:
        for payload in (
                        b'{"a":1,"a":2}',
                        b'{"outer":{"a":1,"a":2}}',
                        b'{"outer":{"nested":{"a":1,"\x5cu0061":2}}}',
                        b'{ "a":1}', b'{"a":NaN}',
                        b'{"a":Infinity}', b'{"a":-Infinity}', b'{"a":1e999}',
                        b'{"a":1.25}', b'{"a":1.0}', b'{"a":1e0}',
                        b'{"a":"\\ud800"}', b"\xff"):
            with self.subTest(payload=payload):
                with self.assertRaises(ProductionEvidenceVerificationError) as caught:
                    ProductionEvidenceVerifier.parse_envelope(payload)
                self.assertEqual(caught.exception.code, "EVIDENCE_ENVELOPE_INVALID")

    def test_noncanonical_key_order_refuses(self) -> None:
        fields = _signed_receipt().to_dict()
        canonical = canonical_json_bytes(fields)
        reverse_order = json.dumps(
            dict(reversed(sorted(fields.items()))), separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        self.assertNotEqual(reverse_order, canonical)
        with self.assertRaises(ProductionEvidenceVerificationError) as caught:
            ProductionEvidenceVerifier.parse_envelope(reverse_order)
        self.assertEqual(caught.exception.code, "EVIDENCE_ENVELOPE_INVALID")

    def test_structural_node_and_byte_limits_stop_before_json_loads(self) -> None:
        import erp_mcp_private_writer.production_evidence_verifier as module

        original_loads = json.loads
        within_nodes = "[" + ",".join(["0"] * 99_999) + "]"
        over_nodes = "[" + ",".join(["0"] * 100_000) + "]"
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(within_nodes.encode("ascii"))
            self.assertEqual(loads.call_count, 1)
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(over_nodes.encode("ascii"))
            self.assertEqual(loads.call_count, 0)

        # Object keys count as structural nodes alongside their values. Root + key + array
        # + entries is exactly 100,000 here; the next entry must be rejected pre-allocation.
        within_object_nodes = '{"k":[' + ",".join(["0"] * 99_997) + ']}'
        over_object_nodes = '{"k":[' + ",".join(["0"] * 99_998) + ']}'
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(within_object_nodes.encode("ascii"))
            self.assertEqual(loads.call_count, 1)
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(over_object_nodes.encode("ascii"))
            self.assertEqual(loads.call_count, 0)

        at_depth_limit = "[" * 32 + "0" + "]" * 32
        over_depth_limit = "[" * 33 + "0" + "]" * 33
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(at_depth_limit.encode("ascii"))
            self.assertEqual(loads.call_count, 1)
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(over_depth_limit.encode("ascii"))
            self.assertEqual(loads.call_count, 0)

        at_byte_limit = b"{}" + b" " * (2 * 1024 * 1024 - 2)
        over_byte_limit = at_byte_limit + b" "
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(at_byte_limit)
            self.assertEqual(loads.call_count, 1)
        with patch.object(module.json, "loads", wraps=original_loads) as loads:
            with self.assertRaises(ProductionEvidenceVerificationError):
                ProductionEvidenceVerifier.parse_envelope(over_byte_limit)
            self.assertEqual(loads.call_count, 0)

    def test_each_supported_envelope_schema_parses_once_and_canonicalizes_once(self) -> None:
        import erp_mcp_private_writer.production_evidence_verifier as module

        records = (
            _signed_receipt(), _signed_outcome(), _signed_outcome_v2(), _signed_outcome_v3(),
            _signed_completion_proof(), _signed_challenge(sequence_floor=0),
            _signed_read_attestation(),
        )
        original_loads = json.loads
        original_canonical = module.canonical_json_bytes
        for record in records:
            encoded = canonical_json_bytes(record.to_dict())
            with self.subTest(record_type=type(record).__name__):
                with patch.object(module.json, "loads", wraps=original_loads) as loads, \
                        patch.object(module, "canonical_json_bytes", wraps=original_canonical) as canonical:
                    parsed = ProductionEvidenceVerifier.parse_envelope(encoded)
                self.assertIs(type(parsed), type(record))
                self.assertEqual(loads.call_count, 1)
                self.assertEqual(canonical.call_count, 1)

    async def test_malformed_unknown_and_boundary_refusals_do_not_load_trust(self) -> None:
        import erp_mcp_private_writer.production_evidence_verifier as module

        class Source:
            def __init__(self) -> None:
                self.calls = 0

            async def load_snapshot(self, request):
                self.calls += 1
                raise AssertionError("invalid envelope must not load trust data")

        source = Source()
        verifier = ProductionEvidenceVerifier(source)
        over_nodes = ('{"k":[' + ",".join(["0"] * 99_998) + ']}').encode("ascii")
        receipt_fields = _signed_receipt().to_dict()
        challenge_fields = _signed_challenge(sequence_floor=0).to_dict()
        ambiguous_schema = canonical_json_bytes({**receipt_fields, **challenge_fields})
        malformed_cases = (
            (b'{"truncated":', None, "EVIDENCE_ENVELOPE_INVALID"),
            (b'{"outer":{"a":1,"\x5cu0061":2}}', None, "EVIDENCE_ENVELOPE_INVALID"),
            (canonical_json_bytes({"unknown": 1}), None, "EVIDENCE_ENVELOPE_INVALID"),
            (ambiguous_schema, None, "EVIDENCE_ENVELOPE_INVALID"),
            (b'{"a":1e0}', None, "EVIDENCE_ENVELOPE_INVALID"),
            (("[" * 33 + "0" + "]" * 33).encode("ascii"), None,
             "EVIDENCE_ENVELOPE_INVALID"),
            (over_nodes, 0, "EVIDENCE_ENVELOPE_INVALID"),
            (b"{}" + b" " * (2 * 1024 * 1024 - 1), None,
             "EVIDENCE_VALIDATION_CONTEXT_INVALID"),
        )
        original_loads = json.loads
        for payload, expected_load_count, expected_code in malformed_cases:
            with self.subTest(payload_size=len(payload)):
                with patch.object(module.json, "loads", wraps=original_loads) as loads:
                    with self.assertRaises(ProductionEvidenceVerificationError) as caught:
                        await verifier.verify(payload, attempt=_attempt())
                self.assertEqual(caught.exception.code, expected_code)
                if expected_load_count is not None:
                    self.assertEqual(loads.call_count, expected_load_count)
                self.assertEqual(source.calls, 0)


if __name__ == "__main__":
    unittest.main()
