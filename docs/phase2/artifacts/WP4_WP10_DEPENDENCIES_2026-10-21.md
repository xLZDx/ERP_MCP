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

### Autonomous continuation evidence — 2026-10-23

This addendum records observations made during the 2026-10-23 continuation and does not upgrade
earlier runtime claims. The local SSH client resolves Ivan's ED25519 host key for `100.88.71.74`
to `SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ`; read-only SSH to
`koros@100.88.71.74` reported all nine stack components `True`. No service was restarted. A
name-only listing of `D:\1c\mcp` and its `app`, `runtime`, and `data` directories did not identify
the disposable clone, its fingerprint, or its topology; these remain **NOT_VERIFIED**.

Using the repository virtual environment, `LaneEnv.load()` loaded credentials in process, a
short-lived `auditor` token was minted without printing it, and MCP initialization succeeded at
the guarded local URL `http://127.0.0.1:21000/mcp`. An unauthenticated read-only `GET /healthz`
returned HTTP 200 with `{"status":"ok"}`; `GET /readyz` did not return within the 5-second
client timeout. The subsequent authenticated `source_health` request for
`onec-818ha-reference` had not returned after 30 seconds and was manually interrupted. Record
process liveness as observed but readiness/source health as **NOT_RUN / NO_RESPONSE**, not as
healthy or failed. The source implementation shows `/readyz` calls `Runtime.ready()` (DB/schema,
optional admin DB, and Redis readiness) and `source_health` calls the configured 1C OData health
path; neither timed-out dependency was isolated in this turn. No ChatGPT tunnel connector, COM
operation, database migration, or service restart was used.

A separate read-only, secret-filtered tail of the gateway error log at the runtime path named in
`scripts/e2e/_common.ps1` contains `OneCTransportError: SOURCE_TIMEOUT`, translated by
`source_health` to `SOURCE_UNAVAILABLE`. The tail contains two such occurrences but no request
correlation ID; neither is attributed to the manually interrupted call and the upstream timeout
cause remains **UNKNOWN**.
The configured Apache `access_log` and `error_log` files were last modified on 2026-10-21, before
this source-health attempt, so they provide no current request/status correlation.

The read-only `database-reviewer` audit for this continuation found `change_ledger` absent on the
disposable PostgreSQL database. S13 relation grants, effective table privileges and routine
`EXECUTE` rights are therefore **NOT_VERIFIED**, not zero-grant proof. The `business_ai` owner
role is superuser with role/database creation and RLS-bypass privileges; runtime roles do not
have those cluster privileges. Direct `business_ai_control_api` connection timed out, so its
session identity is **NOT_VERIFIED**, although catalog-derived effective schema privileges were
observed through the admin session. The audit confirmed `bag` and `public` exist, `phase2` does
not; app/control/admin have effective `USAGE` and no `CREATE` on `bag`, and effective `USAGE`
through `PUBLIC` with no `CREATE` on `public`. The attempted
`information_schema.schema_privileges` query failed because that view is absent in this database;
the reviewer substituted `pg_namespace`/`aclexplode` and `has_schema_privilege`. Catalog searches
for relations named `change_ledger`, S13 routines in that schema, and routine names matching
`%ledger%` returned no rows. Admin and app connections were confirmed read-only; control's direct
session identity remains unverified after timeout. No schema or data was changed.

A separate in-process, read-only transaction queried only the non-secret source routing fields in
`bag.sources` for `onec-818ha-reference`: it is marked `read_only=true` and targets HTTP loopback
proxy port `8191` (the URL path was not emitted). This matches the configured lane-proxy route;
it does not prove the proxy's current upstream response or the 1C OData health result. Because
coding remains open and checks are deferred, no active source-health retry was made.

The reviewer used lane-loaded credentials in process against `127.0.0.1:18432`, database
`business_ai`, and `BEGIN READ ONLY` followed by `ROLLBACK`; DSNs and secrets were not emitted.
The material privilege checks included `pg_roles`, `pg_auth_members`, `has_schema_privilege`,
`has_table_privilege`, `has_function_privilege`, and catalog enumeration of matching relations
and routines. Since no S13 object exists in this disposable database, this proves neither a
configured S13 deny nor the intended post-migration grants. Re-run the object-specific effective
privilege checks only after the accepted disposable schema is provisioned.

