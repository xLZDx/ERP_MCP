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

## 6. R1 gateway write surface, R2 scripts and config (2026-10-12, read-only agent; agent-reported, not independently verified)

R1 root `D:\Repo\ERP_MCP-integration-candidate`, package `src/business_ai_gateway`. Git HEAD and dirty state of both repos were not checked.

- MCP tools: about 25 `@mcp.tool` functions (`server.py` 277-2150), all annotated read-only (`readOnlyHint=True`, `destructiveHint=False`, lines 89-91), scope `onec:read`. No tool name suggests a write. `onec_read` writes only gateway state (capability cache, audit rows), not 1C. The grep that listed the tools was capped, so the full tool list is NOT_VERIFIED.
- 1C adapters: `adapters/onec/client.py` uses GET and HEAD only (lines 73-162); the sidecar and COM-bridge clients POST JSON read RPCs (`sidecar_client.py:261`, `com_bridge_client.py:96`); the server side of the sidecar and COM bridge is not in R1, so it is NOT_VERIFIED that they cannot write. No OData write verb and no COM write call (Записать, Провести) was found in `adapters/onec`.
- Guard: `models.py:28-34` refuses a source with `read_only` false.
- Admin API: about 25 mutating HTTP routes (`admin_api.py:1725-1842`, handlers in `admin_mutations.py`) write only Postgres `bag.*` state (sources, grants, role bindings, capability overrides); they need a separate admin audience and scope and the flags `BAG_ADMIN_API_ENABLED` and `BAG_ADMIN_MUTATIONS_ENABLED` (both default False); sources are created `read_only=True`. They are HTTP routes, not MCP tools.
- Authentication to 1C: per-source HTTP Basic (secret references) or a Bearer token to a sidecar or COM bridge; egress limited to allowed CIDRs; redirects are errors; inbound MCP auth is OAuth (JWKS, audience, scope).
- R2 scripts (`scripts/remote/*.ps1`): the stack starter, the scheduled task `ERP_MCP_Ivan_Stack` (a disable path by unregistering the task, inferred), the tunnel runner, a token minter issuing a roughly ten-year TEST read token (a lifetime risk, test only), reader and admin DPAPI storage scripts (the admin identity is for the CT14 COM spike on a disposable base), the OData publication and repoint scripts. `lane_proxy.py` (the "read-only GET/HEAD" proxy) lives on the host and was not read, so it is NOT_VERIFIED that it blocks writes. `pyproject.toml` is the only config file found.
- Consequence for the plan: R1 exposes no write path of its own to reuse or to close; the write service is entirely new (D4). The one write-capable identity near the lanes is the admin DPAPI blob for a disposable base, which must never become the write-service identity (TM20).

## 7. OB-15 donor and license inventory state

FACT (agent-reported): OB-15 is defined in `OPERATOR_BACKLOG.md` line 28; no inventory document exists; `S10_RELEASE_HANDOFF.md` line 163 states that no donor code was found in `src/business_ai_gateway/phase2`; `DECISIONS_AND_SOURCES_RU.md` line 51 names the earlier-inspected PDCC connector donors (Gmail, Slack, Telegram) and requires a repeat pin and audit; no LICENSE or NOTICE file at the R2 root; Python runtime dependencies are asyncpg, defusedxml, httpx, PyYAML; dev dependencies are pytest, pytest-asyncio, ruff, jsonschema; the test-lane extra is mcp and uvicorn. NOT_VERIFIED: the license of each dependency (nothing in the files states them), any lock file or SBOM, and the licenses of host binaries (Apache, PostgreSQL, Redis, the tunnel client, the 1C platform).

Missing before the operator can approve OB-15: an inventory table (donor repo and path, pinned commit, license, copied or adapted or referenced, GPL/AGPL boundary), a confirmed license table from resolved package metadata, the S0 re-pin of the PDCC donors, a statement on host binaries, a LICENSE or NOTICE for R2, and a recorded operator approval entry. This pass produced no approval; OB-15 stays open and operator-owned.

## 8. Bridge, proxy and sidecar write-capability check (read-only agent; agent-reported, not independently verified)

