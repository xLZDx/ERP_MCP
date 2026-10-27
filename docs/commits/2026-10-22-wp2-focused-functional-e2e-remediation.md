# WP2 focused functional and E2E remediation — 2026-10-22

## Scope

This change repairs four concrete issues surfaced by the mapped WP2 test-agent run: missing
read-only MCP metadata on `counterparty_find`, an eager Docker-harness import in the injected
capacity-drill test path, stale lifecycle test doubles, and simulation tests that assumed an older
receipt schema. It also rebinds the existing engineering checkpoint to the resulting implementation
fingerprint without changing any frozen gate status.

## Changes and rationale

- `src/business_ai_gateway/server.py`: declares the same `CHATGPT_READ_ONLY_ANNOTATIONS` on
  `counterparty_find` that the other public read tools expose. Principal resolution and company
  authorization remain in place; annotations are client-facing metadata, not access control.
- `scripts/phase2_capacity_drill.py`: imports `_pg_harness` only when the default container identity
  probe is needed. An explicitly supplied `container_identifier` is selected by `is not None`, so
  even a falsey callable is used as injected. The default path still verifies the named test
  container and compares its system identifier with the DSN before any database creation.
- `tests/phase2/test_s13_lifecycle_preflight.py` and
  `tests/phase2/test_s13_lifecycle_preflight_e2e.py`: add ledger doubles that provide the current
  checkpoint-suffix contract. The E2E fixture uses a chain head consistent with checkpoint sequence
  12 while preserving `NOT_READY / SHARED_FENCE_UNAVAILABLE`.
- `tests/phase2/test_simulation_scenarios_offline.py`: constructs writers with each clone's trusted
  receipt public key and asserts generation binding through the signed receipt's
  `dispatch_id = change_id:generation` contract. The cross-key signature rejection remains tested.
- The two historical G1 notes now mark their dated snapshots as superseded and point to
  `EVIDENCE_MATRIX.md`.
- `reports/CURRENT_ENGINEERING_CHECKPOINT.json`, its four Markdown status reports and the two
  synchronized engineering dashboard copies carry implementation fingerprint
  `2d964faf481b83402823e920e21cb745b9b10b44972f08fd160851c981d2651b`. The checkpoint remains
  production `NO-GO`, DoD `PARTIAL`, PR 11 `DRAFT`; earlier run results remain historical.

## Verification

All tests were authored/executed by the designated functional-test-reviewer or e2e-runner roles;
the primary agent did not run tests.

- Functional tests: the four targeted nodes for historical G1 markers, public MCP read-only
  annotations, engineering checkpoint/artifact consistency, and S13 lifecycle preflight passed
  (`4 passed in 1.43s`). After the final checkpoint rebound, the artifact/checkpoint node passed
  again (`1 passed in 0.97s`).
- E2E/offline tests: seven offline simulation nodes passed in the initial focused run; the remaining
  operation-kind/receipt node initially exposed the stale `receipt['generation']` assertion. After
  correcting it to verify the current `dispatch_id` binding, that node passed separately. Thus all
  eight assigned offline nodes passed, with one node verified in a follow-up run.
- E2E lifecycle preflight passed; G1 capacity smoke passed after the lazy import and explicit
  injected-probe selection changes (`1 passed` on the final capacity rerun).
- No database, Docker container, migration, external 1C, or COM test was run. WP2 migration-backed
  database cases remain `NOT_RUN` because their current harness creates containers and no approved
  adapter to the declared disposable PostgreSQL service was available in this test pass.
- Read-only Python review found no BLOCKER/MAJOR/MINOR findings and rechecked the final explicit
  selector. Read-only security review found no findings in the annotated read tool or the fail-closed
  identity verification path; its pass preceded the selector-only robustness clarification.

## Limits and next action

This is not S13 implementation or runtime qualification and does not close WP2 database coverage,
WP3 language-scan findings, G1 formal acceptance, or production authorization. Continue by designing
a test-role-owned adapter for the declared disposable database, resolving WP3 scanner findings
without broad path exemptions, and then proceed with dependency-ordered WP5–WP8/WP10 work. WP9
remains optional.

Accountable task owner: operator. Executor: Codex. Required test owners: functional-test-reviewer
and e2e-runner. No push or PR is authorized by this record.
