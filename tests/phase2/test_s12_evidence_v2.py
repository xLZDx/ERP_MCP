"""S12 v2 evidence contract tests (local, synthetic, in-memory only).

Coverage maps directly to the accepted S12 freeze: closed canonical envelopes,
distinct signed evidence roles, pre-image and attempt binding, complete movement
summaries, and fail-closed malformed/unknown result handling. These tests do not
establish runtime or production evidence.
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from business_ai_gateway.phase2 import ed25519
from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidence,
    canonical_json_bytes,
    record_digest,
    seal_record_fixture,
    verify_record_signature,
)


H = "a" * 64
UUID_CHANGE = "123e4567-e89b-42d3-a456-426614174000"
UUID_CALL = "123e4567-e89b-42d3-a456-426614174001"
UUID_CAS = "123e4567-e89b-42d3-a456-426614174002"
UUID_RECEIPT = "123e4567-e89b-42d3-a456-426614174003"
UUID_PROCESS = "123e4567-e89b-42d3-a456-426614174004"
UUID_SESSION = "123e4567-e89b-42d3-a456-426614174005"
UUID_PERMIT = "123e4567-e89b-42d3-a456-426614174006"
AT = "2026-10-16T12:34:56.123456Z"
SEED_WRITER = bytes(range(32))
SEED_VERIFIER = bytes(range(1, 33))
SEED_SUPERVISOR = bytes(range(2, 34))


def attempt(**updates: object) -> DispatchAttempt:
    fields: dict[str, object] = {
        "tenant_id": "tenant-1", "company_id": "company-1", "organization_ref": "org-1",
        "base_fingerprint": "base-fingerprint-1", "change_id": UUID_CHANGE,
        "claim_generation": 2, "dispatch_generation": 3, "dispatch_cas_id": UUID_CAS,
        "call_id": UUID_CALL, "operation_kind": "POST", "approval_digest": H,
        "auth_epoch": 4, "permit_id": UUID_PERMIT, "permit_digest": H,
        "expected_target_ref": "doc-42", "expected_pre_version": "v7",
        "writer_service_id": "writer-service", "writer_host_id": "writer-host",
        "writer_process_instance_id": UUID_PROCESS, "onec_session_instance_id": UUID_SESSION,
    }
    fields.update(updates)
    return DispatchAttempt.from_mapping(fields)


def receipt_fields(**updates: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "receipt_version": "1", "tenant_id": "tenant-1", "company_id": "company-1",
        "organization_ref": "org-1", "base_fingerprint": "base-fingerprint-1",
        "target_class": "qualified-receipt", "expected_target_ref": "doc-42",
        "expected_pre_version": "v7", "change_id": UUID_CHANGE, "request_id": UUID_CHANGE,
        "claim_generation": 2, "approval_digest_version": "2", "approval_digest": H,
        "auth_epoch": 4, "permit_id": UUID_PERMIT, "permit_digest": H,
        "receipt_id": UUID_RECEIPT, "call_id": UUID_CALL, "dispatch_generation": 3,
        "dispatch_cas_id": UUID_CAS, "writer_service_id": "writer-service",
        "writer_host_id": "writer-host", "writer_process_instance_id": UUID_PROCESS,
        "onec_session_id": "session-1", "onec_session_instance_id": UUID_SESSION,
        "operation_kind": "POST", "started_at": AT, "write_invocation_stage": "INVOKED",
        "call_returned": True, "returned_at": AT, "result_class": "CALL_RETURNED_SUCCESS",
        "returned_target_ref": "doc-42", "returned_version": "v8",
        "no_effect_evidence_digest": None, "error_family": None, "mapping_version": "map-v2",
        "configuration_fingerprint": H, "approved_payload_digest": H,
        "mapped_property_manifest_sha256": H, "COM_operation_manifest_sha256": H,
        "signer_key_id": "writer-key", "key_version": "key-v1", "signer_role": "writer_receipt",
        "algorithm": "Ed25519", "signed_payload_digest": H, "signature": "",
    }
    fields.update(updates)
    return fields


def receipt(**updates: object) -> DispatchReceipt:
    return seal_record_fixture(DispatchReceipt, receipt_fields(**updates), SEED_WRITER)  # type: ignore[return-value]


def outcome_fields(**updates: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "evidence_version": "1", "tenant_id": "tenant-1", "company_id": "company-1",
        "organization_ref": "org-1", "base_fingerprint": "base-fingerprint-1",
        "change_id": UUID_CHANGE, "claim_generation": 2, "call_id": UUID_CALL,
        "dispatch_receipt_id": UUID_RECEIPT, "approval_digest": H,
        "verifier_service_id": "verifier-service", "verifier_host_id": "verifier-host",
        "signer_key_id": "verifier-key", "key_version": "key-v1", "algorithm": "Ed25519",
        "role": "verification_worker", "operation_kind": "POST", "observed_at": AT,
        "read_session_id": "read-session-1", "target_ref": "doc-42", "pre_version": "v7",
        "observed_version": "v8", "document_posting_state": "POSTED",
        "field_snapshot_digest": H, "lines_digest": H, "movement_multiset": (),
        "registrar": "doc-42", "register_catalogue_version": "catalogue-v1",
        "movement_count_by_register": {}, "movement_digest_by_register": {},
        "movement_multiset_digest": hashlib.sha256(b"[]").hexdigest(),
        "expected_effect_digest": H, "observed_effect_digest": H,
        "fields_match": True, "movements_match": True, "version_relation": "ADVANCED",
        "reader_health": "HEALTHY", "observation_complete": True,
        "effect_presence": "PRESENT", "effect_identity": "MATCH", "completion_proof_class": "WRITER_CALL_RETURNED",
        "attribution_result": "PROVEN", "attribution_evidence_ref": "audit-ref-1",
        "uncertainties": (), "canonical_evidence_digest": H, "signature": "",
    }
    fields.update(updates)
    return fields


def outcome(**updates: object) -> OutcomeEvidence:
    return seal_record_fixture(OutcomeEvidence, outcome_fields(**updates), SEED_VERIFIER)  # type: ignore[return-value]


def completion_fields(**updates: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "proof_version": "1", "completion_proof_id": UUID_RECEIPT,
        "tenant_id": "tenant-1", "company_id": "company-1", "organization_ref": "org-1",
        "base_fingerprint": "base-fingerprint-1", "change_id": UUID_CHANGE,
        "claim_generation": 2, "dispatch_generation": 3, "dispatch_cas_id": UUID_CAS,
        "call_id": UUID_CALL, "operation_kind": "POST", "writer_process_instance_id": UUID_PROCESS,
        "onec_session_instance_id": UUID_SESSION, "proof_class": "WRITER_CALL_RETURNED",
        "source_service_id": "writer-service", "source_host_id": "writer-host",
        "source_process_instance_id": UUID_PROCESS, "source_session_instance_id": "writer-local-session",
        "observed_session_instance_id": UUID_SESSION, "evidence_ref": "completion-ref-1",
        "evidence_digest": H, "observed_at": AT, "signer_key_id": "writer-key",
        "key_version": "key-v1", "signer_role": "writer_receipt", "algorithm": "Ed25519",
        "canonical_evidence_digest": H, "signature": "",
    }
    fields.update(updates)
    return fields


def completion(**updates: object) -> CompletionProof:
    return seal_record_fixture(CompletionProof, completion_fields(**updates), SEED_WRITER)  # type: ignore[return-value]


class S12EvidenceV2Tests(unittest.TestCase):
    """S12 freeze: local model acceptance, not formal gate/runtime acceptance."""

    def test_closed_schema_and_canonical_json_round_trip_reject_ambiguity(self) -> None:
        record = receipt()
        encoded = canonical_json_bytes(record.to_dict())
        restored = DispatchReceipt.from_json(encoded)
        self.assertEqual(restored.to_dict(), record.to_dict())
        self.assertEqual(record_digest(restored), record_digest(record))

        for fields in (
            {**receipt_fields(), "unapproved_extra": "x"},
            {key: value for key, value in receipt_fields().items() if key != "call_id"},
        ):
            with self.assertRaisesRegex(ValueError, "SCHEMA_INVALID"):
                DispatchReceipt.from_mapping(fields)
        for malformed in (b'{"a":1,"a":2}', b'{ "a":1}', b'{"a":NaN}'):
            with self.assertRaises(ValueError):
                DispatchReceipt.from_json(malformed)
        with self.assertRaisesRegex(ValueError, "NON_CANONICAL_VALUE"):
            canonical_json_bytes({"amount": 1.25})

    def test_digests_and_signatures_are_domain_separated_and_role_separated(self) -> None:
        r = receipt()
        o = outcome()
        c = completion()
        self.assertNotEqual(r.digest_preimage(), o.digest_preimage())
        self.assertNotEqual(o.digest_preimage(), c.digest_preimage())
        self.assertTrue(verify_record_signature(r, ed25519.public_key_from_seed(SEED_WRITER)))
        self.assertTrue(verify_record_signature(o, ed25519.public_key_from_seed(SEED_VERIFIER)))
        self.assertTrue(verify_record_signature(c, ed25519.public_key_from_seed(SEED_WRITER)))
        self.assertFalse(verify_record_signature(r, ed25519.public_key_from_seed(SEED_VERIFIER)))
        self.assertFalse(verify_record_signature(o, ed25519.public_key_from_seed(SEED_WRITER)))
        tampered = DispatchReceipt({**r.to_dict(), "returned_version": "v999"})
        self.assertFalse(verify_record_signature(tampered, ed25519.public_key_from_seed(SEED_WRITER)))
        with self.assertRaisesRegex(ValueError, "DISPATCH_METADATA_INVALID"):
            DispatchReceipt({**receipt_fields(), "signer_role": "verification_worker"})
        with self.assertRaisesRegex(ValueError, "OUTCOME_METADATA_INVALID"):
            OutcomeEvidence({**outcome_fields(), "role": "writer_receipt"})

    def test_operation_preimage_and_writer_session_pair_are_required(self) -> None:
        for operation in ("POST", "UNPOST"):
            for target, version in ((None, "v1"), ("doc-1", None)):
                with self.subTest(operation=operation, target=target, version=version):
                    with self.assertRaisesRegex(ValueError, "OPERATION_PREIMAGE_REQUIRED"):
                        attempt(operation_kind=operation, expected_target_ref=target, expected_pre_version=version)
        draft = attempt(operation_kind="CREATE_DRAFT", expected_target_ref=None, expected_pre_version=None)
        self.assertEqual(draft.operation_kind, "CREATE_DRAFT")
        with self.assertRaisesRegex(ValueError, "CREATE_DRAFT_PREIMAGE_INVALID"):
            attempt(operation_kind="CREATE_DRAFT", expected_target_ref="doc-1", expected_pre_version="v1")
        with self.assertRaisesRegex(ValueError, "SESSION_BINDING_INCOMPLETE"):
            DispatchReceipt(receipt_fields(onec_session_id=None))

    def test_receipt_outcome_and_completion_are_bound_to_exact_dispatch_attempt(self) -> None:
        a = attempt()
        r = receipt()
        o = outcome()
        c = completion()
        self.assertEqual(DispatchAttempt.from_receipt(r), a)
        r.validate_attempt_binding(a)
        o.validate_attempt_binding(a, r)
        c.validate_attempt_binding(a, r)
        for changed in (
            attempt(auth_epoch=5),
            attempt(permit_id="123e4567-e89b-42d3-a456-426614174099"),
            attempt(permit_digest="b" * 64),
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(ValueError, "RECEIPT_ATTEMPT_BINDING_INVALID"):
                    r.validate_attempt_binding(changed)
        with self.assertRaisesRegex(ValueError, "RECEIPT_ATTEMPT_BINDING_INVALID"):
            o.validate_attempt_binding(attempt(dispatch_cas_id="123e4567-e89b-42d3-a456-426614174099"), r)
        with self.assertRaisesRegex(ValueError, "OUTCOME_PREIMAGE_BINDING_INVALID"):
            outcome(target_ref="doc-elsewhere").validate_attempt_binding(a, r)
        with self.assertRaisesRegex(ValueError, "COMPLETION_DISPATCH_BINDING_INVALID"):
            completion(dispatch_cas_id="123e4567-e89b-42d3-a456-426614174099").validate_attempt_binding(a, r)
        with self.assertRaisesRegex(ValueError, "WRITER_SOURCE_BINDING_INVALID"):
            completion(source_service_id="other-writer").validate_attempt_binding(a, r)

    def test_outcome_movement_multiset_is_complete_and_summary_consistent(self) -> None:
        movements = (
            {"register": "stock", "registrar": "doc-42", "movement_digest": "b" * 64},
            {"register": "stock", "registrar": "doc-42", "movement_digest": "c" * 64},
        )
        # The implementation summarizes canonical movement entries as a sorted multiset.
        raw = sorted(canonical_json_bytes(item) for item in movements)
        per_register = hashlib.sha256(b"[" + b",".join(raw) + b"]").hexdigest()
        total = hashlib.sha256(b"[" + b",".join(raw) + b"]").hexdigest()
        valid = outcome(
            movement_multiset=movements,
            movement_count_by_register={"stock": 2},
            movement_digest_by_register={"stock": per_register},
            movement_multiset_digest=total,
        )
        self.assertEqual(valid.movement_count_by_register, {"stock": 2})
        self.assertEqual(len(valid.movement_multiset), 2)
        self.assertIn(b"movement_multiset", valid.signature_preimage())
        with self.assertRaisesRegex(ValueError, "MOVEMENT_SUMMARY_MISMATCH"):
            outcome(
                movement_multiset=movements,
                movement_count_by_register={"stock": 1},
                movement_digest_by_register={"stock": per_register},
                movement_multiset_digest=total,
            )
        with self.assertRaisesRegex(ValueError, "MOVEMENT_ITEM_SCHEMA_INVALID"):
            outcome(movement_multiset=({"register": "stock", "movement_digest": H},))
        with self.assertRaisesRegex(ValueError, "MOVEMENT_REGISTRAR_MISMATCH"):
            outcome(movement_multiset=({"register": "stock", "registrar": "other", "movement_digest": H},))

    def test_unknown_and_malformed_writer_outcomes_fail_closed(self) -> None:
        unknown = receipt(
            call_returned=False, returned_at=None, returned_target_ref=None, returned_version=None,
            result_class="POST_START_UNKNOWN",
        )
        self.assertEqual(unknown.result_class, "POST_START_UNKNOWN")
        for bad in (
            {"result_class": "UNRECOGNIZED"},
            {"result_class": "POST_START_UNKNOWN", "call_returned": True, "returned_at": AT},
            {"result_class": "CALL_RETURNED_SUCCESS", "call_returned": False, "returned_at": None},
            {"returned_target_ref": None},
            {"returned_version": None},
            {"returned_target_ref": "doc-elsewhere"},
            {"write_invocation_stage": "NOT_INVOKED", "result_class": "POST_START_UNKNOWN"},
            {"operation_kind": "UPDATE_DRAFT"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    receipt(**bad)
        with self.assertRaisesRegex(ValueError, "WRITER_COMPLETION_BINDING_INVALID"):
            completion(signer_role="completion_supervisor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
