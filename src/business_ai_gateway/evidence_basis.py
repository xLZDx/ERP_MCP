"""Evidence basis of a validated semantic profile (test-lane machine reconciliation, plan 198889).

A profile is validated by at least ten PASS cases stored in ``validation_evidence_json``.  Historically every case was a
native 1C report.  A *machine* case is a two-source comparison (a hand-written 1C COM query versus the production tool
path) that an operator authorized explicitly; it is NOT a native UI report and is labelled accordingly everywhere.

The basis is always computed from the stored cases, never read from a field that a writer supplies:

* only native cases (no ``evidence_class`` or ``NATIVE_UI_REPORT``) -> ``NATIVE`` (the legacy behaviour);
* only machine cases -> ``MACHINE``;
* any mixture -> ``MIXED`` (non-native label, the restrictions of ``MACHINE``);
* an unknown class, a missing field or a contradiction -> refusal.

Only the account.balance_by_analytics concept of an explicitly allow-listed test-lane source may use a non-native profile.
Every other consumer of ``status = 'VALIDATED'`` accepts ``NATIVE`` only.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from .semantic import canonical_fingerprint

NATIVE_UI_CLASS = "NATIVE_UI_REPORT"
MACHINE_EVIDENCE_CLASS = "MACHINE_TWO_SOURCE_RECONCILIATION"
BASIS_NATIVE = "NATIVE"
BASIS_MACHINE = "MACHINE"
BASIS_MIXED = "MIXED"
MACHINE_COMPARISON_KIND = "cross_copy_comparison"  # ADR-0008 section 8: different physical copies are never parity proof
MACHINE_REFERENCE_PREFIX = "machine-artifact:"
MACHINE_METHOD_A = "onec_query_com_v8"
MACHINE_METHOD_B = "mcp_tool_accounting_balance_by_analytics"
MACHINE_MIN_CASES = 10
MACHINE_SCOPE_KEYS = frozenset(
    {
        "source_id",
        "company_id",
        "concept",
        "mapping_fingerprint",
        "metadata_fingerprint",
        "capability_fingerprint",
        "authorization_scope_sha256",
    }
)
RUN_RECORD_KEYS = frozenset(
    {
        "run_id",
        "side",
        "source_identity",
        "method",
        "parameters",
        "snapshot",
        "started_at",
        "finished_at",
        "artifact_sha256",
        "code_identity",
    }
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY = re.compile(r"^ROSETTA_PLAN:([A-Za-z0-9_.\-]{8,200}):([0-9a-f]{64})$")

# SQL twin of ``stored_evidence_basis(...) == NATIVE`` for consumers that filter in the database.  It is deliberately
# conservative: a machine marker anywhere, or any case whose class is not the native class, excludes the profile.
NATIVE_ONLY_SQL = """
 jsonb_typeof(p.validation_evidence_json) = 'object'
 AND jsonb_typeof(p.validation_evidence_json->'native_reconciliation_cases') = 'array'
 AND NOT (p.validation_evidence_json ? 'machine_scope')
 AND coalesce(p.validation_evidence_json->>'evidence_basis', 'NATIVE') = 'NATIVE'
 AND NOT EXISTS (
   SELECT 1
   FROM jsonb_array_elements(
          CASE WHEN jsonb_typeof(p.validation_evidence_json->'native_reconciliation_cases') = 'array'
               THEN p.validation_evidence_json->'native_reconciliation_cases' ELSE '[]'::jsonb END
        ) AS ec(item)
   WHERE jsonb_typeof(ec.item) IS DISTINCT FROM 'object'
      OR (ec.item ? 'evidence_class' AND ec.item->>'evidence_class' IS DISTINCT FROM 'NATIVE_UI_REPORT')
 )
