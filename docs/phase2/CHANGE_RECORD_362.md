# Change Record 362 — hardening of the host-side CT14 inventory script after the GPT-PM review

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers `scripts/remote/ct14_metadata_inventory_ivan.ps1`, the new
  `tests/phase2/test_ct14_inventory_script_input_boundary.py` and the log entries.

## Findings addressed (GPT-PM delta gate 2, head f013c0b)

- M-01 MAJOR: the script interpolated the free-form `-BasePath` parameter into the credential-bearing COM
  connection string, so quote or semicolon syntax could alter the string. Fix: the path must equal one entry of the
  approved list (`D:\1c\env\bases\818HA_p2diff`, case sensitive); anything else prints
  `{"error":"BASE_PATH_NOT_APPROVED"}` and exits with code 2 before the stored login is decrypted or COM is touched.
- N-01 MINOR: the error handler printed up to 200 characters of exception text and could not replace the password
  after it had been cleared. Fix: only the stable code `INVENTORY_FAILED` and the exception class name are printed.
- The generator keeps the file ASCII only; the script was regenerated, not edited by hand.

## Tests

- Seven refusal cases (quote plus semicolon injection, semicolon injection, an unapproved base, a case variant, a UNC
  path, a relative path, an empty value): exit code 2, the stable error JSON, empty stderr. They run the real script
  with Windows PowerShell and touch neither COM nor the stored login.
- One text check that the error path never prints `$_.Exception.Message`.

## Verification state

- RUN: 8 passed; the hardened script was redeployed to Ivan's host and the inventory ran again with the same output
  shape (configuration, platform, 73 attributes of the document).
- NOT_RUN: a failing COM connection to see the sanitized error live (it would need a deliberately broken login),
  wider suite, GPT-PM re-review of this change.
- Known minor: the `-Root` parameter (location of the stored login blob) is not allow-listed; it cannot change the
  base the login is sent to.
