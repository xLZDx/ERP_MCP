# Change record 140 — add the S13 acceptance and migration map

## Goal and scope

Make the remaining S13 acceptance concrete by mapping each canonical story to its current implementation evidence, exact evidence boundary, migration lineage, and next owner/action. Correct current backlog and SDLC references so the local status no longer says CR134 specialist re-review is pending or presents the older local HEAD as current.

## Changes and affected paths

- Added `S13_ACCEPTANCE_MAP_AND_MIGRATION_INVENTORY.md`, mapping V2-S13-01 through V2-S13-05, their source/migration lineage, current runtime evidence, full-suite NOT_RUN state, migration-022 reliability findings, formal gate state, and owner/dependency route.
- Updated `S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md` to reference CR134 evidence and the new story map, and to state the strict limitation of cooperative timeout cancellation.
- Updated `OPERATOR_BACKLOG.md` and `S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md` with the acceptance-map link and a concrete next local code tranche: resolve or constrain the three CR130 reliability MAJORs before recovery-to-READY design.
- Updated `docs/sdlc/STATE.md` to reconcile the CR134 specialist-review state, local range at the start of this documentation pass, and the cancelled-before-send GPT-PM request. Formal gate states remain unchanged.

## Evidence and limitations

- This is a documentation reconciliation based on the canonical S11 story register, S11 test-design package, S13 lifecycle design, CR130 and CR134 records, current migration headers, and read-only `code-explorer` and `database-reviewer` inventories.
- CR134's previously recorded evidence remains: functional 14/14 and local module-boundary E2E 10/10 at source HEAD `264fb62a41bc38796d173fe676ad01ad3efb2fe2`. It is narrow preflight evidence using doubles/in-memory checkpoint storage, not full S13 acceptance.
- Full story-mapped S13 PostgreSQL, multiprocess, restore, provider, service-startup, physical-dispatch, and 1C-skew acceptance remains NOT_RUN or unavailable as specified in the map.
- No tests, builds, database operations, migrations, gate-manifest edits, or production actions were performed for this documentation change.
- Formal S13 remains `NOT_STARTED / NOT_APPROVED`; G1–G8 remain `NOT_PASSED`; Release 2 remains `NO-GO`; production authorization remains `NONE`.
- The current complete local range still has no exact-head GPT-PM approval. A prior PM Bridge request was cancelled before send after its deadline; no GPT reply or approval was received. No push is authorized by this change record.

## Ownership and next action

- The operator remains accountable for delegated project closure; GPT/Codex maintains the local engineering and documentation queue.
- The next local code tranche is to design and implement fixes or explicit activation constraints for the three CR130 reliability MAJORs: worker-triggered permanent recovery, physical dispatch overlap with recovery, and unbounded fence-row lock waits.
- After all in-scope code for that tranche is complete, `functional-test-reviewer` and `e2e-runner` own focused disposable-database tests; database, security, reliability, and code reviewer agents own their relevant reviews. No shared/live database activation is authorized.
- Fresh GPT-PM review of the exact final local range remains the push gate.
