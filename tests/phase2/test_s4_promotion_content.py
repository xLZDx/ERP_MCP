"""Acceptance tests for scoped evidence-byte verification before promotion writes."""

from dataclasses import replace
from hashlib import sha256

import pytest

from business_ai_gateway.phase2.promotion import (
    EvidenceContent,
    Outcome,
    PromotionService,
)
from test_promotion import APPROVER, MODEL, REQUESTER, SCOPE, World, uid


COMPANY = "company-1"
MARKER = b"synthetic promotion evidence marker\n"
CONTENT_DIGEST = sha256(MARKER).hexdigest()


class SyntheticEvidenceReader:
    """Deterministic trusted-reader stand-in; it records requested scope and effects."""

    def __init__(self, *, content: EvidenceContent | None = None,
                 raises: Exception | None = None):
        self.content = content
        self.raises = raises
        self.calls: list[tuple[object, ...]] = []

    async def read_attested_content(self, scope, company_id, attestation_id,
                                    revision_id, evidence_ref):
        self.calls.append((scope, company_id, attestation_id, revision_id, evidence_ref))
        if self.raises is not None:
            raise self.raises
        return self.content


async def _configured_world(*, alter: str | None = None,
                            reader_error: Exception | None = None):
    world = await World().setup()
    revision_id, evidence, attestation_id = await world.attest(1)
    material = EvidenceContent(
        scope=SCOPE,
        company_id=COMPANY,
        attestation_id=attestation_id,
        revision_id=revision_id,
        evidence_ref=evidence.evidence_ref,
        artifact_version="artifact-v1",
        content_digest=CONTENT_DIGEST,
        content=MARKER,
    )
    if alter == "tenant":
        material = replace(material, scope=type(SCOPE)("other-tenant", SCOPE.source_id))
    elif alter == "source":
        material = replace(material, scope=type(SCOPE)(SCOPE.tenant_id, "other-source"))
    elif alter == "company":
        material = replace(material, company_id="other-company")
    elif alter == "attestation":
        material = replace(material, attestation_id=uid(999))
    elif alter == "revision":
        material = replace(material, revision_id=uid(998))
    elif alter == "reference":
        material = replace(material, evidence_ref="other-reference")
    elif alter == "digest":
        material = replace(material, content_digest="f" * 64)
    content_reader = SyntheticEvidenceReader(content=material, raises=reader_error)
    service = PromotionService(
        world.port,
        world.reader,
        world.clock.now,
        content_reader=content_reader,
        company_id=COMPANY,
    )
    return world, revision_id, evidence, attestation_id, content_reader, service


async def _attempt(world, service, revision_id, evidence, *, acceptance_id=None):
    return await service.promote(
        SCOPE,
        MODEL,
        revision_id,
        0,
        REQUESTER,
        APPROVER,
        evidence,
        acceptance_id or uid(900),
    )


async def _assert_no_new_write(world, service, revision_id, evidence, *, code,
                               reader_calls: int = 1):
    before = await world.snapshot()
    writes_before = world.port.promote_calls
    result = await _attempt(world, service, revision_id, evidence)

    assert result.outcome is Outcome.REJECTED_EVIDENCE
    assert result.code == code
    assert not result.ok and result.new_version is None
    assert world.port.promote_calls == writes_before
    assert await world.snapshot() == before
    return result


async def test_valid_content_marker_is_verified_before_single_promotion_write():
    world, revision_id, evidence, attestation_id, reader, service = await _configured_world()
    before = await world.snapshot()
    writes_before = world.port.promote_calls

    result = await _attempt(world, service, revision_id, evidence)

    assert (result.outcome, result.new_version, result.ok) == (Outcome.PROMOTED, 1, True)
    assert len(reader.calls) == 1
    assert reader.calls[0] == (
        SCOPE, COMPANY, attestation_id, revision_id, evidence.evidence_ref
    )
    assert world.port.promote_calls == writes_before + 1
    assert await world.snapshot() != before


