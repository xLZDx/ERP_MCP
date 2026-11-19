"""Check structural coverage in the S11 invariant-to-scenario matrix only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = Path("docs/phase2/S11_TEST_DESIGN_PACKAGE_2026-10-12.md")
EXPECTED_INVARIANTS = tuple(f"I{number}" for number in range(1, 16))
ACTIVE_SCENARIOS = frozenset(set(range(1, 48)) - {8})
INVARIANT_ID = re.compile(r"^I([0-9]+)\b")
SCENARIO_ID = re.compile(r"\bE([0-9]+)\b")
GATE_MAPPING_MARKERS = ("E46", "E47", "map to gates and CT14, not to invariants")
MATRIX_HEADING = "## A. Invariant -> scenarios -> failing assertion at the enforcement boundary -> data-level negative control"
LIMITATION = (
    "Structural table coverage does not prove that any boundary assertion passed; "
    "runtime boundary results remain NOT_RUN until exact-head evidence is reviewed."
)


def _split_row(line: str) -> list[str]:
    if not line.startswith("|") or not line.endswith("|"):
        return []
    return [cell.strip() for cell in line.split("|")[1:-1]]


def inspect_matrix(text: str) -> dict[str, Any]:
    findings: list[str] = []
    invariant_rows: list[tuple[str, str, str]] = []
    document_lines = text.splitlines()
    try:
        section_start = document_lines.index(MATRIX_HEADING) + 1
    except ValueError:
        section_start = len(document_lines)
        findings.append("authoritative invariant matrix section is missing")
    section = []
    for line in document_lines[section_start:]:
        if line.startswith("## "):
            break
        section.append(line)

    for line_number, line in enumerate(section, start=section_start + 1):
        cells = _split_row(line)
        if not cells or cells[0] == "Inv" or not cells[0].startswith("I"):
            continue
        match = INVARIANT_ID.match(cells[0])
        if not match:
            findings.append(f"line {line_number}: malformed invariant identifier")
            continue
        if len(cells) != 5:
            findings.append(f"line {line_number}: {match.group(0)} must have five table columns")
            continue
        invariant_rows.append((match.group(0), cells[1], cells[2]))

    observed_ids = [row[0] for row in invariant_rows]
    duplicates = sorted({identifier for identifier in observed_ids if observed_ids.count(identifier) > 1})
    if duplicates:
        findings.append("duplicate invariant rows: " + ", ".join(duplicates))
    missing_ids = sorted(set(EXPECTED_INVARIANTS) - set(observed_ids), key=lambda value: int(value[1:]))
    unexpected_ids = sorted(set(observed_ids) - set(EXPECTED_INVARIANTS))
    if missing_ids:
        findings.append("missing invariant rows: " + ", ".join(missing_ids))
    if unexpected_ids:
        findings.append("unexpected invariant rows: " + ", ".join(unexpected_ids))

    mapped_scenarios: set[int] = set()
    for identifier, scenario_cell, assertion_cell in invariant_rows:
        matches = [int(value) for value in SCENARIO_ID.findall(scenario_cell)]
        if not matches:
            findings.append(f"{identifier}: no scenario IDs are mapped")
        if len(matches) != len(set(matches)):
            findings.append(f"{identifier}: duplicate scenario ID in mapping")
        invalid = sorted(set(matches) - ACTIVE_SCENARIOS)
        if invalid:
            findings.append(f"{identifier}: invalid or reserved scenario IDs: "
                             + ", ".join(f"E{value}" for value in invalid))
        if not assertion_cell.strip():
            findings.append(f"{identifier}: enforcement-boundary assertion is empty")
        mapped_scenarios.update(matches)

    special_gate_mapping_found = any(
        all(marker in line for marker in GATE_MAPPING_MARKERS)
        for line in section
    )
    if not special_gate_mapping_found:
        findings.append("E46 and E47 must be explicitly mapped to gate/CT14 outcomes outside invariants")
    elif 46 not in ACTIVE_SCENARIOS or 47 not in ACTIVE_SCENARIOS:
        findings.append("internal active-scenario definition is inconsistent")
    else:
        mapped_scenarios.update({46, 47})

    missing_scenarios = sorted(ACTIVE_SCENARIOS - mapped_scenarios)
    if missing_scenarios:
        findings.append("active scenarios are unmapped: "
                         + ", ".join(f"E{value}" for value in missing_scenarios))

    return {
        "schema_version": 1,
        "assessment": "STRUCTURAL_COVERAGE_ONLY",
        "structural_status": "COMPLETE" if not findings else "INCOMPLETE",
        "invariant_rows": len(invariant_rows),
        "invariant_ids": observed_ids,
        "active_scenarios_expected": len(ACTIVE_SCENARIOS),
        "active_scenarios_mapped": len(mapped_scenarios & ACTIVE_SCENARIOS),
        "runtime_boundary_results": "NOT_RUN",
        "gate_status": "UNCHANGED",
        "production_authorization": "NONE",
        "limitations": [LIMITATION],
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=Path, default=REPO_ROOT / MATRIX_PATH,
                        help="S11 invariant-to-scenario markdown source")
    args = parser.parse_args()
    document = args.document.resolve()
    try:
        content = document.read_bytes()
        result = inspect_matrix(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        result = {
            "schema_version": 1,
            "assessment": "STRUCTURAL_COVERAGE_ONLY",
            "structural_status": "INCOMPLETE",
            "runtime_boundary_results": "NOT_RUN",
            "gate_status": "UNCHANGED",
            "production_authorization": "NONE",
            "limitations": [LIMITATION],
            "findings": [f"cannot read matrix document: {exc.__class__.__name__}"],
        }
        content = b""
    result["matrix_document"] = str(document)
    result["matrix_sha256"] = hashlib.sha256(content).hexdigest() if content else None
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["structural_status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