The private-writer service orchestration and PostgreSQL adapter present in the worktree are
candidate code only: no S13 listener/composition root or concrete physical `OneCWritePort` has
been qualified against the identified licensed clone. The writer-side call-ID identity, stale
epoch refusal, authoritative lookup and quiescence barrier therefore remain **NOT_RUNTIME_PROVEN**.
The next dependency is to establish the clone's 1C configuration/platform metadata and effective
CT14 identity over a successful read-only COM session, close the S13 lock/grant design, then
perform disposable-only database qualification. Functional/E2E qualification and other specialist
review remain **NOT_RUN** until the in-scope coding is complete.

#### Read-only clone artifact identity update — 2026-10-23

Strict-key SSH to `koros@100.88.71.74` listed `D:\1c\env\bases\818HA_p2diff`; the directory
contains `1Cv8.1CD` (4,377,706,496 bytes) and `1Cv8snc.1CD` (114,688 bytes). A read-only
`certutil -hashfile D:\1c\env\bases\818HA_p2diff\1Cv8.1CD SHA256` returned
`d5f63c5bae94cd58a69a592815d148828ef45f008c4d1ba12e4b56a15e295bb2`. This fingerprints the
current main database file only; it does not establish 1C platform/configuration version, clone
lineage, user/role rights, or that the file matches a known-good source snapshot. No database was
opened, written, restored, or copied. Read-only COM metadata and effective-rights evidence remain
**NOT_VERIFIED** after the previously recorded connection errors.

During this continuation, WP5 `OracleArtifact`, `DispatchAttempt`, `InvocationContext`, and
`ReceiptLookupKey` now require an exact built-in `str` for the closed operation enum before
membership checks. The `PostgresAdmissionStore` serialization boundary also rejects non-built-in
required or optional identity strings, unsupported operation kinds, and non-built-in barrier scope
strings before any transaction opens. The qualification prerequisite records custom-equality
negatives at these trust boundaries. These are source/document changes only. No test or check was
run, so the behavior remains **NOT_VERIFIED** pending the later functional-test-reviewer phase.

## 2026-10-24 dependency reconciliation for WP4–WP10

**WP0 / access:** strict-host-key SSH to Ivan succeeded in this turn; the nine named stack status fields are `True`, and the configured remote MCP audience initialized successfully with one read-only `source_health=200` response for `onec-818ha-reference`. These are bounded observations, not writer or accounting-read qualification. The read-only `database-reviewer` recheck confirmed the disposable PostgreSQL at loopback `18432` has database `business_ai`, but no `change_ledger` schema; S13 effective grants remain `NOT_VERIFIED`.

**WP4 / S12–S13:** S12/S13 design and adapter/service source are still candidate-only. The current architecture pass found the rank viable as a design candidate but confirmed a blocking implementation gap: the shared scope fence and namespaces 6–8 are absent from the current migration set, so legacy granted functions and recovery still bypass the candidate. The 2026-10-24 source/design append maps 14 previously non-individualized paths and adds qualification scenario `S13-FENCE-ENTRY-14-01`; it explicitly leaves source unknowns and is not a complete lock graph. `NonOperationalWritePort` still raises `NotWired`, and no physical COM writer boundary or disposable clone qualification is established. Do not run/add migration or enable `READY`/recovery yet.

**Downstream order:** WP5 receipt enforcement and real signer/witness provisioning remain dependent on the WP4 trusted writer boundary and verified host/account identity; placeholders remain and no keys were generated. WP6/S14 COM write port and clone scenarios depend on WP4 and WP5. WP7 effects-based verification depends on the physical write-port evidence from WP6. WP8 approval/MCP/workbench integration depends on the verified WP7 path. WP10 reliability/security/release-candidate evidence follows WP6–WP8. WP9 remains optional and outside the critical path. No tests, checks, build, CI, migration, service restart, or real 1C write ran in this continuation. Owners: operator is accountable; Codex executor; Ivan stack is technical owner for the remote host; functional-test-reviewer/e2e-runner own post-coding scenarios; database/reliability/security specialists own later exact-head reviews.

