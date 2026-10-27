# Change record 247 — align trusted process PID with PostgreSQL

Date: 2026-10-25  
Scope: source-only WP5 trust-model domain correction; no database or process-attestation runtime was exercised.

## What changed

- `TrustedProcessBinding.os_pid` now accepts only an exact built-in integer in PostgreSQL `integer` range `1..2,147,483,647`.
- Added `S13-TRUSTED-PROCESS-PID-01` with positive endpoint and invalid/overflow cases, all `NOT_RUN`.
- Current source SHA-256: `A27938D1695666A7D4A8E2963633D9E2D836CF60658863AA7AF214BD0F8D28FB`.

## Why

The candidate trust schema stores `os_pid` as PostgreSQL `integer`, whose upper bound is 2,147,483,647. The Python trust model previously accepted larger integers from injected snapshots, creating values that cannot originate from the typed database column and weakening the source contract's strict decoding boundary.

## Scope and verification state

- This validates only the value domain. It does not establish process identity, supervisor signature provenance, an authoritative trust source, or runtime database state.
- Static source inspection only. No tests/checks/build/CI, SQL parse, migration, database, COM, listener, staging, commit, or push ran. `S13-TRUSTED-PROCESS-PID-01` remains `NOT_RUN`.

## Ownership and next action

- Accountable task owner: operator; executor: Codex.
- Scenario owner after coding closure: `functional-test-reviewer`; relevant independent review follows the accepted workflow.
- Next: qualify the PID domain through the functional-test owner after all in-scope coding is complete, then continue trust-source and S13 lock/caller closure.
