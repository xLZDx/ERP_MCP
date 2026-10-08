"""Doc lint: status documents must not contradict the evidence matrix.

Not product evidence. It only keeps the gate ledger, status and notes from drifting apart
(GPT-PM MAJOR-05: the ledger kept saying SQL was never executed after integration tests ran).
"""
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs" / "phase2"
STALE = ("never executed", "SQL never executed")


def test_evidence_matrix_has_required_columns_and_a_postgres_row():
    text = (DOCS / "EVIDENCE_MATRIX.md").read_text(encoding="utf-8")
    header = next(line for line in text.splitlines() if line.startswith("| Date"))
    for column in ("Tree / SHA", "Command", "Result", "Status", "Superseded by"):
        assert column in header
    assert "-m integration" in text and "20 passed" in text


def test_task_ledger_does_not_claim_sql_was_never_executed():
    ledger = (DOCS / "TASK_LEDGER.md").read_text(encoding="utf-8")
    assert not any(phrase in ledger for phrase in STALE)
    assert "EVIDENCE_MATRIX.md" in ledger


def test_old_g1_notes_carry_a_superseded_banner():
    for name in ("G1_IMPLEMENTATION_NOTE_2026-10-08.md", "G1_OPERATOR_BACKLOG.md"):
        text = (DOCS / name).read_text(encoding="utf-8")
        assert "SUPERSEDED 2026-10-08" in text and "EVIDENCE_MATRIX.md" in text, name
