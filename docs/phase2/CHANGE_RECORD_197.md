# Change Record 197 — bound private-writer token verification

## What changed

- `PrivateWriterAuthenticator` now bounds each injected token-verifier call with a validated timeout (default five seconds, hard maximum ten seconds) and makes its verifier, client allowlist, and timeout immutable after construction.
- `ConfiguredPrivateWriterAuthorizer` now freezes its ticket/permit verifier, exact scope grants, and verification timeout after construction.
- Both classes, `WindowsDpapiEd25519Signer`, and `CheckpointSignerHexAdapter` now reject slot deletion as well as reassignment; deletion could otherwise bypass their existing immutable-configuration guard.
- Both timeout validators check the hard range before the finite-number conversion, so an oversized integer produces the stable configuration error rather than leaking `OverflowError`.
- Timeout and verifier failures map to the existing `AUTHENTICATION_UNAVAILABLE` error, preserving the ingress's fail-closed 503 response without exposing verifier details.

## Why

Injected verifier protocols permit implementations beyond the current JWKS verifier. A stalled implementation could otherwise hold an authenticated private-writer request indefinitely, and mutable verifier/allowlist/grant configuration could change the authentication boundary after construction. Slot deletion also bypassed reassignment-only immutability guards on security adapters. The adapter-level deadline and delete-resistant immutable configuration bound these risks independently of deployment wiring.

## Evidence and verification state

- Reviewed source before change: `src/erp_mcp_private_writer/private_auth.py` SHA-256 `A80CCB2A625A43175CD2EDACE865420591E1AB7C32BD27748DD01B20F1073D55`.
- `src/erp_mcp_private_writer/private_auth.py` SHA-256 after timeout, configuration freeze, and delete guard: `9784101A9E24A115FFE7789A73563FFD23D13A7D2628E9AFC8CBDDABC71777E5`.
- `src/erp_mcp_private_writer/private_authorization.py` SHA-256 after bounded-timeout validation, configuration freeze, and delete guard: `9D978B230E2F40F3A5A63793D04405CBC0BB375D17119D1D4E2A3ED115EFD179`.
- `src/erp_mcp_private_writer/dpapi_signer.py` SHA-256 after delete guard: `5F6FB4AB2FC9A0198251515907695997105F9929C9AFD51A5071F6A7E7A81409`.
- `src/erp_mcp_private_writer/checkpoint_signer_adapter.py` SHA-256 after delete guard: `09839555B45983A1267766D027A158FA97CA82C666C5D2DD73E095C00E8E4830`.
- Qualification plan `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` current SHA-256: `D356AD6BD740DA6BC24E2B7C4BE262B6A59F73E1B97DFEF23AF08286FA4B37C6` (recomputed after the later S13 candidate cases were added).
- Source inspection only. Tests/checks/build, service startup, token calls, and runtime qualification were not run. Private ingress remains a candidate and is not enabled.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: include timeout and cancellation behavior in private-ingress functional/E2E cases after coding closes; keep ingress disabled until authentication, caller-scope, startup-recovery, and disposable-lane gates are qualified.
