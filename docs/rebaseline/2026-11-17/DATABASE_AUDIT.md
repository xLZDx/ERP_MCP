# Database implementation and qualification audit — 2026-11-17

Static database-reviewer inspection; no SQL parse/execution, migrations,
test suite, database connection or effective-grant probe was run.

## Current source versus recorded evidence

Committed db/phase2/027_private_writer_admission_schema.sql is identical between
HEAD and origin/main in the inspected comparison. Its working-copy delta is
115 insertions and 24 deletions. The delta is uncommitted evidence, not part of
the current main baseline or the old qualification run.

The 2026-10-28 S13_PG_QUALIFICATION_REPORT records 27/27 migrations applied and
027 SHA d60423aafb89ca3f7d4c9e0b8b48e563a083550162df7c710b2fe45690a0b90b.
That historical SQL/grants report cannot qualify the different current dirty
027 bytes. Preserve its passes as historical; rerun only affected qualification
after the integrated candidate is coded and permitted named scenarios are ready.

## Implemented mechanisms inspected

027 contains constrained service/key/version/scope/revocation tables, dispatch
intents, permit bindings, immutable typed evidence and attempt links, barrier
acknowledgments and purpose/dispatch constraints (1160-1195). SECURITY DEFINER
routines pin search_path; revokes/grants are concentrated at 12046-12444 and
13132-13187. These are source observations, not installed grant evidence.

Dirty lifecycle changes add fresh READ COMMITTED fence re-reads after locked
reads. private_writer_assert_transaction_v1 (1929-1954) explicitly requires
READ COMMITTED and no preheld advisory/strong relation locks. Barrier ACK code
(1368-1488) sorts and deduplicates key-material advisory IDs before later fences,
then locks binding/trust revision rows. Inspected changes align with their
stated lock-order rationale; no reachable correctness defect was established
from those hunks. This is not approval of every SQL path.

## Historical grants and qualification limits

The recorded matrix reported no PUBLIC EXECUTE/usage/table/sequence grants,
no direct runtime table DML, 57 private-writer SECURITY DEFINER routines owned
by ledger_owner with pinned search_path, and 13 private-writer execution
endpoints. Evidence-ingest had no function/table grants and the production
validator identity was explicitly absent, preventing operational registration.
This is a deliberate qualification boundary, not proof that current deployment
is misconfigured or correctly installed.

Historical partial cases include E18 crash, E25 restore skew without ledger-to-1C,
E36 test-double anchor, E11 kill-switch without actual COM outage, E13 audit sink,
E20 approval race without complete live routing. E38 parallel follow-up exists,
but mixed currencies, consumed POST and revocation/update-vs-claim remain open.
The prerequisites document also lists source-only rank/recovery/physical-dispatch
follow-ups as NOT_RUN. Do not erase earlier bounded passes or promote partial
scenarios to whole-writer acceptance.

## Gateway capability migration concurrency

Separate Python-reviewer source finding G-01 is corroborated by migration 016:
record_capability_observation deletes all source observations (151-155) while
its advisory lock is transaction-scoped (129). Observer then calls acceptor in
a later HTTP step. Two requests can overwrite each other's pending observation.
Fix and qualify the two-request/retry/crash matrix before integrating this new
flow. See INTEGRATION_BACKLOG.md for the exact bounded correction requirement.

## Coverage

Reviewed changed 027 hunks, key constraints, transaction assertion, selected
claim/grant/recovery declarations, grants tail, and the qualification/grants/
prerequisite documents. Not a line-by-line review of all 13,000 SQL lines.
Certificate/session binding, current installed schema/ACL, full lock graph and
live physical-writer behavior remain unverified. These are explicit follow-up
qualification requirements in the rebuilt program, not new operator requests.
