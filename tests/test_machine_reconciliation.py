"""Machine two-source verifier: exact comparison, artifact integrity and plan authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.real1c import machine_reconciliation as mr

PLAN_ID = "erp_mcp-test-2026-10-08T00-00-00-000Z-424242"
PLAN_HASH = "a" * 64
SCOPE = "b" * 64
AUTHORITY = f"ROSETTA_PLAN:{PLAN_ID}:{PLAN_HASH}"


def _row(ref="cp-1", debit="100.00", credit="0.00", currency="MDL"):
    return {
        "account": "521.1",
        "analytics": [{"type": "counterparty", "ref": ref}, {"type": "contract", "ref": "k-1"}],
        "currency_ref": currency,
        "balance_debit": debit,
        "balance_credit": credit,
    }


def test_identical_rows_match_exactly():
    summary = mr.compare_rows([_row(), _row("cp-2", "5.50")], [_row("cp-2", "5.50"), _row()])
    assert summary == {"row_count": 2, "total_debit": "105.50", "total_credit": "0.00"}


def test_one_cent_difference_fails():
    with pytest.raises(mr.MachineReconciliationError):
        mr.compare_rows([_row(debit="100.00")], [_row(debit="100.01")])


def test_sub_cent_value_is_not_rounded_away():
    with pytest.raises(mr.MachineReconciliationError, match="more than two decimals"):
        mr.compare_rows([_row(debit="100.004")], [_row(debit="100.00")])


def test_float_values_are_refused():
    with pytest.raises(mr.MachineReconciliationError):
        mr.compare_rows([_row(debit=100.0)], [_row(debit="100.00")])


def test_missing_extra_and_currency_mismatched_keys_fail():
    with pytest.raises(mr.MachineReconciliationError):
        mr.compare_rows([_row(), _row("cp-2")], [_row()])
    with pytest.raises(mr.MachineReconciliationError):
        mr.compare_rows([_row(currency="MDL")], [_row(currency="EUR")])


def test_duplicate_key_on_one_side_fails():
    with pytest.raises(mr.MachineReconciliationError, match="repeats"):
        mr.compare_rows([_row(), _row()], [_row()])


PARAMS = {"as_of": "2025-01-31T23:59:59+00:00", "account": "521.1", "source_id": "src-1", "company_id": "co-1"}
ACCOUNTS = frozenset({"521.1"})
ROLES = frozenset({"counterparty", "contract"})


def _write_side(directory: Path, side: str, method: str, **payload_changes):
    payload = {"run_id": f"run-{side.lower()}", "method": method, "side": side,
               "as_of": "2025-01-31T23:59:59+00:00", "truncated": False, "context": dict(PARAMS), "rows": [_row()]}
    payload.update(payload_changes)
    raw = json.dumps(payload).encode()
    (directory / mr.ARTIFACT_FILES[side]).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _case(tmp_path: Path, **side_b_changes):
    directory = tmp_path / "case-1"
    directory.mkdir()
    digest_a = _write_side(directory, "A", mr.MACHINE_METHOD_A)
    digest_b = _write_side(directory, "B", mr.MACHINE_METHOD_B, **side_b_changes)
    return {
        "as_of": "2025-01-31T23:59:59+00:00",
        "native_report_ref": "machine-artifact:case-1",
        "run_record_a": {"run_id": "run-a", "artifact_sha256": digest_a, "parameters": dict(PARAMS)},
        "run_record_b": {"run_id": "run-b", "artifact_sha256": digest_b, "parameters": dict(PARAMS)},
    }


def test_case_artifacts_verify(tmp_path):
    assert mr.verify_case_artifacts(_case(tmp_path), tmp_path)["row_count"] == 1


def test_tampered_artifact_digest_fails(tmp_path):
    case = _case(tmp_path)
    case["run_record_b"]["artifact_sha256"] = "0" * 64
    with pytest.raises(mr.MachineReconciliationError, match="digest"):
        mr.verify_case_artifacts(case, tmp_path)


def test_copied_artifact_with_foreign_run_id_fails(tmp_path):
    case = _case(tmp_path, run_id="run-a")  # side B file claims side A's run id
    with pytest.raises(mr.MachineReconciliationError, match="embed"):
        mr.verify_case_artifacts(case, tmp_path)


def test_truncated_and_empty_artifacts_fail(tmp_path):
    with pytest.raises(mr.MachineReconciliationError, match="truncated"):
        mr.verify_case_artifacts(_case(tmp_path, truncated=True), tmp_path)
    other = tmp_path / "second"
    other.mkdir()
    with pytest.raises(mr.MachineReconciliationError, match="no rows"):
        mr.verify_case_artifacts(_case(other, rows=[]), other)


def test_reference_cannot_escape_the_artifact_root(tmp_path):
    case = _case(tmp_path)
    case["native_report_ref"] = "machine-artifact:../outside"
    with pytest.raises(mr.MachineReconciliationError):
        mr.verify_case_artifacts(case, tmp_path)


def _plan(tmp_path: Path, **changes) -> Path:
    plan = {
        "plan_id": PLAN_ID,
        "status": "in-progress",
        "plan_hash": PLAN_HASH,
        "scope": f"machine evidence scope {SCOPE} operator GO",
        "approval": {
            "approved_by": "GPT-PM",
            "verdict": "APPROVE",
            "correlated": True,
            "approved_plan_hash": PLAN_HASH,
        },
    }
    plan.update(changes)
    (tmp_path / f"{PLAN_ID}.json").write_text(json.dumps(plan), encoding="utf-8")
    return tmp_path


def test_plan_authority_accepts_the_approved_current_plan(tmp_path):
    assert mr.verify_plan_authority(AUTHORITY, scope_sha256=SCOPE, plans_dir=_plan(tmp_path))["plan_id"] == PLAN_ID


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "draft"},
        {"plan_hash": "c" * 64},
        {"scope": "no scope hash here"},
        {"approval": {"approved_by": "GPT-PM", "verdict": "REJECT", "correlated": True,
                      "approved_plan_hash": PLAN_HASH}},
        {"approval": {"approved_by": "GPT-PM", "verdict": "APPROVE", "correlated": False,
                      "approved_plan_hash": PLAN_HASH}},
        {"approval": {"approved_by": "me", "verdict": "APPROVE", "correlated": True,
                      "approved_plan_hash": PLAN_HASH}},
    ],
)
def test_plan_authority_refusals(tmp_path, changes):
    with pytest.raises(mr.MachineReconciliationError):
        mr.verify_plan_authority(AUTHORITY, scope_sha256=SCOPE, plans_dir=_plan(tmp_path, **changes))


def test_unknown_plan_is_refused(tmp_path):
    with pytest.raises(mr.MachineReconciliationError, match="exactly once"):
        mr.verify_plan_authority(AUTHORITY, scope_sha256=SCOPE, plans_dir=tmp_path)


def test_artifact_context_must_equal_the_run_record_parameters(tmp_path):
    foreign = dict(PARAMS, company_id="co-2")
    with pytest.raises(mr.MachineReconciliationError, match="parameters"):
        mr.verify_case_artifacts(_case(tmp_path, context=foreign), tmp_path)


def test_currency_must_be_text_and_missing_is_only_the_empty_string():
    for bad in (None, False, 0):
        with pytest.raises(mr.MachineReconciliationError, match="not text"):
            mr.compare_rows([_row(currency=None)], [_row(currency=bad)])
    assert mr.compare_rows([_row(currency="")], [_row(currency="")])["row_count"] == 1


def test_analytics_slots_are_a_closed_schema():
    extra = _row()
    extra["analytics"][0]["role"] = "other"
    with pytest.raises(mr.MachineReconciliationError, match="invalid analytics slot"):
        mr.compare_rows([extra], [extra])
    repeated = _row()
    repeated["analytics"].append({"type": "counterparty", "ref": "cp-9"})
    with pytest.raises(mr.MachineReconciliationError, match="repeats an analytics role"):
        mr.compare_rows([repeated], [repeated])


def test_rows_must_stay_inside_the_authorized_accounts_and_roles():
    foreign_account = _row()
    foreign_account["account"] = "521.2"
    with pytest.raises(mr.MachineReconciliationError, match="authorized accounts"):
        mr.compare_rows([foreign_account], [foreign_account], allowed_accounts=ACCOUNTS, allowed_roles=ROLES)
    employee = _row()
    employee["analytics"] = [{"type": "employee", "ref": "e-1"}]
    with pytest.raises(mr.MachineReconciliationError, match="invalid analytics slot"):
        mr.compare_rows([employee], [employee], allowed_accounts=ACCOUNTS, allowed_roles=ROLES)


@pytest.mark.parametrize("kept", ["counterparty", "contract"])
def test_rows_must_cover_the_complete_authorized_projection(kept):
    full = _row()
    reduced = _row()
    reduced["analytics"] = [slot for slot in reduced["analytics"] if slot["type"] == kept]
    for rows_a, rows_b in (([reduced], [reduced]), ([full], [reduced]), ([reduced], [full])):
        with pytest.raises(mr.MachineReconciliationError, match="authorized analytics projection"):
            mr.compare_rows(rows_a, rows_b, allowed_accounts=ACCOUNTS, allowed_roles=ROLES)
    assert mr.compare_rows([full], [full], allowed_accounts=ACCOUNTS, allowed_roles=ROLES)["row_count"] == 1


def test_credit_only_difference_and_debit_credit_swap_fail():
    with pytest.raises(mr.MachineReconciliationError, match="differ"):
        mr.compare_rows([_row(credit="0.00")], [_row(credit="1.00")])
    with pytest.raises(mr.MachineReconciliationError, match="differ"):
        mr.compare_rows([_row(debit="100.00", credit="5.00")], [_row(debit="5.00", credit="100.00")])


def test_plan_approver_must_be_exactly_gpt_pm(tmp_path):
    approval = {"approved_by": "NOT GPT-PM", "verdict": "APPROVE", "correlated": True, "approved_plan_hash": PLAN_HASH}
    with pytest.raises(mr.MachineReconciliationError, match="approved, correlated, current"):
        mr.verify_plan_authority(AUTHORITY, scope_sha256=SCOPE, plans_dir=_plan(tmp_path, approval=approval))


def test_malformed_plan_file_is_a_verification_error_not_a_crash(tmp_path):
    (tmp_path / f"{PLAN_ID}.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(mr.MachineReconciliationError, match="cannot be read as JSON"):
        mr.verify_plan_authority(AUTHORITY, scope_sha256=SCOPE, plans_dir=tmp_path)


MAPPING = {"accounts": [{"code": "521.1"}], "analytics": [{"role": "counterparty"}, {"role": "contract"}]}


def _ten_cases(tmp_path: Path, authority_for=lambda index: AUTHORITY):
    cases = []
    for index in range(1, 11):
        sub = tmp_path / f"c{index}"
        sub.mkdir()
        case = _case(sub)
        case["native_report_ref"] = f"machine-artifact:c{index}/case-1"
        case["authorized_by"] = authority_for(index)
        cases.append(case)
    return {"native_reconciliation_cases": cases}


def test_verify_all_accepts_ten_cases_with_one_approved_authority(tmp_path):
    evidence = _ten_cases(tmp_path)
    (tmp_path / "plans_ok").mkdir()
    plans = _plan(tmp_path / "plans_ok")
    result = mr.verify_all(evidence, artifacts_root=tmp_path, plans_dir=plans, scope_sha256=SCOPE, mapping=MAPPING)
    assert result["cases"] == 10 and result["row_counts"] == [1] * 10


def test_verify_all_refuses_a_case_citing_an_unapproved_plan(tmp_path):
    other = f"ROSETTA_PLAN:erp_mcp-test-2026-10-08T00-00-00-000Z-999999:{'d' * 64}"
    evidence = _ten_cases(tmp_path, lambda index: other if index == 7 else AUTHORITY)
    (tmp_path / "plans_ok").mkdir()
    with pytest.raises(mr.MachineReconciliationError, match="exactly once"):
        mr.verify_all(
            evidence, artifacts_root=tmp_path, plans_dir=_plan(tmp_path / "plans_ok"), scope_sha256=SCOPE,
            mapping=MAPPING,
        )


def test_verify_all_refuses_empty_and_short_case_lists(tmp_path):
    (tmp_path / "plans_ok").mkdir()
    plans = _plan(tmp_path / "plans_ok")
    for cases in ([], _ten_cases(tmp_path)["native_reconciliation_cases"][:9]):
        with pytest.raises(mr.MachineReconciliationError, match="at least"):
            mr.verify_all(
                {"native_reconciliation_cases": cases}, artifacts_root=tmp_path, plans_dir=plans,
                scope_sha256=SCOPE, mapping=MAPPING,
            )
