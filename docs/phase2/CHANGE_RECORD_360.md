# Change Record 360 — 1C license obtained on Ivan's host; COM connection to the disposable clone works

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- The operator performed the license steps in the 1C client on Ivan's host over Remote Desktop and entered every
  credential and account detail personally. The session saw only screenshots and read-only command output.
- Documentation only. No repository source changed.

## What happened

1. Before: `store-onec-admin.ps1 -TestOnly -BasePath D:\1c\env\bases\818HA_p2diff` returned `License not found` and no
   license file existed in `C:\ProgramData\1C\licenses` (see `artifacts/WP0_LOCAL_LICENSE_RECHECK_2026-10-27.md`).
2. The operator could not use "Acquire license" (no license kit number or PIN). The license file found on the local
   machine had been written 2026-10-12 and was recorded as expired 2026-10-19, exactly seven days later, which fits a
   time-limited developer license (INFERENCE). The operator chose the community license path with their own account.
3. The clone opened in the 1C client as the test administrator with the banner "This is version for developers".
   The "database was moved or restored" dialog was answered "This is a copy of the information base", which keeps
   external exchanges and scheduled external resources of the copy blocked.
4. After: the same `store-onec-admin.ps1 -TestOnly` run over SSH printed `COM connect ok     : True`. The
   `current user match` line printed no value; it was not investigated.

## Consequences

- A developer license is time limited and carries use restrictions set by 1C. The operator is responsible for
  checking that this use is allowed and for renewing the license when it expires.
- A 1C client session of the operator was still running on Ivan's host (`1cv8.exe`) when the check ran; it should be
  closed so that no interactive session stays attached to the file base.
- This unblocks only read access through COM to the clone. The operational `OneCWritePort` is still not composed,
  COM writes are not qualified, and no write to the clone was made.

## Verification state

- RUN: the COM connection test above (one call, boolean output only).
- NOT_RUN: the read-only metadata inventory (`ct14_metadata_inventory_readonly.py`) against the licensed clone, the
  CT14 effective-rights check, any COM write.
