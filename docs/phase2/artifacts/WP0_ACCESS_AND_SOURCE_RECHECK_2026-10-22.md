# WP0 access and source recheck — 2026-10-22

This note records current-turn runtime observations after the operator corrected the earlier
environment report. It supersedes conflicting WP0 access claims in
`WP4_WP10_DEPENDENCIES_2026-10-21.md`; it does not establish S12/S13 qualification, native
accounting evidence, or release readiness. Observed repository base before this turn's edits:
`0fe023db1ec2adcf1820356db1dd1db09d23c3ab`.

## Local and Ivan service access

| Check | Evidence | Result and limit |
|---|---|---|
| Local listeners | Read-only `Get-NetTCPConnection -State Listen` for 8088, 8191–8193, 18432, 19379, 21000, 21080, 21200 and 21768 | All ten ports were listening. Observed listener PIDs: 8088/7380, 8191/10996, 8192/31516, 8193/2704, 18432 and 19379/32540, 21000/27616, 21080/36088, 21200/32004, 21768/10988. Point-in-time only. |
| Apache configuration | Read-only process metadata for PID 7380 | Command line referenced `httpd-erp-mcp-test-ready.conf`. No restart was attempted. |
| Phase2 process identity | Read-only process metadata for PID 32004 | Executable was `C:\Python314\python.exe`; command line identified `-m testlane.phase2_mcp` and the project venv launcher argument. This is consistent with the Windows venv launcher behavior; it is not a process replacement. |
| Ivan SSH identity and stack | `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes koros@100.88.71.74 'powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status'` | Exit 0; `postgres`, `redis`, `apache`, `proxy8191`, `proxy8192`, `proxy8193`, `sidecar`, `idp` and `gateway` each returned `True`. Host-key verification remained strict. |
| Ivan stack directory | Same strict SSH identity; `cmd /c dir /b D:\1c\mcp` | Names only were listed; no file contents or credentials were read. The directory contains the stack app/data/env/runtime/scripts and the token/stack management scripts. |

The operator is the accountable owner for this delegated project task. The Ivan stack is the
technical owner of the remote connection and host boundary, as recorded in the current
continuation prompt. No human contact for deployed grant confirmation is named in the source
records inspected so far.

## Read-only source calls

Using `.venv\Scripts\python.exe`, `scripts/real1c/gateway_client.py`, and a short-lived
`auditor` token held only in process memory, the local gateway at
`http://127.0.0.1:21000/mcp` returned `source_health.ok=true` and an account 521.1 read for
`onec-818ha-reference` and the operator-specified company/cutoff. The result contained 15
rows and was labeled `VALIDATED_MACHINE_RECONCILED`,
`PROFILE_VALIDATED_MACHINE`, `MACHINE_TWO_SOURCE`, with warning
`MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT`. No row, amount, or name was printed or stored
in this note.

The equivalent read through Ivan's gateway used a separate short-lived token minted on Ivan
with `mint-token.ps1 -Ttl 3600`; stdout was captured in process and not printed. It also
returned `source_health.ok=true`, with the same machine-evidence labels, but returned 16
rows. An in-memory row-content digest comparison was unequal. The row contents and digest were
not printed or persisted. Therefore the two source reads are **not reconciled**; the difference
requires investigation before treating either lane as a cross-base match.

The 21200 process was reachable and listed the two Phase2 comparison tools. Its
`phase2_capabilities` reported `side_a_configured=false` and `side_b_configured=false`.
Calling comparison tools through the running server returned `GATEWAY_TOKEN_UNAVAILABLE`.
The process was not restarted or replaced. A read-only in-process invocation of the repository's `Reconciler` with separately
minted short-lived gateway tokens returned:

- Overall authority `EVALUATION_ONLY`, status ceiling `IMPLEMENTED_UNVERIFIED`, release verdict
  `NO-GO`, and `native_pass=false`.
- The 521.1 partial closing comparison was `PARTIAL_MISMATCH`, with one difference; the two
  sides exposed 10 and 11 analytical rows. No values or names were printed.
