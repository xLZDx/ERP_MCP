# Change record: record authenticated Ivan gateway read path

Date: 2026-10-22  
Scope: WP0 read-only transport and cross-base evidence.

## What changed

- Added current-turn evidence showing how to reach Ivan's gateway over a temporary SSH local forward while preserving the gateway's expected Host header.
- Recorded short-lived token minting on the remote host with output piped directly into the local client process.
- Recorded only sanitized health/profile/count results and the in-memory exact-row comparison.

## Why

Direct requests from the local machine did not establish the remote MCP session. The host already exposes a fixed remote token-mint script and a Tailscale-bound gateway; the SSH forward provides an auditable transport without restarting services or handling tokens in console output.

## Verification and limits

- Local listener check: all ten expected ports were listening.
- Strict SSH status check: all nine Ivan stack components returned `True`.
- Local and Ivan `source_health`: `ok=true`, HTTP 200.
- Local and Ivan 521.1 account reads: both machine-reconciled; 15 local rows and 16 Ivan rows; 15 exact full rows common, one Ivan-only row.
- No row contents, names, amounts, credentials, tokens or row-content hashes were emitted or stored. No source writes, migration, service restart, tests, checks or builds were performed.
- The extra Ivan row remains unexplained, so the cross-base comparison is `NOT_RECONCILED`.

## Ownership and next step

- Accountable task owner: operator.
- Executor: Codex.
- Technical owner of the remote host and connection boundary: Ivan stack.
- Next: after coding completion, have the test roles investigate the single extra analytic row through the disposable qualification path and document the accepted cross-base rule.