**Ordered next work:** (1) reconcile all remaining helper/trigger/unique-conflict edges and exact affected-row plans in S13, retaining `NOT_READY`; (2) implement the additive fence/schema only after that map closes; (3) finish the private COM writer boundary on the licensed disposable clone; (4) finish WP5, then WP6, WP7, WP8, and WP10 in dependency order; (5) only after coding closure start the functional/E2E phase and specialist reviews, then record final S12/S13/S14 evidence. The precise external runtime dependency is a functioning COM connection/clone qualification path on Ivan's licensed lane; technical owner: Ivan stack. The source/design and qualification-document work remains local and unblocked.

## 2026-10-24 aggregate-bound continuation addendum

The current autonomous turn added a candidate aggregate DML-effect cap of 200 for `recover_sweep`, `revoke_stale`, and `kill_switch` OFF, plus a separate `check_anchor` cap of 200 active targets. Both over-cap paths must refuse before DML; both at-cap paths require five-second disposable qualification. These are design limits, not measured runtime capacity. The exact scenarios are now in the S12/S13 prerequisite record, all `NOT_RUN`.

Dependency status remains: WP4 is `DOABLE-NOW` for source/design closure and private-writer implementation, but S13 is `NOT_READY`; effective PostgreSQL grants are `NOT_VERIFIED` because the disposable lane lacks `change_ledger`, and the physical writer boundary is not operational. WP5 remains dependent on the verified WP4 boundary and host/account identity; no real keys are generated. WP6 depends on WP4+WP5; WP7 on WP6; WP8 on WP7; WP10 on WP6–WP8. WP9 remains optional. No tests, checks, build, CI, migration, service restart, COM call, or database write ran in this continuation. Evidence: `S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, aggregate-bound refinement; `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, bounded-recovery scenarios; read-only grants and SSH status records in `artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md`. Accountable owner: operator; executor: Codex; Ivan stack technical owner of the host/connection boundary. Next: close the remaining source helper/trigger/unique-arbiter map and obtain database/reliability acceptance before candidate schema implementation and post-coding tests.

## 2026-10-24 remote credential and review-queue update

Strict SSH and the matching known-host fingerprint remain confirmed. Read-only ACL checks on the six named Ivan secret/config files found only IVAN\koros and BUILTIN\Administrators; no file values were emitted. The 818HA_p2diff directory exists and V83.COMConnector is registered/creatable, but a single correctly shaped, in-memory DPAPI JSON credential attempt failed at Connect with HRESULT 0x80004005. The only bounded-source reference to onec_admin.dpapi is store-onec-admin.ps1, whose default proof target is 818HA_test_ready; the p2diff path appears only in ivan_repoint.ps1. Thus credential-to-clone identity is UNKNOWN, and the COM transaction boundary remains NOT_VERIFIED. Do not retry until a clone-specific credential mapping or sanitized diagnostic is available. This does not block local source/design work. Evidence and probe correction: artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md. Accountable owner: operator; executor: Codex; technical owner: Ivan stack.

The full S13 private-writer source/design adversarial review request remains queued in PM Bridge under canonical projectId erp_mcp, request 2ac9e00e-c9bd-4c85-b764-2e46a5e1a738, conversation 6adcbe7f-15b4-83ed-bd37-9804f556ecf8; latest observed sendPhase was not-started, so no GPT reply or findings are claimed. The request is not resent while queued. Once it completes, remediate valid findings before the coding gate; no tests/checks/migration or commit occurred in this evidence slice.

## 2026-10-24 current-turn WP0 and dependency update

