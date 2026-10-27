# Change record 327 — verify DPAPI provisioning round-trip before publication

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator by explicit delegation; executor: Codex.
- `signer_provisioning.py` and the disposable prerequisite document were already untracked in the
  shared worktree; their earlier origin is not attributed. This increment adds the round-trip
  verification to the pre-existing provisioning function and records its acceptance.
- No remote host, key, database, COM, tests, checks, staging, commit, or push operation occurred.

## Change

`provision_windows_dpapi_ed25519_key()` now calls `CryptUnprotectData` on the exact ciphertext
returned by `CryptProtectData` before creating a temporary file. It accepts only the pywin32
two-item result shape with bytes as its plaintext and constant-time compares those bytes with the
generated Ed25519 seed. An exception, malformed result, or mismatch raises the stable
`SIGNER_PROVISIONING_ROUNDTRIP_FAILED` code. No ciphertext is published on that path.

This proves only that the current Windows account can recover the generated seed immediately. It
does not prove that this is the approved service account, validate the host or directory ACL, select
signer identity/scope/validity, or register a key. The recovered plaintext is transient in memory;
Python does not guarantee zeroization.

Acceptance `WP5-DPAPI-PROVISION-ROUNDTRIP-01` was added to
`S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` with failure/no-file and success/
ciphertext-only cases.

## Verification state

- Source SHA-256: `87A23976EF2E1F169516D87C46C719C0DF5220D4930C7A07D98ECD09B34A574D`.
- The `functional-test-reviewer` added the exact mocked Windows acceptance cases and ran
  `uv run pytest -q tests/phase2/test_dpapi_signer_provisioning.py`: **8 tests and 9 subtests passed
  in 0.84 s**. Test SHA-256:
  `D77F1F3FDC3DAA7DE6598FDCC80859707DC9637C2B8CB6A736F9A097C7A55DD6`. It covers successful
  round-trip, exact call, exception, malformed result, wrong type/length/value, and no temporary or
  destination file on refusals. Both `python-reviewer` and `security-reviewer` reported no
  actionable issue; they confirmed that the evidence proves only current-account DPAPI recovery.
  The primary session did not run tests.
- No real DPAPI key or blob was generated. Remote provisioning and registry registration remain
  unauthorized until the exact account-private path and reviewed service/host/scope/validity
  inputs are established.

## Next steps

1. Codex: continue source-backed WP5/S13 work that does not assume an external service identity,
   trust root, or licensed-clone property mapping.
2. Functional-test reviewer: after coding closure, test successful round-trip and each malformed,
   throwing, wrong-type, wrong-length, and mismatched unprotect result; prove no file is created on
   refusal and success persists only protected bytes.
3. Operator: accountable for the deployment authority; Codex must not provision a real key until
   the approved service account, private path, registry identity, scope and validity are evidenced.
