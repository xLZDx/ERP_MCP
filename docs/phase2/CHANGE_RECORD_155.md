# Change record 155 — reconcile S13 writer inventory and draft dispatch-boundary contract

Date: 2026-10-17. Status: local S13 documentation reconciliation and PM-approved non-gating S14 simulation implementation; focused functional/E2E evidence green; relevant specialist reviews found no BLOCKER/MAJOR.

## What changed

- Reconciled `S13_MUTATION_AND_WRITER_PATH_INVENTORY_2026-10-17.md` with CR154: extended the source inventory through migration 026, recorded completion and limits of the checkpoint suffix reader/classifier, and corrected the next-work queue.
- Recorded the database-reviewer and reliability-reviewer finding that no safe partial SQL migration can implement recovery/admission fencing while the physical writer boundary and unresolved-call protocol are absent. Migration 023's recovery refusal and the lifecycle coordinator's `NOT_READY` behavior remain in force.
- Added `S13_WRITER_BOUNDARY_CLAIM_AND_RECOVERY_CONTRACT_2026-10-17.md` as a design proposal. It preserves the frozen S12 order (APPLYING/call ownership, checkpoint write/read-back, permit, then the existing DISPATCHED CAS), treats the existing call identity as the single-use dispatch claim, requires a writer-side linearizable epoch barrier, and keeps unknown outcomes fail-closed.
- Added `S13_API_MUTATION_FENCE_COVERAGE_2026-10-17.md`, a grouped per-API source map of mutation surfaces, principal classes, trigger coverage, direct-table constraints and transaction boundaries across migrations 004–026. DB review confirmed the API/grant map after corrections for `LEGACY`, `fence_check`, configured-role distinction, `anchor_gap_cosign`, and internal-only budget helpers.
- Added `S14_SIMULATED_WRITE_PORT_DESIGN_2026-10-17.md` as a proposed non-gating local simulation story. Correlated GPT-PM decision `b5f382b5-86b4-4bc1-9e62-52dc762aad23` returned **GO — LOCAL IMPLEMENTATION ONLY**, subject to simulation-only validation, operation allowlisting, TEST-only result types, no production composition or evidence/gate promotion, and atomic expected-version checks recorded in that design.
- Implemented the opt-in TEST-only `SimulatedOneCWritePort` and clone-owned atomic compare-and-apply synchronization. It binds synthetic ticket/permit fields to simulator identity, one tenant/company/organization tuple, clone base fingerprint, canonical payload digest, target/version, operation, expiry at admission and a single-use call ID; only `CREATE_DRAFT`, `POST`, and `UNPOST` can enter mutation. Scope, organization, fingerprint, digest, expiry and version checks are serialized with the mutation. Synthetic outcomes do not use `FailureEvidence`, clone receipt signatures, or clone-oracle reads; no automatic retry or production composition is added.

## Why

CR154 completed the previously listed S13 suffix reader/classifier task. The source inventory still described it as future work. Independent database and reliability reviews also found that re-enabling recovery or adding a database-only epoch check would not fence a physical call that starts or remains active beyond a short SQL transaction. The new contract records the missing boundary and recovery evidence without inventing an implementation or readiness claim.

The S14 design isolates a local protocol exercise from canonical S14 acceptance criteria, which still require a CT14-approved channel and channel-specific evidence. GPT-PM allows implementation only as an explicitly non-gating local story.

## Review and evidence

