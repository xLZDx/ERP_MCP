"""Focused checks for the RBF-01 historical-document crosswalk."""
from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STABLE_ID = re.compile(r"\b(?:R2-US-\d{3,4}|TC\d{3}|REQ\d{2})\b")

# Each commit is the second parent of the corresponding recorded -X ours merge.
HISTORICAL_DOCS = {
    "26324d43e9d42af8512f0f531f98770c0cf7daa0": (
        "README.md",
        "docs/INSTALLATION_GUIDE_RU.md",
        "docs/LESSONS_LEARNED_RU.md",
    ),
    "8d17448cf2788f48a2b3f26eb70800cefed4d992": (
        "docs/phase2/PACKAGE_COMPLETION_RU.md",
        "docs/phase2/README.md",
    ),
    "88753c207602927c0a72ce2805534b4929e4879f": (
        "docs/phase2/CONTRACTS_AND_API_RU.md",
        "docs/phase2/PLAN_PHASE2_RU.md",
        "docs/phase2/STORIES_PHASE2_RU.md",
        "docs/phase2/TEST_PLAN_PHASE2_RU.md",
    ),
}
MERGE_PARENTS = {
    "c5e2c5fdcf4812ad83b159b7ed117e9faba0b897": (
        "57a8d10bcb67758bb1e5ccd4634ce22b336b2337",
        "88753c207602927c0a72ce2805534b4929e4879f",
    ),
    "57a8d10bcb67758bb1e5ccd4634ce22b336b2337": (
        "b5a5256ba94504b459467f30de25897f4995e224",
        "8d17448cf2788f48a2b3f26eb70800cefed4d992",
    ),
    "b5a5256ba94504b459467f30de25897f4995e224": (
        "48884a2c33434960cb310595e2e303635faa2ddd",
        "26324d43e9d42af8512f0f531f98770c0cf7daa0",
    ),
}
# Immutable audit inputs captured on 2026-11-21; refs below are provenance labels only.
CURRENT_CANONICAL_REF = "origin/main"
CURRENT_CANONICAL_COMMIT = "7916d16ed8da13ee0060fbe4072e173ea5d2bf35"
DECISION_LOG_BRANCH_REF = "origin/phase2/living-model-connectors-reconciliation"
DECISION_LOG_BRANCH_COMMIT = "88753c207602927c0a72ce2805534b4929e4879f"
DECISION_LOG_ARTIFACT = Path(
    "docs/rebaseline/2026-11-20_DECISION_LOG_DIFF_DIGESTS.json"
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def blob_text(revision: str, path: str) -> str:
    # Used only for the nine ordinary documents. Never call this for DECISION_LOG.md.
    return git("show", f"{revision}:{path}")


class RBF01ContractTests(unittest.TestCase):
    def test_historical_document_ids_are_preserved_or_explicitly_extended(self):
        for commit in (CURRENT_CANONICAL_COMMIT, DECISION_LOG_BRANCH_COMMIT):
            self.assertEqual(git("rev-parse", f"{commit}^{{commit}}"), commit)

        for merge, (ours_parent, source_parent) in MERGE_PARENTS.items():
            with self.subTest(merge=merge):
                parents = git("show", "-s", "--format=%P", merge).split()
                self.assertEqual(parents, [ours_parent, source_parent])

        compared_paths = set()
        for historical_ref, paths in HISTORICAL_DOCS.items():
            for path in paths:
                compared_paths.add(path)
                historical_ids = set(STABLE_ID.findall(blob_text(historical_ref, path)))
                current_ids = set(STABLE_ID.findall(blob_text(CURRENT_CANONICAL_COMMIT, path)))
                with self.subTest(path=path):
                    self.assertTrue(historical_ids <= current_ids)
                    current_only = current_ids - historical_ids
                    if path == "docs/phase2/STORIES_PHASE2_RU.md":
                        self.assertEqual(current_only, {"REQ28"})
                    else:
                        self.assertEqual(current_only, set())

        self.assertEqual(
            compared_paths,
            {
                "README.md",
                "docs/INSTALLATION_GUIDE_RU.md",
                "docs/LESSONS_LEARNED_RU.md",
                "docs/phase2/PACKAGE_COMPLETION_RU.md",
                "docs/phase2/README.md",
                "docs/phase2/CONTRACTS_AND_API_RU.md",
                "docs/phase2/PLAN_PHASE2_RU.md",
                "docs/phase2/STORIES_PHASE2_RU.md",
                "docs/phase2/TEST_PLAN_PHASE2_RU.md",
            },
        )
        plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
        story_row = next(line for line in plan.splitlines() if "| R2-US-001 |" in line)
        self.assertIn("REQ28", story_row)
        self.assertIn("TC003", story_row)

    def test_all_inherited_items_have_current_reconciliation_rows(self):
        backlog = (ROOT / "docs/BACKLOG_INHERITED_2026-10-21.md").read_text(
            encoding="utf-8"
        )
        section = backlog.split("## Reconciliation against the 2026-11-20 program rebaseline", 1)[1]
        rows = [line for line in section.splitlines() if line.startswith("| ERPMCP-INH-")]
        self.assertEqual(len(rows), 5)
        self.assertEqual(
            {re.match(r"\| (ERPMCP-INH-\d{3})", line).group(1) for line in rows},
            {f"ERPMCP-INH-{number:03d}" for number in range(1, 6)},
        )
        self.assertIn("counts, severity guesses, and “not fixed by integration” labels above are historical", backlog)

    def test_decision_log_artifact_binds_exact_blobs_without_source_lines(self):
        artifact = json.loads((ROOT / DECISION_LOG_ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual(artifact["kind"], "sanitized_line_digest_diff")
        self.assertEqual(artifact["path"], "core/DECISION_LOG.md")
        self.assertEqual(artifact["branch_ref"], DECISION_LOG_BRANCH_REF)
        self.assertEqual(artifact["target_ref"], CURRENT_CANONICAL_REF)
        self.assertEqual(
            artifact["branch_blob"],
            git("rev-parse", f"{DECISION_LOG_BRANCH_COMMIT}:core/DECISION_LOG.md"),
        )
        self.assertEqual(
            artifact["target_blob"],
            git("rev-parse", f"{CURRENT_CANONICAL_COMMIT}:core/DECISION_LOG.md"),
        )
        self.assertIn("source lines are not emitted", artifact["normalization"])
        self.assertEqual(artifact["branch_line_count"], 511)
        self.assertEqual(artifact["target_line_count"], 3045)
        self.assertEqual(len(artifact["entries"]), 2536)
        for entry in artifact["entries"]:
            self.assertEqual(set(entry), {"side", "line", "normalized_line_sha256"})
            self.assertIn(entry["side"], {"branch", artifact["target_ref"]})
            self.assertIsInstance(entry["line"], int)
            self.assertGreater(entry["line"], 0)
            self.assertRegex(entry["normalized_line_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
