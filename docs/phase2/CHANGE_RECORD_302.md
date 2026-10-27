# Change Record 302 — make lease-generation comparison null-safe

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 private writer.
- Acceptance: `S13-LEASE-RENEW-RANK-01`.
- State: source-only candidate; manual and bounded independent source review found no issue in this function. No tests/checks/build/CI, SQL parse/migration, database or COM operation, stage, commit, or push ran.

## Finding and change

`renew_writer_lease_v1` compared `p_generation` with the record generation using SQL `<>`. When `p_generation` is NULL, that expression is NULL rather than true, so the function could skip the generation-mismatch refusal and continue to permit lookup, returning a later error class such as `PERMIT_MISSING`.

Migration 027 now uses `IS DISTINCT FROM`, making NULL a generation mismatch and preserving the required `TICKET_SUPERSEDED` precedence before execution-state and permit checks. The qualification scenario now states the NULL-generation case explicitly.

## Evidence and limits

The acceptance is `S13-LEASE-RENEW-RANK-01` in `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`. The implementation is `change_ledger.renew_writer_lease_v1` in `db/phase2/027_private_writer_admission_schema.sql`.

This is manual source work, not parsed or runtime-proven. Migration 027 is uninstalled and ungranted; effective privileges remain `NOT_MEASURABLE` on the inspected disposable database and qualification remains `NOT_RUN`.

An independent `code-reviewer` agent reviewed `renew_writer_lease_v1` and adjacent cancellation/release routines. It found no source-level issue in the NULL-generation refusal branch. The review was limited to those routines; ACL, races and runtime qualification remain open. Reviewer model is the configured `gpt-6-luna`; exact reasoning effort was not exposed by the launch result.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — null-safe generation mismatch check before permit checks.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — makes null generation explicit in refusal-precedence coverage.
