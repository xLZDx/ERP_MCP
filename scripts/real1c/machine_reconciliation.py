"""Verifier for labelled machine two-source reconciliation evidence (ADR-0008 section 8).

Side A is a hand-written 1C query run through COM; side B is the production MCP tool.  Both write a private
artifact per case.  This module re-reads those artifacts at validation time and proves, byte for byte, that the
stored case record describes real files: digests, embedded run id and method, exact Decimal equality per row key,
no truncation, no empty result.  It also checks that the cited Rosetta plan really authorizes this scope.

The output is a *cross-copy comparison*.  It is never native parity proof and never replaces human native reports.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from business_ai_gateway.evidence_basis import (
    MACHINE_METHOD_A,
    MACHINE_METHOD_B,
    MACHINE_REFERENCE_PREFIX,
    EvidenceBasisError,
    authorized_accounts,
    authorized_roles,
    parse_authority,
)

PLAN_STATUSES = frozenset({"in-progress", "in_progress", "passed"})
ARTIFACT_FILES = {"A": "side_a.json", "B": "side_b.json"}
_ROW_KEYS = {"account", "analytics", "currency_ref", "balance_debit", "balance_credit"}


class MachineReconciliationError(ValueError):
    """The machine evidence cannot be verified against its artifacts or authority."""


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, (float, bool)) or not isinstance(value, (str, int)):
        raise MachineReconciliationError(f"{label} must be an exact decimal string")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise MachineReconciliationError(f"{label} is not a decimal") from exc
    if not number.is_finite():
        raise MachineReconciliationError(f"{label} is not finite")
    if number != number.quantize(Decimal("0.01")):
        raise MachineReconciliationError(f"{label} has more than two decimals; rounding is not allowed")
    return number


def verify_plan_authority(authority: str, *, scope_sha256: str, plans_dir: Path) -> dict[str, Any]:
    """The cited plan must be approved by GPT-PM for its exact hash and its scope must name this scope hash."""
    plan_id, plan_hash = parse_authority(authority)
    matches = [path for path in Path(plans_dir).glob("*.json") if path.stem == plan_id]
    if len(matches) != 1:
        raise MachineReconciliationError("the cited Rosetta plan was not found exactly once")
    plan = json.loads(matches[0].read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise MachineReconciliationError("the cited Rosetta plan is not an object")
    approval = plan.get("approval")
    if (
        plan.get("plan_id") != plan_id
        or plan.get("status") not in PLAN_STATUSES
        or plan.get("plan_hash") != plan_hash
        or not isinstance(approval, dict)
        or approval.get("verdict") != "APPROVE"
        or approval.get("correlated") is not True
        or approval.get("approved_plan_hash") != plan_hash
        or "GPT-PM" not in str(approval.get("approved_by"))
    ):
        raise MachineReconciliationError("the cited plan is not an approved, correlated, current plan")
    scope = str(plan.get("scope", ""))
    if scope_sha256 not in scope:
        raise MachineReconciliationError("the cited plan scope does not name this authorization scope")
    return {"plan_id": plan_id, "plan_hash": plan_hash}


def _read_artifact(
    path: Path, *, expected_sha256: str, run_id: str, method: str, side: str, as_of: str, parameters: dict[str, Any]
):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise MachineReconciliationError(f"artifact digest mismatch for side {side}")
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or data.get("run_id") != run_id
        or data.get("method") != method
        or data.get("side") != side
        or data.get("as_of") != as_of
    ):
        raise MachineReconciliationError(f"artifact for side {side} does not embed its own run id, method or as_of")
    if data.get("context") != parameters:
        raise MachineReconciliationError(f"artifact for side {side} does not embed the run record parameters")
    if data.get("truncated") is not False:
        raise MachineReconciliationError(f"artifact for side {side} is truncated or does not say otherwise")
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise MachineReconciliationError(f"artifact for side {side} has no rows")
    return rows


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _row_map(
    rows: list[Any],
    side: str,
    allowed_accounts: frozenset[str] | None = None,
    allowed_roles: frozenset[str] | None = None,
) -> dict[tuple, tuple[Decimal, Decimal]]:
    """Typed canonical rows only: a missing currency is the empty string, never null/false/0."""
    result: dict[tuple, tuple[Decimal, Decimal]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise MachineReconciliationError(f"side {side} has a malformed row")
        if not _nonempty_text(row["account"]) or (allowed_accounts is not None and row["account"] not in allowed_accounts):
            raise MachineReconciliationError(f"side {side} has a row outside the authorized accounts")
        if not isinstance(row["currency_ref"], str):
            raise MachineReconciliationError(f"side {side} has a currency reference that is not text")
        analytics = row["analytics"]
        if not isinstance(analytics, list) or not analytics:
            raise MachineReconciliationError(f"side {side} has a row without analytics")
        slots = []
        for slot in analytics:
            if (
                not isinstance(slot, dict)
                or set(slot) != {"type", "ref"}
                or not _nonempty_text(slot["type"])
                or not _nonempty_text(slot["ref"])
                or (allowed_roles is not None and slot["type"] not in allowed_roles)
            ):
                raise MachineReconciliationError(f"side {side} has an invalid analytics slot")
            slots.append((slot["type"], slot["ref"]))
        if len({kind for kind, _ in slots}) != len(slots):
            raise MachineReconciliationError(f"side {side} repeats an analytics role in one row")
        key = (row["account"], tuple(slots), row["currency_ref"])
        if key in result:
            raise MachineReconciliationError(f"side {side} repeats a row key")
        result[key] = (
            _decimal(row["balance_debit"], f"side {side} balance_debit"),
            _decimal(row["balance_credit"], f"side {side} balance_credit"),
        )
    return result


def compare_rows(
    rows_a: list[Any],
    rows_b: list[Any],
    *,
    allowed_accounts: frozenset[str] | None = None,
    allowed_roles: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Exact comparison; any missing key, extra key or one-cent difference fails the whole case."""
    map_a = _row_map(rows_a, "A", allowed_accounts, allowed_roles)
    map_b = _row_map(rows_b, "B", allowed_accounts, allowed_roles)
    if set(map_a) != set(map_b):
        raise MachineReconciliationError("the two sides do not cover the same row keys")
    for key, value in map_a.items():
        if value != map_b[key]:
            raise MachineReconciliationError("the two sides differ on at least one row")
    return {
        "row_count": len(map_a),
        "total_debit": str(sum((v[0] for v in map_a.values()), Decimal(0))),
        "total_credit": str(sum((v[1] for v in map_a.values()), Decimal(0))),
    }


