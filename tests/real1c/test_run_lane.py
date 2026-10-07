"""Offline tests of the lane orchestrator: gate order, fail-closed exits and the result builders (no live 1C)."""

from __future__ import annotations

import asyncio
import copy
import csv
import json
from pathlib import Path

import pytest

from scripts.real1c import run_lane as rl
from scripts.real1c.manifest import FingerprintDrift
from scripts.real1c.schema import validate_case_result
from scripts.real1c.stories import evaluate_story
from tests.real1c.test_stories import BASE, _ev

H1, H2, M = "1" * 64, "2" * 64, "3" * 64
PRIVATE_AMOUNT = "123456.78"


def _fp(content: str = H1, meta: str = M) -> dict:
    return {"content_fingerprint_sha256": content, "metadata_fingerprint": meta, "table_count": 3, "total_rows": 9}


def _manifest() -> dict:
    return {"manifest_sha256": H2, "metadata_fingerprint": M, "pre_run_fingerprint": {"sha256": H1, "table_count": 3},
            "golden": {"sha256": H1, "size_bytes": 10, "source_date": "2026-09-15"}, "chain": ["a", "b", "c"],
            "platform_version": "8.3", "configuration": {"name": "n", "version": "v"}, "odata_identity_sha256": H1,
            "organisations": [{"ref_sha256": H1}]}


class FakeProxy:
    def reset(self) -> None:
        pass


class FakeLane:
    opened = 0
    real_company = "real-company-id"

    @classmethod
    async def open(cls):
        cls.opened += 1
        return cls()

    def proxy(self, _src):
        return FakeProxy()

    async def call(self, *_a, **_k):
        return {"is_error": False, "payload": {}, "audit": None}

    async def close(self) -> None:
        pass


class Env:
    """Patched environment for main_async; every dependency that touches D:\\, COM or the stack is replaced."""

    def __init__(self, monkeypatch, tmp_path: Path, *, verdict: str = "READY_FOR_SCENARIO_EXECUTION", dirty: str = "",
                 fingerprints: tuple[dict, ...] = (_fp(), _fp()), sweep_hit: bool = False, with_amounts: bool = False):
        self.assembled = 0
        self.collected = 0
        readiness = tmp_path / "readiness.json"
        readiness.write_text(json.dumps({"verdict": verdict}), encoding="utf-8")
        (tmp_path / "reports").mkdir(exist_ok=True)
        prints = list(fingerprints)

        class FakeOracle:
            def fingerprint(self_inner):
                return prints.pop(0)

        def fake_git(*args: str) -> str:
            return "a" * 40 if args[0] == "rev-parse" else dirty

        async def fake_collect(*_a, **_k):
            self.collected += 1
            ev = _ev()
            ev["proxy_acc"] = {"methods": ["GET"], "by_method": {"GET": 3}, "refused": {}}
            ev["secret"] = {"sources_scanned": ["x"], "hits": []}
            return ev

        def fake_assemble(ev, catalog, _builder):
            self.assembled += 1
            results = [evaluate_story(s, ev, {**BASE, "finished_at": rl._now()}) for s in catalog.stories]
            if with_amounts:  # a comparison case that carries exact private figures
                results.append(_builder.make("NR", "NR-02", "Native reconciliation: Account 216.1 ending balance", "EVIDENCE_REQUIRED",
                                               "com_agrees_native_ui_report_required", ["NATIVE_COM_QUERY"],
                                               [{"probe": "COM", "outcome": "AGREES", "detail": f"observed {PRIVATE_AMOUNT} candidate -4321.09"}],
                                               [], "ONAT", cls="EV"))
                results[-1]["queries"] = [{"text": "ВЫБРАТЬ 1 ГДЕ Т.Сумма = 987.65"}]
            return results

        monkeypatch.setattr(rl, "READINESS", readiness)
        monkeypatch.setattr(rl, "OUT", tmp_path / "out")
        monkeypatch.setattr(rl, "OUT_DEV", tmp_path / "out_dev")
        monkeypatch.setattr(rl, "PRIVATE_DIR", tmp_path / "private")
        monkeypatch.setattr(rl, "ROOT", tmp_path)
        monkeypatch.setattr(rl, "_git", fake_git)
        monkeypatch.setattr(rl, "verify_reference_manifest", lambda _p: _manifest())
        monkeypatch.setattr(rl, "Oracle", FakeOracle)
        monkeypatch.setattr(rl, "Lane", FakeLane)
        monkeypatch.setattr(rl, "_secret_values", lambda _lane: ["literal-secret-value"])
        monkeypatch.setattr(rl, "collect", fake_collect)
        monkeypatch.setattr(rl, "assemble", fake_assemble)
        if sweep_hit:
            real = rl.sweep_outputs
            monkeypatch.setattr(rl, "sweep_outputs", lambda texts, secrets: real(texts, secrets) or [{"where": "x", "kind": "t"}]
                                if "case_results.json" in texts and "REAL_1C_818HA_L2_REPORT.html" in texts
                                else real(texts, secrets))
        FakeLane.opened = 0
        self.tmp = tmp_path

    def run(self, dev: bool = False) -> int:
        return asyncio.run(rl.main_async(dev))