- R1 COM bridge (6 files grepped: `session.py`, `runtime.py`, `__main__.py`, `config.py`, `app.py`, `query.py`): no write, post or delete call; the only 1C calls are `Dispatch("V83.COMConnector")` and `Connect(...)` (`runtime.py:54-56`) and a query execution on a fixed template (`query.py:86-92`). The 1C-side rights of the account the bridge connects with are NOT_VERIFIED (the code only ever reads, but a write-capable account would make the object model reachable).
- Sidecar server: only the test fake was found (`src/business_ai_gateway/testbed/fake_sidecar.py:85-135`): two POST routes (capabilities and read), operations limited to `query`, `count`, `register_read`, anything else returns 400; its token check is a plain comparison and is skipped when no token is set (test fake only). The real 1C-side sidecar server was not found in the R1 repository (NOT_VERIFIED; it probably lives outside R1).
- Gateway clients: `sidecar_client.py:121-197` sends `entity_get`, `register_read`, `register_capabilities` (POST is transport, not a write); `com_bridge_client.py:90-96` posts only to the balance route; loopback URLs only, no redirects.
- Lane proxy: `lane_proxy.py:65-69, 101` (one review export copy) accepts all methods but refuses non-GET/HEAD in code; the live copy launched by `run-mcp-stack.ps1` was not located, so the enforcement on the host is NOT_VERIFIED.
- Correction to an earlier agent claim: the accurate statement is that `living.*` has no write-grant, proposal or call-ownership table (`role_scope` is a read and context grant map), not that it has no grants table.

Explicit exclusions from the S11 inventory (recorded so the inventory can be called complete for its declared purpose): the nine R2 host scripts not read (`set-tunnel-secret`, `setup-mcp-data`, `setup-mcp-venv`, `install-mcp-runtimes` partially, `discover-host`, `verify-1c-env`, `bootstrap-local`, `phase2_capacity_drill`, `build_spec_bundle`), the real sidecar server, the live lane proxy and the 1C-side rights of the bridge and OData accounts. None of them is part of the governed write path: the write service is a new component (D4), uses its own least-privilege identity, and does not reuse the read lanes. Each exclusion becomes an inventory item again if a future design reuses that component, and the host-side items belong to deployment qualification, not to S11.

## 9. OB-15 donor and license inventory (DRAFT for the operator; agent-reported plus read-only checks by the main session)

Python dependencies (versions installed in the sibling R1 venv, not an R2 resolution; R2 has no venv, lock file or SBOM): asyncpg 0.31.0 Apache-2.0; defusedxml 0.7.1 PSF; httpx 0.28.1 BSD-3-Clause; PyYAML 6.0.3 MIT; dev: pytest 9.1.1 MIT, pytest-asyncio 1.4.0 Apache-2.0, ruff 0.16.10 MIT, jsonschema 4.26.0 MIT; test-lane extra: mcp 2.3.0 MIT, uvicorn 0.54.0 BSD-3-Clause. All are permissive; none is GPL or AGPL. NOT_VERIFIED: transitive dependency licenses, setuptools and wheel, the `License-File` texts. Node scripts import only `node:` built-ins (no third-party package).

Donors: three PDCC connector paths are named as previously inspected donors (Gmail history runtime, Slack connector, Telegram connector) and the S10 handoff states that no donor code exists in `src/business_ai_gateway/phase2` (comments only); this was not independently confirmed by a code-similarity check. One file is adapted: `scripts/build_document_registry.mjs` from the PDCC document-registry tool (PDCC commit `ebf10414aaa8ef858a3df82652fb2050141adc98` as pinned in the file header). Read-only check of the donor repository by the main session: `D:\Repo\Personal_Decision_Command_Center` is the operator's own repository, HEAD `18f9b8d6ef150e2a3ed2bc64f0a88e1c2b157fa2`, it has no LICENSE, NOTICE or COPYING file, last commits per donor path: gmail-connector `28855b383cc2cfe348d8da1598fd3c6f6685d225`, slack-connector `897bc52d71a05c5ba732cc3aa08dcf9205780eb1`, telegram-connector `2951a7bb762706ee419cb759ec129d91b57b576a`. Consequence: the donors carry no third-party license; they are the operator's own code, so no GPL/AGPL boundary arises from them; the reuse basis is the operator's standing rule that code from any project may be reused read-only with origin recorded.

Host binaries named by the install scripts (versions, sources and licenses mostly NOT_VERIFIED; downloads are unpinned and carry no checksums): Apache httpd with the 1C web extension, PostgreSQL 16 (EDB zip), Redis for Windows 5.0.14.1 (tporadowski build), Node.js 24.x, the OpenAI tunnel client, the 1C platform (proprietary, licensed by the operator). No LICENSE or NOTICE file exists in R2 and `pyproject.toml` has no license field.

Missing for the operator's approval of OB-15: a resolved license table from an R2 environment (a lock file or SBOM), transitive and build-tool licenses, a code-similarity statement for the donor claim, license and pin facts for the host binaries with checksums, a LICENSE or NOTICE for R2 and a license field, and the recorded operator approval entry. This pass produced no approval; OB-15 stays open and operator-owned.