def verify_case_artifacts(
    case: dict[str, Any],
    artifacts_root: Path,
    *,
    allowed_accounts: frozenset[str] | None = None,
    allowed_roles: frozenset[str] | None = None,
) -> dict[str, Any]:
    reference = case.get("native_report_ref")
    if not isinstance(reference, str) or not reference.startswith(MACHINE_REFERENCE_PREFIX):
        raise EvidenceBasisError("machine case reference must use the machine-artifact: form")
    relative = Path(reference[len(MACHINE_REFERENCE_PREFIX) :])
    if relative.is_absolute() or ".." in relative.parts:
        raise MachineReconciliationError("machine artifact reference must stay inside the artifact root")
    root = Path(artifacts_root).resolve()
    directory = (root / relative).resolve()
    if root not in directory.parents:
        raise MachineReconciliationError("machine artifact reference escapes the artifact root")
    rows = {}
    for side, method, key in (("A", MACHINE_METHOD_A, "run_record_a"), ("B", MACHINE_METHOD_B, "run_record_b")):
        record = case[key]
        rows[side] = _read_artifact(
            directory / ARTIFACT_FILES[side],
            expected_sha256=record["artifact_sha256"],
            run_id=record["run_id"],
            method=method,
            side=side,
            as_of=case["as_of"],
            parameters=record["parameters"],
        )
    return compare_rows(rows["A"], rows["B"], allowed_accounts=allowed_accounts, allowed_roles=allowed_roles)


def verify_all(
    evidence: dict[str, Any], *, artifacts_root: Path, plans_dir: Path, scope_sha256: str, mapping: dict[str, Any]
) -> dict[str, Any]:
    accounts, roles = authorized_accounts(mapping), authorized_roles(mapping)
    cases = evidence["native_reconciliation_cases"]
    authority = verify_plan_authority(
        cases[0]["authorized_by"], scope_sha256=scope_sha256, plans_dir=plans_dir
    )
    summaries = [
        verify_case_artifacts(case, artifacts_root, allowed_accounts=accounts, allowed_roles=roles) for case in cases
    ]
    return {"authority": authority, "cases": len(cases), "row_counts": [s["row_count"] for s in summaries]}
