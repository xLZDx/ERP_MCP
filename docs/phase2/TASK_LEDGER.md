# Phase 2 Task Ledger — evidence-only inventory (rows for S1-S5 updated 2026-10-09 to head af9f287)

Date: 2026-10-08. Source of story IDs/dependencies: `STORIES_PHASE2_RU.md`.
No story marked VERIFIED or DONE without exact-head end-to-end acceptance.
`IMPLEMENTED_UNVERIFIED` indicates only partial supporting logic found in source/checkpoint, **not** a complete implemented story.

| Story | Sprint | Conservative status | Dependencies | Blocker / evidence |
| --- | --- | --- | --- | --- |
| R2-US-001 | S0 | NOT_STARTED | — | No exact-head acceptance proof |
| R2-US-002 | S0 | NOT_STARTED | US-001 | No exact-head acceptance proof |
| R2-US-003 | S1 | IMPLEMENTED_UNVERIFIED | US-002 | Connector SDK envelope + fail-closed validation (phase2/connector_sdk.py, S1-S4); no OAuth/secret provider; no real connector |
| R2-US-004 | S1 | IMPLEMENTED_UNVERIFIED | US-003 | Scope epoch/revocation at port level on fake and real SQL (S1-S4); not wired |
| R2-US-005 | S1 | NOT_STARTED | US-004 | No exact-head acceptance proof |
| R2-US-006 | S1 | NOT_STARTED | US-003 | No exact-head acceptance proof |
| R2-US-007 | S3 | NOT_STARTED | US-003, US-009, US-017 | No exact-head acceptance proof |
| R2-US-008 | S3 | IMPLEMENTED_UNVERIFIED | US-010 | Isolated module only; no product acceptance |
| R2-US-009 | S3 | IN_PROGRESS | US-010 | Failure-vs-drift classification (drift.py) and capture loop (capture_loop.py); PARTIAL completeness path tested; baseline hash in memory only |
| R2-US-010 | S2 | IMPLEMENTED_UNVERIFIED | US-004 | SQL (`db/phase2/001`-`003`) executed on a disposable PostgreSQL 16, 20 integration tests green (see EVIDENCE_MATRIX.md); GPT-PM REJECT of a8b5b4d open (BLOCKER-01..03), no backup/restore or crash-kill evidence |
| R2-US-011 | S2 | IMPLEMENTED_UNVERIFIED | US-010 | Isolated module only; no product acceptance |
| R2-US-012 | S3 | IMPLEMENTED_UNVERIFIED | US-010 | Cursor-loss resnapshot tracker + resume revalidation + capture loop enforcement (S4/S4b); cursor identity checked (issue 33); not wired |
| R2-US-013 | S4 | IMPLEMENTED_UNVERIFIED | US-007, US-008 | taxonomy.py candidate-only edges, independent approver, versions (S4b); no persistence, no concept accept/reject API |
| R2-US-014 | S4 | IMPLEMENTED_UNVERIFIED | US-013 | aliases.py exact scoped resolution + human queue (S4b); in-memory |
| R2-US-015 | S4 | IMPLEMENTED_UNVERIFIED | US-013 | Isolated module only; no product acceptance |
| R2-US-016 | S4 | IMPLEMENTED_UNVERIFIED | US-015, US-028 | SQL `promote_head` executed on disposable PostgreSQL (integration green); GPT-PM MAJOR-01: attestation evidence authenticity not verified; no service layer |
| R2-US-017 | S2 | IMPLEMENTED_UNVERIFIED | US-010 | Lease/fence/reap/poison on SQL and scheduler; real multi-process tests on PostgreSQL (S4b); one host only |
| R2-US-018 | S2 | IMPLEMENTED_UNVERIFIED | US-017 | SQL cursor CAS + outbox exercised on disposable PostgreSQL (NULL batch, replay, digest conflict); GPT-PM BLOCKER-01 (replay with changed batch) open; no publisher/consumer |
| R2-US-019 | S3 | IMPLEMENTED_UNVERIFIED | US-017 | Per-backend budget + deferral (scheduler); fairness not guaranteed (no queue/aging) |
| R2-US-020 | S3 | IMPLEMENTED_UNVERIFIED | US-005, US-018 | Pause/quarantine, state export/import, resume_revalidated (scheduler/resnapshot); caller persists state |
| R2-US-021 | S5 | NOT_STARTED | US-006, US-024, US-026 | No exact-head acceptance proof |
| R2-US-022 | S5 | NOT_STARTED | US-021, US-025 | No exact-head acceptance proof |
| R2-US-023 | S6 | NOT_STARTED | US-021, US-025 | No exact-head acceptance proof |
| R2-US-024 | S5 | IMPLEMENTED_UNVERIFIED | US-004, US-006 | capture_permit.py (S5): scope/window/mode, prod default OFF, idempotency, owner registry; caller-supplied owners, in-memory |
| R2-US-025 | S5 | IMPLEMENTED_UNVERIFIED | US-024 | side_effect_boundary.py (S5): READ allow-list, rights, prod probes; illustrative registry |
| R2-US-026 | S5 | IMPLEMENTED_UNVERIFIED | US-010, US-004 | artifact_vault.py (S5): immutable versions, evidence verification, current ACL; in-memory, no real storage |
| R2-US-027 | S5 | IMPLEMENTED_UNVERIFIED | US-026 | safe_parser.py (S5): values-only xlsx/csv with bounds; Windows child memory bound not enforced; not a sandbox |
| R2-US-028 | S6 | IMPLEMENTED_UNVERIFIED | US-026, US-027 | c4b13f4: 40 offline tests; caller-asserted identity, not wired into promotion |
| R2-US-029 | S6 | IMPLEMENTED_UNVERIFIED | US-015, US-024, US-027 | c4b13f4: 86 offline tests; in-memory, READ_SNAPSHOT permit mode |
| R2-US-030 | S6 | IMPLEMENTED_UNVERIFIED | US-021, US-029 | c4b13f4: six-balance tests and contract netting (TC090); no real 521.1 source bytes |
| R2-US-031 | S6 | IMPLEMENTED_UNVERIFIED | US-030 | S6b code commit: ap_account_strategy.py, 141 offline tests; ledger strategy / ABSENT register / BALANCE_ONLY without aging; fixtures only, no real 818HA source, ap.account_based still refused |
| R2-US-032 | S6 | IMPLEMENTED_UNVERIFIED | US-014, US-021, US-029 | S6b code commit: posted_receipts.py, 122 offline tests (62+36+24) plus comparator; retrieval, alias proof, pagination, three-way assessment over fakes only; no real paginated source or MOLDRETAIL data |
| R2-US-033 | S6 | IMPLEMENTED_UNVERIFIED | US-030 | c4b13f4: 24 offline tests; in-memory snapshots and runs |
| R2-US-034 | S6 | IMPLEMENTED_UNVERIFIED | US-028, US-030, US-031, US-032 | c4b13f4: 37 offline tests; reserved ap.account_based |
| R2-US-035 | S7 | IMPLEMENTED_UNVERIFIED | US-003, US-004, US-026 | S7 code commit: drive_port.py, drive_fake.py, drive_oauth.py, drive_scope.py, 334 offline tests (108+110+116); scoped access, broad-never-isolation, ERP_MCP-owned fake consent over a scripted fake only; no real Google OAuth, tokens or new-child proof; G4 open |
| R2-US-036 | S7 | IMPLEMENTED_UNVERIFIED | US-018, US-035 | S7 code commit: drive_baseline.py, drive_cursor.py, 109 offline tests (53+56, count as of drafting); start-token-first baseline, namespaces, durable fail-closed cursor over the existing cursor CAS port fake; no real changes.list behavior, no PostgreSQL for S7; G4 open |
| R2-US-037 | S7 | IMPLEMENTED_UNVERIFIED | US-005, US-036 | S7 code commit: drive_revisions.py, drive_membership.py, 90 offline tests (48+42); new revision UNATTESTED / old PASS historical, scope escape denied, removal tombstone over fakes only; no real revision history; G4 open |
| R2-US-038 | S7 | IMPLEMENTED_UNVERIFIED | US-006, US-036 | S7 code commit: drive_auth_state.py, 57 offline tests (41+16); AUTH_REQUIRED on invalid_grant/revoke, hint-only notifications, polling without watch over fakes only; no real Google auth or watch; G4 open |
| R2-US-039 | S8 | IMPLEMENTED_UNVERIFIED | US-030, US-032, US-034 | S8 code: workbench_types.py, workbench_review.py, 194 offline tests (66+128); cards with exact delta/owner/fragment, original digest and verify_original, rerun creates a new run, over fakes only; RunRecord.differences keeps measure names only (ROW_DETAIL_UNAVAILABLE); no real UI; G5 open (exact head recorded in the S8 commit) |
| R2-US-040 | S8 | IMPLEMENTED_UNVERIFIED | US-011, US-016, US-037 | S8 code: timeline_view.py, coverage_view.py, 401 offline tests (204+197); known/effective labels, is_green only for LIVE_CURRENT, scoped diff/evidence with opaque HIDDEN_BY_SCOPE, over fakes only; no real UI; G5 open (exact head recorded in the S8 commit) |
| R2-US-041 | S8 | IMPLEMENTED_UNVERIFIED | US-003, US-024, US-034 | S8 code: safe_errors.py, jobs_api.py, 187 offline tests (61+67+59); fixed safe errors, endpoint annotations, CSRF/idempotency decisions, refusal not bypassed by respelling, over fakes only; no HTTP/cookie/RBAC, JobQueuePort not called; G5 open (exact head recorded in the S8 commit) |
| R2-US-042 | S10 | NOT_STARTED | US-023, US-034, US-043, US-044, US-045 | No exact-head acceptance proof; S10 offline closure is ENGINEERING_HANDOFF only (`S10_RELEASE_HANDOFF.md`), canary NOT_RUN pending operator permission and real data |
| R2-US-043 | S9 | IMPLEMENTED_UNVERIFIED | US-019, US-041 | S9 code: ops_types.py, capacity_model.py, capacity_interference.py, 387 offline tests (107+195+85); sessions vs active clients vs sources vs backends kept as separate axes, refusals never counted as throughput, interference ratio and budget plan over scripted samples only; no real load, no real 1C; G6-pre stays open (test counts as first collected at 50e4c6e and grown by the review-fix batch; the exact head is the S9 PR head in git log) |
| R2-US-044 | S9 | IMPLEMENTED_UNVERIFIED | US-018, US-020, US-041 | S9 code: audit_gate.py, delivery_replay.py, alert_rules.py, 176 offline tests (44+48+84); audit-before-effect fail-closed gate, at-least-once delivery with digest de-dup over fake sinks, alert state machine with hysteresis; no real audit sink, no real alert delivery, no chaos run; G6-pre stays open (test counts as first collected at 50e4c6e and grown by the review-fix batch; the exact head is the S9 PR head in git log) |
| R2-US-045 | S9 | IMPLEMENTED_UNVERIFIED | US-016, US-041 | S9 code: release_migration.py, release_rollback.py, 304 offline tests (134+126+44 SQL guard); typed step classification, shadow compare by digest, decision-only rollback (executed=False), effective grants from current state only; SQL text guard reads db/phase2/001..003 only; no migration executed, no Release 1 regression run; G6-pre stays open (test counts as first collected at 50e4c6e and grown by the review-fix batch; the exact head is the S9 PR head in git log) |
| R2-US-046 | S9 | IMPLEMENTED_UNVERIFIED | US-026, US-037, US-045 | S9 code: restore_verify.py, export_safety.py, retention_hold.py, 318 offline tests (118+143+57); restore manifest/FK catalogue/digest/head verification over in-memory rows, export masking/tenant filter/formula neutralization, decision-only retention and hold (executed=False, no delete path); real pg restore is not run; G6-pre stays open (test counts as first collected at 50e4c6e and grown by the review-fix batch; the exact head is the S9 PR head in git log) |
| R2-US-047 | FOLLOW_ON | NOT_STARTED | US-002, US-041 | No exact-head acceptance proof |
| R2-US-048 | S10 | NOT_STARTED | US-042, US-043, US-044, US-045, US-046 | No exact-head acceptance proof; no exact-head release bundle approved (see `S10_RELEASE_HANDOFF.md`), Release 2 NO-GO |

## Global blockers

- G0 authority, donor license review; isolated PostgreSQL permission for G1; real 1C read grant and native report provenance for G2/G3; dedicated server-side Google Drive OAuth for G4; independent UAT and production release authority for G5–G7.
- Evidence base: base HEAD `9b4fc0c`, see `EVIDENCE_MATRIX.md` (single source for SHAs, results and superseded records). Not pushed.
- Operator-only blockers are tracked in `OPERATOR_BACKLOG.md` (OB-01..OB-21) and `G1_OPERATOR_BACKLOG.md`.
- Per-story acceptance results and owner approvals remain unpopulated pending verified evidence.
- 2026-10-08 status refresh: US-003/009/012/030/032/036 downgraded or set to IN_PROGRESS (partial logic, not a story); US-010/016/017/018 set to IMPLEMENTED_UNVERIFIED because unexecuted SQL drafts exist.
