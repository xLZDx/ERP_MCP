# Autonomous work packages WP4–WP10: dependency status — 2026-10-21

Repository revision observed before this turn's local edits: `4dfceeddb071a63e7d8f815e7c276555de6d2375`.
This note records which downstream packages can proceed from the evidence and controls
available in this turn. It does not claim qualification, a source write, a test run, or
production readiness.

| Package | Current state | Evidence | Remaining acceptance and dependency | Recommended next action / owner |
|---|---|---|---|---|
| WP4 — finish S12 and S13 | BLOCKED | `docs/phase2/OPERATOR_BACKLOG.md` current reconciliation says S12 local engineering is approved but formal qualification remains open. `docs/phase2/S13_MUTATION_AND_WRITER_PATH_INVENTORY_2026-10-17.md` records that the repository inventory is complete but the operational writer inventory is `UNKNOWN / NOT_RUN`; the bundled write port raises `NotWired`, while lifecycle preflight always returns `NOT_READY`. The 2026-10-22 static source-final grant/lock inventory reconciles identified mutation grants, helper/trigger effects, recovery-stage paths and UPSERT conflicts; it does not establish deployed effective privileges, a global viable lock order or the physical writer boundary. At the 2026-10-21 checkpoint strict SSH had not succeeded; the 2026-10-22 recheck now verifies the Ivan stack, but still finds no deployed ledger schema or physical writer boundary. | S12 still needs the formal disposable PostgreSQL/COM-clone qualification. S13 still needs effective deployed grant/owner evidence, a real writer-side stable-call-ID idempotency boundary, stale-epoch rejection, authoritative outcome lookup, quiescence barrier, a viable cross-path fence, and recovery-to-READY evidence. Ivan stack is the technical owner of the intended private service boundary; operator is accountable owner. No migration was applied in the WP0 recheck. | Continue implementation and qualification on the authorized disposable lane; reconcile the missing `change_ledger` schema and measured grants, then demonstrate the writer boundary on Ivan's licensed clone. Database, security, reliability and test agents own their later reviews and tests. |
| WP5 — key/signature registry and real signers | BLOCKED | WP1 recorded the operator's authorization to implement the registry; `core/DECISION_LOG.md` records that real signer and witness identities are still required before a first real write. Strict SSH and the Ivan stack are now verified, superseding the earlier 2026-10-21 connection failure. | Implement mandatory trusted-boundary receipt enforcement after the WP4 writer boundary is identified. Generate D9 signer and separate D10b witness on the licensed host, protect private keys with DPAPI, and register public keys only after verified host/account identity. No key was generated or printed in the WP0 recheck. | Continue local registry implementation and prepare licensed-host provisioning for the clone phase; the Ivan stack owns the host boundary, operator is accountable, and Codex implements the repository work. |
| WP6 — S14 1C write port | BLOCKED | The source inventory and CT14 evidence are limited to a measured COM purchase-receipt path on clone `818HA_p2diff`; the repo inventory says there is no operational writer/composition root. | Depends on WP4 writer fencing and WP5 signer identities. Clone qualification must prove create/post/unpost, marker integrity, stale-write refusal, expected movement effects, and no payment side effect. The current prompt authorizes writes only to the named disposable clones through the controlled path, after code completion and by the functional/E2E agents. No clone write was attempted in the WP0 recheck. | Complete WP4 and WP5, then implement against the frozen CT14 contract and run the mapped scenarios only through the authorized functional/E2E agents. |
| WP7 — S15 verification and reconciliation | BLOCKED | Depends on WP6 in the execution plan; no operational write port or new clone effects were produced. | Clone evidence must establish effects-based MATCH/FINDING reconciliation and unknown-outcome recovery without trusting a missing marker. | Resume after WP6 clone evidence exists; Codex implements and test agents author/run acceptance scenarios. |
| WP8 — S16 approval channel and S17 workbench | BLOCKED | Depends on WP7 in the execution plan. No new approval-channel or UI code was implemented in this turn. | Per-story approval and workbench behavior, with UI and accessibility review if the UI is changed. | Resume after WP7; Codex implements, functional/E2E agents test, and product UX/accessibility reviewers cover any UI change. |
| WP9 — optional Drive/G4 | DEFERRED; delete probe is BLOCKED | The WP1 decision entry records prior create/read/list/change-feed probe claims but no delete-probe evidence. The manifest remains G4 `NOT_PASSED` with Drive intake disabled. The task authorization explicitly excludes deleting data; a delete probe is therefore not authorized by this turn. | If the operator later authorizes deletion of only newly created probe files, the Drive route and scope must still be verified; OAuth token lifetime and scope concerns remain open. No Drive call or deletion was performed. | Keep Drive outside the critical path. Operator owns any future deletion authorization; the Drive connector owner must provide a verified route and scoped token. |
| WP10 — S18 reliability, security, canary, release | BLOCKED | Depends on WP6–WP8. Local and Ivan gateway source reads now work, but the WP0 comparison has a row-count mismatch and the running phase2 service has no outbound token providers; this is not canary evidence. Staging deployment is forbidden; explicit Git staging is allowed. | Requires clone reliability/capacity/recovery evidence, independent security review, operator UAT where a UI exists, the delegated read-only canary on the authorized source, exact-head test/reviewer evidence, GPT-PM approval, and operator-signed `PRODUCTION_GO` before any production authorization. | Resume after WP6–WP8 and reconciled source/tool routes. Codex coordinates; test and specialist agents provide evidence; operator retains UAT/production-signoff decisions. |