- The six-column turnover and purchase sections returned `GATEWAY_TOOL_ERROR`; the synthetic
  negative-control tool also returned `GATEWAY_TOOL_ERROR`. These are incomplete runtime
  results, not a pass or a successful negative-control demonstration.

The direct MCP client and in-process reconciler used only read operations; the requested
synthetic negative control perturbed a row only in memory and returned an error. `show_values=false`;
no source write or migration was run. A GET on the MCP root is not evidence of the
published OData anonymous-auth behavior, so that boundary remains operator-reported only.

## Current-turn outbound-token implementation update

The source cause of `GATEWAY_TOKEN_UNAVAILABLE` was that the running Phase 2 process had no
configured outbound token providers. In this turn, `testlane/phase2_mcp/config.py` now provides
the default operator-approved local `auditor` mint through `LaneEnv`/`Idp` and the remote Ivan
mint through strict SSH host-key checking to `koros@100.88.71.74`. The fixed remote command
requests a 3600-second token; alternate remote script paths and SSH targets fail closed, and a
script-path setting without its matching target is a configuration error unless a higher-priority
token source is selected. The
gateway client refreshes short-lived credentials before expiry and allows one provider re-read
after HTTP 401/403 because its exposed tools are read-only. Static legacy providers have no expiry
metadata, so their retry may return the same credential. Provider precedence and this distinction
are documented in the design record at
`artifacts/PHASE2_TESTLANE_MCP_DESIGN.md`.

This is an **implemented source change, not runtime-proven**. The 21200 server was not restarted
or replaced, so the running process still has its original configuration and its prior
`GATEWAY_TOKEN_UNAVAILABLE` result is not yet cleared. No new MCP calls, tests, checks, builds, or
migrations were run after this implementation. Owner: operator is accountable; Codex executed the
local change; Ivan stack owns the remote host boundary. Next: after all in-scope code is complete,
the test roles should start an isolated Phase 2 instance on a separate loopback port with the
verified env and exercise both token providers and read-only comparison scenarios. Leave the
operator-verified 21200 process in place; no restart or replacement is part of this work.

## Effective grants

The read-only `database-reviewer` inspected the disposable PostgreSQL endpoint configured for
host loopback port 18432. Docker showed `erpmcp-e2e-real1c-postgres-1` publishing that port to
container port 5432; the connected database was `business_ai`, with session/current role
`business_ai_admin`. The reviewer queried `pg_roles`, `pg_auth_members`,
`information_schema.role_table_grants`, and `has_function_privilege` in a read-only
transaction. No schema or functions named `change_ledger` existed, so the requested S13
effective grants could not be established from this database. No migration was applied.

The role inventory included a highly privileged `business_ai` role (superuser, role/database
creation, replication and RLS bypass) and non-superuser `business_ai_admin`,
`business_ai_app`, and `business_ai_control_api` roles without RLS bypass. No non-system role
memberships were present. This is test-database role metadata, not evidence that a runtime
application uses the elevated role. S13 database grants remain **NOT_VERIFIED** until the
approved disposable schema is bootstrapped and the same read-only grant review is repeated.

The same read-only audit found no RLS-enabled or forced-RLS table among the 15 inspected
`bag` base tables. The app role had SELECT on 13 `bag` tables plus SELECT/INSERT on
`audit_events`, and no `company_scope_mappings` grant. The per-role details and function
privileges were queried through each role's own connection; the admin view alone did not
represent every role's effective grants. All seven inspected `bag` routines were executable
by app/admin/control. In particular, `bag.record_capability_observation(...)` is
`SECURITY DEFINER` with `PUBLIC EXECUTE` and performs an upsert into `source_capabilities`
without an explicit authorization check in its body; see
`db/migrations/014_capability_observation_boundary.sql:13-105`. This is an authorization
review item, not a demonstrated exploit. No schema/data changes were made.