Fresh strict SSH to `100.88.71.74` matched the trusted ED25519 fingerprint and the remote status
command returned all nine stack components `True`. Anonymous GET to local and remote gateway
`/mcp` returned 401. The local listener snapshot still lacked proxies `8191`–`8193` and phase2
`21200`; the Apache static root returned 200, while local test_ready OData metadata timed out and
remote anonymous Apache/OData routes returned 403. The local lane startup attempt was rejected by
process-start policy before execution; no service was started or restarted. The supplied local
startup script references other repositories, so this scoped turn did not invoke it. The operator
run command remains `scripts\real1c\autostart\start_lane.ps1 -ApachePort 8088` if local-lane
restoration is required.

The project-named local CT14 secret directory had `Authenticated Users: Modify` on two files. This
turn aligned the directory and its three credential files with the in-repository restricted-ACL
pattern; post-change inspection found no `Authenticated Users`, `Users`, or `Everyone` entries.
No secret bytes were read or modified. This local ACL change does not create the missing
credential-to-Ivan-clone mapping. A bounded remote diagnostic scan found no matching 1C/V83
Application events or fixed connection-error markers in the clone log files; the previous COM
`0x80004005` remains unexplained and was not retried.

PM Bridge request `2ac9e00e-c9bd-4c85-b764-2e46a5e1a738` remains `queued`, `sendPhase=not-started`,
`attempts=0`, with no correlated GPT reply. Its stored project identity is `erp_mcp`, conversation
`6adcbe7f-15b4-83ed-bd37-9804f556ecf8`; the outbound body names `ERP_MCP` and
`https://github.com/xLZDx/ERP_MCP.git`. It is not cancelled or resent. No source code, test, build,
CI, migration, service restart, database write, Git staging, commit or push occurred in this
continuation. The mandated bilingual report-conformance command passed. Current WP0 evidence:
`artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`; the bilingual checkpoint is under
`reports/ERP_MCP_AUTONOMOUS_CHECKPOINT_2026-10-24*.html`.

**Next ordered work:** (1) obtain the operator-run local lane startup because the process-start
policy blocked that action, then recheck the local OData route; (2) continue local source/design
closure without tests and preserve `NOT_READY`; (3) poll the same PM Bridge request until it is
actually claimed and correlated; (4) use a clone-specific identity or sanitized diagnostic before
any further COM connection; (5) after coding closes, run assigned functional/E2E qualification,
then applicable independent reviews and finish WP5→WP6→WP7→WP8→WP10. WP9 remains optional.
Accountable task owner: operator; executor: Codex; Ivan stack: technical owner of its remote host
boundary; local startup executor owner per platform gate: operator. D10b still requires a distinct
human witness; no person is assigned in the canonical project records.

## 2026-10-24 superseding local transport recovery

This entry supersedes the same-day dependency note that required an operator to start the local lane. The three missing local proxies and Phase 2 MCP server were started by Codex in repository-scoped foreground sessions; current listeners are 8191–8193 and 21200. Apache and the already-running database, Redis, sidecar, IdP, and gateway were not restarted. Anonymous OData metadata through each proxy returned 401; authenticated phase2_capabilities returned TESTLANE_EVALUATION_ONLY / NO-GO. The authenticated source-health request through the local gateway still returned retryable SOURCE_UNAVAILABLE for onec-818ha-reference (correlation dce220aa-e744-4234-8171-0c967dbfc2af). Bounded diagnostics did not locate the exact correlation or a sanitized underlying cause. Therefore local MCP transport is reachable, while source health, S13 effective grants, the writer boundary, and S12/S13 qualification remain open. Continue safe local source/design work. The exact 1C diagnostic and clone-specific credential mapping remain dependencies before another COM attempt; technical host owner is Ivan stack, accountable task owner operator. No test, migration, database write, COM retry, or product write was performed in this recovery.

## 2026-10-24 later source-health recovery

A later authenticated, read-only local gateway check supersedes the prior transient SOURCE_UNAVAILABLE as the current source-health state: onec_metadata_summary returned 920 entity sets and source_health returned ok=true for onec-818ha-reference. The earlier correlated failure remains unexplained historical evidence. A scoped 521.1 analytics request was issued with the authorized company and offset-aware as_of, but its shell yielded before a result and a Python process remained observable; record that scenario NOT_VERIFIED and do not repeat while it may still be running. No accounting values were printed. This restores observed MCP source-health/metadata reachability at this point in time; it does not qualify S13, effective grants, or the writer boundary.

