# Change record 189 — enforce the S13 recovery-witness independence rule

## What changed

Candidate migration 027 now rejects a T16/T17 recovery witness who is the change's current approver.
The operator may remain the approver when the separately identified witness is independent. The
T16 candidate applies the condition inline; the candidate replacement for
`consume_two_person_cosign()` applies it to T17 closure and any remaining definer caller.

## Why

The candidate's prior check rejected the approver only when both operator and witness mapped to
that person. That allowed the recovery witness to be the approver when the operator was a different
person. The S12 role definition says the recovery witness is never the requester or approver, and
the S13 operator-resolution design explicitly preserves that split.

## Affected contract and paths

- `db/phase2/027_private_writer_admission_schema.sql` — candidate
  `operator_resolve_v1()` and the candidate `consume_two_person_cosign()` implementation used by
  `operator_close_failed_verify_v1()`.
- `docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md`, §§1 and T16 — the recovery witness is
  distinct from the requester and approver; T16's approver-disjointness rule.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, `operator_resolve` — the
  witness is not the approver; the operator may be approver only with an independently distinct
  witness.

## Decisions and boundaries

- Comparisons use the current scoped approval and the repository's `same_person()` mapping, not
  role-name equality alone.
- The candidate helper refuses when no current approval is available, and continues to enforce
  operator/witness distinction and requester independence.
- Historical migrations are unchanged. Candidate migration 027 remains uninstalled, ungranted for
  these routes, and unqualified; this source change is not proof of installed ACLs or identity
  mappings.

## Verification state

- Manually compared both candidate T16 and T17 paths with the cited role and design rules.
- No SQL parsing, tests/checks, build, migration, database, COM, service/listener, staging, commit,
  or push was run. SQL and runtime acceptance remain `NOT_RUN`.

## Remaining acceptance and ownership

This closes only the source-level witness-versus-approver gap in these candidate paths. The complete
FK/trigger/unique-conflict graph, person-registry behavior, exact installed grants, and disposable
concurrency cases remain open. The operator is accountable task owner; Codex is executor; the
database-reviewer role owns later schema review and the functional/E2E roles own post-coding
qualification. Next: continue the source-wide candidate closure without installing or enabling
027.
