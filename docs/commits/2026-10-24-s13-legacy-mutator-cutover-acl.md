# S13 legacy mutation API cutover ACL

## Change

Added `S13-LEGACY-MUTATOR-CUTOVER-ACL-01` to the S12/S13 disposable acceptance matrix and
recorded the source gap in the S13 final grant/lock inventory. The gate requires a final
signature-by-signature audit of all runtime-reachable mutation functions after migration 027:
each function must participate in the approved scope/epoch/invocation contract or lose
`EXECUTE` for runtime roles. Added the decision lesson and linked the acceptance item in the
document index.

## Why

Migration 027 is additive and its final revoke/grant block (`027:3811-3957`) controls the new
private-writer API. Historical migrations contain explicit named-role grants on mutation paths,
including `record_evidence` (`005:1342`), `complete_lock_busy` (`007:998`),
`verify_dispatch_payload` (`009:718`) and `budget_revoke` (`008:1973`). Later revokes from
`PUBLIC` do not prove that these named-role grants were removed. Leaving any legacy mutation
route reachable could bypass the new private-writer gates.

## Affected contracts and paths

- `db/phase2/027_private_writer_admission_schema.sql` (read-only grant-block inspection; not
  changed by this record)
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `docs/DOCUMENT_INDEX.md`
- `core/LESSONS_LOG.md`

## Decision and limits

- Before private admission is enabled, freeze the exact final routine signatures and runtime
  roles; preserve necessary read-only/admin APIs and explicitly fence or revoke every legacy
  mutator that can change records, grants, approvals, evidence, dispatch or resources.
- The accepted candidate must include effective-privilege evidence for each runtime role and
  `PUBLIC`; do not infer deployed rights from source grants or the current disposable database,
  which lacks the S13 schema.
- No broad wildcard revoke is proposed here because the accepted read/admin surface and exact role
  responsibilities require a signature-level inventory first.

## Verification

`NOT_RUN`: PostgreSQL catalog query, SQL parse, migration, tests, checks, build, CI, or direct
database operation. This is source-derived acceptance/design work only. No stage, commit or push
was performed.

## Current-turn source reconciliation — 2026-10-24 19:38 UTC

A lexical pass over the ordered phase-2 SQL history now records the last direct signature-level
`GRANT`/`REVOKE` per named role. It found 26 requester, 13 approver, 30 operator, 25 writer, 36
worker, 15 auditor, 9 checkpoint and 13 candidate private-writer role/signature pairs with a last
explicit source action of GRANT. The counts overlap across roles and remain source-only; they do
not expand membership/default privileges, owners, dynamic execution, installed catalog ACLs or
`PUBLIC` effective rights. Explicit revoke exceptions in migrations 007 and 008 are retained in
scope. No SQL file was changed and no catalog query, SQL parse or migration was run. Current
acceptance is still `NOT_RUN` on the disposable database lacking the S13 schema. A separate
read-only local listener check found all ten expected loopback ports present; strict SSH status on
Ivan's host reported all nine stack components `True`. Neither observation proves COM access or
transaction boundary. Evidence is recorded in
`artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`.

The qualification prerequisite now includes a read-only post-install capture template for exact
function signatures, routine owner/SECURITY DEFINER, explicit and PUBLIC ACL, effective execute for
all expected runtime roles, default function privileges, transitive role membership and direct
relation DML. A corrective source parser pass also includes the distinct evidence-ingest principal:
its four candidate grants cover trust snapshot loading, signer-key resolution, evidence registration
and barrier-ack registration. Missing roles remain visible as null rows. The template is unexecuted because the
current disposable database lacks the S13 schema and roles; no catalog query or migration ran.

Source-pass correction: the first lexical role allowlist omitted `private_writer_evidence_ingest`.
The corrected pass includes its four candidate trust-source/key-resolution/evidence-registration/
barrier-ack registration grants; the count in the source inventory now includes them. No ACL or
migration changed.

The detail record now classifies the exact candidate 027 grants by identity: three private-writer
lookups plus ten transition/barrier APIs, and four separate evidence-ingest APIs for signer
resolution, snapshot loading and the two registration routines. This is source signature mapping;
it does not establish installed ACLs, validator provenance or runtime authority.