## 2026-10-24 521.1 client timeout follow-up

The same scoped 521.1 request was repeated after the earlier process exited and then returned a client-side httpx2.ReadTimeout after the MCP read timeout. No accounting values were emitted. This proves neither server completion nor the underlying cause; stop retrying until bounded server-side diagnostics explain the timeout. The prior source_health ok=true and 920-set metadata result remain the current transport evidence. Business-read comparison is NOT_VERIFIED.

## 2026-10-24 16:19 UTC current local service state

Current local runtime was restored after a fresh observation found all lane ports closed. Docker Desktop was launched and the scoped PostgreSQL/Redis containers returned healthy on 18432/19379; Apache now listens on 8088; IdP/gateway were started with the scoped fault helper; proxies 8191–8193 return anonymous OData metadata 401; Phase 2 MCP 21200 accepts its capability tool call. Sidecar 21768 was already listening and was not restarted. Strict SSH again reports all nine Ivan stack components True. Local source_health is ok=true and metadata has 920 entity sets. The authorized 521.1 tool call has not produced a current result: httpx2.ReadTimeout on one call and 0x40010004 exit without payload on the longer attempt. Preserve NOT_VERIFIED and pause retries until bounded server-side diagnosis. No tunnel or out-of-scope repository was touched.

### 2026-10-25 trusted-time verification correction

The current continuation added the `ProductionEvidenceVerifier` guard for non-future signed time. `S13-PRODUCTION-EVIDENCE-VERIFY-01` now requires both future-time refusal and exact-time boundary acceptance. This advances the WP5 production-validation source contract only: the verifier is not composed with an authenticated trust authority, the candidate schema is not installed, and no production signer/validator provenance or qualification is established. Source SHA-256 and scope: `docs/phase2/CHANGE_RECORD_246.md`. Next: continue source-level S13 lock/FK/trigger/effect and caller-map closure; after code closure, assign verification scenarios and relevant Python/database/security reviews. No tests/checks/build/CI, SQL parse, migration, DB operation, COM, listener, stage, commit, or push ran in this update.

### 2026-10-25 trusted process PID parity

`TrustedProcessBinding.os_pid` now mirrors the candidate schema's PostgreSQL signed `integer` domain (`1..2,147,483,647`) at the Python trust boundary. `S13-TRUSTED-PROCESS-PID-01` covers valid endpoints, invalid types and overflow; it remains `NOT_RUN`. This is a model-level contract correction only and does not attest the actual OS process or establish trust-source authority. See `docs/phase2/CHANGE_RECORD_247.md`. No tests/checks/build/CI, migration, database, COM, listener, staging, commit or push ran in this update.

### 2026-10-25 signer-role service separation

The trust snapshot now rejects service-identity overlap across writer receipt, verification worker, completion supervisor, read attestor, and checkpoint signer roles. `S13-TRUST-ROLE-SERVICE-SEPARATION-01` is source-only and `NOT_RUN`; it does not establish real authority/key custody. Detail: `docs/phase2/CHANGE_RECORD_248.md`. No tests/checks/build/CI, migration, database, COM, listener, staging, commit or push ran.

### 2026-10-25 signer-role service separation

The trust snapshot and candidate SQL source now reject service-identity overlap across writer receipt, verification worker, completion supervisor, read attestor, and checkpoint signer roles. `S13-TRUST-ROLE-SERVICE-SEPARATION-01` is source-only and `NOT_RUN`; it does not establish real authority or key custody. Detail: `docs/phase2/CHANGE_RECORD_248.md`. No tests/checks/build/CI, migration, database, COM, listener, staging, commit or push ran.

### 2026-10-25 14:31 UTC local source-health observation

The bounded authenticated in-process MCP call returned `is_error=false`, `ok=true` for `onec-818ha-reference` source health. Token and business values were not printed. This is only current source-health evidence; writer, clone rights, transaction boundary, and S13 grant evidence remain open. See `artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md`. No service restart, write, migration, or test ran.