def test_happy_path_writes_all_outputs(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path)
    assert env.run() == 0
    names = {p.name for p in (tmp_path / "out").iterdir()}
    assert {"case_results.json", "case_results.csv", "summary.json", "REAL_1C_818HA_L2_REPORT.html",
            "REAL_1C_818HA_L2_REPORT.ru.html", "REAL_1C_818HA_L2_TEST_DETAILS.html",
            "REAL_1C_818HA_L2_TEST_DETAILS.ru.html"} <= names
    assert (tmp_path / "reports" / "FUNCTIONAL_TESTER_REAL-1C-818HA.md").read_text(encoding="utf-8").count(
        "REAL 1C 818HA L2 ACCEPTANCE") == 1
    results = json.loads((tmp_path / "out" / "case_results.json").read_text(encoding="utf-8"))
    assert len(results) == 130 and not [e for r in results for e in validate_case_result(r)]


def test_public_outputs_carry_no_exact_figures_but_the_private_bundle_does(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path, with_amounts=True)
    assert env.run() == 0
    public = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "out").iterdir())
    for canary in (PRIVATE_AMOUNT, "4321.09", "987.65"):
        assert canary not in public and canary.replace(".", ",") not in public
    assert "<amount>" in public
    private = next((tmp_path / "private").iterdir()).read_text(encoding="utf-8")
    assert PRIVATE_AMOUNT in private and "4321.09" in private


def test_a_leaking_public_view_aborts_the_write(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path, with_amounts=True)
    monkeypatch.setattr(rl, "public_copy", lambda r: r)  # simulate a sanitizer regression
    with pytest.raises(rl.GateFailure, match="nothing written"):
        env.run()
    assert not (tmp_path / "out").exists()


def test_readiness_not_ready_stops_before_oracle_and_lane(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path, verdict="BLOCKED")
    with pytest.raises(rl.GateFailure, match="readiness"):
        env.run()
    assert FakeLane.opened == 0 and env.collected == 0 and env.assembled == 0


def test_dirty_lane_tree_is_refused_in_gate_mode_but_not_dev(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path, dirty=" M scripts/real1c/stories.py")
    with pytest.raises(rl.GateFailure, match="committed"):
        env.run()
    assert FakeLane.opened == 0
    env2 = Env(monkeypatch, tmp_path, dirty=" M x")
    assert env2.run(dev=True) == 0
    assert (tmp_path / "out_dev" / "summary.json").exists() and not (tmp_path / "out").exists()
    assert json.loads((tmp_path / "out_dev" / "summary.json").read_text(encoding="utf-8"))["mode"] == "DEV"


