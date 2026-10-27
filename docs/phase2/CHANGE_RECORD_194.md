# Change Record 194 — bind private ingress to the accepted socket endpoint

## What changed

- `_private_loopback_request` now requires the ASGI `scope['server']` endpoint to be a literal IPv4 or IPv6 loopback address with a valid TCP port, in addition to the existing loopback client and loopback `Host` checks.
- Added `S13-PRIVATE-INGRESS-BIND-01` to qualify wildcard/non-loopback/malformed endpoint refusal and valid loopback controls. Qualification remains `NOT_RUN`.

## Why

The previous guard checked the peer address and caller-supplied `Host`, but not the local endpoint that accepted the connection. A wildcard or non-loopback listener could therefore satisfy those two app-level predicates for a loopback caller. Failing closed on missing endpoint data makes the app's own boundary match its loopback-only contract. Deployment must still bind the socket privately; a local reverse proxy must not expose it publicly.

## Affected contract and paths

- `src/erp_mcp_private_writer/private_ingress.py` — ASGI request admission.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — future functional/E2E qualification.

## Evidence and verification state

- `private_ingress.py` SHA-256: `BAE5646B8CAB97FD2493403B1C96D4B53A94156E8AE0BB77B93CD773BB9BE76A`.
- Qualification prerequisites SHA-256: `68476A3CD4F483F749B0DDEE1BBF39EDA9C203FD7A5EEACD69F6050B33D01AFF`.
- Source-only edit. No test/check/build, runtime listener, migration, database operation, staging, commit, or push ran. The ASGI behavior and actual listener binding remain `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: finish source coding, then assign this case to the functional/E2E test roles and separately review the production listener binding before any service enablement.