"""


class EvidenceBasisError(ValueError):
    """The stored or supplied evidence is unknown, incomplete or contradictory."""


def _evidence_object(validation_evidence: Any) -> dict[str, Any]:
    if isinstance(validation_evidence, str):
        try:
            validation_evidence = json.loads(validation_evidence)
        except ValueError as exc:
            raise EvidenceBasisError("validation evidence is not valid JSON") from exc
    if not isinstance(validation_evidence, dict):
        raise EvidenceBasisError("validation evidence is not an object")
    return validation_evidence


def _cases(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    cases = evidence.get("native_reconciliation_cases")
    if not isinstance(cases, list) or not cases:
        raise EvidenceBasisError("validation evidence has no cases")
    if any(not isinstance(case, dict) for case in cases):
        raise EvidenceBasisError("every evidence case must be an object")
    return cases


def case_class(case: dict[str, Any]) -> str:
    value = case.get("evidence_class")
    if value is None:
        return NATIVE_UI_CLASS  # legacy cases never carried a class and were native
    if value in (NATIVE_UI_CLASS, MACHINE_EVIDENCE_CLASS):
        return value
    raise EvidenceBasisError("unknown evidence class")


def compute_evidence_basis(cases: list[dict[str, Any]]) -> str:
    if not cases:
        raise EvidenceBasisError("no evidence cases")
    classes = {case_class(case) for case in cases}
    if classes == {NATIVE_UI_CLASS}:
        return BASIS_NATIVE
    if classes == {MACHINE_EVIDENCE_CLASS}:
        return BASIS_MACHINE
    return BASIS_MIXED


def stored_evidence_basis(validation_evidence: Any) -> str:
    """Recompute the basis of a stored profile; refuse contradictions (never trust a stored label)."""
    evidence = _evidence_object(validation_evidence)
    basis = compute_evidence_basis(_cases(evidence))
    has_scope = "machine_scope" in evidence
    if basis == BASIS_NATIVE and has_scope:
        raise EvidenceBasisError("machine scope present on evidence that classifies as native")
    if basis != BASIS_NATIVE and not has_scope:
        raise EvidenceBasisError("non-native evidence without a machine scope")
    declared = evidence.get("evidence_basis")
    if declared is not None and declared != basis:
        raise EvidenceBasisError("declared evidence basis disagrees with the cases")
    return basis


def require_native_basis(validation_evidence: Any) -> None:
    """Consumers that do not explicitly allow machine evidence call this."""
    if stored_evidence_basis(validation_evidence) != BASIS_NATIVE:
        raise EvidenceBasisError("a non-native profile cannot be used here")


def authorization_scope(
    *, source_id: str, company_id: str, concept: str, mapping: dict[str, Any]
) -> dict[str, Any]:
    accounts = mapping.get("accounts") if isinstance(mapping, dict) else None
    if not isinstance(accounts, list) or not accounts:
        raise EvidenceBasisError("mapping has no accounts")
    codes = []
    for account in accounts:
        code = account.get("code") if isinstance(account, dict) else None
        if not isinstance(code, str) or not code:
            raise EvidenceBasisError("mapping account has no code")
        codes.append(code)
    return {
        "source_id": source_id,
        "company_id": company_id,
        "concept": concept,
        "mapping_fingerprint": canonical_fingerprint(mapping),
        "accounts": sorted(codes),
    }


def authorization_scope_sha256(**kwargs: Any) -> str:
    return canonical_fingerprint(authorization_scope(**kwargs))


def parse_authority(value: Any) -> tuple[str, str]:
    match = _AUTHORITY.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise EvidenceBasisError("authorized_by must be ROSETTA_PLAN:<plan_id>:<plan_hash>")
    return match.group(1), match.group(2)


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise EvidenceBasisError(f"{label} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceBasisError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceBasisError(f"{label} must carry a time zone")
    return parsed


def _run_record(record: Any, *, side: str, method: str, case_as_of: str) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != RUN_RECORD_KEYS:
        raise EvidenceBasisError(f"run record {side} has missing or unexpected fields")
    if record["side"] != side or record["method"] != method:
        raise EvidenceBasisError(f"run record {side} has the wrong side or method")
    try:
        uuid.UUID(str(record["run_id"]))
    except ValueError as exc:
        raise EvidenceBasisError(f"run record {side} has an invalid run_id") from exc
    if not isinstance(record["artifact_sha256"], str) or not _HEX64.fullmatch(record["artifact_sha256"]):
        raise EvidenceBasisError(f"run record {side} has an invalid artifact digest")
    for key in ("source_identity",):
        if not isinstance(record[key], str) or not record[key].strip():
            raise EvidenceBasisError(f"run record {side} has an empty {key}")
    parameters = record["parameters"]
    if not isinstance(parameters, dict) or parameters.get("as_of") != case_as_of:
        raise EvidenceBasisError(f"run record {side} parameters do not match the case as_of")
    snapshot = record["snapshot"]
    if not isinstance(snapshot, dict) or not snapshot.get("identity") or not snapshot.get("kind"):
        raise EvidenceBasisError(f"run record {side} has no snapshot identity")
    code = record["code_identity"]
    if (
        not isinstance(code, dict)
        or not isinstance(code.get("git_head"), str)
        or not isinstance(code.get("script_sha256"), str)
        or not _HEX64.fullmatch(code["script_sha256"])
    ):
        raise EvidenceBasisError(f"run record {side} has no producing code identity")
    started = _timestamp(record["started_at"], f"run record {side} started_at")
    finished = _timestamp(record["finished_at"], f"run record {side} finished_at")
    if finished < started:
        raise EvidenceBasisError(f"run record {side} finished before it started")
    return record


def check_machine_evidence_structure(
    validation_evidence: Any,
    *,
    source_id: str,
    company_id: str,
    concept: str,
    mapping: dict[str, Any],
    metadata_fingerprint: str,
    capability_fingerprint: str,
) -> str:
    """Re-check the stored machine evidence against the profile row (called at runtime and at validation).

    This proves the record is complete, consistent and bound to this profile.  The artifact bytes themselves are
    verified by ``scripts/real1c/machine_reconciliation.py`` at validation time, when the private files are present.
    """
    evidence = _evidence_object(validation_evidence)
    basis = stored_evidence_basis(evidence)
    if basis == BASIS_NATIVE:
        raise EvidenceBasisError("evidence is native; no machine structure to check")
    scope = evidence["machine_scope"]
    if not isinstance(scope, dict) or set(scope) != MACHINE_SCOPE_KEYS:
        raise EvidenceBasisError("machine scope has missing or unexpected fields")
    expected = {
        "source_id": source_id,
        "company_id": company_id,
        "concept": concept,
        "mapping_fingerprint": canonical_fingerprint(mapping),
        "metadata_fingerprint": metadata_fingerprint,
        "capability_fingerprint": capability_fingerprint,
        "authorization_scope_sha256": authorization_scope_sha256(
            source_id=source_id, company_id=company_id, concept=concept, mapping=mapping
        ),
    }
    if scope != expected:
        raise EvidenceBasisError("machine scope is not bound to this source, company, mapping or fingerprints")
    cases = _cases(evidence)
    if len(cases) < MACHINE_MIN_CASES:
        raise EvidenceBasisError("fewer than ten machine cases")
    case_ids, as_ofs, run_ids = set(), set(), set()
    for case in cases:
        if case_class(case) != MACHINE_EVIDENCE_CLASS:
            raise EvidenceBasisError("mixed evidence cannot be used at runtime")
        if case.get("status") != "PASS" or case.get("result") != "MATCH":
            raise EvidenceBasisError("a machine case is not a PASS/MATCH")
        if case.get("comparison_kind") != MACHINE_COMPARISON_KIND:
            raise EvidenceBasisError("machine cases must be labelled cross_copy_comparison")
        reference = case.get("native_report_ref")
        if not isinstance(reference, str) or not reference.startswith(MACHINE_REFERENCE_PREFIX):
            raise EvidenceBasisError("machine case reference must use the machine-artifact: form")
        case_id, as_of = case.get("case_id"), case.get("as_of")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in case_ids:
            raise EvidenceBasisError("machine case ids must be non-empty and unique")
        instant = _timestamp(as_of, "case as_of").astimezone(UTC)
        if instant in as_ofs:
            raise EvidenceBasisError("the same as_of cannot be used by two cases")
        case_ids.add(case_id)
        as_ofs.add(instant)
        parse_authority(case.get("authorized_by"))
        record_a = _run_record(case.get("run_record_a"), side="A", method=MACHINE_METHOD_A, case_as_of=as_of)
        record_b = _run_record(case.get("run_record_b"), side="B", method=MACHINE_METHOD_B, case_as_of=as_of)
        if record_a["run_id"] == record_b["run_id"] or record_a["method"] == record_b["method"]:
            raise EvidenceBasisError("the two sides need independent run ids and methods")
        if record_a["parameters"] != record_b["parameters"]:
            raise EvidenceBasisError("the two sides were not run with the same parameters")
        for run_id in (str(uuid.UUID(str(record_a["run_id"]))), str(uuid.UUID(str(record_b["run_id"])))):
            if run_id in run_ids:
                raise EvidenceBasisError("a run id is reused across cases")
            run_ids.add(run_id)
    authorities = {case["authorized_by"] for case in cases}
    if len(authorities) != 1:
        raise EvidenceBasisError("all machine cases must cite one authorization")
    return basis