The 1C role evidence remains recorded, not reproduced in this turn:
`testlane/onec_extension/STATUS.md`,
`testlane/onec_extension/CT14_FEASIBILITY_SPIKE_2026-10-12.md`,
`scripts/ct14_rights_state.json`, and
`testlane/onec_extension/CT14Ext/Roles/CT14Писатель/Ext/Rights.xml`. The recorded clone
measurement reports 53 allowlisted objects, receipt read/insert/update/post/unpost, sequence
read/update, read-only support access, and no delete/interactive/admin rights. It also records
that marker attributes are not protected by role-level rights; marker integrity still needs
consumer-side enforcement. This is clone evidence, not deployed or production evidence.

## Ordered remaining work

1. After all in-scope coding is complete, have the test roles start a separate Phase 2 instance
   on another loopback port with the verified environment, then rerun the read-only comparison
   and negative control through the actual MCP endpoint. Preserve the operator-verified process
   on 21200 without restart or replacement. Owner: operator accountable; Codex executor; the
   functional-test-reviewer and e2e-runner own execution of their mapped scenarios.
2. Reconcile why local and Ivan 521.1 reads differ (15 vs 16 rows) and why turnover/purchase
   calls fail; keep values and names in private process memory only. Owner: operator accountable;
   Ivan stack owns the remote source boundary; no human contact is recorded.
3. Complete S12/S13 design and implementation on the approved disposable lane, then bootstrap
   only that disposable database and repeat effective-grant review. The S13 writer service is
   a private Ivan-lane deliverable with stable call-ID idempotency, stale-epoch rejection,
   authoritative outcome lookup and a quiescence barrier. No public tunnel write path.
4. Proceed with WP5–WP8 and WP10 in dependency order. WP9 remains optional and outside the
   critical path. Functional/E2E agents run after coding is complete; specialist reviews and
   exact-head GPT-PM approval follow their evidence.

## Follow-up read-only comparison — current executor turn

After the S13 lock-protocol commit, I repeated the Ivan check with
`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`.
It exited 0 and reported all nine stack components `True`: postgres, redis, apache, proxies 8191–8193,
sidecar, idp, and gateway. `ssh-keygen -F 100.88.71.74` found the existing known-hosts entry;
strict host-key verification succeeded. A names-only listing of `D:\1c\mcp` returned the stack app/data/env/logs/runtime/tunnel/venv directories and its management scripts. No service restart or credential-file read occurred.

Using the approved in-process gateway client and short-lived `auditor` tokens, I repeated
`source_health` and `accounting_balance_by_analytics` for `onec-818ha-reference`, the operator-specified
company and cutoff, against local `http://127.0.0.1:21000/mcp` and Ivan
`http://100.88.71.74:21000/mcp`. Both health calls returned `ok=true`; both balance calls returned
without MCP error and reported `VALIDATED_MACHINE_RECONCILED`. The account payload had 15 local rows
and 16 Ivan rows. Metadata and profile fingerprints matched, and both routes were `odata`.

I compared normalized row groups in process by account key, typed analytics references, and currency.
The local payload contained 10 distinct groups (5 repeated rows); Ivan contained 11 (5 repeated rows).
All 10 common groups had matching multiplicities and matching aggregate debit/credit values; no group
was local-only, and one group was Ivan-only. Names, references, balances, and tokens were not emitted.
A first-pass full-payload digest appeared only in the agent tool output and is intentionally omitted
from this durable record. This narrows the prior mismatch to one additional normalized analytic group
on Ivan; it does not establish why that group exists or reconcile the two bases.

These were read-only source calls. The gateway's normal audit records may be written by the service;
no 1C/source mutation, migration, COM write, deployment, or process restart was performed. The prior
WP0 result and current independent comparison both remain **NOT_RECONCILED** until the Ivan-only group
is explained and an accepted cross-base rule accounts for it. The next step is a privacy-preserving
source-side diagnosis on the disposable qualification path after coding is complete; operator is the
accountable owner, the Ivan stack owns the host/connection boundary, and no individual responsible for
the data difference is established in the repository.
