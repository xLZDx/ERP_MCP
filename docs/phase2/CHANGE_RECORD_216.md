# Change Record 216 — reject forwarded peer metadata at private ingress

## What changed

- The private ingress loopback gate now refuses requests carrying `Forwarded`, `X-Forwarded-*`, or `X-Real-IP` headers.
- The disposable qualification contract requires refusal even when trusted ASGI proxy middleware rewrites the apparent client address to loopback.

## Why

The boundary derives the peer from ASGI `scope['client']`. Proxy middleware can replace that value from request headers, which would make a forwarded remote peer appear to be the loopback peer required by the private-writer gate. Forwarding metadata is not evidence of the accepted socket peer, so this endpoint rejects it. This does not prove the real listener address; deployment still requires a separately verified loopback bind and must not expose the service through a proxy.

## Affected contracts and paths

- `src/erp_mcp_private_writer/private_ingress.py` — ASGI private-ingress request admission.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — `S13-PRIVATE-INGRESS-BIND-01` qualification.

## Evidence and verification state

- Initial private-ingress file was already untracked before this turn; its pre-edit SHA-256 was `2BAE3A9484414054D00BC9E92DB1578B9F9D06934C496A53D798259CF88A1942`.
- Current private-ingress source SHA-256: `C688B13F9F108C13E4B73A8145B5714C2A57E627693E838B1AC2EBE0817C786F`.
- Qualification prerequisite SHA-256: `618DCA784D9065CAB9A0759FEA3C4FB35246438E565D2CD0656E0EDA298B0322`.
- Source inspection only. No tests/checks/build, listener startup, runtime qualification, migration, database operation, staging, commit, or push ran. Qualification remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after code closure, the functional/E2E roles must exercise the forwarded-header cases through the deployed ASGI middleware and separately verify the socket listener is loopback-bound. Relevant security review follows the test phase.
