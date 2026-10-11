# S11 source-evidence inventory: what the existing R2 modules really contain (2026-10-12)

Status: first pass, DRAFT. Scope: the claims in `PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` (section 3, section 6) about existing R2 modules under `src/business_ai_gateway/phase2/`. Method: direct reading and text search of the files at the head of `main` after commit `aff0e63`. Labels: FACT = seen in the cited file; INFERENCE = a consequence of facts; NOT_VERIFIED = not yet checked in this pass. No test, CI or mutation run was started; nothing was executed except text search.

## 1. Claims checked

| Plan claim | Result | Evidence |
| --- | --- | --- |
| There is no kill switch anywhere in `src` | FACT (for the searched patterns) | Case-insensitive search of `src` for `kill.?switch`, `killswitch`, `emergency_stop`, `STOP_EFFECTS` returned 0 matches. A differently named mechanism is not excluded by this search. |
| `aliases` resolves only `SupplierEntity`, by exact reference | FACT for the type; exact-reference part NOT_VERIFIED | `aliases.py` defines `class SupplierEntity` and `add_entity` refuses any other type (`if type(entity) is not SupplierEntity`). |
| `capture_permit` is bound to a request, process-local, and has no write mode | FACT | `CaptureMode` has exactly `READ_SNAPSHOT` and `READ_INCREMENTAL` (both reads); permits live in instance dictionaries (`self._permits`, `self._uses`, `self._by_key`). CORRECTION: earlier chat wording and plan rev 1-2 said the permit knows only `READ_SNAPSHOT`; the real set has two read modes. The plan text says "no write mode", which stays true. |
| `side_effect_boundary` admits only READ | FACT | The module header says "Only READ operations are allowed"; `OperationClass` already has `WRITE`, `POST`, `DELETE`, `RESET`, `ADMIN`, `UNCLASSIFIED`, each non-READ class maps to a refusal code (`WRITE_OPERATION`, `POST_OPERATION`, ...), and the registry already names `create_document`/`update_document` as WRITE and `post_document` as POST. INFERENCE: S12 needs a new evaluator for governed WRITE/POST, not new class names. |
| `audit_gate` keeps request ids in process memory | FACT | The header says "Offline, unwired, in-memory, EVALUATION_ONLY"; state is held in instance dictionaries (`self._acks`, `self._phase_mode`); a known request id is suppressed (`DUPLICATE_SUPPRESSED`). |
| `jobs_api` is a decision model whose job kinds map to reads | FACT for the kinds; "fakes" NOT_VERIFIED | `JobKind` = RESCAN, REPORT, RECONCILIATION, CAPTURE, RERUN: none is a change. |
| `reconciliation` is a six-column per-account calculation | FACT for the types | `BalanceSix`, `LedgerScope`, `LedgerRow`, `LedgerStatement`, `Comparison`, `Difference`. Multiset comparison of movements (plan CT6) is not present in this module: NOT_VERIFIED, to be built or confirmed. |
| `workbench_review` is discrepancy cards, not approval cards | INFERENCE | The module compares native and gateway values (`_delta(native, gateway)`) over epochs, ledgers and snapshots; no approval or change concept was seen in the names. Full read NOT_VERIFIED. |

## 2. Consequences for the plan

1. A change proposal, an approval record, a write grant, a kill switch, a call-ownership record and a 1C write port do not exist and must be written (plan CT1-CT15). What can be reused are patterns: the operation-class registry and refusal codes, the audit phase/acknowledgement flow, the permit issuance and use accounting, the reconciliation row types.
2. `side_effect_boundary` is the natural place to attach the governed WRITE/POST evaluator; its READ-only guarantees must stay under regression.
3. In-memory stores (`audit_gate`, `capture_permit`) cannot carry the durable intent, grant and budget state the plan needs: the ledger (CT2, CT5, CT13) is new.

## 3. Not covered yet

`workbench_review` full read, the `jobs_api` fakes, exact-reference behaviour of `aliases`, `safe_parser` limits for the xlsx/csv intake, the `drive_*` modules, `restore_verify` and `release_rollback` as patterns for ops. The next pass must close these before any component is reused.

## 4. GPT-PM deep review of this package (2026-10-12)

