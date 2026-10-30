"""Focused checks for formal requirement mapping in the derived SPEC/L0 bundle."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "scripts" / "phase2" / "build_spec_bundle.py"


def test_canonical_catalog_deduplicates_narrative_rows_and_keeps_related_reqs_nonformal(monkeypatch):
    spec = importlib.util.spec_from_file_location("build_spec_bundle_under_test", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "DOCS", ROOT / "docs" / "phase2")
    monkeypatch.setattr(module, "save", lambda _rel, _value: None)

    requirements, stories, cases = module.make_data()

    assert (len(requirements), len(stories), len(cases)) == (28, 48, 144)
    assert len({story["id"] for story in stories}) == 48
    assert len({case["id"] for case in cases}) == 144

    story = next(item for item in stories if item["id"] == "R2-US-001")
    assert story["requirements"] == ["R2-REQ-01"]

    story_cases = [case for case in cases if case["story"] == "R2-US-001"]
    assert len(story_cases) == 3
    assert all(case["requirements"] == ["R2-REQ-01"] for case in story_cases)
    assert all(case["actual_status"] == "NOT_RUN" for case in cases)


def test_tc002_register_keeps_r1_items_visible_and_unresolved():
    backlog = (ROOT / "docs" / "PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md").read_text(
        encoding="utf-8"
    )
    r1_marked_items = {
        match.group(1)
        for line in backlog.splitlines()
        if (match := re.match(r"^([A-Z]\d+)\s+\(([^)]*)\):", line))
        and re.search(r"\bR1\b", match.group(2))
    }
    assert {"B2", "B3", "M2", "M5"}.issubset(r1_marked_items)

    ledger = (ROOT / "docs" / "phase2" / "TASK_LEDGER.md").read_text(encoding="utf-8")
    heading = "## S0 TC002 — R1 defect visibility and disposition"
    assert heading in ledger
    section = ledger.split(heading, 1)[1].split("\n## ", 1)[0]
    rows = {
        item: [cell.strip().lower() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("| ")
        for item in r1_marked_items
        if line.startswith(f"| {item} —")
    }

    # This guards only the R1 labels present in this backlog, not defects that
    # have not been discovered or marked there.
    assert r1_marked_items.issubset(rows)
    for cells in rows.values():
        _item, _evidence, disposition, next_action = cells
        # A row must keep an unresolved / verification-pending disposition and
        # a Codex closure action; a resolved or R2-reclassified row is not enough.
        assert any(marker in disposition for marker in (
            "potential r1", "unverified", "must remain visible", "remain unverified",
        ))
        assert "codex" in next_action
        assert not any(marker in disposition for marker in (
            "resolved", "closed", "shifted to r2", "moved to r2", "r2-only", "r2 only",
        ))
