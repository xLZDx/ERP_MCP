"""S13-EVIDENCE-PROVIDER-COMPOSITION-01: production evidence graph is bound fail-closed."""
from __future__ import annotations

import asyncpg
import pytest

from erp_mcp_private_writer import runtime_composition as composition
from erp_mcp_private_writer.barrier_ack_verifier import ProductionBarrierAcknowledgementVerifier
from erp_mcp_private_writer.postgres_barrier_ack_registrar import (
    PostgresBarrierAcknowledgementRegistrar,
)
from erp_mcp_private_writer.postgres_barrier_ack_trust import (
    PostgresBarrierAcknowledgementTrustSource,
)
from erp_mcp_private_writer.postgres_attempt_source import PostgresEvidenceAttemptSource
from erp_mcp_private_writer.postgres_evidence_registrar import PostgresWriterReceiptRegistrar
from erp_mcp_private_writer.postgres_evidence_resolver import PostgresWriterEvidenceResolver
from erp_mcp_private_writer.postgres_evidence_trust import PostgresEvidenceTrustSource
from erp_mcp_private_writer.postgres_outcome_provider import PostgresOutcomeEvidenceProvider
from erp_mcp_private_writer.production_evidence_verifier import ProductionEvidenceVerifier


class _SpyPool(asyncpg.Pool):
    def __init__(self) -> None:
        self.acquire_calls = 0

    def acquire(self, *args, **kwargs):  # pragma: no cover - must not be reached in composition
        self.acquire_calls += 1
        raise AssertionError("composition must not acquire a database connection")


class _WriterStub:
    operational = False

    def verify_ticket(self, *_args, **_kwargs): ...
    def verify_permit(self, *_args, **_kwargs): ...
    def authenticate_base(self, *_args, **_kwargs): ...
    def lookup_receipt(self, *_args, **_kwargs): ...
    def quiesce(self, *_args, **_kwargs): ...
    def create_draft(self, *_args, **_kwargs): ...
    def post(self, *_args, **_kwargs): ...
    def unpost(self, *_args, **_kwargs): ...
    def close_after_drain(self, *_args, **_kwargs): ...


class _BuildSource:
    async def load_current_approved_build(self): ...


class _BundleSource:
    async def load_success_bundle(self, *_args, **_kwargs): ...
    async def load_conditional_conflict_bundle(self, *_args, **_kwargs): ...


def _composition_graph(*, share_evidence_and_admission: bool = False):
    admission_pool = _SpyPool()
    evidence_pool = admission_pool if share_evidence_and_admission else _SpyPool()
    acknowledgement_pool = _SpyPool()

    attempt_source = PostgresEvidenceAttemptSource(evidence_pool)
    trust_source = PostgresEvidenceTrustSource(evidence_pool)
    evidence_verifier = ProductionEvidenceVerifier(trust_source)
    registrar = PostgresWriterReceiptRegistrar(
        evidence_pool, attempt_source, evidence_verifier,
        build_provenance_source=_BuildSource(),
        approved_build_policy_id="test-policy",
    )
    outcome_provider = PostgresOutcomeEvidenceProvider(_BundleSource(), registrar)
    evidence_resolver = PostgresWriterEvidenceResolver(
        evidence_pool, attempt_source, evidence_verifier,
    )

    ack_trust = PostgresBarrierAcknowledgementTrustSource(acknowledgement_pool)
    ack_registrar = PostgresBarrierAcknowledgementRegistrar(acknowledgement_pool)
    ack_verifier = ProductionBarrierAcknowledgementVerifier(ack_trust, ack_registrar)

    return {
        "admission_pool": admission_pool,
        "evidence_pool": evidence_pool,
        "acknowledgement_pool": acknowledgement_pool,
        "tracked_pools": list({admission_pool, evidence_pool, acknowledgement_pool}),
        "writer": _WriterStub(),
        "host_id": "host-test",
        "base_fingerprint": "f" * 64,
        "service_sid": "S-1-5-21-1000",
        "barrier_ack_verifier": ack_verifier,
        "writer_receipt_verifier": registrar,
        "outcome_evidence_provider": outcome_provider,
        "writer_evidence_resolver": evidence_resolver,
    }


def _assert_no_pool_acquisition(graph):
    assert all(pool.acquire_calls == 0 for pool in graph["tracked_pools"])


def _compose(graph):
    keys = (
        "admission_pool", "writer", "host_id", "base_fingerprint", "service_sid",
        "barrier_ack_verifier", "writer_receipt_verifier", "outcome_evidence_provider",
        "writer_evidence_resolver",
    )
    return composition.compose_private_writer_runtime(**{key: graph[key] for key in keys})


