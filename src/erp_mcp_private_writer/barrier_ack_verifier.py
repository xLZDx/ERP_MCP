"""Fail-closed verification orchestration for S13 physical barrier acknowledgements.

Trust loading and persistence are injected ports. The verifier checks the exact acknowledgement
signer and independently attested writer process before it calls the durable registry. SQL must
still recheck mutable key authorization and barrier/scope bindings in the registration transaction.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from business_ai_gateway.phase2.change.evidence import canonical_json_bytes
from business_ai_gateway.phase2.change_ledger.write_port import BarrierAcknowledgement

from .barrier_ack_protocol import (
    BarrierAcknowledgementProtocolError,
    barrier_acknowledgement_ref,
    barrier_acknowledgement_signed_bytes,
    validate_barrier_acknowledgement,
    verify_barrier_acknowledgement_signature,
)
from .dependency_shape import has_static_callable_method
from .evidence_trust import (
    EvidenceScope,
    EvidenceTrustSnapshot,
    SignerKeyRef,
    TrustedProcessBinding,
    TrustedSigner,
    is_canonical_positive_trust_revision,
)

_PROCESS_ATTESTATION_PREFIX = b"ERP_MCP_R2:S13:PROCESS-INSTANCE:v1\n"
_MAX_TIMEOUT_SECONDS = 5.0
_MAX_BARRIER_ORGANIZATIONS = 4096
_MAX_STALE_TRUST_RETRIES = 1


@dataclass(frozen=True, slots=True)
class BarrierAcknowledgementTrustContext:
    """One authoritative, non-cached trust snapshot covering the supplied acknowledgement."""

    snapshot: EvidenceTrustSnapshot
    represented_scopes: tuple[EvidenceScope, ...]

    def __post_init__(self) -> None:
        if (type(self.snapshot) is not EvidenceTrustSnapshot
                or type(self.represented_scopes) is not tuple
                or len(self.represented_scopes) > _MAX_BARRIER_ORGANIZATIONS
                or any(type(scope) is not EvidenceScope for scope in self.represented_scopes)
                or len(set(self.represented_scopes)) != len(self.represented_scopes)
                or self.represented_scopes != tuple(sorted(
                    self.represented_scopes,
                    key=lambda scope: (scope.tenant_id, scope.company_id,
                                       scope.organization_ref, scope.base_fingerprint),
                ))):
            raise ValueError("BARRIER_ACK_TRUST_CONTEXT_INVALID")


class BarrierAcknowledgementTrustSource(Protocol):
    """Resolve the acknowledgement key and process/supervisor chain from one coherent snapshot.

    Implementations must load the exact signer key version and process binding plus the complete
    supervisor rotation chain from an authoritative, uncached database snapshot. They must not
    convert a missing or stale trust row into a permissive result. The database registration
    routine separately rechecks current key revocation, signer scope and process-row identity.
    """

    async def load_barrier_snapshot(
            self, acknowledgement: BarrierAcknowledgement
    ) -> BarrierAcknowledgementTrustContext: ...


class BarrierAcknowledgementRegistrar(Protocol):
    """Persist one already verified immutable barrier proof using a bounded own transaction."""

    async def lookup_barrier_acknowledgement(
            self, barrier_id: UUID) -> dict[str, object] | None: ...

    async def register_barrier_acknowledgement(
            self, acknowledgement: BarrierAcknowledgement, *, acknowledgement_ref: str,
            signed_bytes: bytes, trust_revision: int) -> str: ...


class BarrierAcknowledgementVerifierError(RuntimeError):
    """Stable trust-provider configuration or snapshot failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BarrierAcknowledgementTrustRevisionStale(RuntimeError):
    """Registration definitely rolled back because its coherent trust snapshot went stale."""

    code = "BARRIER_ACK_TRUST_REVISION_STALE"


