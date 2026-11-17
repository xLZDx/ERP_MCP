"""Focused checks for formal requirement mapping in the derived SPEC/L0 bundle."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "scripts" / "phase2" / "build_spec_bundle.py"

_TC002_OPEN_MARKERS = (
    "potential r1",
    "unverified",
    "must remain visible",
    "remain unverified",
    "not reproduced",
    "cannot be resolved",
)
_TC002_TERMINAL_CLAIM = re.compile(
    r"\b(?:no\s+remaining\s+(?:r1\s+)?(?:defects?|issues?|items?|work)|"
    r"no\s+(?:r1\s+)?(?:defects?|issues?|items?)\s+remain|verified\s+fixed|"
    r"fixed(?:\s+and\s+accepted)?|resolved|closed|accepted|complete(?:d)?|approved|done|passed)\b"
)
_TC002_ACTION_IMPERATIVES = {
    "add",
    "ask",
    "check",
    "collect",
    "confirm",
    "coordinate",
    "create",
    "document",
    "implement",
    "inspect",
    "keep",
    "obtain",
    "prepare",
    "preserve",
    "reconcile",
    "reproduce",
    "request",
    "review",
    "run",
    "test",
    "update",
    "validate",
    "verify",
}
_TC002_EVIDENCE_PLACEHOLDERS = {
    "",
    "—",
    "-",
    "n/a",
    "na",
    "none",
    "unknown",
    "tbd",
    "todo",
    "placeholder",
    "no evidence",
    "not provided",
}
_TC002_NO_EVIDENCE_CLAIM = re.compile(
    r"\b(?:no\s+(?:[a-z-]+\s+){0,4}evidence|evidence\s+(?:is\s+)?not\s+(?:provided|available|collected|recorded)|"
    r"evidence\s+unavailable|not\s+provided)\b",
    re.IGNORECASE,
)
_TC002_NEGATED_PREFIX = re.compile(
    r"\b(?:(?:(?:do|does|did|will|shall|should|must|can|could|would)\s+not)(?:\s+\w+){0,3}|"
    r"(?:don't|doesn't|didn't|won't|shan't|shouldn't|mustn't|can't|couldn't|wouldn't|"
    r"isn't|aren't|wasn't|weren't|hasn't|haven't|hadn't)(?:\s+yet)?|"
    r"cannot(?:\s+be)?(?:\s+yet)?|not\s+yet|never|not)\s+$",
    re.IGNORECASE,
)
_TC002_CODEX_OWNER_PREFIX = re.compile(r"^\s*codex\s*(?:—|:|-)?\s+", re.IGNORECASE)
_TC002_SOURCE_REFERENCE = re.compile(
    r"(?<![\w./-])((?:[\w.-]+[\\/])*[\w.-]+\.(?:py|sql|json|ya?ml|md))(?![\w-]|\.[A-Za-z0-9])",
    re.IGNORECASE,
)
_TC002_SOURCE_MAP = {
    "B2": {
        "src/business_ai_gateway/compatibility.py": ("compatibility.py",),
        "db/migrations/014_capability_observation_boundary.sql": ("014_capability_observation_boundary.sql",),
    },
    "B3": {
        "db/migrations/006_semantic_profiles.sql": ("006_semantic_profiles.sql",),
        "src/business_ai_gateway/semantic.py": ("semantic.py",),
        "scripts/semantic_profiles.py": ("semantic_profiles.py",),
    },
    "M2": {
        "db/migrations/014_capability_observation_boundary.sql": (
            "014_capability_observation_boundary.sql",
            "record_capability_observation",
        ),
    },
    "M5": {
        "src/business_ai_gateway/external_evidence.py": ("external_evidence.py",),
        "src/business_ai_gateway/invoice_evidence.py": ("invoice_evidence.py",),
        "src/business_ai_gateway/evidence_store.py": ("evidence_store.py",),
        "src/business_ai_gateway/server.py": ("server.py",),
    },
    "M7": {
        "scripts/validate_prometheus.py": ("promtool",),
        "tests/phase2/test_alert_rules.py": ("alert_delivery",),
    },
    "M8": {
        "tests/test_admin_role_matrix.py": ("restricted-role matrix",),
        "db/migrations/011_admin_mutation_control.sql": ("least-privilege migration",),
    },
}
_TC002_M5_EXCLUDED_R2_SOURCES = {
    "src/business_ai_gateway/phase2/safe_parser.py": ("phase2/safe_parser.py",),
    "src/business_ai_gateway/phase2/artifact_vault.py": ("phase2/artifact_vault.py",),
}


def _tc002_resolved_repo_paths(reference: str, root: Path | None = None) -> set[str]:
    relative = Path(reference.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        return set()
    root = ROOT if root is None else root
    root_resolved = root.resolve()
    direct = root.joinpath(*relative.parts)
    if direct.exists() or direct.is_symlink():
        candidates = [direct]
    else:
        suffix = relative.as_posix()
        candidates = [
            path
            for path in root.rglob(relative.name)
            if path.is_file() and path.relative_to(root).as_posix().endswith(f"/{suffix}")
        ]
    resolved_paths: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            if resolved.is_file() and resolved.is_relative_to(root_resolved):
                resolved_paths.add(resolved.relative_to(root_resolved).as_posix())
        except (OSError, RuntimeError):
            continue
    return resolved_paths


def _tc002_reference_resolves(reference: str, root: Path | None = None) -> bool:
    return bool(_tc002_resolved_repo_paths(reference, root))


def _tc002_m5_r2_exclusion_is_explicit(alias: str, text: str) -> bool:
    lowered = text.lower()
    for match in re.finditer(r"\br2\b.{0,80}\bdo not establish r1 coverage\b", lowered):
        context = lowered[max(0, match.start() - 180) : match.end()]
        if alias.lower() in context:
            return True
    return False


def _tc002_has_valid_source_reference(item: str, text: str) -> bool:
    if item not in _TC002_SOURCE_MAP:
        return False
    allowed_map = _TC002_SOURCE_MAP[item]
    allowed_paths = set(allowed_map)
    lowered = text.lower()
    mentioned_allowed_paths: set[str] = set()
    for path, aliases in allowed_map.items():
        if path not in _tc002_resolved_repo_paths(path):
            return False
        if path.lower() in lowered or any(alias.lower() in lowered for alias in aliases):
            mentioned_allowed_paths.add(path)
    if not mentioned_allowed_paths:
        return False

    file_references = _TC002_SOURCE_REFERENCE.findall(text)
    for reference in file_references:
        normalized = reference.replace("\\", "/").lower()
        mapped_paths = {
            path
            for path, aliases in allowed_map.items()
            if normalized == path.lower()
            or normalized == Path(path).name.lower()
            or any(normalized == alias.lower() for alias in aliases)
        }
        if mapped_paths:
            continue

        resolved = _tc002_resolved_repo_paths(reference)
        if resolved and resolved.issubset(allowed_paths):
            continue
        if item == "M5" and any(
            resolved == {path}
            and any(_tc002_m5_r2_exclusion_is_explicit(alias, text) for alias in aliases)
            for path, aliases in _TC002_M5_EXCLUDED_R2_SOURCES.items()
        ):
            continue
        return False
    return True


def _tc002_has_positive_terminal_claim(disposition: str) -> bool:
    for match in _TC002_TERMINAL_CLAIM.finditer(disposition):
        prefix = disposition[: match.start()]
        if _TC002_NEGATED_PREFIX.search(prefix):
            continue
        if match.group(0) == "passed" and re.search(
            r"\b(?:tests?|checks?|validation|fixtures?|lint)\s+$", prefix
        ):
            continue
        return True
    return False


def _tc002_has_affirmative_action(next_action: str) -> bool:
    action_text = _TC002_CODEX_OWNER_PREFIX.sub("", next_action, count=1)
    first_token = re.match(r"([a-z]+)\b", action_text.lstrip(), re.IGNORECASE)
    return bool(first_token and first_token.group(1).lower() in _TC002_ACTION_IMPERATIVES)


def _assert_tc002_row(item: str, evidence: str, disposition: str, next_action: str) -> None:
    evidence = evidence.strip()
    assert evidence.lower() not in _TC002_EVIDENCE_PLACEHOLDERS
    assert len(evidence) >= 24
    assert not _TC002_NO_EVIDENCE_CLAIM.search(evidence)
    assert _tc002_has_valid_source_reference(item, f"{evidence} {disposition}")

    if item == "M5":
        # The N/A disposition is bounded to native-format controls, with the
        # normalized CSV/JSON path still explicitly evidenced.
        assert "normalized csv/json only" in evidence
        assert "native pdf/xlsx parser sandbox controls are not applicable" in disposition
    else:
        assert any(marker in disposition for marker in _TC002_OPEN_MARKERS)

    assert not _tc002_has_positive_terminal_claim(disposition)

    assert _TC002_CODEX_OWNER_PREFIX.match(next_action)
    assert len(next_action.strip()) >= 20
    assert _tc002_has_affirmative_action(next_action)


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
    # Keep the already identified R1 items as a floor: deriving the entire
    # expected set from the backlog alone would let a removed R1 marker hide
    # an existing item from this regression. Newly R1-marked items are added
    # dynamically below and must also have a ledger disposition.
    known_r1_items = {"B2", "B3", "M2", "M5", "M7", "M8"}
    backlog = (ROOT / "docs" / "PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md").read_text(
        encoding="utf-8"
    )
    r1_marked_items = {
        match.group(1)
        for line in backlog.splitlines()
        if (match := re.match(r"^([A-Z]\d+)\s+\(([^)]*)\):", line))
        and re.search(r"\bR1\b", match.group(2))
    }
    assert known_r1_items.issubset(r1_marked_items)
    required_items = known_r1_items | r1_marked_items
    assert required_items.issubset(_TC002_SOURCE_MAP)

    ledger = (ROOT / "docs" / "phase2" / "TASK_LEDGER.md").read_text(encoding="utf-8")
    heading = "## S0 TC002 — R1 defect visibility and disposition"
    assert heading in ledger
    section = ledger.split(heading, 1)[1].split("\n## ", 1)[0]
    matching_rows = {
        item: [line for line in section.splitlines() if line.startswith(f"| {item} —")]
        for item in required_items
    }
    assert all(len(lines) == 1 for lines in matching_rows.values()), {
        item: len(lines) for item, lines in matching_rows.items() if len(lines) != 1
    }
    rows = {
        item: [cell.strip().lower() for cell in line.strip().strip("|").split("|")]
        for item, lines in matching_rows.items()
        for line in lines
    }

    # This guards the pinned known items plus every newly R1-marked row in this
    # backlog, not defects that have not been discovered or marked here.
    assert required_items.issubset(rows)
    for item, cells in rows.items():
        _label, evidence, disposition, next_action = cells
        _assert_tc002_row(item, evidence, disposition, next_action)


@pytest.mark.parametrize(
    "item,evidence,disposition",
    [
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "potential R1; verified fixed",
        ),
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "not reproduced; fixed and accepted",
        ),
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "Potential R1; remains unverified; complete",
        ),
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "Potential R1; remains unverified; completed",
        ),
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "Potential R1; remains unverified; approved",
        ),
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "Potential R1; remains unverified; done",
        ),
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "Potential R1 remains unverified; resolved",
        ),
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "Potential R1 remains unverified; no remaining defects",
        ),
        (
            "B2",
            "Current code path and database behavior remain unverified.",
            "Potential R1 remains unverified; no defects remain",
        ),
        (
            "M5",
            "Current R1 paths expose normalized CSV/JSON only: external_evidence.py rejects native PDF.",
            "Native PDF/XLSX parser sandbox controls are not applicable; complete",
        ),
    ],
)
def test_tc002_rejects_contradictory_terminal_dispositions(item, evidence, disposition):
    with pytest.raises(AssertionError):
        _assert_tc002_row(
            item,
            evidence,
            disposition,
            "Codex — reproduce the behavior with the isolated fixture.",
        )


def test_tc002_allows_explicitly_negated_terminal_words():
    _assert_tc002_row(
        "B2",
        "Current `src/business_ai_gateway/compatibility.py` path remains unverified.",
        "Potential R1; remains unverified; not complete and not approved.",
        "Codex — reproduce the behavior with the isolated fixture.",
    )


def test_tc002_keeps_cannot_be_resolved_as_open():
    _assert_tc002_row(
        "B2",
        "Current `src/business_ai_gateway/compatibility.py` path remains unverified.",
        "Potential R1; cannot be resolved until an isolated database fixture is available.",
        "Codex — prepare the isolated fixture and reproduce the behavior.",
    )


@pytest.mark.parametrize("owner", ["GPT-PM", "Operator"])
def test_tc002_requires_codex_owner_for_actionable_follow_up(owner):
    with pytest.raises(AssertionError):
        _assert_tc002_row(
            "B2",
            "Current `src/business_ai_gateway/compatibility.py` path remains unverified.",
            "Potential R1; remains unverified.",
            f"{owner} — reproduce the behavior with the isolated fixture.",
        )


def test_tc002_rejects_codex_prefix_hiding_pm_assigned_action():
    with pytest.raises(AssertionError):
        _assert_tc002_row(
            "B2",
            "Current `src/business_ai_gateway/compatibility.py` path remains unverified.",
            "Potential R1; remains unverified.",
            "Codex — GPT-PM should verify the evidence.",
        )


def test_tc002_allows_codex_to_coordinate_pm_adjudication():
    _assert_tc002_row(
        "B2",
        "Current `src/business_ai_gateway/compatibility.py` path remains unverified.",
        "Potential R1; remains unverified.",
        "Codex — coordinate GPT-PM adjudication and preserve the evidence link.",
    )


def test_tc002_allows_codex_to_implement_fail_closed_evidence_verification():
    _assert_tc002_row(
        "B3",
        "Current `src/business_ai_gateway/semantic.py` path remains unverified.",
        "R1 evidence-acceptance gap remains unverified.",
        "Codex — implement fail-closed evidence verification.",
    )


@pytest.mark.parametrize(
    "evidence,next_action",
    [
        ("", "Codex — reproduce the behavior with the isolated fixture."),
        ("placeholder", "Codex — reproduce the behavior with the isolated fixture."),
        (
            "Current behavior remains unverified in the source.",
            "Codex: none",
        ),
        (
            "No evidence has been collected; status remains unknown pending review.",
            "Codex — reproduce the behavior with the isolated fixture.",
        ),
        (
            "No evidence has been collected; status remains unknown; see nonexistent.py",
            "Codex — reproduce the behavior with the isolated fixture.",
        ),
        (
            "No evidence has been collected; see src/business_ai_gateway/compatibility.py",
            "Codex — reproduce the behavior with the isolated fixture.",
        ),
        (
            "No direct evidence has been collected; see src/business_ai_gateway/compatibility.py",
            "Codex — reproduce the behavior with the isolated fixture.",
        ),
        (
            "No primary evidence has been collected; see src/business_ai_gateway/compatibility.py.",
            "Codex — reproduce the behavior with the isolated fixture.",
        ),
        (
            "Current behavior remains unverified in the source.",
            "Codex — do not verify this item; no action is planned.",
        ),
        (
            "Current behavior remains unverified in the source.",
            "Codex — don't verify this item; no action is planned.",
        ),
        (
            "Current behavior remains unverified in the source.",
            "Codex — don't bother to verify this item; no action is planned.",
        ),
        (
            "Current `src/business_ai_gateway/compatibility.py` behavior remains unverified.",
            "Codex — can't yet verify this item; no action is planned.",
        ),
        (
            "Current `src/business_ai_gateway/compatibility.py` behavior remains unverified.",
            "Codex — do not attempt to run tests; no action is planned.",
        ),
    ],
)
def test_tc002_rejects_uncited_evidence_or_non_actionable_follow_up(evidence, next_action):
    with pytest.raises(AssertionError):
        _assert_tc002_row(
            "B2",
            evidence,
            "Potential R1 behavior; verification remains unverified.",
            next_action,
        )


def test_tc002_requires_dynamic_r1_id_to_have_explicit_source_map(monkeypatch):
    assert not _tc002_has_valid_source_reference("NEW1", "See tests/test_admin_role_matrix.py.")
    monkeypatch.setitem(
        _TC002_SOURCE_MAP,
        "NEW1",
        {"tests/test_admin_role_matrix.py": ("test_admin_role_matrix.py",)},
    )
    assert _tc002_has_valid_source_reference("NEW1", "See tests/test_admin_role_matrix.py.")
    assert not _tc002_has_valid_source_reference("NEW1", "See nonexistent.py.")
    assert _tc002_has_valid_source_reference("B2", "See src/business_ai_gateway/compatibility.py.")
    assert not _tc002_has_valid_source_reference("B2", "See tests/test_admin_role_matrix.py.")


def test_tc002_constrains_m5_references_to_r1_scope():
    assert not _tc002_has_valid_source_reference(
        "M5",
        "external_evidence.py and phase2/safe_parser.py are present in this source inventory.",
    )
    assert _tc002_has_valid_source_reference(
        "M5",
        "external_evidence.py is in the R1 path; phase2/safe_parser.py is R2 and do not establish R1 coverage.",
    )
    assert not _tc002_has_valid_source_reference(
        "M5",
        "external_evidence.py plus tests/test_admin_role_matrix.py.",
    )


def test_tc002_rejects_source_symlink_resolving_outside_repo(tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    external_file = tmp_path / "external.py"
    external_file.write_text("outside repo", encoding="utf-8")
    reference = repo_root / "src" / "external.py"
    try:
        reference.symlink_to(external_file)
    except (NotImplementedError, OSError):
        pytest.skip("filesystem does not permit creating the symlink fixture")
    assert not _tc002_reference_resolves("src/external.py", repo_root)
