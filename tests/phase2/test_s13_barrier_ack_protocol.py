"""Functional tests for the S13 physical-writer barrier acknowledgement boundary."""
from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import UUID
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from business_ai_gateway.phase2.change_ledger.write_port import BarrierAcknowledgement
from erp_mcp_private_writer.barrier_ack_protocol import (
    BarrierAcknowledgementProtocolError,
    barrier_acknowledgement_ref,
    barrier_acknowledgement_signed_bytes,
    validate_barrier_acknowledgement,
    verify_barrier_acknowledgement_signature,
)
from erp_mcp_private_writer.dpapi_signer import DpapiSignerError, WindowsDpapiEd25519Signer
from test_private_writer_barrier_ack import _acknowledgement, _service


_DOMAIN = b"ERP_MCP_R2:S13:PHYSICAL-WRITER-BARRIER:v1\n"


def _signed_ack(seed: bytes = bytes(range(32))) -> tuple[BarrierAcknowledgement, bytes]:
    unsigned = _acknowledgement()
    # The writer protocol uses a fixed-width UTC timestamp with a Z suffix.
    unsigned = replace(unsigned, signed_at="2026-10-26T10:00:00.000000Z")
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    signature = private_key.sign(unsigned.signature_preimage())
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return replace(unsigned, signature=signature), public_key


