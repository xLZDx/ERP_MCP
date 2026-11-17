"""Offline acceptance for S5 manual baseline intake and synthetic TC064 comparison.

These tests exercise only synthetic bytes and in-memory adapters. They do not
establish native origin, completeness, live authority, or 1C equivalence.
"""
from __future__ import annotations

import hashlib
import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from business_ai_gateway.phase2.artifact_vault import (
    ArtifactScope,
    ArtifactVault,
    AuditKind,
    Principal,
)
from business_ai_gateway.phase2.native_baseline_intake import (
    BaselineCompleteness,
    BaselineIntake,
    BaselineIntakeStatus,
    BaselineManifestClaims,
    TrustedCaptureContext,
)
from business_ai_gateway.phase2.native_capture_compare import (
    CanonicalCaptureObservation,
    CaptureComparisonState,
    compare_capture_observations,
)


CONTEXT = TrustedCaptureContext(
    "tenant-test", "source-test", "database-test", "company-test",
    "caller-test", "report-test", "variant-test",
)
CALLER = Principal("caller-test")
VAULT_PRINCIPAL = Principal("intake-vault-test")
ADMIN = Principal("vault-admin-test")
SCOPE = ArtifactScope(CONTEXT.tenant_id, CONTEXT.source_id)
CSV = b"code,total\nA,42\n"
PDF = b"%PDF-1.4\nsynthetic receipt\n%%EOF\n"


def claims(**changes: object) -> BaselineManifestClaims:
    values: dict[str, object] = {
        "tenant_id": CONTEXT.tenant_id,
        "source_id": CONTEXT.source_id,
        "database_id": CONTEXT.database_id,
        "company_id": CONTEXT.company_id,
        "report_object": CONTEXT.report_object,
        "variant": CONTEXT.variant,
        "period": "2026-Q1",
        "filters": (("currency", "MDL"),),
        "columns": ("code", "total"),
        "totals": (("total", "42"),),
        "row_limit_reached": False,
        "partial": False,
        "known_truncated": False,
    }
    values.update(changes)
    return BaselineManifestClaims(**values)  # type: ignore[arg-type]


def world(*, authorize_request=None, id_source=None):
    vault_ids = itertools.count(1)
    vault = ArtifactVault(
        lambda: datetime(2026, 1, 1, tzinfo=UTC),
        admins=(ADMIN.principal_id,),
        id_source=id_source or (lambda: next(vault_ids).to_bytes(16, "big")),
    )
    assert vault.grant(SCOPE, VAULT_PRINCIPAL, ADMIN) == "OK"
    intake_ids = itertools.count(1)
    intake = BaselineIntake(
        vault,
        VAULT_PRINCIPAL,
        lambda context, principal: context == CONTEXT and principal == CALLER,
        authorize_request=authorize_request or (
            lambda context, principal, request_id: context == CONTEXT and principal == CALLER
        ),
        id_source=lambda: f"baseline-test-{next(intake_ids)}",
    )
    return intake, vault


def submit(intake: BaselineIntake, *, request_id: str = "request-test-1",
           data: bytes = CSV, media_type: str = "text/csv",
           manifest: BaselineManifestClaims | None = None,
           publication_authorized=None):
    return intake.intake(
        context=CONTEXT,
        principal=CALLER,
        request_id=request_id,
        claims=manifest or claims(),
        content=data,
        media_type=media_type,
        publication_authorized=publication_authorized,
    )


def successful_puts(vault: ArtifactVault) -> tuple[object, ...]:
    return tuple(event for event in vault.audit()
                 if event.kind is AuditKind.PUT and event.code == "OK")


@pytest.mark.parametrize("media_type,data", [("text/csv", CSV), ("application/pdf", PDF)])
def test_tc061_supported_synthetic_original_is_scoped_and_remains_unattested(media_type, data):
    intake, _ = world()

    result, code = submit(intake, data=data, media_type=media_type)

    assert code == "OK"
    assert result is not None
    assert result.attestation is BaselineIntakeStatus.UNATTESTED
    assert result.completeness is BaselineCompleteness.UNVERIFIED
    assert result.size == len(data)
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert (result.tenant_id, result.source_id, result.database_id, result.company_id) == (
        CONTEXT.tenant_id, CONTEXT.source_id, CONTEXT.database_id, CONTEXT.company_id
    )
    read = intake.read(context=CONTEXT, principal=CALLER, baseline_id=result.baseline_id)
    assert (read.code, read.result, read.content) == ("OK", result, data)