## WP3 registry generation dependency

The default `scripts/build_document_registry.mjs` mode inventories Markdown paths from
attached worktrees, including untracked files. This worktree contains protected
untracked user files, so default generation is not safe. Chosen policy: preserve the
default inventory contract and add an explicit `--exclude-local-only` mode for a
tracked-refs-only snapshot. It must not enumerate local untracked Markdown in that mode,
and the generated scope must state that local-only paths were excluded. This preserves
historical Git-ref documents without publishing protected worktree paths. Implementation
and generation have now completed. `node scripts/build_document_registry.mjs
--exclude-local-only` exited 0 at `33f76b7f4f49ae773b3f86876940c9c6234a636d`, scanned
46 Git refs, and wrote a snapshot with 422 tracked paths; local-only paths were
**NOT_ENUMERATED**. Its
scope explicitly says local-only files in attached worktrees were not inventoried; this
mode does not enumerate those files. Cyrillic in generated titles, paths, and ref names
is encoded with `\uXXXX` escapes. Functional acceptance for the new mode remains
**NOT_RUN** under the current no-tests policy. The registry is a development navigation
aid, not release evidence.

## Overall evidence state

Local listener liveness is runtime-observed. Source business reads, remote Ivan
checks, database qualification, licensed-host key provisioning, clone write tests,
Drive deletion, S15–S19 acceptance and production authorization are **NOT_RUN**.
The precise external access blocker for Ivan is the missing trusted ED25519 host key
for `ivan.tail08f9f9.ts.net`; strict verification was retained. The optional Drive
delete action is additionally blocked by the operator-only deletion boundary.

## Dated status addendum — 2026-10-22

This addendum supersedes the WP3 registry counts and source revision above; the WP4–WP10
dependency states remain as recorded unless their named external or authorization
dependencies change.

- At committed base HEAD `d82cfa4cd44b105608c294d742c84fa8cdbc950f`,
  `node scripts/build_document_registry.mjs --exclude-local-only` exited 0, scanned 46
  refs and 423 tracked Markdown paths, and recorded local-only paths as
  **NOT_ENUMERATED**. A later generation against committed base HEAD
  `3b439f2a59c1cb1b8a961b269eae190dceec6083` also exited 0 and observed 46 refs and 424
  tracked paths. The current generation against committed base HEAD
  `0fe023db1ec2adcf1820356db1dd1db09d23c3ab` exited 0 and observed 46 refs and 426
  tracked paths. The generated `governance/DOCUMENT_REGISTRY.md` contains no local-only path
  inventory. This is generation evidence, not functional acceptance; tests and `--check`
  remain **NOT_RUN** under the active restriction.
- WP0's 2026-10-22 read-only SSH recheck confirms matching local client-key fingerprints
  and a restricted inherited ACL, but does not establish remote authorization. Ivan's
  host key remains untrusted pending authenticated out-of-band confirmation; strict SSH
  stopped before authentication, so remote checks remain **NOT_RUN**.
- Targeted `docker ps` output observed the real1c PostgreSQL and Redis containers healthy
  with host bindings `127.0.0.1:18432` and `127.0.0.1:19379`. This is a point-in-time
  observation only; ownership/origin, database connectivity, and business reads were not
  established. No migration was run.
- Connected `ERP_MCP_REAL1` source/status calls returned `-32603`; `erp-mcp-chatgpt`
  returned `UNAUTHORIZED`. No business data was read. The Phase 2 MCP local handshake and
  tool listing succeeded, but do not prove a connected source route or release readiness.

