"""Explicit composition root for the private S13 writer process.

This module wires already-authenticated host configuration and already-created adapters. It does
not load secrets, connect to PostgreSQL/1C, start the STA lane, claim a serving epoch, or expose an
HTTP/MCP listener. In particular, constructing this object is not a readiness or deployment gate.
"""
from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass, field

import asyncpg

from business_ai_gateway.phase2.change_ledger.write_port import (
    OneCWritePort,
    NonOperationalWritePort,
)

from .dependency_shape import has_static_callable_method
from .barrier_ack_verifier import ProductionBarrierAcknowledgementVerifier
from .postgres_barrier_ack_registrar import PostgresBarrierAcknowledgementRegistrar
from .postgres_barrier_ack_trust import PostgresBarrierAcknowledgementTrustSource
from .postgres_evidence_registrar import PostgresWriterReceiptRegistrar
from .postgres_evidence_resolver import PostgresWriterEvidenceResolver
from .postgres_outcome_provider import PostgresOutcomeEvidenceProvider
from .postgres_store import PostgresAdmissionStore
from .validator_build_attestation import (
    ValidatorBuildAttestationVerifier,
)
from .service import (
    BarrierAcknowledgementVerifier,
    OutcomeEvidenceProvider,
    PrivateWriterService,
    ServiceError,
    WriterEvidenceResolver,
    WriterReceiptVerifier,
)
from .windows_authority_mutex import WindowsServingAuthorityMutex


_MAX_RUNTIME_CLOSE_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class PrivateWriterRuntime:
    """Private service with an explicit drain-before-close sequence; never a public gateway."""

    service: PrivateWriterService
    authority_mutex: WindowsServingAuthorityMutex
    writer: OneCWritePort
    _close_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        """Bind shutdown ownership to the exact writer and mutex used by the service."""
        if (type(self.service) is not PrivateWriterService
                or type(self.authority_mutex) is not WindowsServingAuthorityMutex
                or self.service._serving_authority_mutex is not self.authority_mutex
                or self.service._writer is not self.writer):
            raise ValueError("WRITER_RUNTIME_DEPENDENCIES_MISMATCH")

    async def close(self, *, timeout_seconds: float = 30.0) -> None:
        """Drain admission and close the STA within one bounded deadline, then close authority.

        The caller must stop the HTTP/MCP listener first. Any failed drain or writer close leaves
        the authority mutex open, so another process cannot take over while COM outcome is unknown.
        """
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= _MAX_RUNTIME_CLOSE_SECONDS):
            raise ValueError("WRITER_RUNTIME_CLOSE_TIMEOUT_INVALID")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout_seconds)
        try:
            async with asyncio.timeout(timeout_seconds):
                await self._close_lock.acquire()
        except TimeoutError:
            raise ServiceError("WRITER_RUNTIME_CLOSE_TIMEOUT", outcome_unknown=True) from None

        try:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ServiceError("WRITER_RUNTIME_CLOSE_TIMEOUT", outcome_unknown=True)
            await self.service.shutdown(timeout_seconds=remaining)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ServiceError("WRITER_RUNTIME_CLOSE_TIMEOUT", outcome_unknown=True)
            try:
                async with asyncio.timeout(remaining):
                    await self.writer.close_after_drain()
            except TimeoutError:
                # The writer may still be completing its shielded STA cleanup. Keep the host
                # authority mutex open until a later close attempt observes completion.
                raise ServiceError("WRITER_RUNTIME_CLOSE_TIMEOUT",
                                   outcome_unknown=True) from None
            await self.authority_mutex.close_async()
        finally:
            self._close_lock.release()


def _require_methods(dependency: object, methods: tuple[str, ...], error_code: str) -> None:
    if any(not has_static_callable_method(dependency, name) for name in methods):
        raise ValueError(error_code)