- Reviewed source baseline: `761542b6dc4d78fab5dc494df09f8aecc79de113` (`fix: minimize S13 checkpoint suffix data`).
- Exact-head GPT-PM review `a6ee1544-6cc6-4f36-8b19-18ccbb911542` approved that commit for push to `origin/main`; the push completed, and `git ls-remote origin refs/heads/main` returned the same SHA. This approval does not cover the documentation changes in this record.
- Local `Get-FileHash .../lifecycle.py -Algorithm SHA256` returned `2542380E5F67A1A2B776D416842EFD5FCAABFB680986EA5D35CAA8E4E45D3FDD`, matching CR154.
- Database and reliability reviews of the existing S13 shared-fence proposal found no safe partial migration; keep recovery disabled and lifecycle `NOT_READY`.
- Architecture and reliability review of the new writer-boundary contract found its reported major/minor issues corrected after a focused follow-up. The database reviewer then confirmed the corrected S12 ordering, writer barrier and candidate lock contract, with final refinements applied: distinguish DB desired epoch from writer-installed epoch, make lost-CAS recovery a status read on the identical call identity, and retain migration 008 lock invariants. The document remains design-only; no migration should start yet.
- Final `node scripts/build_document_registry.mjs` execution completed successfully and scanned four refs: `refs/heads/main` at `761542b6dc4d78fab5dc494df09f8aecc79de113`, `refs/heads/worktree-agent-abd0046aa55cead7b` at `dd819a4a85ff16ecedb0efcaf8e52911076682b8`, `refs/heads/worktree-agent-aebf3202355a7a3f7` at `f03852476d66c61c552c66fcb994ad25611d5d57`, and `refs/remotes/origin/main` at `761542b6dc4d78fab5dc494df09f8aecc79de113`. It reported 225 tracked Markdown paths and 4 local-only Markdown paths.
- Functional-test-reviewer added `tests/phase2/test_s14_simulated_write_port.py` and ran `$env:PYTHONPATH = 'src'; python -m unittest discover -s tests/phase2 -p 'test_s14_simulated_write_port.py' -v`: 16 tests passed (exit 0). Coverage maps to PM AC-01–AC-16, including malformed/mismatched bindings, canonical payload digest, cross-tenant/company adapter rejection, organization, two-adapter concurrency, reused call IDs, duplicate/repeat, TEST-only outcomes, no oracle leakage, uncertain timeout/crash without retry, and expiry after preflight but before clone admission. The expiry case proves no write and that the same call ID remains usable with a fresh valid permit.
- E2E-runner added `tests/phase2/test_s14_simulated_write_port_protocol_e2e.py` and ran `python -m pytest tests/phase2/test_s14_simulated_write_port_protocol_e2e.py -q`: 4 passed, one pytest-asyncio deprecation warning, 1.60 seconds on the final source. Journey: `CREATE_DRAFT → POST → UNPOST`; organization and altered-payload mismatch plus `UPDATE_DRAFT` refuse; uncertain timeout/crash-after-write cannot be retried; result classifies to `CALL_UNKNOWN`. The test does not connect to a formal gate-state service, which is not wired to this local adapter.
- Both agents ran on working-tree changes with base HEAD `761542b6dc4d78fab5dc494df09f8aecc79de113`; neither test commit exists yet. Final source SHA-256: `simulated_write_port.py` `3327B841DFA773B4FED6D2ED272DF50CF69872F80AE555553E97C9A85D28133D`; `clone_1c.py` `590F0BE82F30F005831D30922139A0CE8B130251F762D0AEA555E9ADB95EA646`. Security, reliability and code specialist rechecks found no remaining BLOCKER/MAJOR. No build, database operation, migration, real 1C, or CT14 operation is in scope for this local slice.

## Acceptance and remaining work

- **S13 documentation reconciliation:** completed locally; inventory now covers 004–026 and states the remaining acceptance accurately.
- **S13 implementation:** not complete. The per-API source map was reconciled against repository function/grant definitions by the database reviewer; this is not evidence of effective deployed grants. Actual licensed writer/service boundary evidence is still needed before any fence migration or activation.
- **S14 local simulated port:** implementation, focused local functional/E2E runs, and relevant specialist reviews are complete under correlated GPT-PM decision `b5f382b5-86b4-4bc1-9e62-52dc762aad23`, LOCAL ONLY under the conditions above. Exact-head GPT decision and local commit remain. Even if committed and reviewed, it will not close formal S14 without CT14 and measured channel evidence.
- **Gates and release:** no gate status changed. G1–G8 remain `NOT_PASSED`; S13 remains `NOT_STARTED / NOT_APPROVED`; R-01/R-03 remain formally open; Release 2 remains `NO-GO`; production authorization remains `NONE`.

## Affected paths

- `docs/phase2/S13_MUTATION_AND_WRITER_PATH_INVENTORY_2026-10-17.md`
- `docs/phase2/S13_API_MUTATION_FENCE_COVERAGE_2026-10-17.md`
- `docs/phase2/S13_WRITER_BOUNDARY_CLAIM_AND_RECOVERY_CONTRACT_2026-10-17.md`
- `docs/phase2/S14_SIMULATED_WRITE_PORT_DESIGN_2026-10-17.md`
- `docs/phase2/CHANGE_RECORD_155.md`
- `src/business_ai_gateway/phase2/simulation/clone_1c.py`
- `src/business_ai_gateway/phase2/simulation/simulated_write_port.py`
- `tests/phase2/test_s14_simulated_write_port.py`
- `tests/phase2/test_s14_simulated_write_port_protocol_e2e.py`
- `governance/DOCUMENT_REGISTRY.md` (generated)

## Decision ownership and next action

The operator is accountable for delegated project closure; GPT/Codex performs local engineering. `functional-test-reviewer` and `e2e-runner` authored and executed the required focused tests. Database, reliability, architecture, and security specialists reviewed their relevant boundaries. The licensed writer/service owner is not identified in canonical project records; this external ownership/evidence gap is not assigned to an invented person.

Next: obtain the licensed writer/service owner and writer-side epoch barrier, idempotent call-ID lookup, and in-flight-call/quiescence evidence needed to design S13 admission fencing. For the completed local S14 slice, prepare the exact commit and request GPT-PM review for that exact head before any push. No S13 readiness, gate pass, real 1C behavior, merge, release, or production action is implied.