The SSH, registry and container details are recorded in
`docs/phase2/artifacts/WP0_SOURCE_LIVENESS_2026-10-21.md`; current overall gate states and
the owner/dependency queue are summarized in `docs/phase2/OPERATOR_BACKLOG.md`.

## Superseding access and source recheck — 2026-10-22

`docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md` supersedes the stale
WP0 SSH/host-key and local-service claims above. Strict SSH to `koros@100.88.71.74` now
returns all nine Ivan stack components as `True`; local listeners 8088, 8191–8193, 18432,
19379, 21000, 21080, 21200 and 21768 were observed listening. Do not restart Apache or the
proxies. The 21200 process is the project `testlane.phase2_mcp` module through the Windows
venv launcher.

Read-only local and Ivan source calls both report healthy sources and machine-reconciled
labels, but the 521.1 reads have 15 and 16 rows respectively and an unequal private
in-memory comparison. The running 21200 server reports `GATEWAY_TOKEN_UNAVAILABLE` for its
outbound tokens; direct in-process reconciliation reports a one-row-count/one-difference
partial closing mismatch and gateway-tool errors for the six-column, purchase, and synthetic
negative-control sections. This is **NOT reconciled** and does not qualify WP0's comparison
acceptance.

The read-only PostgreSQL review found no `change_ledger` schema or functions in the disposable
database on 18432, so effective S13 grants remain **NOT_VERIFIED**; no migration was applied.
The recorded CT14 clone rights evidence is summarized in the new WP0 note and still has a
marker-integrity caveat. Operator is accountable owner; Ivan stack is the technical owner of
the remote host boundary. The next gate is repairing the 21200 outbound token provider and
resolving the source discrepancy, then completing S12/S13 on the authorized disposable lane.

### Capability-function effective grant follow-up — 2026-10-22

A read-only `database-reviewer` audit through the authorized lane environment connected as
`business_ai_admin`, `business_ai_app`, and `business_ai_control_api` separately. It confirmed
that the separate `change_ledger` schema is absent, so S13 effective grants cannot be read
from this database. A separate lookup also found no `bag.change_ledger` table; absence of
that table does not establish whether the other schema exists. On the existing `bag` schema,
all seven inspected routines were executable by the three
roles, and `bag.record_capability_observation(...)` also had effective `PUBLIC EXECUTE`.
The focused security review found no unauthenticated HTTP/MCP path; it rated the privilege
gap MINOR because a database identity with schema usage can write source-scoped capability
claims through the `SECURITY DEFINER` routine without source authorization in its body.
Migration 015 now removes the PUBLIC grant and retains the explicitly used app-role grant.
It is implemented but **NOT_RUN / NOT_RUNTIME_VERIFIED**; only the functional/E2E roles may
qualify it after coding is complete. No other lane's `bag` grants establish Ivan or production
access.

## S13 database review addendum — 2026-10-22

At source HEAD `0fe023db1ec2adcf1820356db1dd1db09d23c3ab`, a read-only database review
reconciled identified source-final grants and traced the corresponding helper/trigger
effects. It confirmed that `validate` takes a row lock before a named advisory lock and
alphabetical event-trigger order requests the event-chain advisory lock before the lifecycle
row; a path may already hold that lifecycle row before appending the event. These facts
show that the documented global order is not established, but do not
prove an active deadlock cycle while recovery is disabled. Keep recovery refusal and
lifecycle `NOT_READY`. The detailed source map, explicit grant chronology and lock trace are in
`docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`. The database
reviewer, reliability and security reviewer roles should review the eventual complete
proposal. The operator's latest correction identifies Ivan stack as technical host/system
owner for the private writer boundary and the operator as accountable task owner; no
individual human contact for deployed evidence is named in the repository records.

### Business-key mutation follow-up — 2026-10-22

At the same source HEAD, a targeted read of `declare_business_key` and `validate` found that
both lock the parent record, but only `validate` takes the named business-key advisory lock;
`declare_business_key` can update `key_hash` without that lock. This is a source-level
concurrency concern, not proof of an incorrect production outcome or active deadlock. The
operator's latest correction assigns Ivan stack as technical host/system owner and the
operator as accountable task owner; no individual contact to provide deployed grant evidence
or confirm the transaction boundary is named.
The focused source evidence and design prerequisites are recorded in
`docs/phase2/S13_BUSINESS_KEY_LOCK_ORDER_NOTE_2026-10-22.md`. Do not change the historical
function definitions or propose an additive migration until a complete old/new-key lock-order
design covers both functions and the remaining mutation/trigger paths. Tests, migration
execution and runtime database access remain `NOT_RUN`.