def compose_private_writer_runtime(
        *,
        admission_pool: asyncpg.Pool,
        writer: OneCWritePort,
        host_id: str,
        base_fingerprint: str,
        service_sid: str,
        barrier_ack_verifier: BarrierAcknowledgementVerifier,
        writer_receipt_verifier: WriterReceiptVerifier,
        outcome_evidence_provider: OutcomeEvidenceProvider,
        writer_evidence_resolver: WriterEvidenceResolver,
        barrier_wait_seconds: float = 5.0,
) -> PrivateWriterRuntime:
    """Compose the private writer from explicit, fail-closed process dependencies.

    ``host_id`` and ``base_fingerprint`` must come from the deployment's authenticated host and
    read-only base-measurement sources. The function validates their shape through the coordinator
    but does not authenticate their provenance. The caller must provide an operational COM writer
    port and trusted evidence services; skeletons and absent providers are rejected.

    The PostgreSQL pool must use the dedicated private-writer login. The adapter independently
    checks ``SESSION_USER`` and ``CURRENT_USER`` inside every bounded transaction. No database
    operation occurs here. The caller must explicitly run startup recovery and must not open a
    listener until recovery is complete and all deployment gates are satisfied.
    """
    if os.name != "nt":
        raise OSError("PRIVATE_WRITER_RUNTIME_REQUIRES_WINDOWS")
    if not isinstance(admission_pool, asyncpg.Pool):
        raise ValueError("ADMISSION_POOL_INVALID")

    _require_methods(writer, (
        "verify_ticket", "verify_permit", "authenticate_base", "lookup_receipt", "quiesce",
        "create_draft", "post", "unpost", "close_after_drain",
    ), "WRITER_PORT_INCOMPLETE")
    _require_methods(barrier_ack_verifier, ("verify_and_store",),
                     "BARRIER_ACK_VERIFIER_MISSING")
    if type(barrier_ack_verifier) is not ProductionBarrierAcknowledgementVerifier:
        raise ValueError("BARRIER_ACK_VERIFIER_NOT_PRODUCTION")
    if (type(barrier_ack_verifier._trust) is not PostgresBarrierAcknowledgementTrustSource
            or type(barrier_ack_verifier._registrar)
            is not PostgresBarrierAcknowledgementRegistrar
            or barrier_ack_verifier._trust._pool is not barrier_ack_verifier._registrar._pool
            or barrier_ack_verifier._trust._pool is admission_pool):
        raise ValueError("BARRIER_ACK_VERIFIER_DEPENDENCIES_NOT_PRODUCTION")
    _require_methods(writer_receipt_verifier, ("verify_and_store",),
                     "WRITER_RECEIPT_VERIFIER_MISSING")
    if type(writer_receipt_verifier) is not PostgresWriterReceiptRegistrar:
        raise ValueError("WRITER_RECEIPT_VERIFIER_NOT_PRODUCTION")
    # Synthetic roots and abstract-marker subclasses can exercise the pure verifier, but cannot
    # enter this production composition root. The verifier requires an exact source type added to
    # its reviewed allowlist; none exists until the external trust root, policy, clock, revocation
    # source, and runtime measurement are authorized. The registrar independently enforces the
    # same boundary on every write path.
    build_attestation_verifier = writer_receipt_verifier._build_provenance_source
    if (type(build_attestation_verifier) is not ValidatorBuildAttestationVerifier
            or not build_attestation_verifier.has_production_authority_source):
        raise ValueError("VALIDATOR_BUILD_AUTHORITY_NOT_PRODUCTION")
    _require_methods(outcome_evidence_provider,
                     ("verify_success", "verify_conditional_conflict"),
                     "OUTCOME_EVIDENCE_PROVIDER_MISSING")
    if type(outcome_evidence_provider) is not PostgresOutcomeEvidenceProvider:
        raise ValueError("OUTCOME_EVIDENCE_PROVIDER_NOT_PRODUCTION")
    _require_methods(writer_evidence_resolver,
                     ("load_receipt", "load_conditional_conflict_terminal_records"),
                     "WRITER_EVIDENCE_RESOLVER_MISSING")
    if type(writer_evidence_resolver) is not PostgresWriterEvidenceResolver:
        raise ValueError("WRITER_EVIDENCE_RESOLVER_NOT_PRODUCTION")

    # These providers must be one production evidence graph, not separately injected objects
    # that happen to implement the same methods. The bundle source only locates signed bytes;
    # this graph binds loading, trust verification and durable registration to the same
    # evidence-ingest pool and attempt source. Its pool must remain separate from admission.
    evidence_pool = writer_receipt_verifier._pool
    evidence_attempt_source = writer_receipt_verifier._attempt_source
    evidence_verifier = writer_receipt_verifier._verifier
    if (evidence_pool is admission_pool
            or outcome_evidence_provider._registrar is not writer_receipt_verifier
            or getattr(evidence_attempt_source, "_pool", None) is not evidence_pool
            or writer_evidence_resolver._pool is not evidence_pool
            or writer_evidence_resolver._attempt_source is not evidence_attempt_source
            or writer_evidence_resolver._verifier is not evidence_verifier):
        raise ValueError("WRITER_EVIDENCE_DEPENDENCIES_NOT_PRODUCTION")

    # Method presence alone accepts duck-typed no-op stubs. Require the explicit declaration in
    # the concrete writer class's own dictionary, as well as the nominal skeleton exclusion.
    # This flag is an additional composition guard, not a trust or provenance proof.
    writer_type = type(writer)
    writer_mro = type.__getattribute__(writer_type, "__mro__")
    writer_namespace = type.__getattribute__(writer_type, "__dict__")
    if (any(base is NonOperationalWritePort for base in writer_mro)
            or writer_namespace.get("operational", False) is not True):
        raise ValueError("WRITER_PORT_NOT_OPERATIONAL")

    store = PostgresAdmissionStore(admission_pool)
    authority_mutex = WindowsServingAuthorityMutex(base_fingerprint, service_sid)
    try:
        service = PrivateWriterService(
            store,
            writer,
            host_id=host_id,
            base_fingerprint=base_fingerprint,
            serving_authority_mutex=authority_mutex,
            barrier_wait_seconds=barrier_wait_seconds,
            barrier_ack_verifier=barrier_ack_verifier,
            writer_receipt_verifier=writer_receipt_verifier,
            outcome_evidence_provider=outcome_evidence_provider,
            writer_evidence_resolver=writer_evidence_resolver,
        )
    except BaseException:
        authority_mutex.close()
        raise

    return PrivateWriterRuntime(service, authority_mutex, writer)


__all__ = ["PrivateWriterRuntime", "compose_private_writer_runtime"]