def test_valid_production_graph_passes_evidence_checks_without_database_access(monkeypatch):
    monkeypatch.setattr(composition.os, "name", "nt")
    graph = _composition_graph()

    # The deliberately non-operational writer is rejected only after the evidence graph passes.
    with pytest.raises(ValueError, match="^WRITER_PORT_NOT_OPERATIONAL$"):
        _compose(graph)

    _assert_no_pool_acquisition(graph)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("receipt_verifier_type", "WRITER_RECEIPT_VERIFIER_NOT_PRODUCTION"),
        ("outcome_provider_type", "OUTCOME_EVIDENCE_PROVIDER_NOT_PRODUCTION"),
        ("provider_registrar", "WRITER_EVIDENCE_DEPENDENCIES_NOT_PRODUCTION"),
        ("attempt_pool", "WRITER_EVIDENCE_DEPENDENCIES_NOT_PRODUCTION"),
        ("resolver_pool", "WRITER_EVIDENCE_DEPENDENCIES_NOT_PRODUCTION"),
        ("resolver_attempt_source", "WRITER_EVIDENCE_DEPENDENCIES_NOT_PRODUCTION"),
        ("resolver_verifier", "WRITER_EVIDENCE_DEPENDENCIES_NOT_PRODUCTION"),
        ("shared_admission_pool", "WRITER_EVIDENCE_DEPENDENCIES_NOT_PRODUCTION"),
    ],
)
def test_invalid_evidence_graph_fails_before_database_access(
        monkeypatch, mutation: str, expected_error: str):
    monkeypatch.setattr(composition.os, "name", "nt")
    graph = _composition_graph(share_evidence_and_admission=mutation == "shared_admission_pool")
    registrar = graph["writer_receipt_verifier"]
    evidence_pool = graph["evidence_pool"]

    if mutation == "receipt_verifier_type":
        graph["writer_receipt_verifier"] = type(
            "ReceiptDuck", (), {"verify_and_store": lambda self: None},
        )()
    elif mutation == "outcome_provider_type":
        graph["outcome_evidence_provider"] = type(
            "OutcomeDuck", (), {
                "verify_success": lambda self: None,
                "verify_conditional_conflict": lambda self: None,
            },
        )()
    elif mutation == "provider_registrar":
        different_registrar = PostgresWriterReceiptRegistrar(
            registrar._pool, registrar._attempt_source, registrar._verifier,
            build_provenance_source=_BuildSource(),
            approved_build_policy_id="test-policy",
        )
        graph["outcome_evidence_provider"] = PostgresOutcomeEvidenceProvider(
            _BundleSource(), different_registrar,
        )
    elif mutation == "attempt_pool":
        alternate_pool = _SpyPool()
        graph["tracked_pools"].append(alternate_pool)
        mismatched_source = PostgresEvidenceAttemptSource(alternate_pool)
        alternate_verifier = ProductionEvidenceVerifier(
            PostgresEvidenceTrustSource(alternate_pool),
        )
        mismatched_registrar = PostgresWriterReceiptRegistrar(
            evidence_pool, mismatched_source, alternate_verifier,
            build_provenance_source=_BuildSource(),
            approved_build_policy_id="test-policy",
        )
        graph["writer_receipt_verifier"] = mismatched_registrar
        graph["outcome_evidence_provider"] = PostgresOutcomeEvidenceProvider(
            _BundleSource(), mismatched_registrar,
        )
        graph["writer_evidence_resolver"] = PostgresWriterEvidenceResolver(
            alternate_pool, mismatched_source, alternate_verifier,
        )
    elif mutation == "resolver_pool":
        resolver_pool = _SpyPool()
        graph["tracked_pools"].append(resolver_pool)
        resolver_source = PostgresEvidenceAttemptSource(resolver_pool)
        resolver_verifier = ProductionEvidenceVerifier(
            PostgresEvidenceTrustSource(resolver_pool),
        )
        graph["writer_evidence_resolver"] = PostgresWriterEvidenceResolver(
            resolver_pool, resolver_source, resolver_verifier,
        )
    elif mutation == "resolver_attempt_source":
        resolver_source = PostgresEvidenceAttemptSource(evidence_pool)
        graph["writer_evidence_resolver"] = PostgresWriterEvidenceResolver(
            evidence_pool, resolver_source, registrar._verifier,
        )
    elif mutation == "resolver_verifier":
        another_verifier = ProductionEvidenceVerifier(registrar._verifier._source)
        graph["writer_evidence_resolver"] = PostgresWriterEvidenceResolver(
            evidence_pool, registrar._attempt_source, another_verifier,
        )

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        _compose(graph)

    _assert_no_pool_acquisition(graph)
