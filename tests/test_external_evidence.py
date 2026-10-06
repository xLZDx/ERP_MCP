import hashlib
from dataclasses import replace
from datetime import date

import pytest

from business_ai_gateway.external_evidence import (
    MAX_BYTES,
    EvidenceClass,
    EvidenceParserProfile,
    EvidenceRejected,
    EvidenceScope,
    parse_normalized_csv,
    require_evidence,
)


def scope():
    return EvidenceScope("synthetic-source", "synthetic-company", "a" * 64, "b" * 64,
                         date(2026, 1, 1), date(2026, 2, 1), "MDL", "Europe/Chisinau")


def parse(payload, *, candidate=None, confirmed=True, private_ref="private:fixture",
          retention="fixture-policy", expected_scope=None, digest=None):
    profile = candidate or EvidenceParserProfile("fixture", "v1", EvidenceClass.BANK_STATEMENT, scope())
    return parse_normalized_csv(
        payload, profile=profile, expected_scope=expected_scope or scope(),
        validated_profiles=frozenset({profile.fingerprint()}) if confirmed else frozenset(),
        private_blob_ref=private_ref, retention_policy_id=retention,
        approved_retention_policies=frozenset({"fixture-policy"}),
        expected_document_sha256=digest or hashlib.sha256(payload).hexdigest())


def test_normalized_evidence_is_immutable_bounded_and_public_manifest_minimized():
    payload = b"key,date,currency,amount\nprivate-business-key,2026-01-12,MDL,12.340000\n"
    evidence = parse(payload)
    assert str(evidence.facts[0].amount) == "12.340000"
    assert evidence.facts[0].key == "private-business-key"
    manifest = evidence.safe_manifest()
    assert manifest["fact_count"] == 1 and manifest["native_format_validation"] == "NOT_PROVEN"
    for value in ("private-business-key", "synthetic-company", "private:fixture", "12.340000"):
        assert value not in str(manifest)


@pytest.mark.parametrize("evidence_class", list(EvidenceClass))
def test_all_frozen_evidence_classes_need_exact_confirmed_parser_profile(evidence_class):
    profile = EvidenceParserProfile("fixture", "v1", evidence_class, scope())
    payload = b"key,date,currency,amount\nfixture,2026-01-12,MDL,1\n"
    assert parse(payload, candidate=profile).evidence_class == evidence_class
    with pytest.raises(EvidenceRejected, match="PROFILE_UNCONFIRMED"):
        parse(payload, candidate=profile, confirmed=False)


@pytest.mark.parametrize("row", ["fixture,2026-01-12,USD,1", "fixture,2026-02-01,MDL,1",
                                 "fixture,2025-12-31,MDL,1", "fixture,invalid,MDL,1",
                                 "fixture,2026-01-12,MDL,NaN", "fixture,2026-01-12,MDL,1e99",
                                 "fixture,2026-01-12,MDL,0.1234567", ",2026-01-12,MDL,1",
                                 "fixture,2026-01-12,MDL,1,unexpected"])
def test_malformed_or_cross_scope_facts_are_sanitized(row):
    with pytest.raises(EvidenceRejected) as failure:
        parse(("key,date,currency,amount\n" + row + "\n").encode())
    assert row not in str(failure.value)
    assert failure.value.__cause__ is None


@pytest.mark.parametrize("private_ref", ["https://private.invalid/doc", "file:///secret", "../doc"])
def test_no_model_url_or_file_reference_is_accepted(private_ref):
    with pytest.raises(EvidenceRejected, match="RETENTION_UNCONFIRMED"):
        parse(b"key,date,currency,amount\nfixture,2026-01-12,MDL,1\n", private_ref=private_ref)


def test_missing_duplicate_oversized_or_mismatched_inputs_cannot_prove_pass():
    payload = b"key,date,currency,amount\nfixture,2026-01-12,MDL,1\n"
    for data in (b"key,date,currency,amount\n", payload + payload.split(b"\n", 1)[1], b"x" * (MAX_BYTES + 1)):
        with pytest.raises(EvidenceRejected):
            parse(data)
    with pytest.raises(EvidenceRejected, match="FINGERPRINT_MISMATCH"):
        parse(payload, digest="0" * 64)
    with pytest.raises(EvidenceRejected, match="PROFILE_UNCONFIRMED"):
        parse(payload, expected_scope=replace(scope(), company_id="other-company"))
    with pytest.raises(EvidenceRejected, match="RETENTION_UNCONFIRMED"):
        parse(payload, retention="unapproved-policy")


def test_fact_count_limit_and_duplicate_headers_are_rejected():
    rows = [f"fixture-{index},2026-01-12,MDL,1" for index in range(2001)]
    with pytest.raises(EvidenceRejected, match="INPUT_LIMIT"):
        parse(("key,date,currency,amount\n" + "\n".join(rows)).encode())
    with pytest.raises(EvidenceRejected, match="SCHEMA_INVALID"):
        parse(b"key,date,currency,amount,amount\nfixture,2026-01-12,MDL,1,2\n")


def test_business_gate_does_not_invent_missing_evidence_or_accept_stale_scope():
    candidate = parse(b"key,date,currency,amount\nfixture,2026-01-12,MDL,1\n")
    approved = frozenset({candidate.profile_fingerprint})
    required = frozenset({EvidenceClass.BANK_STATEMENT})
    assert require_evidence(required, (candidate,), scope=scope(), validated_profiles=approved) is None
    with pytest.raises(EvidenceRejected, match="EVIDENCE_REQUIRED"):
        require_evidence(required, (), scope=scope(), validated_profiles=approved)
    with pytest.raises(EvidenceRejected, match="EVIDENCE_REQUIRED"):
        require_evidence(frozenset({EvidenceClass.TERMINAL_REPORT}), (candidate,),
                         scope=scope(), validated_profiles=approved)
    with pytest.raises(EvidenceRejected, match="EVIDENCE_INCONCLUSIVE"):
        require_evidence(required, (candidate,), scope=scope(), validated_profiles=frozenset())
    with pytest.raises(EvidenceRejected, match="EVIDENCE_INCONCLUSIVE"):
        require_evidence(required, (candidate,), scope=replace(scope(), company_id="other"),
                         validated_profiles=approved)