Verdict: APPROVE for S11 execution entry (plan baseline revision 5, inventory PARTIAL); S11 exit NOT_PASSED; S12 interface freeze NOT approved; G0-G8 NOT_PASSED; Release 2 NO-GO. The reviewer read the attached files only (no execution) and could not verify that they match the local head or that no differently named kill switch exists anywhere in the repository; both stay inventory items.

Reuse claims: all seven modules CONFIRMED against the attached text, with one WRONG plan statement (capture_permit modes; corrected in plan section 1). Reuse is as pattern only: `side_effect_boundary.evaluate()` stays the READ-only path, `capture_permit.admit()` consumes a use immediately (unlike the reserved/consumed/released grant of CT13), `audit_gate` acknowledgements prove audit persistence only, `jobs_api` keeps sticky refusals and a read-only operation map, `reconciliation` is six-column and not a registrar-movement multiset, `workbench_review` annotations are not approval authority, `aliases` trusts a caller-asserted HUMAN approver.

Four requirements to be settled in S11 before the S12 interface freeze:

- S11-A read/write boundary separation: two authorization paths with different trusted contexts; the legacy READ evaluator stays deny-by-default for every non-READ class; acceptance: a proposed WRITE/POST stays denied through every legacy read entry point even when an approved change exists elsewhere.
- S11-B audit phases are not write finality: a documented mapping between the audit gate phases and the CT2/CT10 states; an audit acknowledgement or DUPLICATE_SUSPECTED-style suppression never means VERIFIED; acceptance: lost completion ack, failed effect, unknown 1C outcome and duplicate request give distinguishable durable states.
- S11-C live authorization epoch: entitlement and base-epoch checks at queue claim and immediately before the effect, separate from the 1C base fingerprint epoch; acceptance: entitlement change, revoked requester or approver, replaced source or base epoch between proposal, approval, dequeue and execution all refuse before a write.
- S11-D separate evidence types: document fields, registrar movements, 1C state versions and authorization receipts; a six-column MATCH or an ORIGINAL_INTACT card never produces VERIFIED.

Next inventory pass must cover: ops_types, _identity, workbench_types, comparison_snapshot, safe_errors, connector_sdk, the complete db/phase2 schemas and migrations, safe_parser, the Drive adapters, the 1C reader, restore_verify, release_rollback and the deployment/permission configuration; for each dependency record exact path, revision, relevant lines, authority level, tenant/company scope, persistence, error-code semantics and whether reuse is code, pattern only or not at all. A live CT14 spike that changes a disposable 1C clone still needs the applicable operator permission; the review is not that permission.

## 5. Second inventory pass (2026-10-12, read-only agent; FACT here means an agent-reported source observation, NOT independently verified by the reviewer from attached source)

`P2` = `src/business_ai_gateway/phase2`. Authority of every module is EVALUATION_ONLY. Reuse type: code / pattern / none.