class BarrierAcknowledgementProtocolTests(unittest.TestCase):
    def test_signed_bytes_use_fixed_domain_and_canonical_sorted_json(self) -> None:
        ack, _ = _signed_ack()
        signed_bytes = barrier_acknowledgement_signed_bytes(ack)
        self.assertTrue(signed_bytes.startswith(_DOMAIN))
        body = signed_bytes[len(_DOMAIN):]
        self.assertEqual(body, json.dumps(
            ack.unsigned_dict(), sort_keys=True, ensure_ascii=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8"))
        self.assertEqual(json.loads(body), ack.unsigned_dict())

    def test_ed25519_signature_accepts_exact_message_and_rejects_wrong_key_or_bytes(self) -> None:
        ack, public_key = _signed_ack()
        _, other_public_key = _signed_ack(bytes(reversed(range(32))))
        self.assertTrue(verify_barrier_acknowledgement_signature(ack, public_key))
        self.assertFalse(verify_barrier_acknowledgement_signature(ack, other_public_key))
        self.assertFalse(verify_barrier_acknowledgement_signature(
            replace(ack, signature=b"x" * 64), public_key,
        ))

    def test_signature_over_wrong_domain_is_rejected(self) -> None:
        ack, public_key = _signed_ack()
        private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        wrong_message = b"ERP_MCP_R2:S13:OTHER-BARRIER:v1\n" + ack.signature_preimage().split(
            b"\n", 1,
        )[1]
        wrong_domain_ack = replace(ack, signature=private_key.sign(wrong_message))
        self.assertFalse(verify_barrier_acknowledgement_signature(wrong_domain_ack, public_key))

    def test_writer_receipt_signer_accepts_barrier_domain_and_refuses_other_domain(self) -> None:
        ack, public_key = _signed_ack()
        seed = bytes(range(32))
        signer = WindowsDpapiEd25519Signer(
            key_id=ack.key_id,
            key_version=ack.key_version,
            signer_role="writer_receipt",
            protected_seed_path=Path("C:/not-opened/protected-seed.bin"),
            expected_public_key=public_key,
        )
        with patch.object(WindowsDpapiEd25519Signer, "_unprotect_seed", return_value=seed):
            signature = signer.sign(ack.signature_preimage())
            self.assertTrue(verify_barrier_acknowledgement_signature(
                replace(ack, signature=signature), public_key,
            ))
            with self.assertRaises(DpapiSignerError) as raised:
                signer.sign(b"ERP_MCP_R2:S13:UNREGISTERED-DOMAIN:v1\nbody")
        self.assertEqual(raised.exception.code, "SIGNER_DOMAIN_REFUSED")

    def test_timestamp_requires_exact_utc_microsecond_form(self) -> None:
        ack, _ = _signed_ack()
        validate_barrier_acknowledgement(ack)
        for value in (
            "2026-10-26T10:00:00+00:00",
            "2026-10-26T10:00:00.1Z",
            "2026-10-26T10:00:00.000000+00:00",
            "2026-02-30T10:00:00.000000Z",
        ):
            with self.subTest(signed_at=value), self.assertRaises(
                    BarrierAcknowledgementProtocolError):
                validate_barrier_acknowledgement(replace(ack, signed_at=value))

    def test_process_attestation_reference_must_equal_process_instance_id(self) -> None:
        ack, _ = _signed_ack()
        self.assertEqual(ack.process_attestation_ref, ack.writer_process_instance_id)
        with self.assertRaises(BarrierAcknowledgementProtocolError):
            validate_barrier_acknowledgement(
                replace(ack, process_attestation_ref="00000000-0000-4000-8000-000000000005"),
            )

    def test_reference_is_deterministic_and_binds_message_signature_and_key_version(self) -> None:
        ack, _ = _signed_ack()
        expected = barrier_acknowledgement_ref(ack)
        self.assertEqual(barrier_acknowledgement_ref(ack), expected)
        variants = (
            replace(ack, signed_at="2026-10-26T10:00:01.000000Z"),
            replace(ack, signature=bytes([ack.signature[0] ^ 1]) + ack.signature[1:]),
            replace(ack, key_id="other-key"),
            replace(ack, key_version="2"),
        )
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertNotEqual(barrier_acknowledgement_ref(changed), expected)

    def test_call_ids_must_be_canonical_unique_and_sorted(self) -> None:
        ack, _ = _signed_ack()
        first = "00000000-0000-4000-8000-000000000010"
        second = "00000000-0000-4000-8000-000000000020"
        validate_barrier_acknowledgement(replace(ack, call_ids=(first, second)))
        for call_ids in (
            (second, first),
            (first, first),
            ("00000000-0000-4000-8000-00000000001A",),
            ("00000000000040008000000000000010",),
        ):
            with self.subTest(call_ids=call_ids), self.assertRaises(
                    BarrierAcknowledgementProtocolError):
                validate_barrier_acknowledgement(replace(ack, call_ids=call_ids))

    def test_epoch_fields_reject_bool_zero_and_bigint_overflow(self) -> None:
        ack, _ = _signed_ack()
        for field, value in (
            ("lifecycle_epoch", True),
            ("barrier_origin_service_epoch", 0),
            ("writer_queue_epoch", 9_223_372_036_854_775_808),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(
                    BarrierAcknowledgementProtocolError):
                validate_barrier_acknowledgement(replace(ack, **{field: value}))

    def test_service_rejects_noncanonical_ack_before_verifier_and_finalization(self) -> None:
        class CountingVerifier:
            calls = 0

            async def verify_and_store(self, _ack: BarrierAcknowledgement) -> str:
                self.calls += 1
                return "should-not-be-called"

        verifier = CountingVerifier()
        service, store, writer, _ = _service(verifier)
        writer.ack = replace(_acknowledgement(), signed_at="2026-10-26T10:00:00+00:00")

        async def exercise() -> Exception:
            try:
                await service.fence_scope(
                    store.snapshot.scope, store.snapshot.expected_current_epoch,
                    store.snapshot.barrier_id,
                )
            except Exception as error:
                return error
            raise AssertionError("malformed acknowledgement unexpectedly finalized")

        error = asyncio.run(exercise())
        self.assertEqual(getattr(error, "code", None), "BARRIER_ACK_INVALID")
        self.assertEqual(verifier.calls, 0)
        self.assertEqual(store.finish_calls, [])


if __name__ == "__main__":
    unittest.main()