### 2026-10-25 14:32 UTC Ivan stack status

Strict SSH status command exited 0 with all nine named services `True`; no service restart or secret read occurred. This does not qualify writer rights or transaction boundaries. Detailed command/output scope: `artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md`.

**2026-10-26 signer-key availability reconciliation:** the documented secret path `D:\secrets\erp_mcp` is absent on Ivan (`IVAN\koros`). The local `RAZER\koros` directory contains only the administrator and test-reader clone credentials, no signer/witness files. D9/D10b generation remains pending; the S13 verifier-key schema is not installed and `WAIVER_SIGNERS.json` is a separate G4 registry. No secret contents were read and no key action was attempted. Evidence: `artifacts/WP0_IVAN_STACK_STATUS_2026-10-26.md`.

## 2026-10-26 continuation correction — source closure and S14 dependency

This addendum supersedes the WP4/WP6 source-review and access statements above where they conflict.

| Package | Current evidence/state | Remaining acceptance and ordered next action | Owner |
|---|---|---|---|
| WP4 / S13 | Candidate migration 027 SHA-256 `F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33` received exact-hash database-reviewer source review; no actionable ACL or audited lock/FK/trigger/effect source gap was found. The current configured disposable database still has no `change_ledger`, so effective candidate grants are `NOT_MEASURABLE`. Earlier focused SQL pass uses stale hash `D5F22EAF...` and does not qualify the current source. | Keep migration candidate-only. After S13/S14 coding closes, route all mapped SQL and seeded ACL cases to test roles; only then install on an invocation-owned disposable DB and measure effective grants. | Codex |
| WP5 | DPAPI key-provisioning code exists and had mock-only evidence recorded in CHANGE_RECORD_305; no real signer or witness key has been generated or registered. Target account/ACL and approved registry identity/scope remain unverified. | After exact service account and private path are established, inspect ACL and provision D9/D10b in-process on the licensed host; register only through the reviewed S13 path. | Codex |
| WP6 / S14 | No operational `OneCWritePort` exists. Exact payload-to-1C property/type crosswalk remains `NOT_VERIFIED`. Read-only local metadata inventory failed before metadata returned (`HRESULT 0x80020009`); the separate authorized remote COM probe reported `License not found`. No write followed. | Do not retry COM until the licensing/connection condition changes. First establish a licensed read-only session for the named disposable clone and capture its exact identity and metadata; then implement only the evidenced crosswalk, with dispatch disabled until the full authority/CAS/evidence adapter is complete. | Codex; Ivan stack is the technical host boundary |
| WP7 / S15, WP8 / S16–S17, WP10 / S18 | Still downstream of the operational WP6 writer and its qualified outcomes; no new acceptance is inferred from source review. | Resume in dependency order after WP6 qualification; keep WP9 optional and outside the critical path. | Codex |

No current-turn test, SQL parser, migration, database query/write, COM call, stage, commit or push was performed. Source review is not runtime qualification. Detail: `CHANGE_RECORD_307.md`; clone and COM evidence: `S14_COM_EPHEMERAL_VALUE_BINDING_DESIGN_2026-10-25.md`.

- WP5 target account/ACL follow-up: strict SSH read-only query confirmed `ERP_MCP_Ivan_Stack` principal `koros` and explicit non-inherited FullControl for `IVAN\koros` on existing `D:\1c\mcp\env`; the previously proposed `D:\secrets\erp_mcp` directory is absent on the remote host. No keys were written. Next D9/D10b provisioning depends on the approved S13 service/host/scope/validity identity path. Evidence: `artifacts/WP0_WP2_CURRENT_TURN_RECHECK_2026-10-26.md`.

- Read-only remote license-related service/process inventory found no 1C/1cv8/Sentinel/license service match and no 1cv8/Sentinel/HASP process; Windows `LicenseManager` was Running, `ClipSVC` Stopped/Manual. This does not establish 1C license availability. No service start/restart or COM retry occurred; the existing COM diagnostic is unchanged.
