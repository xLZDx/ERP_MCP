# Change record: isolate source-derived material during WP3 classification

Date: 2026-10-22  
Scope: WP3 documentation-only handling rule for remaining source-derived English-policy candidates.

## What changed

- Recorded a sanitized review boundary for `docs/phase2/S11_DECISION_RECORDS_AND_THREAT_MODEL_2026-10-12.md`, `scripts/real1c/raw_l2.py`, and generated `reports/real1c/case_results.json` in the inherited backlog.
- Required occurrence-level classification by exact path, line number, and normalized-line digest without emitting source-derived values into chat or durable records.
- Recorded that `case_results.json` must be corrected in `scripts/real1c/run_lane.py` and regenerated, not hand-edited; the current output references are `run_lane.py:540,571`.
- Kept the 15 repeated-hash occurrences withheld and WP3 acceptance open.

## Why

These files contain source-derived evidence or generated output. A broad exception or an output that copies source values would weaken the policy and expose material unnecessarily. Exact occurrence metadata allows review without placing the values into the change record.

## Verification state

- Manually reconciled the paths with the existing WP3 inventory. A repository-source check confirmed that `scripts/real1c/run_lane.py:540,571` writes `case_results.json`; the source contents are outside this documentation patch.
- No source-derived values were added to this record.
- No scanner, test, check, build, CI, or migration was run. This change does not establish a scanner pass or WP3 acceptance.
- GPT-PM exact-patch review: pending.
