# Change record 187 — bound the S13 validation duplicate witness

## What changed

`validate_v1` now selects at most two matching validated business records, ordered by
`(created_at, change_id)`, before building its duplicate-witness array.

## Why

The transition only distinguishes zero matches, exactly one match for a specific duplicate
override, and multiple matches. Materializing every duplicate was unnecessary and made the
temporary result size depend on the full lifetime volume for one business key.

## Affected contract and path

- `db/phase2/027_private_writer_admission_schema.sql`, `change_ledger.validate_v1()` — duplicate
  detection and the single-collision override decision.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md` — candidate remains subject to
  bounded transaction plans and disposable qualification.

## Decisions and boundaries

- Zero results still admit normal validation; one result preserves the exact override comparison;
  two results still mean duplicate without needing further identities.
- The secondary `change_id` ordering makes the limited witness deterministic when timestamps tie.
- The change does not modify historical migrations, change grants/routes, install the candidate,
  or claim that the complete lock graph is bounded.

## Verification state

- Manually compared the consumer of `colls` with the new zero/one/multiple-result semantics.
- No SQL parser, tests/checks, build, migration, database, COM, staging, commit, or push ran.
  Candidate SQL validity and runtime behavior remain `NOT_RUN`.

## Remaining acceptance and ownership

This bounds one S13 validation query result only. The candidate remains uninstalled and unqualified;
the complete affected-row/trigger/unique-conflict graph, effective installed ACLs, and disposable
replay/race behavior are still open. The operator is accountable task owner; Codex is executor; the
database-reviewer role owns later schema/lock review. Next: continue source closure, then qualify
the duplicate and override scenarios in the approved disposable database after coding completes.
