# Change record 333 — Ivan stack strict-SSH status recheck

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator; evidence collection owner: Codex; technical boundary: Ivan stack.
- The repository worktree was already extensively modified before this turn. This record describes only the read-only command executed in this turn.

## Evidence collected

Executed from `D:\Repo\ERP_MCP`:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\\1c\\mcp\\run-mcp-stack.ps1 -Action Status"
```

Exit code: `0`. The remote status command returned `True` for PostgreSQL, Redis, Apache, proxies 8191, 8192 and 8193, sidecar, IdP, and gateway. No service was restarted and no business data, credentials, key material, or remote files were read.

The local `known_hosts` entry for `100.88.71.74` resolves to the ED25519 fingerprint `SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ`; the strict-host-key SSH session succeeded against that trusted entry.

Using the repository helper from the project virtual environment, an in-process five-minute auditor token opened the local gateway MCP session and called `source_health` for `onec-818ha-reference`. The bounded output was `is_error=False`, `ok=True`; the helper did not expose or print the token. No business-row tool was called. This is local gateway/source-health evidence, not an Ivan COM or writer-transaction observation.

## Scope and limitations

This is transport and process-status evidence only. It does not establish the current COM license, authenticated source health, effective database grants, the current 1C role rights, service identity, clone crosswalk, or the physical writer transaction boundary. The separate recorded COM connection attempt in the S14 design reported `LICENSE` / “License not found”; this status recheck did not retry COM.

## Acceptance and next action

- Criterion 1: strict-host-key SSH reaches the Ivan status command and reports the nine listed components healthy; the local gateway helper also returned `source_health ok=True` for `onec-818ha-reference`. Both checks passed for these invocations.
- Criterion 2: the latest recorded same-day catalog audit found the candidate schema, runtime roles and routines absent (`NOT_MEASURABLE_CANDIDATE_SCHEMA_ABSENT`); the physical writer boundary remains unimplemented. Evidence: `artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-25.md`, supplemental current-state recheck dated 2026-10-27.
- Owner: Codex continues source and in-scope evidence work; operator remains accountable for licensed-lane authority; Ivan stack is the technical host boundary.
- Next: continue fail-closed S13 source closure. Re-measure candidate grants only after the reviewed candidate schema/roles are installed in an approved disposable database. Do not grant evidence-ingest EXECUTE or invoke COM without the recorded identity/provenance and license/crosswalk prerequisites.

No tests, checks, builds, SQL parsing, migrations, database operations, COM operations, staging deployment, Git staging, commit, or push were performed. The gateway `source_health` call was read-only and returned no business rows.
