"""S13-EVIDENCE-PROVIDER-COMPOSITION-01: production evidence graph is bound fail-closed."""
from __future__ import annotations

import asyncio

import asyncpg
import pytest

from erp_mcp_private_writer import runtime_composition as composition
from erp_mcp_private_writer import validator_build_attestation as build_attestation
from erp_mcp_private_writer.barrier_ack_verifier import ProductionBarrierAcknowledgementVerifier
from erp_mcp_private_writer.postgres_barrier_ack_registrar import (
    PostgresBarrierAcknowledgementRegistrar,
)
from erp_mcp_private_writer.postgres_barrier_ack_trust import (
    PostgresBarrierAcknowledgementTrustSource,
)
from erp_mcp_private_writer.postgres_attempt_source import PostgresEvidenceAttemptSource
from erp_mcp_private_writer.postgres_evidence_registrar import (
    EvidenceRegistrationError,
    PostgresWriterReceiptRegistrar,
)
from erp_mcp_private_writer.postgres_evidence_resolver import PostgresWriterEvidenceResolver
from erp_mcp_private_writer.postgres_evidence_trust import PostgresEvidenceTrustSource
from erp_mcp_private_writer.postgres_outcome_provider import PostgresOutcomeEvidenceProvider
from erp_mcp_private_writer.production_evidence_verifier import ProductionEvidenceVerifier
from erp_mcp_private_writer.validator_build_attestation import (
    ProductionValidatorBuildInputsSource,
    ValidatorBuildAttestationVerifier,
)


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


class _ProductionInputsStub(ProductionValidatorBuildInputsSource):
    """Concrete stand-in for the future host-authorized source; never contacted by these tests."""

    async def load_current_inputs(self):  # pragma: no cover - must not be reached
        raise AssertionError("composition must not load attestation inputs")


def _BuildSource():  # noqa: N802 - keeps the call sites reading as a source constructor
    return ValidatorBuildAttestationVerifier(_ProductionInputsStub())


@pytest.fixture(autouse=True)
def _allow_the_stub_as_a_production_build_source(monkeypatch):
    # The production allowlist is empty until a host-bound source is reviewed, so the registrar refuses
    # every real source by design. These tests exercise the composition around that gate, not the gate.
    monkeypatch.setattr(build_attestation, "_PRODUCTION_INPUT_SOURCE_TYPES", (_ProductionInputsStub,))


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


def _registrar_on_the_register_path(monkeypatch, *, same_build: bool):
    """A registrar whose build re-read and comparison are stubbed so only the call site is exercised."""
    pool = _SpyPool()
    registrar = PostgresWriterReceiptRegistrar(
        pool, PostgresEvidenceAttemptSource(pool),
        ProductionEvidenceVerifier(PostgresEvidenceTrustSource(pool)),
        build_provenance_source=_BuildSource(), approved_build_policy_id="test-policy",
    )
    approved = object()

    async def reread_current_build(self):
        return object()

    monkeypatch.setattr(PostgresWriterReceiptRegistrar, "_require_registration_authority",
                        lambda self, build: None)
    monkeypatch.setattr(PostgresWriterReceiptRegistrar, "_approved_validator_build", reread_current_build)
    monkeypatch.setattr(PostgresWriterReceiptRegistrar, "_same_validator_build_authority",
                        staticmethod(lambda expected, current: same_build))
    return pool, registrar, approved


def test_register_compares_the_reread_build_and_then_reaches_the_database(monkeypatch):
    pool, registrar, approved = _registrar_on_the_register_path(monkeypatch, same_build=True)

    with pytest.raises(EvidenceRegistrationError) as raised:
        asyncio.run(registrar._register("{}", "ref", approved))

    # The spy pool refuses the connection, so the registration ends as UNAVAILABLE; what matters is that
    # the build comparison ran (a bare-name call raised NameError first) and the pool was then reached.
    assert raised.value.code == "EVIDENCE_REGISTER_UNAVAILABLE"
    assert pool.acquire_calls == 1


def test_register_refuses_before_the_database_when_the_build_policy_changed(monkeypatch):
    pool, registrar, approved = _registrar_on_the_register_path(monkeypatch, same_build=False)

    with pytest.raises(EvidenceRegistrationError) as raised:
        asyncio.run(registrar._register("{}", "ref", approved))

    assert raised.value.code == "EVIDENCE_REGISTER_BUILD_POLICY_STALE"
    assert pool.acquire_calls == 0


def test_outer_cancellation_terminates_the_connection_instead_of_returning_it(monkeypatch):
    from erp_mcp_private_writer import postgres_evidence_registrar as registrar_module

    class _Transaction:
        async def start(self):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class _HangingConnection:
        terminated = False

        def transaction(self):
            return _Transaction()

        def is_in_transaction(self):
            return True

        def terminate(self):
            self.terminated = True

        async def execute(self, *_args):
            return None

        async def fetchval(self, *_args):
            await asyncio.sleep(3600)

    async def _identity_ok(*_args):
        return True

    monkeypatch.setattr(registrar_module, "has_expected_database_identity", _identity_ok)
    _pool, registrar, _approved = _registrar_on_the_register_path(monkeypatch, same_build=True)
    conn = _HangingConnection()

    async def _run():
        deadline = registrar_module.time.monotonic() + 30
        async with asyncio.timeout(0.05):
            await registrar._register_on_connection(conn, "{}", "ref", deadline)

    with pytest.raises(TimeoutError):
        asyncio.run(_run())

    assert conn.terminated is True


def test_a_pool_timeout_before_any_statement_is_not_reported_as_outcome_unknown(monkeypatch):
    pool, registrar, approved = _registrar_on_the_register_path(monkeypatch, same_build=True)

    def _acquire_times_out(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(pool, "acquire", _acquire_times_out)

    with pytest.raises(EvidenceRegistrationError) as raised:
        asyncio.run(registrar._register("{}", "ref", approved))

    assert raised.value.code == "EVIDENCE_REGISTER_TIMEOUT"
    assert raised.value.outcome_unknown is False


def test_unexpected_error_logging_omits_the_message(monkeypatch, caplog):
    from erp_mcp_private_writer import postgres_evidence_registrar as registrar_module

    try:
        raise TypeError("secret-value\nFAKE LOG LINE")
    except TypeError as exc:
        with caplog.at_level("ERROR"):
            registrar_module._log_unexpected("test", exc)

    assert "TypeError" in caplog.text
    assert "secret-value" not in caplog.text
    assert "FAKE LOG LINE" not in caplog.text
