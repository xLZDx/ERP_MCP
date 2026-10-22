# Phase 2 test-lane MCP server: design (stage 1)

Date: 2026-10-11. Status: TESTLANE_EVALUATION_ONLY. Phase 2 stays NO-GO / IMPLEMENTED_UNVERIFIED with EVALUATION_ONLY authority; no gate is moved by anything described here.

## 1. Purpose

Let the operator exercise the offline Phase 2 reference modules on real data from ChatGPT or Claude: read two copies of the same 1C base through their Release 1 read-only gateways, run Release 2 comparison code over the results, change data on one side by hand, and see the difference found. Base A (local, reference/oracle) and base B (host Ivan) are copies of the same base (source `onec-818ha-reference`, one company). See `REMOTE_1C_HOST_STACK_2026-10-11.md` for the gateways.

A and B are positional labels only. Neither is a native 1C report, so nothing here is native validation, and the two reads are not independent-origin evidence (same source id, same company, copied base).

## 2. Boundary

- The server lives in `testlane/phase2_mcp/`, outside `src/business_ai_gateway/phase2`. The offline package keeps its no-network, no-Release-1-import invariants; its AST boundary tests only scan that package and stay green (run: `tests/phase2/test_s6b..s9_boundaries.py`).
- The test lane imports R2 modules (`reconciliation`) and never the reverse. It imports no Release 1 code; it talks to the gateways over MCP streamable HTTP with a small own client.
- Read-only: tools only read two gateways and compare in memory. Nothing is written to any base, database or file.
- Optional dependencies: `pip install -e .[testlane]` (`mcp>=2,<3`, `uvicorn`). Not part of the installed distribution (`testlane/` is not under `src`).
- Inbound: binds 127.0.0.1:21200 by default. A non-loopback bind is refused unless `TESTLANE_INBOUND_TOKEN` is set (bearer guard). Exposure through a tunnel/OAuth is the operator's separate step.

## 3. Tools

| Tool | What it does |
| --- | --- |
| `phase2_capabilities` | Lists the Phase 2 modules found in the package with status ceiling `IMPLEMENTED_UNVERIFIED`, authority `EVALUATION_ONLY`, which ones this lane exposes, and what is not covered. No gate is reported passed. |
| `phase2_reconcile_two_bases(company_id, as_of, start_period, end_period, show_values=false)` | Three sections, see section 4. |
| `phase2_reconcile_negative_control(company_id, start_period, end_period, delta="1", measure="closing_debit", show_values=false)` | `SYNTHETIC_NEGATIVE_CONTROL`: fetches the six-column data of both sides, perturbs one side-B account row in memory by `delta`, runs the same R2 comparison and returns the Difference found. |

Every response carries `authority`, `status_ceiling`, `native_pass=false` and, per side, the gateway labels `profile_kind`, `evidence_level`, `native_reconciliation` and warning codes. Timestamps need a timezone offset.

## 4. Mapping onto R2 modules

