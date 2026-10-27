# Change record 338 — current transport recheck and remaining ERP_MCP gates

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator; coordination and repository work owner: Codex; GPT-PM owns any contract adjudication or exact-head approval when required.
- This record captures read-only observations from the current continuation. It does not attribute earlier code or test work in the shared worktree to this turn.
- No application source, database, service, secret, or Git index was changed by the observations below.

## Current-turn evidence

- Strict SSH command `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\\1c\\mcp\\run-mcp-stack.ps1 -Action Status"` exited 0. It returned `True` for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp and gateway. No service was restarted.
- A bounded top-level read-only listing of `D:\1c\mcp` returned the directories `app`, `data`, `dl`, `env`, `logs`, `runtime`, `tunnel`, `venv` and the stack scripts. This establishes presence only; it does not verify the COM writer process, transaction boundary, effective service grants, or license availability.
- Through this repository's `.venv`, `LaneEnv.load()` and an in-process short-lived `auditor` token, the local MCP call `source_health(source_id="onec-818ha-reference")` returned `is_error=false`, `ok=true`, HTTP 200. The token was not printed; no business rows were requested.
- Current source hashes were rechecked: migration 027 `D60423AAFB89CA3F7D4C9E0B8B48E563A083550162DF7C710B2FE45690A0B90B`, `postgres_evidence_trust.py` `6348B6E74AF642B989EAB084B21F583BBD5CD387D334846F0085ACC1EEC30E5B`, and S12/S13 prerequisites `C99D3F7DAF443549EFE7A77575EA054E1748ABC59E91F2E026835F6238BEB0BA`; they match the hashes documented in CHANGE_RECORD_337.
- Two attempts to quote a remote inventory command were malformed and returned command-line errors. They made no changes and are not used as evidence. The successful top-level listing above was performed afterward.

## Acceptance state and limits

- ERP MCP transport recovery and trusted SSH access are currently demonstrated narrowly by strict SSH success, stack status, and the authenticated source-health response. This is not S13 or physical-writer qualification.
- Effective candidate S13 database grants remain `NOT_MEASURABLE`: CHANGE_RECORD_336 documents that the candidate schema, relations, routines and roles were absent from the configured disposable PostgreSQL database. The measured CT14 writer-role rights in the extension remain separate evidence and do not establish the S13/S14 writer boundary.
- Source-level S13 review recorded in CHANGE_RECORD_337 found no actionable BLOCKER/MAJOR for its reviewed paths. It does not establish SQL/runtime behavior, formal S13 approval, effective grants, or disposable qualification.
- The concrete S14 COM writer remains unimplemented. Its exact payload-to-1C property/type crosswalk and a licensed read-only clone session are `NOT_VERIFIED`; prior source records document the license error. No COM call was attempted in this continuation.
- No tests, checks, SQL parsing, build, migration, DB mutation, local commit, or push ran in this continuation.

## GPT-PM design adjudication

- A complete S13 architecture/contract review was sent to the canonical PM Bridge project `erp_mcp`, explicitly bound to `https://github.com/xLZDx/ERP_MCP.git` and `D:\Repo\ERP_MCP`.
- Correlation: request `b73cbf50-173d-4507-8af9-035668d20f7f`; correlated reply `9ca65b28-dd05-5c34-bc73-028bf7faceb3`; PM Bridge project ID `erp_mcp`; status `succeeded`, `correlated=true`.
- GPT-PM verdict: `ACCEPT — S13 Criterion 3: DESIGN_COMPLETE`, architecture/design contract only. The response found 0 BLOCKER, 0 MAJOR and one deferred MINOR, `S13-DES-N01`, retained for S18 lock-order/contention work. It states that this verdict does not approve the source candidate or close implementation, runtime qualification, effective grants, external trust, physical COM writer, formal S13 approval, deployment or production.
- This is the required design criterion adjudication only. The overall formal S13 gate remains not approved; no gate manifest was changed.

## Ordered next work

1. Codex continues only source changes justified by an evidenced contract; do not invent 1C property/type mappings or a physical transaction boundary.
2. Codex coordinates the exact licensed, read-only `818HA_p2diff` metadata and identity evidence through the Ivan stack; the operator remains accountable for the project acceptance. Once that evidence exists, implement the concrete S14 writer and its transaction/idempotency, stale-epoch, outcome-lookup and quiescence behavior.
3. Complete dependent WP7, WP8 and WP10 code in order; keep optional WP9 out of the critical path.
4. Only after in-scope coding closes, assign the mapped functional and E2E cases to their required test roles, then run applicable exact-source independent reviews and reconcile findings.
5. Keep candidate installation, effective-grant measurement and any push/PR behind their documented qualification and exact-head GPT-PM gates.