def test_pre_run_fingerprint_must_equal_manifest(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path, fingerprints=(_fp(content="9" * 64), _fp()))
    with pytest.raises(FingerprintDrift):
        env.run()
    assert FakeLane.opened == 0 and env.assembled == 0


def test_pre_run_metadata_fingerprint_must_equal_manifest(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path, fingerprints=(_fp(meta="9" * 64), _fp()))
    with pytest.raises(rl.GateFailure, match="metadata"):
        env.run()
    assert FakeLane.opened == 0


def test_post_run_drift_fails_before_any_story_is_evaluated(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path, fingerprints=(_fp(), _fp(content="9" * 64)))
    with pytest.raises(FingerprintDrift):
        env.run()
    assert env.collected == 1 and env.assembled == 0
    assert not (tmp_path / "out").exists()


def test_secret_hit_in_outputs_writes_nothing(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path, sweep_hit=True)
    with pytest.raises(rl.GateFailure, match="nothing written"):
        env.run()
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "reports" / "FUNCTIONAL_TESTER_REAL-1C-818HA.md").exists()


def test_write_seen_upstream_returns_exit_3_but_keeps_the_evidence(monkeypatch, tmp_path):
    env = Env(monkeypatch, tmp_path)
    real_collect = rl.collect

    async def collect_with_write(*a, **k):
        ev = await real_collect(*a, **k)
        ev["proxy_acc"] = {"methods": ["GET", "POST"], "by_method": {"GET": 1, "POST": 1}, "refused": {}}
        return ev

    monkeypatch.setattr(rl, "collect", collect_with_write)
    assert env.run() == 3
    assert (tmp_path / "out" / "case_results.json").exists()


def test_load_ev_without_dev_is_rejected(monkeypatch, tmp_path):
    Env(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["run_lane", "--load-ev", "x.pkl"])
    with pytest.raises(SystemExit):
        rl.main()


def test_main_returns_2_on_gate_failure(monkeypatch, tmp_path):
    Env(monkeypatch, tmp_path, verdict="BLOCKED")
    monkeypatch.setattr("sys.argv", ["run_lane"])
    assert rl.main() == 2


# ------------------------------------------------------------------------------------------------ builders
def _builder() -> rl.Builder:
    return rl.Builder("a" * 40, "b" * 64)


def _assert_valid_no_pass(results: list[dict]) -> None:
    assert not [e for r in results for e in validate_case_result(r)]
    assert all(r["disposition"] != "PASS" for r in results)


def test_nr_results_never_pass_and_map_verdicts():
    native = {"NR-01": {"assertion": {}, "observed": {}, "verdict": "AGREES"},
              "NR-02": {"assertion": {}, "observed": {}, "verdict": "DISAGREES"},
              "NR-03": {"assertion": {}, "observed": {}, "verdict": "NOT_COMPUTABLE"}}
    results = rl.nr_results(_builder(), native, {})
    assert [r["disposition"] for r in results] == ["EVIDENCE_REQUIRED", "FINDING", "INCONCLUSIVE"]
    _assert_valid_no_pass(results)
    assert results[0]["owner_action"] and "owner_action" not in results[1]


def _inv_row(index: int, *, found=True, amount=True, date=True) -> dict:
    return {"index": index, "number_sha8": f"{index:08x}", "found": found, "documents": int(found), "amount_match": amount if found else False,
            "date_match": date if found else None, "pdf_date_in_july_registration": False}


