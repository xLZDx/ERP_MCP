# Autonomous completion direction — 2026-10-21

## Scope

- Repository: `D:\Repo\ERP_MCP`
- Base revision: `81a4fe8`
- Purpose: record the operator's latest instruction to make technical decisions and continue without routine questions.

## Decision

Ordinary implementation and sequencing decisions are delegated to Codex. Continue the accepted work packages until completion or a concrete external/platform/operator-only blocker. Preserve explicit boundaries for production writes, staging, real-money actions, deletion, secret handling, strict remote-host identity and test ownership.

Reconcile the existing disposable-clone write permission with the test process as follows: clone mutations may occur only as mapped tests authored and run by `functional-test-reviewer` or `e2e-runner`, after all coding for the accepted scope is complete. No manual write run, production-base write, or staging action is authorized.

## Evidence and remaining limits

- WP0's Tailscale reachability and SSH attempts are recorded in `docs/phase2/artifacts/WP0_SOURCE_LIVENESS_2026-10-21.md`. The remote service remains unverified because host-key checking failed.
- The S13 and S14 inventories/contracts still require a real physical writer boundary before a production adapter or READY transition can be implemented safely.
- This decision does not establish a service owner, host identity, key custodian, gate PASS, or production authorization.
- No tests, checks, generators, migrations, clone writes, or production actions were run for this decision record.
