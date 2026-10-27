# Change Record 364 - CT14 effective rights measured on the disposable clone

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Evidence only: `docs/phase2/artifacts/CT14_EFFECTIVE_RIGHTS_2026-10-27.json`. No source file is changed.

## What was run

- `testlane/onec_extension/scripts/ct14_effective_rights.py` on the local disposable clone
  `D:\ERP_MCP_Testbed\1c\reference\working\818HA_p2diff` (clone-only guard in `ct14_common.py`). No 1C process was running.
- The script resets the roles and password of the clone user `CT14_NARROW` (a write confined to the disposable clone; the password
  is random, in memory only), then reads the effective rights through COM as that user.

## Result (FACT: from the saved JSON)

- Roles: `CT14Писатель`, `ЗапускВнешнегоСоединения`. Committed objects: 53. Mismatch: 0. Effective rights beyond the
  committed file: 0. Listed but not effective: 0. Forbidden rights (delete, interactive delete or deletion mark) anywhere: 0.
  Effective entries: 55 (53 objects + 2 marker attributes).
- The output contains no credentials (the saved file has no password field).

## Not established

- This is the clone's rights state, not production, and not the writer composition or any document write.
- The file does not fingerprint the base or configuration; the earlier inventory (Change Record 361) covers Ivan's clone, this
  measurement covers the local clone.

## Verification state

- RUN: the script once, exit code 0. NOT_RUN: wider suite, GPT-PM review of this record.