| Item | Path and lines | Scope | Persistence | Error semantics | Reuse |
| --- | --- | --- | --- | --- | --- |
| ops_types | `P2/ops_types.py` 83-207, 312-403, 409-443 | `OpsScope(tenant, company, actor)`; entitlement check is one boolean, no read/write split | memory (`TenantBoundedMap`) | closed `OpsReason` + `NextAction`, import-time completeness guard; port exception -> `DEPENDENCY_FAILED` | code (scope-order check, refusal carrier) |
| _identity | `P2/_identity.py` 17-139 | `scope_key(tenant, company)` | none | returns empty/None, never raises | code (`same_person`, `is_empty_1c_ref`) |
| workbench_types | `P2/workbench_types.py` 37-196, 278-341 | `ViewerScope` carries `scope_epoch`; no write-target ownership kind | memory (fakes) | `SafeError`; success-like codes degrade to `INTERNAL_REFUSED` | code + pattern |
| comparison_snapshot | `P2/comparison_snapshot.py` 114-188, 264-382 | tenant only (no company) | memory; run ids global across tenants | floats refused | code (`canonical_digest`), pattern (supersession chain) |
| safe_errors | `P2/safe_errors.py` 38-139 | none | none | message table tied to workbench codes only | code, needs new tables |
| connector_sdk | `P2/connector_sdk.py` 40-196, 325-374 | `source_id`, `tenant_id`, `scope_epoch`; read-only (`SNAPSHOT_ONLY`) | none | `ValidationError.reasons` as `field:REASON` | pattern only (key/value scanner reusable) |
| db/phase2 001-003 | `db/phase2/001_living_registry.sql`, `002_job_cursor_functions.sql`, `003_security_hardening.sql` | per (tenant, source), RLS, company nullable | Postgres, immutable ledgers | fixed `RAISE` codes (`SCOPE_REVOKED`, `STALE_JOB_FENCE`, `APPROVER_NOT_INDEPENDENT`, ...) | pattern: epoch rechecked under the source row lock at claim (002 `acquire_job`), separate approver with digest-bound attestation (003 `promote_head`), role change bumps epoch; no write grant, proposal or call-ownership table exists |
| safe_parser | `P2/safe_parser.py` 66-169, 703-996 | none | none | fixed codes, content never echoed; Windows memory bound not enforced | code (untrusted xlsx/csv intake) |
| drive_port/scope/http/oauth | `P2/drive_*.py` (headers only) | `scope_epoch` first on every call; read-only by construction | memory | closed code sets | pattern; other drive modules NOT_VERIFIED |
| 1C metadata reader | `P2/onec_discovery.py` 39-182 | per (tenant, source) | none | audit write awaited before fetch, fail closed `AUDIT_WRITE_FAILED` | pattern |
| test-lane gateway client | `testlane/phase2_mcp/gateway_client.py`, `config.py` | env-configured | none | fixed `GATEWAY_*` codes | none for writes |
| restore_verify | `P2/restore_verify.py` 88-845 | `OpsScope` + declared source ids | memory | `OpsReason.RESTORE_*` | code + pattern, `living.*` tables only |
| release_rollback | `P2/release_rollback.py` 168-587 | platform level | memory (`FakeGrantRegistry`) | `OpsReason.ROLLBACK_*`; `executed` always False | pattern (separate approver, no resurrection) |
| capture_permit | `P2/capture_permit.py` 66-471 | per (tenant, source) | memory | `PERMIT_NOT_ADMITTABLE`, `PROD_DISABLED` | pattern; `set_prod_enabled` is a global PROD flag, not a write kill switch |
| side_effect_boundary | `P2/side_effect_boundary.py` 73-303 | none | none | `BoundaryCode.*_OPERATION` | pattern; `evaluate` can never allow a non-READ class |
| audit_gate | `P2/audit_gate.py` 90-468 | tenant sink; request-id space per tenant | memory | `AUDIT_UNAVAILABLE`, `DUPLICATE_SUPPRESSED`, `EFFECT_FAILED`, `AUDIT_COMPLETION_PENDING` | pattern only (INTENT before effect, COMPLETION after); the in-memory gate is not a code-level replacement for the durable ledger and checkpoint service |
| scheduler | `P2/scheduler.py` 92-137 | per source | memory | `IllegalTransition` | pattern (ACTIVE/PAUSED/QUARANTINED) |

Kill switch search (FACT, not exhaustive): no kill switch or disable-writes mechanism in `src` under any searched name. Nearest anchors: `living.sources.status` SUSPENDED/REVOKED with `scope_epoch` bump (001 lines 86, 90-100), `SourceStateMachine`, `PermitStore.set_prod_enabled`, deny-wins in `OperatorAuthorityPort`. An R1 "kill switch" in the decision log is a profile re-verify command, not a write stop. The scripts and config folders were not searched by content.

Gaps confirmed for S11-A..D: (1) no read/write authorization split: entitlement, ownership and permit are read-only booleans; (2) audit has only INTENT/COMPLETION with `EFFECT_FAILED`, no unknown-outcome state, in-memory obligations and request ids lost on restart; (3) the epoch is compared under a row lock in the DB only, no Python module compares a carried `scope_epoch` to a live store, and DB jobs have no company dimension; (4) no separation of field, movement, version and authorization evidence; (5) nearly all Python state is process-local, and `living.*` has no table for proposals, approvals, write grants or call ownership. Still NOT_VERIFIED: the R1 gateway write surface, evidence_attestation, release_migration, backend_budget, ports, the remaining drive modules, and `scripts/` and config content.