Current status (2026-10-13): OB-15 is still OPEN. The operator answered "accept" in chat without qualification; that is recorded as DRAFT_ACKNOWLEDGED only, not as acceptance of a complete inventory, because the items listed as missing above are still missing. INVENTORY_ACCEPTED and LICENSE_BOUNDARY_APPROVED are NOT granted. The statements "OB-15 stays open" in sections 7 and 9 remain accurate. See `OPERATOR_BACKLOG.md`.

### 9a. Resolved license table (added 2026-10-14)

Method: the license field of each installed distribution's metadata (License-Expression, else License classifiers, else the License field), read with `importlib.metadata` in the sibling R1 environment `D:\Repo\ERP_MCP\.venv`, following Requires-Dist transitively from the declared roots (asyncpg, defusedxml, httpx, PyYAML, mcp, uvicorn, pytest, pytest-asyncio, ruff, jsonschema). Limits: this is the R1 environment, not an R2 lock file or SBOM (R2 still has none); versions are the installed ones; metadata fields are what packages declare, the `License-File` texts were not read; Windows-only and extra-conditional dependencies are included only if installed.

| package | version | declared license |
| --- | --- | --- |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| asyncpg | 0.31.0 | Apache-2.0 |
| attrs | 26.1.0 | MIT |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| defusedxml | 0.7.1 | Python Software Foundation License |
| h11 | 0.16.0 | MIT License |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpcore2 | 2.13.1 | BSD-3-Clause |
| httpx | 0.28.1 | BSD License |
| httpx2 | 2.13.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| mcp | 2.3.0 | MIT License |
| mcp-types | 2.3.0 | MIT License |
| opentelemetry-api | 1.45.0 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pluggy | 1.6.0 | MIT License |
| pydantic | 2.13.5 | MIT |
| pydantic_core | 2.46.5 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| PyJWT | 2.15.1 | MIT |
| pytest | 9.1.1 | MIT |
| pytest-asyncio | 1.4.0 | Apache-2.0 |
| python-multipart | 0.0.32 | Apache-2.0 |
| pywin32 | 312 | Python Software Foundation License |
| PyYAML | 6.0.3 | MIT License |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.9.1 | MIT |
| ruff | 0.16.10 | MIT |
| sse-starlette | 3.5.0 | BSD-3-Clause |
| starlette | 1.7.0 | BSD-3-Clause |
| tomli | 2.4.1 | MIT |
| truststore | 0.10.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |

Result: 41 distributions, no GPL or AGPL. One weak-copyleft entry: `certifi` (MPL-2.0, file-level copyleft; used unmodified as a dependency, no file of it is copied into R2). Not installed in that environment, so their licenses are NOT_VERIFIED: async-timeout, backports-asyncio-runner, exceptiongroup, httpx2-jsfetch.

This table closes the item "resolved license table" and the "transitive licenses" part of the missing list above, for the R1 environment only.

### 9b. Donor code-similarity statement (added 2026-10-14)

FACT (checked by the main session, read-only): the pinned donor commit `ebf10414aaa8ef858a3df82652fb2050141adc98` exists in `D:\Repo\Personal_Decision_Command_Center`, and the blob `scripts/tools/build-document-registry.mjs` at that commit has the id `b581feac23e4caea5c056a71dd0587cc7c58eef0`, exactly as the provenance header of `scripts/build_document_registry.mjs` states. A comparison of trimmed, de-duplicated, non-empty lines: the donor has 134, the R2 file has 174, and 33 are identical (about 25% of the donor lines, about 19% of the R2 lines). This is a line-overlap measure, not a semantic or legal analysis. It is consistent with the header's list of substantial changes.

FACT: a search of `src` and `scripts` of R2 for the donor paths `gmail-connector`, `slack-connector`, `telegram-connector`, `Personal_Decision_Command_Center` and `PDCC` finds only the provenance header above and comments in `phase2/drive_oauth.py` and `phase2/drive_port.py` that state no PDCC code or token is used. No connector code from the three named donor paths was found. This was a text search, not a code-similarity tool run.

INFERENCE: the only donor-derived code in R2 is the one adapted registry script, and the donor repository is the operator's own code without a third-party license (section 9, read-only check of 2026-10-12).

Still missing for OB-15: an R2 lock file or SBOM, license and pin facts with checksums for the host binaries, a LICENSE or NOTICE for R2 with a license field, and the operator's explicit acceptance or named deferral.