@pytest.mark.parametrize(
    "alter,code",
    [
        ("digest", "EVIDENCE_CONTENT_DIGEST_MISMATCH"),
        ("tenant", "EVIDENCE_CONTENT_BINDING_MISMATCH"),
        ("source", "EVIDENCE_CONTENT_BINDING_MISMATCH"),
        ("company", "EVIDENCE_CONTENT_BINDING_MISMATCH"),
        ("attestation", "EVIDENCE_CONTENT_BINDING_MISMATCH"),
        ("revision", "EVIDENCE_CONTENT_BINDING_MISMATCH"),
        ("reference", "EVIDENCE_CONTENT_BINDING_MISMATCH"),
    ],
)
async def test_bad_hash_or_wrong_binding_causes_zero_new_writes(alter: str, code: str):
    world, revision_id, evidence, _, reader, service = await _configured_world(alter=alter)
    before = await world.snapshot()
    writes_before = world.port.promote_calls

    result = await _attempt(world, service, revision_id, evidence)

    assert result.outcome is Outcome.REJECTED_EVIDENCE
    assert result.code == code
    assert world.port.promote_calls == writes_before
    assert await world.snapshot() == before
    assert len(reader.calls) == 1


@pytest.mark.parametrize(
    "reader_error,expected_code",
    [
        (None, "EVIDENCE_CONTENT_NOT_FOUND"),
        (RuntimeError("synthetic reader outage"), "EVIDENCE_CONTENT_UNAVAILABLE"),
    ],
)
async def test_missing_or_unavailable_content_fails_before_write(reader_error, expected_code):
    world, revision_id, evidence, _, reader, service = await _configured_world(
        reader_error=reader_error
    )
    if reader_error is None:
        reader = SyntheticEvidenceReader(content=None)
        service = PromotionService(
            world.port, world.reader, world.clock.now,
            content_reader=reader, company_id=COMPANY,
        )

    result = await _assert_no_new_write(
        world, service, revision_id, evidence, code=expected_code
    )
    assert len(reader.calls) == 1


@pytest.mark.parametrize(
    "content_reader,company_id",
    [
        (None, COMPANY),
        (SyntheticEvidenceReader(), None),
        (SyntheticEvidenceReader(), "  "),
    ],
)
async def test_incomplete_content_verifier_configuration_fails_before_reader_or_write(
    content_reader, company_id
):
    world = await World().setup()
    revision_id, evidence, _ = await world.attest(1)
    service = PromotionService(
        world.port,
        world.reader,
        world.clock.now,
        content_reader=content_reader,
        company_id=company_id,
    )
    before = await world.snapshot()
    writes_before = world.port.promote_calls

    result = await _attempt(world, service, revision_id, evidence)

    assert result.outcome is Outcome.REJECTED_EVIDENCE
    assert result.code == "CONTENT_VERIFIER_CONFIG_INCOMPLETE"
    assert world.port.promote_calls == writes_before
    assert await world.snapshot() == before
    if content_reader is not None:
        assert content_reader.calls == []


async def test_historical_replay_without_content_fingerprint_is_not_promoted_again():
    world, revision_id, evidence, _, reader, service = await _configured_world()
    acceptance_id = uid(901)
    legacy_result = await world.svc.promote(
        SCOPE, MODEL, revision_id, 0, REQUESTER, APPROVER, evidence, acceptance_id
    )
    assert legacy_result.ok
    writes_before = world.port.promote_calls
    after_original_write = await world.snapshot()

    replay = await _attempt(world, service, revision_id, evidence, acceptance_id=acceptance_id)

    assert replay.outcome is Outcome.REJECTED_ACCEPTANCE_ID
    assert replay.code == "REPLAY_FINGERPRINT_UNAVAILABLE"
    assert world.port.promote_calls == writes_before
    assert await world.snapshot() == after_original_write
    assert reader.calls == []

