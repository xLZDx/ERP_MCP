# Change Record 222 — freeze private writer service dependencies

## What changed

- Added slots for every `PrivateWriterService` field so no instance dictionary can shadow its
  validated state or configuration.
- Froze the store, physical writer, serving-authority mutex, host/base/process identity, barrier
  timeout, barrier/receipt verifiers, outcome provider and evidence resolver after construction.
- Kept startup/recovery state, service epoch, quiescence task, locks and terminal call map mutable
  for normal operation. Deletion of service fields is refused; barrier-timeout mutation preserves
  the existing `BARRIER_TIMEOUT_CONFIGURATION_IMMUTABLE` error.
- Added `S13-SERVICE-CONFIG-IMMUTABILITY-01` for dependency mutation, `__dict__` bypass, zero calls
  on refusal and continued runtime-state behavior.

## Why

The service is the bridge between authenticated admission and the physical writer. Swapping its
store, writer, host/base binding, mutex or evidence authority after construction could invalidate
the checks performed at composition time. The timeout had an existing immutability contract; this
extends the same protection to every dependency that defines the writer boundary without freezing
the runtime lifecycle state required for recovery and shutdown.

## Affected contracts and paths

- `src/erp_mcp_private_writer/service.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Evidence and verification state

`service.py` was already modified before this edit. Its captured pre-edit SHA-256 was
`27F95F216030067CBF65CB5D43A3503F53D2CE87BF933BCDFBE922D01A850768`. Current SHA-256:
`2C684B37DDA0A3E591467D062BAAFA63432F973F6A8002FE67E07818111075A5`. Current qualification
prerequisite SHA-256 after later source closures: `90E9C89AAF2C81DC8BDE2909471ED92AC6D251EFBB62CFFE1C8C206F45764CF6`.

Only source inspection and hash capture were performed. Tests/checks/build, PostgreSQL, Windows COM,
mutex/ACL runtime, staging, commit and push were not run. Runtime qualification remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: functional/E2E roles must exercise constructor
configuration, mutation refusal, no-call behavior and mutable runtime lifecycle after coding closes;
Python, security and reliability reviewers inspect the exact final composition/service boundary.