1. Six-column per account -> `reconciliation.compare_statements`. The gateway tool `accounting_balance_and_turnovers` returns sparse rows (several rows per account, each carrying only some columns). Adaptation: rows are summed per account with exact `Decimal` (floats parsed straight to Decimal); the account is the analytic key (`counterparty_ref`), `contract_ref` is the constant `ACCOUNT_LEVEL`; totals are derived from the fetched rows (the gateway reports none, so R2's aggregate-consistency guard is satisfied by construction); scope uses the shared source id, the requested company and period, grouping `("account",)`; the snapshot reference is `profile_fingerprint|metadata_fingerprint`, so differing fingerprints give `SOURCE_SNAPSHOT_MISMATCH`. Side A fills R2's "native" slot and side B its "gateway" slot only positionally; `NATIVE_*` reason codes therefore refer to side A. Tolerance is exact zero. Completeness is `has_more=false`, `truncated=false` and `returned == len(rows)`. The tool has no paging argument and returns at most 200 rows, so the live statement is incomplete and R2 returns INCONCLUSIVE.
2. 521.1 supplier closing balances -> NOT an R2 module. Only closing debit/credit per analytic row exist, so a plain exact-decimal comparison is used and labelled `PARTIAL_521_1_CLOSING_BALANCES` with its own states `PARTIAL_MATCH` / `PARTIAL_MISMATCH` / `INCONCLUSIVE` (supplier summary not COMPLETE, truncated, row count mismatch, snapshot mismatch). No columns are zero-filled to imitate six.
3. Purchases -> `purchase_reconciliation.compare_posted_purchases` is not called. `purchase_documents` lacks `contract_ref` and `deletion_mark`, spans many counterparties (R2 scope is one) and is paged without a paging argument. The section reports `NOT_SUPPORTED` with reason codes plus an informational first-page identity digest (`PARTIAL_FIRST_PAGE_ONLY_NOT_AN_R2_RESULT`). Nothing is invented to force the call.
4. Negative control -> same function as item 1 with completeness explicitly assumed (`synthetic_completeness_assumed=true`), because a live incomplete page would otherwise only return INCONCLUSIVE. It reports `baseline_state`, `perturbed_state` and `CONTROL_DETECTED` only when the baseline is MATCH and exactly the injected row difference plus the total difference are found. It proves the detector, not that the real bases agree.

## 5. Honesty rules

- MATCH (and PARTIAL_MATCH) is numeric agreement of two machine reads, never a native PASS and never accounting approval.
- Incomplete or inconsistent data gives INCONCLUSIVE (decided by R2 for the six-column case), never a fake MATCH.
- Amounts, counterparty names and account/analytic refs appear only with `show_values=true` (default false); by default responses carry states, reason codes, counts and digests only. Nothing is logged by the lane (uvicorn access log is off).
- Gateway endpoints and tokens come only from environment/config. Errors are fixed codes (`GATEWAY_UNREACHABLE`, `GATEWAY_AUTH_REJECTED`, `GATEWAY_TOOL_ERROR`, `GATEWAY_TOKEN_UNAVAILABLE`, ...); no URL, token or response text is carried.
- Gateway labels are reproduced as received, including `TEST_LANE_UNRECONCILED`/`L1`/`NOT_RUN`.

## 6. Configuration (environment)

`TESTLANE_A_URL` (default `http://127.0.0.1:21000/mcp`), `TESTLANE_B_URL` (default `http://100.88.71.74:21000/mcp`), `TESTLANE_SOURCE_ID` (default `onec-818ha-reference`), `TESTLANE_HOST`, `TESTLANE_PORT` (21200), `TESTLANE_INBOUND_TOKEN`, `TESTLANE_ALLOWED_HOSTS`. For each side, provider precedence is `TESTLANE_<S>_TOKEN`, then `TESTLANE_<S>_CLAUDE_JSON_SERVER`, then `TESTLANE_<S>_MINT_SSH_TARGET` (with optional paired `TESTLANE_<S>_MINT_SCRIPT`), then that side's default provider. An unpaired `MINT_SCRIPT` setting fails configuration with `TOKEN_MINT_TARGET_REQUIRED` unless a higher-precedence token/Claude provider is selected. A configured SSH target must be exactly `koros@100.88.71.74`; a configured script path must be exactly `D:\1c\mcp\mint-token.ps1`, or minting fails closed. Side A's default mints a 3600-second `auditor` token in-process through the lane IdP (`LaneEnv.load()`, `Idp.token()`); side B's default mints a 3600-second token on Ivan's host over SSH with batch mode, strict host-key checking and identity-only authentication. Short-lived `TokenCredential` providers refresh proactively 60 seconds before their declared expiry. Legacy string providers (including explicit static tokens and Claude JSON entries) carry no expiry metadata; a 401/403 causes one provider re-read/retry, which may return the same credential. Tokens stay in process memory. The running server's environment is captured at process start, so new source configuration is not active in an already running process.

Start (repository root, mcp 2.x environment): `PYTHONPATH=src;.` then `python -m testlane.phase2_mcp`.

## 7. Not covered yet (stage 2)

- S8 job API endpoints ENQUEUE_JOB, RERUN, PAUSE_SOURCE, REVOKE_ATTESTATION, READ_JOB, READ_RESULT (`jobs_api`, `workbench_session`).
- `living.*` SQL ports and any persistence of results.
- Google Drive connector.
- Native report capture and evidence attestation; complete six-column statements (needs paging in the gateway or a native report); purchase comparison through R2.
- Inbound OAuth for ChatGPT; only a static bearer guard exists.

## 8. Verification

Offline tests in `tests/testlane/` use fake gateways (MATCH, MISMATCH with exact row, INCONCLUSIVE on `has_more`, hidden values by default, token never in output, bearer guard, client against a local fake HTTP gateway). Live smoke is read-only and reports states, counts and digests only. Mutation runs, full suite and CI are NOT_RUN by operator policy.
