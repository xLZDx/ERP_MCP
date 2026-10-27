# Change Record 305 — add safe DPAPI signer-key provisioning primitive

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP WP5 private-writer signer tooling.
- Acceptance: `WP5-DPAPI-KEY-PROVISIONING-01`.
- State: source implemented in the working tree; the corrected focused mocked suite passed.
  Remote execution, trust registration and signer qualification are `NOT_RUN`.

## Change and reason

The private-writer package already had a CurrentUser-DPAPI signer reader but no corresponding
provisioning path. Added `provision_windows_dpapi_ed25519_key()`: on Windows it creates an
Ed25519 key in process memory, protects the raw seed with CurrentUser DPAPI with UI forbidden,
then publishes a same-directory temporary file containing only the protected blob through a
no-overwrite rename. It never returns or prints private material and refuses an existing
destination. Its result contains only the path, raw public key, and public-key SHA-256.
The pywin32 `CryptProtectData` API returns the protected bytes directly; the tuple shape returned
by its unprotect counterpart is not accepted as ciphertext.

This primitive deliberately does not choose a service identity, host identity, key ID/version,
role, tenant/company/base scope, validity interval, file ACL, or registry mutation. Those values
must come from the reviewed Ivan private-writer deployment and S13 trust workflow. The project
authorization requires generation on the licensed host under the dedicated account; this turn
did not execute the provisioning function or access any remote key material.

## Affected contracts and paths

- `src/erp_mcp_private_writer/signer_provisioning.py` — new key creation and DPAPI persistence.
- `src/erp_mcp_private_writer/__init__.py` — package exports for the public result, stable error,
  and provisioning entry point.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md` — current work and exact remaining gates.

## Verification

- Implementation and review were initially source-only. The later mocked test-role run is recorded
  below; no build, SQL operation, remote command, signer creation, or trust registration was run.
- The actual `code-reviewer` role found a MINOR interruption window that could leave an
  unreturned ciphertext blob at the final path. The code now records the temporary file identity
  before publication and removes the destination on incomplete return only when that file identity
  matches. The same reviewer rechecked the fix and found no remaining material issue; both reviews
  were source-only. The review tool did not expose model or reasoning-effort metadata.
- During test design, the functional-test-reviewer identified a second cleanup race: after
  publication, cleanup used the destination name when `created` was set and could unlink a
  replacement file. Current source captures identity from the opened temporary descriptor,
  verifies the published path before returning, and removes temporary/final paths only when their
  identity matches this invocation. A second source review accepted the documented trust boundary:
  the parent must be private to the dedicated account, and no untrusted process under that same
  account is isolated because it can already unprotect the CurrentUser DPAPI blob. ACL verification
  before remote provisioning remains required.
- Provisioning source SHA-256: `E55BF447D4B81B99B079E46D626C77AB8C8C0153CA45A156AAD73AEDB196486A`.
- A focused test-role run against that earlier source identity exited 1 (4 passed, 7 failed or
  subfailed). Its test double returned `(ciphertext, description)` for `CryptProtectData`, which
  does not match pywin32: the protect function returns bytes directly. The source now rejects the
  tuple shape. Safe test-only tracing on the next instrumented run identified the common failure
  before DPAPI: the fake serialization namespace lacked `PublicFormat`, raising `AttributeError`
  at the provisioning function's public-key serialization step; mock call counts showed
  `public_bytes=0` and `protect_data=0`. This was a test-double defect, not evidence of a production
  exception. The fake was corrected and exact keyword-call assertions fixed.
- Current provisioning source SHA-256 after rejecting the non-pywin32 tuple shape:
  `C5119D626BC66050439AE748E42E5697D32637EF1420A88C8E63ADDD8B3DF0B3`.
- Focused regression run on corrected source and test identities: command
  `uv run pytest -q tests/phase2/test_dpapi_signer_provisioning.py`; exit 0, 7 tests and 3
  subtests passed in 0.92s. HEAD was `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`; test SHA-256
  `69576400F255601E34C6AE8DFC35CA1DDA12854BB2316B41049B520CB0C26423`, source SHA-256
  `C5119D626BC66050439AE748E42E5697D32637EF1420A88C8E63ADDD8B3DF0B3`. Only mocked keygen and
  DPAPI were used; no real key, DPAPI blob, DB, COM, remote host or signer registration was used.
- The output-file no-overwrite publication is intended to prevent replacement and partial final
  files. Windows ACL
  inheritance remains the responsibility of the account-private parent directory; the DPAPI
  blob remains tied to the current Windows account.
- Private key bytes necessarily exist transiently in process memory. Python does not guarantee
  their zeroization.

## Next steps

1. After the overall code phase closes, run the authored mocked Windows success, existing-path
   refusal, non-Windows refusal, malformed DPAPI result, ciphertext-only disk, and replacement-
   sentinel cases through the authorized functional-test role.
2. Run the reviewed utility only on Ivan's authorized host/account after the exact private parent
   path and public-key registry identity/scope/validity inputs are established from in-scope
   deployment records.
3. Register only the returned public key through the S13 trust workflow; do not put writer keys
   in `governance/WAIVER_SIGNERS.json`.

## 2026-10-26 current-turn source review

A fresh read-only `code-reviewer` pass inspected the current `signer_provisioning.py` against this
record after the identity-checked cleanup change. It found no actionable BLOCKER or MAJOR in the
publication and cleanup path: the implementation captures the temporary file identity from its
open descriptor, flushes the file before same-directory publication, checks the published identity
before returning, and deletes a path only when its identity still matches this invocation. The
review did not run tests or checks; model and effort metadata were not exposed. This review does
not verify the parent ACL, dedicated account/host, or registry scope inputs; those remain
deployment prerequisites and prevent remote provisioning/registration without their exact values.
