# WP0 access and two-base reconciliation recheck, 2026-10-27

Status: read-only observation plus one bounded test-lane code fix. Phase 2 stays `EVALUATION_ONLY`,
Release 2 stays `NO-GO`, no gate is passed by this note.

## Scope

- Accountable owner: operator; executor: Claude Code session; technical host boundary: Ivan stack.
- Step A1 of the continuation plan: re-verify local and Ivan access, then run the Phase 2 test-lane
  comparison of the two gateways. Values stay hidden (`show_values=false`); no amount, name or token
  appears here.
- Not done: no product test suite, no migration, no database write, no COM call, no service restart
  (Apache, proxies and the 21200 process were left alone), no push.

## Access evidence (current turn, 2026-10-27 ~12:09 local)

| Check | Result |
|---|---|
| Local listeners 8088, 8191-8193, 18432, 19379, 21768, 21080, 21000, 21200 | all `True` |
| `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74` with `run-mcp-stack.ps1 -Action Status` | host `Ivan`, account `ivan\koros`; postgres, redis, apache, proxy8191-8193, sidecar, idp, gateway all `True` |
| Ivan gateway `system_status` / `sources_list` | `mode=1c-production`, `read_only=true`, `subject=auditor`, 3 accessible sources (`onec-818ha-down`, `onec-818ha-drift`, `onec-818ha-reference`) |
| Ivan `source_health onec-818ha-reference` | `{"status_code":200,"ok":true}` |
| Local gateway 21000 (short-lived in-process auditor token, never printed) | same `system_status`, 3 sources, `source_health` `ok: true` |
| Fresh process using the Phase 2 token providers | side A and side B `initialize` both HTTP 200 in about 0.1 s |

## Reconciliation observations (company `3e31afc5-351f-4f36-8074-99129fa3d911`, period 2026-08, `+03:00`)

1. First call to the running 21200 server: all three sections errored (`GATEWAY_HTTP_ERROR`,
   `GATEWAY_UNREACHABLE`, `GATEWAY_TOOL_ERROR`) and the negative control errored. An immediate second
   call connected normally. Fresh-process probes of both sides were healthy. Interpretation (INFERENCE,
   not proven): the long-running server held a stale session that the client resets after the first
   error. Not reproduced afterwards.
2. `supplier_521_1_closing_partial`: `PARTIAL_MISMATCH`, reason `CLOSING_VALUES_DIFFER`, one difference
   `ROW_MISSING_IN_A` (row digest `0efc382e068994e0`). Side A has 10 analytic rows and side B (Ivan) has
   11. Both sides report `VALIDATED_MACHINE_RECONCILED` / `MACHINE_TWO_SOURCE` and the warning
   `MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT`. This is a numeric copy-consistency result between two
   machine reads, never a native 1C PASS. Follow-up (same turn, read-only): the ten common rows are
   identical, the extra Ivan row is a counterparty with a non-zero credit and a zero debit, and the
   metadata fingerprint, profile fingerprint, route and profile kind are equal on both sides, so the
   difference is data only. FACT: the local `erp_mcp_ref` publication points at
   `D:\ERP_MCP_Testbed\1c\reference\working\818HA_test_ready`, while Ivan's `erp_mcp_ref` publication
   (`D:\1c\env\odata\erp_mcp_ref\default.vrd`) points at `D:\1c\env\bases\818HA_p2diff`, the write
   clone. The two sides therefore do NOT read copies of one base. INFERENCE (not proven): writes made to
   the write clone explain the extra credit-only counterparty. Ivan also holds `818HA_reference_ro` and
   `818HA_test_ready`. Pointing Ivan's reference source at a read clone, or accepting that it reads the
   write clone, is a decision for the S13/S15 owners; no configuration was changed.
3. `six_column_per_account` and `purchase_documents`: the gateway itself refuses both tools with
   `SEMANTIC_PROFILE_UNVALIDATED` (no validated `account.balance_and_turnovers` profile and no validated
   purchases profile for this exact source and company). This is a capability gap, not a transport
   fault. The negative control depends on the six-column read, so it cannot run until that profile
   exists.
4. The test lane reported refusals only as a generic `GATEWAY_TOOL_ERROR`, and it called
   `purchase_documents` with `start_period`/`end_period`, which the gateway tool rejects as extra inputs
   (it accepts only `source_id`, `company_id`, `top`, `skip`).

## Code change made (see `docs/phase2/CHANGE_RECORD_341.md`)

- `GatewayError` carries an optional `detail_code`, filled only from a bare UPPER_SNAKE refusal code in the
  gateway's JSON error; reports show it as `detail_code` next to the unchanged `reason_code`.
- `purchase_documents` is called with only `source_id` and `company_id`.
- One pre-existing ruff finding (`ISC004` in `testlane/phase2_mcp/config.py`) is fixed.
- Live verification used a fresh in-process `Reconciler` over both real gateways: the three refusals now
  show `detail_code: SEMANTIC_PROFILE_UNVALIDATED`; the 521.1 section is unchanged. The long-running 21200
  server was deliberately not restarted, so it keeps the old generic codes until the operator restarts it.
  ruff over `testlane/phase2_mcp` passes. The new unit test is NOT_RUN (test phase belongs to the test
  agents).

## Remaining

- Decide whether Ivan's `onec-818ha-reference` should read a read clone (`818HA_test_ready` or `818HA_reference_ro`) so the comparison is a true copy-consistency check; until then the 521.1 mismatch is expected, not a defect.
- Validated profiles for six-column and purchases are a separate capability task; until then both
  sections and the negative control stay refused, never reported as agreement.
- Restarting the 21200 server to pick up the new codes is an operator decision.
