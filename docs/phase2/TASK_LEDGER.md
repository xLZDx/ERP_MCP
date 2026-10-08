# Phase 2 Task Ledger — initial evidence-only inventory

Date: 2026-10-08. Source of story IDs/dependencies: `STORIES_PHASE2_RU.md`.
No story marked VERIFIED or DONE without exact-head end-to-end acceptance.
`IMPLEMENTED_UNVERIFIED` indicates only partial supporting logic found in source/checkpoint, **not** a complete implemented story.

| Story | Sprint | Conservative status | Dependencies | Blocker / evidence |
| --- | --- | --- | --- | --- |
| R2-US-001 | S0 | NOT_STARTED | — | No exact-head acceptance proof |
| R2-US-002 | S0 | NOT_STARTED | US-001 | No exact-head acceptance proof |
| R2-US-003 | S1 | IN_PROGRESS | US-002 | `onec_discovery.py` only (allowlist, audit-before-adapter, fingerprint); no SDK envelope, OAuth or secret provider |
| R2-US-004 | S1 | NOT_STARTED | US-003 | No exact-head acceptance proof |
| R2-US-005 | S1 | NOT_STARTED | US-004 | No exact-head acceptance proof |
| R2-US-006 | S1 | NOT_STARTED | US-003 | No exact-head acceptance proof |
| R2-US-007 | S3 | NOT_STARTED | US-003, US-009, US-017 | No exact-head acceptance proof |
| R2-US-008 | S3 | IMPLEMENTED_UNVERIFIED | US-010 | Isolated module only; no product acceptance |
| R2-US-009 | S3 | IN_PROGRESS | US-010 | GAP event kind in-memory only; no scan timeout/partial-recovery path |
| R2-US-010 | S2 | IMPLEMENTED_UNVERIFIED | US-004 | SQL (`db/phase2/001`-`003`) executed on a disposable PostgreSQL 16, 20 integration tests green (see EVIDENCE_MATRIX.md); GPT-PM REJECT of a8b5b4d open (BLOCKER-01..03), no backup/restore or crash-kill evidence |
| R2-US-011 | S2 | IMPLEMENTED_UNVERIFIED | US-010 | Isolated module only; no product acceptance |
| R2-US-012 | S3 | IN_PROGRESS | US-010 | In-memory GAP/availability separation only; no cursor-loss resnapshot (TC036/TC108) |
| R2-US-013 | S4 | NOT_STARTED | US-007, US-008 | No exact-head acceptance proof |
| R2-US-014 | S4 | NOT_STARTED | US-013 | No exact-head acceptance proof |
| R2-US-015 | S4 | IMPLEMENTED_UNVERIFIED | US-013 | Isolated module only; no product acceptance |
| R2-US-016 | S4 | IMPLEMENTED_UNVERIFIED | US-015, US-028 | SQL `promote_head` executed on disposable PostgreSQL (integration green); GPT-PM MAJOR-01: attestation evidence authenticity not verified; no service layer |
| R2-US-017 | S2 | IMPLEMENTED_UNVERIFIED | US-010 | SQL job/lease/fence exercised on disposable PostgreSQL (stale fence, reap, one-running-per-source); GPT-PM BLOCKER-02 (outbox claim fence) open; no worker or retry orchestration |
| R2-US-018 | S2 | IMPLEMENTED_UNVERIFIED | US-017 | SQL cursor CAS + outbox exercised on disposable PostgreSQL (NULL batch, replay, digest conflict); GPT-PM BLOCKER-01 (replay with changed batch) open; no publisher/consumer |
| R2-US-019 | S3 | IMPLEMENTED_UNVERIFIED | US-017 | Single-process physical backend budget + 5 unit tests; distributed backend/fairness/prod tests missing |
| R2-US-020 | S3 | NOT_STARTED | US-005, US-018 | No exact-head acceptance proof |
| R2-US-021 | S5 | NOT_STARTED | US-006, US-024, US-026 | No exact-head acceptance proof |
| R2-US-022 | S5 | NOT_STARTED | US-021, US-025 | No exact-head acceptance proof |
| R2-US-023 | S6 | NOT_STARTED | US-021, US-025 | No exact-head acceptance proof |
| R2-US-024 | S5 | NOT_STARTED | US-004, US-006 | No exact-head acceptance proof |
| R2-US-025 | S5 | NOT_STARTED | US-024 | No exact-head acceptance proof |
| R2-US-026 | S5 | NOT_STARTED | US-010, US-004 | No exact-head acceptance proof |
| R2-US-027 | S5 | NOT_STARTED | US-026 | No exact-head acceptance proof |
| R2-US-028 | S6 | NOT_STARTED | US-026, US-027 | No exact-head acceptance proof |
| R2-US-029 | S6 | NOT_STARTED | US-015, US-024, US-027 | No exact-head acceptance proof |
| R2-US-030 | S6 | IN_PROGRESS | US-021, US-029 | Numeric comparator only (EVALUATION_ONLY); no source, no netting/TC090, no policy pins |
| R2-US-031 | S6 | NOT_STARTED | US-030 | No exact-head acceptance proof |
| R2-US-032 | S6 | IN_PROGRESS | US-014, US-021, US-029 | Comparator only; no receipt retrieval, alias proof (TC096) or pagination |
| R2-US-033 | S6 | NOT_STARTED | US-030 | No exact-head acceptance proof |
| R2-US-034 | S6 | NOT_STARTED | US-028, US-030, US-031, US-032 | No exact-head acceptance proof |
| R2-US-035 | S7 | NOT_STARTED | US-003, US-004, US-026 | No exact-head acceptance proof |
| R2-US-036 | S7 | IN_PROGRESS | US-018, US-035 | Mock-HTTP changes reader/projector only; no OAuth, start-token baseline, shared-drive namespace or durable cursor (TC106/TC108 open) |
| R2-US-037 | S7 | NOT_STARTED | US-005, US-036 | No exact-head acceptance proof |
| R2-US-038 | S7 | NOT_STARTED | US-006, US-036 | No exact-head acceptance proof |
| R2-US-039 | S8 | NOT_STARTED | US-030, US-032, US-034 | No exact-head acceptance proof |
| R2-US-040 | S8 | NOT_STARTED | US-011, US-016, US-037 | No exact-head acceptance proof |
| R2-US-041 | S8 | NOT_STARTED | US-003, US-024, US-034 | No exact-head acceptance proof |
| R2-US-042 | S10 | NOT_STARTED | US-023, US-034, US-043, US-044, US-045 | No exact-head acceptance proof |
| R2-US-043 | S9 | NOT_STARTED | US-019, US-041 | No exact-head acceptance proof |
| R2-US-044 | S9 | NOT_STARTED | US-018, US-020, US-041 | No exact-head acceptance proof |
| R2-US-045 | S9 | NOT_STARTED | US-016, US-041 | No exact-head acceptance proof |
| R2-US-046 | S9 | NOT_STARTED | US-026, US-037, US-045 | No exact-head acceptance proof |
| R2-US-047 | FOLLOW_ON | NOT_STARTED | US-002, US-041 | No exact-head acceptance proof |
| R2-US-048 | S10 | NOT_STARTED | US-042, US-043, US-044, US-045, US-046 | No exact-head acceptance proof |

## Global blockers

- G0 authority, donor license review; isolated PostgreSQL permission for G1; real 1C read grant and native report provenance for G2/G3; dedicated server-side Google Drive OAuth for G4; independent UAT and production release authority for G5–G7.
- Evidence base: base HEAD `9b4fc0c`, see `EVIDENCE_MATRIX.md` (single source for SHAs, results and superseded records). Not pushed.
- Operator-only blockers are tracked in `OPERATOR_BACKLOG.md` (OB-01..OB-21) and `G1_OPERATOR_BACKLOG.md`.
- Per-story acceptance results and owner approvals remain unpopulated pending verified evidence.
- 2026-10-08 status refresh: US-003/009/012/030/032/036 downgraded or set to IN_PROGRESS (partial logic, not a story); US-010/016/017/018 set to IMPLEMENTED_UNVERIFIED because unexecuted SQL drafts exist.