## Current autonomous continuation — 2026-10-22

The operator's latest verified answers supersede the 2026-10-21 SSH and service ownership
statements above. Ivan's key is already trusted for `koros@100.88.71.74`; the Ivan stack
(`ERP_MCP_Ivan_Stack`) is the technical owner of the host/connection boundary and the operator
is accountable for the delegated task. The project-venv `testlane.phase2_mcp` listener on 21200
is the intended process and must not be replaced during coding. The user confirmed the private
writer design direction: separate service on Ivan's licensed lane, loopback/authenticated
Tailscale only, starting with a disposable `818HA_p2diff` clone.

The current S13 design is recorded in
`docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md`. Architecture review found no
contradiction with S12; database review found that the current source does not establish a viable
all-path lock order or mutation fence. In particular, event-chain/lifecycle lock order, record
versus business-key advisory locks, verifier-key receipt locks, recovery/kill-switch sweep locks,
unique-index `ON CONFLICT` waits, and granted APIs outside lifecycle coverage must be reconciled
before an activating additive migration. The database epoch and
private service's durable admission/barrier must form one protocol. Recovery therefore remains
`NOT_READY`; no migration, effective deployed-grant claim, S13 implementation, or physical COM
writer qualification is complete. The local disposable PostgreSQL endpoint inspected read-only
contains no `change_ledger` schema/functions, so effective S13 grants there are `NOT_VERIFIED`.
On 2026-10-22, Codex independently repeated the read-only check through the project virtualenv,
loading the admin DSN in process from `LaneEnv` without printing it. In a read-only transaction,
the query captured `current_database()`, `session_user`, and `current_user`; inspected the four
lane roles in `pg_roles`; queried `information_schema.role_table_grants` for
`table_schema='change_ledger'`; and evaluated `has_function_privilege(current_user, p.oid,
'EXECUTE')` for functions in that schema. The connection was to database `business_ai` on the
disposable local endpoint, with session/current role `business_ai_admin`; the role rows matched
the read-only review, and the table-grant and function result sets both had zero rows because the
schema is absent. This is not evidence about grants after S13 migrations or on Ivan's host. No
migration was run.
The S12 freeze also records a receipt-to-independent-read-back target/version clarification whose
exact-revision GPT review is still pending; this approval is separate from S12's disposable
qualification and formal gate.

WP5–WP8 and WP10 remain dependency-ordered as follows: WP4 implements the S12/S13 contract and
private service boundary against an injected writer port; WP5 adds receipts and the signer
registry; WP6 implements the physical COM write port and S14 disposable-clone qualification; WP7
adds effects-based verification/reconciliation; WP8 adds the approval channel, MCP surface and
workbench; WP10 completes reliability, security review and release-candidate evidence after
WP6–WP8. WP9 remains optional and outside the critical path. The S12/S13/S14 formal qualification
and acceptance record is finalized only after all in-scope WP4–WP8 and WP10 coding is complete and
the functional/E2E and specialist evidence is available. This supersedes the earlier shorthand
in this artifact that placed physical COM implementation inside WP4 acceptance; historical
entries above are retained as records of the earlier sequence. No key was generated and no clone
write or migration was performed in this continuation. Queue: complete remaining WP2/WP3 coding
and documentation; implement WP4 S12/S13 service foundation; proceed through WP5, WP6/S14, WP7,
WP8, then WP10; run required functional/E2E and specialist verification after all in-scope coding;
then record final S12/S13/S14 acceptance. Preserve `NOT_READY` until its actual evidence exists.

### S13 exact-review corrections — 2026-10-22

An exact-patch GPT review identified a dependency inconsistency and an obsolete mutex test
description. The plan above now separates the WP4 S13 service foundation (injected writer port)
from the WP6 S14 physical COM adapter and defers final S12/S13/S14 acceptance until the
dependency-ordered coding and qualification evidence is complete. The contention scenario now
uses the proposed private singleton mutex row acquired with `SELECT ... FOR UPDATE NOWAIT`; a
caller-held unrelated transaction advisory lock is adversarial setup, and refusal requires full
top-level rollback/discard before a subsequent writer proceeds. This is a documentation correction
only; no mutex, migration, COM adapter, or runtime qualification was implemented here.