@pytest.mark.parametrize(("row", "result_text", "want"), [
    (_inv_row(1), "total and VAT match", "EVIDENCE_REQUIRED"),
    (_inv_row(1, found=False), "payment found but receipt not found", "EVIDENCE_REQUIRED"),
    (_inv_row(1), "payment found but receipt not found", "FINDING"),
    (_inv_row(1, found=False), "total and VAT match", "FINDING"),
    (_inv_row(1, amount=False), "total and VAT match", "FINDING"),
    (_inv_row(1, date=False), "total and VAT match", "FINDING"),
])
def test_inv_results_table(monkeypatch, tmp_path, row, result_text, want):
    path = tmp_path / "inv.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, ["invoice_no", "supplier", "pdf_date", "onec_registration_date", "total_mdl", "result", "scenario"])
        w.writeheader()
        w.writerow({"invoice_no": "X1", "supplier": "S", "pdf_date": "2026-08-03", "onec_registration_date": "2026-08-03",
                    "total_mdl": "10.00", "result": result_text, "scenario": "RO-21"})
    monkeypatch.setattr(rl, "INVOICES_CSV", path)
    results = rl.inv_results(_builder(), [row])
    assert results[0]["disposition"] == want
    _assert_valid_no_pass(results)
    assert "S" not in json.dumps(results[0]["observations"])  # supplier names never reach the results


def _rules_csv(tmp_path: Path) -> Path:
    path = tmp_path / "rules.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, ["source_row", "account", "analytic_account", "name", "type", "financial_statement_element",
                                "test_operations", "required_documents", "findings"])
        w.writeheader()
        w.writerow({"source_row": "1", "account": "211", "analytic_account": "211.1", "required_documents": "X"})
        w.writerow({"source_row": "2", "account": "311", "analytic_account": "", "required_documents": ""})
        w.writerow({"source_row": "3", "account": "", "analytic_account": "", "required_documents": ""})
    return path


def test_rule_results_split_by_required_documents_and_never_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(rl, "RULES_CSV", _rules_csv(tmp_path))
    ev = _ev()
    app = {"211.1": {"exists_in_chart": True, "august_posting_rows": 4}, "311": {"exists_in_chart": False, "august_posting_rows": 0}}
    results = rl.rule_results(_builder(), ev, app)
    assert [r["disposition"] for r in results] == ["EVIDENCE_REQUIRED", "CAPABILITY_UNSUPPORTED", "CAPABILITY_UNSUPPORTED"]
    assert [r["case_id"] for r in results] == ["RULE-001", "RULE-002", "RULE-003"]
    _assert_valid_no_pass(results)
    ev["disc"]["surface"] = "month close rule pack proposal"
    assert rl.rule_results(_builder(), ev, app)[1]["disposition"] == "FINDING"


@pytest.mark.parametrize(("mutate", "equal", "write_seen"), [
    (lambda pre, post, acc: None, True, False),
    (lambda pre, post, acc: post.update(content_fingerprint_sha256="9" * 64), False, False),
    (lambda pre, post, acc: post.update(metadata_fingerprint="9" * 64), False, False),
    (lambda pre, post, acc: acc.update(methods=["GET", "POST"]), True, True),
    (lambda pre, post, acc: acc.update(refused={"POST": 1}), True, True),
])
def test_zero_write_combines_fingerprints_and_methods(mutate, equal, write_seen):
    pre, post = _fp(), _fp()
    acc = {"methods": ["GET", "HEAD"], "by_method": {"GET": 1}, "refused": {}}
    mutate(pre, post, acc)
    z = rl.zero_write(pre, post, {"proxy_acc": acc})
    assert z["fingerprint_equal"] is equal and z["upstream_write_seen"] is write_seen


def test_no_builder_or_story_can_pass_outside_class_rr():
    ev = _ev()
    ev["related"] = {}
    results = [evaluate_story(s, ev, BASE) for s in rl.verify_frozen(rl.CATALOG).stories]
    results += rl.nr_results(_builder(), {"NR-01": {"assertion": {}, "observed": {}, "verdict": "AGREES"}}, {})
    assert all(r["catalogue_class"] == "RR" for r in results if r["disposition"] == "PASS")


def test_sweep_of_a_deep_copy_does_not_mutate_input():
    texts = {"a": "x"}
    snapshot = copy.deepcopy(texts)
    rl.sweep_outputs(texts, ["secret-value"])
    assert texts == snapshot
