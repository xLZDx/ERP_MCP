# WP5 production trust source candidate — 2026-10-24

## Purpose

Continue the private-writer evidence trust boundary without connecting it to the public MCP gateway
or making it operational. Preserve a strict separation from the evaluation-only identity registry.

## Current-turn changes

- Refined the uninstalled `db/phase2/027_private_writer_admission_schema.sql` candidate with
  bounded trust-record identifiers, a NULL-safe operation check, tuple-based duplicate detection,
  an exact-scope request check, historical rotation-chain output without requiring old keys to
  retain current scope, exact-oracle filtering, and explicit revokes/grants for all candidate
  runtime roles. The global collision query and trust-revision triggers were already in the
  candidate and remain unverified source claims.
- Added `src/erp_mcp_private_writer/postgres_evidence_trust.py`, an injected-pool adapter with a
  bounded top-level REPEATABLE READ READ ONLY transaction, UTC timestamp rendering, a strict
  bounded JSON decoder and stable errors. Exported it from the package and allowed historical
  rotation-only keys to carry an empty current-scope set.
- Extended `S13-PRODUCTION-TRUST-SNAPSHOT-01`, the S13 design, decision logs, backlog and WP0
  evidence to distinguish source candidates from installed authority and to record the remaining
  qualification and ownership gaps.
- Rechecked Ivan's SSH host fingerprint and stack status with strict host-key checking; called only
  local `source_health` with an in-process short-lived auditor token. A `database-reviewer` agent
  performed a read-only catalog audit of the disposable PostgreSQL instance.

## Decisions and boundaries

- The current disposable PostgreSQL database has no `change_ledger` schema or S13 roles/routines;
  installed S13 grants remain `NOT_VERIFIED`. Absence of those objects does not prove candidate
  ACL behavior.
- The measured `CT14Писатель` rights in `testlane/onec_extension/STATUS.md` and
  `CT14_FEASIBILITY_SPIKE_2026-10-12.md` are inherited clone evidence; no 1C write or rights probe
  was performed in this turn.
- Validator build provenance, trust-policy administration and private-key custody have no named
  human/service owner in the in-scope project records. The operator remains accountable for this
  delegated task; Codex is the executor; the Ivan stack owns the remote host boundary.
- The schema remains unparsed, uninstalled, unreviewed and unqualified. No evidence registrar or
  service caller was added. No private key was read or created.

## Verification state

`NOT_RUN`: tests, checks, build, CI, SQL parsing, migration, direct PostgreSQL mutation, 1C rights
probe, COM call, secret inspection and specialist code review. The only runtime observations are the
read-only SSH/stack check and local `source_health` call documented in
`docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`; the PostgreSQL catalog state was
read by the database-reviewer agent in a read-only transaction. This record is a working-tree
change record, not evidence of a commit or approval.

## Trusted-time continuation — 2026-10-24

The production verifier no longer accepts a caller-selected `trusted_now`. It uses `loaded_at` from
the coherent trust snapshot for key validity, revocation and process-binding checks, with one
monotonic deadline across source loading and signature/policy validation. The PostgreSQL source
candidate samples `loaded_at` using `clock_timestamp()` during a repeatable-read, read-only
transaction, after its MVCC snapshot begins. That time sample is not guaranteed atomic with the
snapshot's revocation view, so the verifier result is explicitly provisional. Candidate final
registration locks the signer key-version row; the revocation trigger takes an incompatible lock
on the same row, and the evidence trigger rechecks revocation against database-assigned
`verified_at`. This acceptance boundary must be retained and qualified. The trust-source contract
prohibits cached snapshots. Added `S13-TRUSTED-VALIDATION-TIME-01` as `NOT_RUN`. No tests, checks,
parser, migration, database operation, key operation, COM call, staging, commit, or push ran. The
Python reviewer identified the snapshot-time/revocation race; this continuation records the
provisional-result/final-registration boundary as its remediation. The Python reviewer re-reviewed
the source and confirmed that the candidate registration path locks the key row `FOR SHARE`, while
the revocation trigger locks it `FOR UPDATE`; the insert trigger checks revocation against
database-assigned `verified_at`. This closes the source-contract finding for new inserts only.
Runtime proof remains `NOT_RUN`; existing-row replay still requires downstream current-state
authorization. No test or SQL qualification was performed.