@pytest.mark.parametrize(
    "manifest,media_type",
    [
        (claims(partial=True), "text/csv"),
        (claims(known_truncated=True), "text/csv"),
        (claims(row_limit_reached=True), "text/csv"),
        (claims(company_id="another-company"), "text/csv"),
        (claims(variant="another-variant"), "text/csv"),
        (claims(columns=()), "text/csv"),
        (claims(totals=()), "text/csv"),
        (claims(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ],
)
def test_tc062_incomplete_mismatched_or_unsupported_candidate_is_not_published(manifest, media_type):
    intake, vault = world()

    result, code = submit(intake, manifest=manifest, media_type=media_type)

    assert result is None and code == "INTAKE_REFUSED"
    assert successful_puts(vault) == ()
    assert intake.recover(context=CONTEXT, principal=CALLER,
                          request_id="request-test-1") == (None, "INTAKE_REFUSED")


def test_tc063_changed_bytes_under_known_request_are_refused_and_original_remains_readable():
    intake, _ = world()
    original, code = submit(intake)
    assert code == "OK" and original is not None

    changed, changed_code = submit(intake, data=b"code,total\nA,43\n")
    recovered, recover_code = intake.recover(
        context=CONTEXT, principal=CALLER, request_id="request-test-1"
    )
    read = intake.read(context=CONTEXT, principal=CALLER, baseline_id=original.baseline_id)

    assert changed is None and changed_code == "INTAKE_REFUSED"
    assert recover_code == "OK" and recovered == original
    assert read.code == "OK" and read.content == CSV


def test_forged_request_id_is_denied_before_any_artifact_write():
    intake, vault = world(authorize_request=lambda context, principal, request_id: False)

    result, code = submit(intake, request_id="forged-request-id")

    assert result is None and code == "INTAKE_REFUSED"
    assert successful_puts(vault) == ()


def test_equal_concurrent_requests_publish_one_receipt_and_replay_same_id():
    intake, vault = world()
    start = threading.Barrier(2)

    def upload():
        start.wait(timeout=2)
        return submit(intake)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: upload(), range(2)))

    assert [code for _, code in results] == ["OK", "OK"]
    first, second = results[0][0], results[1][0]
    assert first is not None and second == first
    assert len(successful_puts(vault)) == 1
    assert intake.recover(context=CONTEXT, principal=CALLER,
                          request_id="request-test-1") == (first, "OK")


def test_conflicting_retry_cannot_replace_request_binding():
    intake, _ = world()
    first, code = submit(intake)
    assert code == "OK" and first is not None

    conflicting, conflict_code = submit(
        intake, manifest=claims(period="2026-Q2")
    )
    recovered, recover_code = intake.recover(
        context=CONTEXT, principal=CALLER, request_id="request-test-1"
    )

    assert conflicting is None and conflict_code == "INTAKE_REFUSED"
    assert recover_code == "OK" and recovered == first


def test_lost_success_response_is_recoverable_by_exact_authorized_replay():
    intake, _ = world()
    published, code = submit(intake)
    assert code == "OK" and published is not None

    recovered, recover_code = intake.recover(
        context=CONTEXT, principal=CALLER, request_id="request-test-1"
    )

    assert recover_code == "OK" and recovered == published


def test_authority_revocation_before_publication_leaves_only_unreferenced_vault_blob():
    intake, vault = world()
    checks = itertools.count(1)

    def authorization_is_current() -> bool:
        return next(checks) == 1

    result, code = submit(intake, publication_authorized=authorization_is_current)

    assert result is None and code == "INTAKE_REFUSED"
    assert len(successful_puts(vault)) == 1
    assert intake.recover(context=CONTEXT, principal=CALLER,
                          request_id="request-test-1") == (None, "INTAKE_REFUSED")


def observation(*, rows=(("A", "42"),), **changes: object) -> CanonicalCaptureObservation:
    values: dict[str, object] = {
        "tenant_id": CONTEXT.tenant_id,
        "source_id": CONTEXT.source_id,
        "database_id": CONTEXT.database_id,
        "configuration_id": "configuration-test",
        "company_id": CONTEXT.company_id,
        "report_object": CONTEXT.report_object,
        "variant": CONTEXT.variant,
        "normalized_parameters": (("currency", "MDL"),),
        "columns": ("code", "total"),
        "normalized_totals": (("total", "42"),),
        "normalized_rows": rows,
    }
    values.update(changes)
    return CanonicalCaptureObservation(**values)  # type: ignore[arg-type]


def test_tc064_equal_synthetic_observations_match_without_claiming_native_equivalence():
    result = compare_capture_observations(observation(), observation())

    assert result.state is CaptureComparisonState.MATCH
    assert result.reason_code == "SYNTHETIC_CAPTURE_VALUES_EQUAL"
    assert result.authority == "SYNTHETIC_EVALUATION_ONLY"
    assert result.native_equivalence_established is False


def test_tc064_synthetic_value_difference_is_visible_and_context_difference_inconclusive():
    different_value = compare_capture_observations(
        observation(), observation(rows=(("A", "43"),))
    )
    different_scope = compare_capture_observations(
        observation(), observation(company_id="other-company")
    )

    assert different_value.state is CaptureComparisonState.MISMATCH
    assert different_value.differences == ("rows[0][1]",)
    assert different_scope.state is CaptureComparisonState.INCONCLUSIVE
    assert different_scope.reason_code == "CAPTURE_CONTEXT_MISMATCH"