class ProductionBarrierAcknowledgementVerifier:
    """Verify canonical bytes, signer trust and process attestation, then persist exact replay data.

    A registration timeout or exception is deliberately allowed to escape: the database may have
    committed, so the caller must treat the result as unknown and retry by barrier identity.
    Definitive malformed/untrusted/signature failures are raised as
    ``BarrierAcknowledgementRejected`` before the registrar is invoked.
    """

    __slots__ = ("_registrar", "_timeout", "_trust")

    def __setattr__(self, name: str, value: object) -> None:
        if name not in self.__slots__ or hasattr(self, name):
            raise AttributeError("BARRIER_ACK_VERIFIER_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("BARRIER_ACK_VERIFIER_CONFIGURATION_IMMUTABLE")

    def __init__(self, trust_source: BarrierAcknowledgementTrustSource,
                 registrar: BarrierAcknowledgementRegistrar, *, timeout_seconds: float = 3.0) -> None:
        if (not has_static_callable_method(trust_source, "load_barrier_snapshot")
                or not has_static_callable_method(registrar, "lookup_barrier_acknowledgement")
                or not has_static_callable_method(registrar, "register_barrier_acknowledgement")):
            raise ValueError("BARRIER_ACK_VERIFIER_DEPENDENCY_INVALID")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
                or not math.isfinite(timeout_seconds)):
            raise ValueError("BARRIER_ACK_VERIFIER_TIMEOUT_INVALID")
        self._trust = trust_source
        self._registrar = registrar
        self._timeout = float(timeout_seconds)

    async def verify_and_store(self, acknowledgement: BarrierAcknowledgement) -> str:
        from .service import BarrierAcknowledgementRejected

        try:
            validate_barrier_acknowledgement(acknowledgement)
        except BarrierAcknowledgementProtocolError:
            raise BarrierAcknowledgementRejected() from None

        deadline = time.monotonic() + self._timeout
        signed_bytes = barrier_acknowledgement_signed_bytes(acknowledgement)
        reference = barrier_acknowledgement_ref(acknowledgement)
        try:
            async with asyncio.timeout(self._timeout):
                prior = await self._registrar.lookup_barrier_acknowledgement(
                    acknowledgement.barrier_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise BarrierAcknowledgementVerifierError(
                "BARRIER_ACK_LOOKUP_UNAVAILABLE",
            ) from None
        if prior is not None:
            if _is_exact_replay(prior, acknowledgement, reference, signed_bytes):
                return reference
            raise BarrierAcknowledgementRejected() from None

        signed_at = datetime.strptime(
            acknowledgement.signed_at, "%Y-%m-%dT%H:%M:%S.%fZ",
        ).replace(tzinfo=UTC)
        stale_retries = 0
        while True:
            context = await self._load_trust_context(acknowledgement, deadline)
            try:
                self._verify_trust(
                    context.snapshot, context.represented_scopes, acknowledgement, signed_at,
                )
            except (TypeError, ValueError, OverflowError):
                raise BarrierAcknowledgementRejected() from None
            except Exception:
                raise BarrierAcknowledgementVerifierError(
                    "BARRIER_ACK_TRUST_CONTEXT_INVALID",
                ) from None

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BarrierAcknowledgementVerifierError("BARRIER_ACK_VERIFY_TIMEOUT")
            try:
                async with asyncio.timeout(remaining):
                    persisted_ref = await self._registrar.register_barrier_acknowledgement(
                        acknowledgement, acknowledgement_ref=reference, signed_bytes=signed_bytes,
                        trust_revision=int(context.snapshot.revision),
                    )
                break
            except asyncio.CancelledError:
                raise
            except BarrierAcknowledgementTrustRevisionStale:
                if stale_retries >= _MAX_STALE_TRUST_RETRIES:
                    raise BarrierAcknowledgementVerifierError(
                        "BARRIER_ACK_TRUST_REVISION_UNSTABLE",
                    ) from None
                stale_retries += 1
                # A competing caller may have committed this exact proof while trust changed.
                # Check durable identity before loading a now-revoked signer snapshot.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BarrierAcknowledgementVerifierError("BARRIER_ACK_VERIFY_TIMEOUT")
                try:
                    async with asyncio.timeout(remaining):
                        prior = await self._registrar.lookup_barrier_acknowledgement(
                            acknowledgement.barrier_id,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    raise BarrierAcknowledgementVerifierError(
                        "BARRIER_ACK_LOOKUP_UNAVAILABLE",
                    ) from None
                if prior is not None:
                    if _is_exact_replay(prior, acknowledgement, reference, signed_bytes):
                        return reference
                    raise BarrierAcknowledgementRejected() from None
                continue
            except Exception:
                # Persistence may have committed; preserve ambiguity for exact lookup/replay.
                raise
        if type(persisted_ref) is not str or persisted_ref != reference:
            raise BarrierAcknowledgementVerifierError("BARRIER_ACK_REGISTER_OUTCOME_UNKNOWN")
        return reference

    async def _load_trust_context(
            self, acknowledgement: BarrierAcknowledgement, deadline: float
    ) -> BarrierAcknowledgementTrustContext:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BarrierAcknowledgementVerifierError("BARRIER_ACK_VERIFY_TIMEOUT")
        try:
            async with asyncio.timeout(remaining):
                context = await self._trust.load_barrier_snapshot(acknowledgement)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise BarrierAcknowledgementVerifierError(
                "BARRIER_ACK_TRUST_UNAVAILABLE",
            ) from None
        if type(context) is not BarrierAcknowledgementTrustContext:
            raise BarrierAcknowledgementVerifierError("BARRIER_ACK_TRUST_CONTEXT_INVALID")
        return context

    @staticmethod
    def _verify_trust(snapshot: EvidenceTrustSnapshot,
                      represented_scopes: tuple[EvidenceScope, ...],
                      acknowledgement: BarrierAcknowledgement, signed_at: datetime) -> None:
        if (type(snapshot) is not EvidenceTrustSnapshot
                or not is_canonical_positive_trust_revision(snapshot.revision)
                or not _is_utc(snapshot.loaded_at)):
            raise ValueError("BARRIER_ACK_TRUST_SNAPSHOT_INVALID")
        validation_time = snapshot.loaded_at
        key_ref = SignerKeyRef(acknowledgement.key_id, acknowledgement.key_version)
        signer = snapshot.signer(key_ref)
        if (type(signer) is not TrustedSigner or signer.signer_role != "writer_receipt"
                or signer.service_id != acknowledgement.writer_service_id
                or signer.host_id != acknowledgement.writer_host_id
                or any((scope.tenant_id, scope.company_id, scope.base_fingerprint)
                       != (acknowledgement.tenant_id, acknowledgement.company_id,
                           acknowledgement.base_fingerprint)
                       or scope not in signer.allowed_scopes for scope in represented_scopes)):
            raise ValueError("BARRIER_ACK_SIGNER_UNTRUSTED")
        _check_current_signer(signer, signed_at, validation_time)
        if not verify_barrier_acknowledgement_signature(
                acknowledgement, signer.public_key):
            raise ValueError("BARRIER_ACK_SIGNATURE_INVALID")

        process = snapshot.process(acknowledgement.writer_process_instance_id)
        if (type(process) is not TrustedProcessBinding
                or process.process_instance_id != acknowledgement.writer_process_instance_id
                or process.host_boot_id != acknowledgement.host_boot_id
                or process.service_id != acknowledgement.writer_service_id
                or process.host_id != acknowledgement.writer_host_id
                or process.process_created_at > signed_at):
            raise ValueError("BARRIER_ACK_PROCESS_UNTRUSTED")
        supervisor = snapshot.signer(process.supervisor_key)
        if (type(supervisor) is not TrustedSigner
                or supervisor.signer_role != "completion_supervisor"
                or supervisor.host_id != acknowledgement.writer_host_id
                or supervisor.service_id == acknowledgement.writer_service_id
                or any(scope not in supervisor.allowed_scopes for scope in represented_scopes)):
            raise ValueError("BARRIER_ACK_PROCESS_SUPERVISOR_UNTRUSTED")
        _check_current_signer(supervisor, process.process_created_at, validation_time)
        attestation_bytes = _PROCESS_ATTESTATION_PREFIX + canonical_json_bytes({
            "attestation_version": "1",
            "process_instance_id": process.process_instance_id,
            "host_boot_id": process.host_boot_id,
            "service_id": process.service_id,
            "host_id": process.host_id,
            "os_pid": process.os_pid,
            "process_created_at": process.process_created_at.astimezone(
                UTC,
            ).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "supervisor_key_id": process.supervisor_key.key_id,
            "supervisor_key_version": process.supervisor_key.key_version,
        })
        from .dpapi_signer import verify_ed25519
        if not verify_ed25519(
                public_key=supervisor.public_key, message=attestation_bytes,
                signature=process.signature):
            raise ValueError("BARRIER_ACK_PROCESS_ATTESTATION_INVALID")


def build_postgres_barrier_acknowledgement_verifier(
        evidence_pool, *, timeout_seconds: float = 3.0
) -> ProductionBarrierAcknowledgementVerifier:
    """Compose the source adapters without opening connections or granting SQL privileges."""
    from .postgres_barrier_ack_registrar import PostgresBarrierAcknowledgementRegistrar
    from .postgres_barrier_ack_trust import PostgresBarrierAcknowledgementTrustSource

    return ProductionBarrierAcknowledgementVerifier(
        PostgresBarrierAcknowledgementTrustSource(
            evidence_pool, timeout_seconds=timeout_seconds,
        ),
        PostgresBarrierAcknowledgementRegistrar(
            evidence_pool, timeout_seconds=timeout_seconds,
        ),
        timeout_seconds=timeout_seconds,
    )


def _is_utc(value: object) -> bool:
    return (type(value) is datetime and value.tzinfo is not None
            and value.utcoffset() is not None and value.utcoffset().total_seconds() == 0)


def _check_current_signer(signer: TrustedSigner, signed_at: datetime,
                          validation_time: datetime) -> None:
    if (not _is_utc(signer.valid_from) or not _is_utc(signer.valid_until)
            or signer.revoked_at is not None and not _is_utc(signer.revoked_at)
            or signed_at > validation_time
            or not (signer.valid_from <= signed_at < signer.valid_until)
            or not (signer.valid_from <= validation_time < signer.valid_until)
            or signer.revoked_at is not None and validation_time >= signer.revoked_at):
        raise ValueError("BARRIER_ACK_SIGNER_NOT_CURRENTLY_AUTHORIZED")


def _is_exact_replay(record: object, acknowledgement: BarrierAcknowledgement,
                     reference: str, signed_bytes: bytes) -> bool:
    expected_keys = {
        "acknowledgement_ref", "barrier_id", "base_fingerprint", "tenant_id", "company_id",
        "lifecycle_epoch", "barrier_origin_instance_id", "barrier_origin_service_epoch",
        "call_ids", "writer_service_id", "writer_host_id", "host_boot_id",
        "writer_process_instance_id", "process_attestation_ref", "writer_queue_epoch",
        "local_queue_closed", "signed_at", "signed_bytes_hex", "signature_hex",
        "signed_bytes_sha256", "signer_key_id", "signer_key_version", "verified_at",
    }
    if type(record) is not dict or set(record) != expected_keys:
        return False
    expected = {
        "acknowledgement_ref": reference,
        "barrier_id": str(acknowledgement.barrier_id),
        "base_fingerprint": acknowledgement.base_fingerprint,
        "tenant_id": acknowledgement.tenant_id,
        "company_id": acknowledgement.company_id,
        "lifecycle_epoch": acknowledgement.lifecycle_epoch,
        "barrier_origin_instance_id": acknowledgement.barrier_origin_instance_id,
        "barrier_origin_service_epoch": acknowledgement.barrier_origin_service_epoch,
        "call_ids": list(acknowledgement.call_ids),
        "writer_service_id": acknowledgement.writer_service_id,
        "writer_host_id": acknowledgement.writer_host_id,
        "host_boot_id": acknowledgement.host_boot_id,
        "writer_process_instance_id": acknowledgement.writer_process_instance_id,
        "process_attestation_ref": acknowledgement.process_attestation_ref,
        "writer_queue_epoch": acknowledgement.writer_queue_epoch,
        "local_queue_closed": True,
        "signed_at": acknowledgement.signed_at,
        "signed_bytes_hex": signed_bytes.hex(),
        "signature_hex": acknowledgement.signature.hex(),
        "signed_bytes_sha256": hashlib.sha256(signed_bytes).hexdigest(),
        "signer_key_id": acknowledgement.key_id,
        "signer_key_version": acknowledgement.key_version,
    }
    if any(type(record.get(key)) is not type(value) or record.get(key) != value
           for key, value in expected.items()):
        return False
    verified_at = record.get("verified_at")
    if type(verified_at) is not str:
        return False
    try:
        parsed = datetime.strptime(verified_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == verified_at


__all__ = [
    "BarrierAcknowledgementRegistrar",
    "BarrierAcknowledgementTrustContext",
    "BarrierAcknowledgementTrustRevisionStale",
    "BarrierAcknowledgementTrustSource",
    "BarrierAcknowledgementVerifierError",
    "ProductionBarrierAcknowledgementVerifier",
    "build_postgres_barrier_acknowledgement_verifier",
]
