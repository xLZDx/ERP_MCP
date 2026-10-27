# Change Record 340 — local 1C license recheck

## Ownership and scope

- Date: 2026-10-27.
- Accountable owner: operator; executor/coordinator: Codex; technical host boundary: Ivan stack.
- This record covers only `docs/phase2/artifacts/WP0_LOCAL_LICENSE_RECHECK_2026-10-27.md` and its matching `core/LESSONS_LOG.md` entry. It does not claim authorship of pre-existing staged, modified, or untracked repository files.
- No product source, license, credential, configuration, database, or service was changed.

## Change

Recorded the operator-directed, read-only attempt to use the local 1C license for disposable clone
`818HA_p2diff`. The metadata inventory failed before COM session establishment with sanitized
classification `LICENSE`; only one `.lic` filename was present in the checked standard local
search paths. Earlier repository evidence records that file as expired. Ivan's separate
`-TestOnly` attempt likewise reported that no software license was found.

The artifact preserves the exact current-turn command/result, the inherited expiration evidence,
scope limits, and ownership/next action. Following GPT-PM's pre-commit review, the historical
expiration is now pinned to the exact source section and same full path/filename, while explicitly
stating that the current turn did not re-decode it. The artifact also scopes path coverage to the
enumerated locations and cites the vendor guide by edition and sections. It explicitly prohibits
inferring a property crosswalk, copying a license file, accepting license terms, or claiming COM
qualification from this evidence.

## Review disposition

- GPT-PM request `5f47d73d-2b14-4dd9-810f-4d0a4cbed65c` returned `MODIFY` (0 BLOCKER, 1 MAJOR,
  2 MINOR). Its MAJOR required exact provenance for the historical expiry; its MINORs required a
  precise vendor citation and bounds on the checked search paths. These documentation corrections
  address those findings. The review did not independently inspect the checkout or reproduce the
  diagnostics.

## Affected contracts and paths

- WP0/S14 read-only clone qualification evidence.
- `docs/phase2/artifacts/WP0_LOCAL_LICENSE_RECHECK_2026-10-27.md`
- `core/LESSONS_LOG.md`

## Verification state

- Read-only metadata inventory: `NOT_CONNECTED`, exit code 1, HRESULT `0x80020009`, sanitized
  class `LICENSE`; no 1C metadata or business data returned.
- Local 1C license search-path inventory: one filename observed; file contents not read.
- Historical expiry is inherited evidence, not reproduced this turn: the cited 2026-10-25 source
  section names the same full file path and records the expiry time; current recheck did not decode it.
- Windows search-path conclusion is limited to the locations enumerated in the current names-only
  check; it does not claim all possible licensing mechanisms or sources were exhausted.
- Vendor guidance citation: 1C:Enterprise 8.3 Administrator Guide, File Mode, §§ 10.3.1.4,
  10.3.7.1, and 10.3.8.1–10.3.8.2.
- No tests, checks, build, SQL parse, migration, database mutation, license activation/transfer,
  service restart, COM write, push, or deployment ran.
- License reissue/source, exact clone metadata crosswalk, effective S13 grants, and operational
  `OneCWritePort` remain outside this record and open.
