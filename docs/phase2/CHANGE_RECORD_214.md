# Change Record 214 — bind private ingress Host to the ASGI endpoint

## What changed

- The private-ingress guard now requires the loopback `Host` IP to equal the literal loopback IP in the actual ASGI `scope['server']` tuple.
- It also requires the effective Host port to equal the accepted server port. An omitted port matches only HTTP 80 or HTTPS 443.
- The S13 qualification contract now covers mismatched loopback addresses and ports in addition to wildcard, non-loopback, missing and invalid server endpoints.

## Why

Checking only that the client, Host and server each looked loopback allowed a valid loopback Host for a different loopback address or port to pass. The application does not bind the socket itself, so the request Host must identify the actual accepted endpoint while the deployment separately proves its listener address.

## Evidence and verification state

- Changed code: candidate-only `src/erp_mcp_private_writer/private_ingress.py`, `_private_loopback_request`.
- Qualification contract: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, `S13-PRIVATE-INGRESS-BIND-01`.
- Source SHA-256 after this change: `D2D95DA4424E4E59AD134FE82BB04B7EEE32130C5330C494EC30C7F1F640A640`.
- Source inspection only. No tests/checks/build or listener startup was run. Runtime qualification remains `NOT_RUN`; the ingress service remains gated on recovery and S12/S13 qualification.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue S13 code closure; after coding completes, have the E2E role exercise matching and mismatched host/address/port pairs and have the relevant security reviewer inspect the listener and proxy boundary.
