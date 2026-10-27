# Change record 176 — typed S13 operator-resolution adapter contract

## Scope and reason

S13 must not route T16 through the legacy `present` / `attributed` boolean API. The next SQL
candidate needs a typed gateway boundary that carries immutable private-writer evidence references
and returns the exact terminal event identity for post-commit checkpointing.

## Changes

- Added the opt-in `operator_resolve_s13` entry to `SqlChangeLedger`'s private-writer signature map,
  naming `change_ledger.operator_resolve_v1` and its typed change/CAS/cosign/evidence-reference
  arguments.
- Added `SqlChangeLedger.operator_resolve_s13`. It rejects zero or non-UUID identities, blank or
  whitespace-padded evidence references, and an incomplete challenge/read-attestation pair before
  issuing SQL. It validates the result shape and event UUID and maps malformed output to
  `S13_STORE_OUTCOME_UNKNOWN`.
- The method has no fallback to the legacy boolean route. It is dormant until its SQL function,
  post-commit checkpoint continuation, and effective grants are implemented and qualified.

## Decisions and boundaries

- The SQL counterpart is not present in migration 027 yet. Enabling this method against the current
  candidate schema would fail closed at SQL function resolution; this record does not claim the
  operation is callable or implemented end to end.
- A returned event ID is necessary but not sufficient to close T16. The caller must keep the
  existing stop-effects hold active until the exact event head has been checkpointed and read back.
- No MCP tool, public gateway route, legacy adapter behavior, SQL grant, or database state was
  changed.

## Review and verification state

- Read-only `python-reviewer` review found no concrete correctness finding in the adapter changes.
  Model: GPT-6 Luna; effort: low.
- No tests, checks, build, parser, migration, database operation, COM call, staging, commit or push
  was run. `S13-OPERATOR-RESOLVE-01` remains `NOT_RUN`; SQL behavior, checkpoint continuation and
  effective grants remain `NOT_VERIFIED`.
- Current full-file SHA-256 for `sql_ledger.py` is
  `7B7A6932195342B6B4ECCFB1DF0F2C701F59610FCB09440E44C6BCFE734578FA` (the file includes prior
  uncommitted work and this record covers only the adapter addition made in this turn).
- Accountable task owner: operator; executor: Codex. A canonical technical owner for the installed
  S13 PostgreSQL function and grants is not established by this source-only change.
