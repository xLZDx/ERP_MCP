# Change Record 284 — revalidate the bounded stale-revocation prefix

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and source-closure owner: Codex.
- Technical owner: ERP_MCP S13 stale-epoch recovery in migration 027.
- Frozen acceptance closed: `S13-REVOKE-STALE-BATCH-RANK-01` in the disposable qualification prerequisites.
- State: SQL source candidate only. No SQL parse, test/check, migration, database operation, build, CI, staging, commit or push ran.

## Baseline and finding

`db/phase2/027_private_writer_admission_schema.sql` was already an untracked candidate before this
turn. Its turn-start SHA-256 was `A99638E2B907919D11A63A6E8EBDD3D745CC83CFA12FBD54FA5E1D103DBA4DC2`.
The qualification prerequisite file was also pre-existing and untracked; its turn-start SHA-256
was `454B333777AEA44A1859231C8CCAE4CCE7BE74E39AE48AC7998E2998B258E1FD`.
The continuation prompt was pre-existing and modified before this turn; its turn-start SHA-256
was `9A7A5C291923285F966112F1B1651D6882175C7D0D5860F13B8379E964D96B52`.

The bounded selector in `revoke_stale_v1` intentionally takes a deterministic prefix of at most 20
eligible records whose cumulative estimated lock and row-effect costs fit the 200-row caps. After
locking, the candidate rebuilt `current_records` from the full top-20 eligible window, then compared
it with `plan_records`, which contains only the selected bounded prefix. If aggregate costs force a
prefix shorter than 20, those snapshots cannot be equal, so the batch fails with `LOCK_PLAN_STALE`
before item processing. That defeats forward progress when the top-20 aggregate exceeds the cap but
its leading prefix fits.

Revalidation now reloads the exact selected record IDs (`ids`), reapplies the original tenant,
authorization, execution, dispatch and stale-epoch eligibility predicates, and compares their
complete locked snapshots with `plan_records`. A selected row that is no longer eligible therefore
produces a different snapshot and refuses. The rest of the lock plan remains separately snapshotted and
revalidated: parent records, tokens, target rows/locks, key locks, reservations, leases and failure
rows. Changes to any selected row still refuse before item effects; unselected candidates are not
misrepresented as members of the planned batch.

## Affected paths and acceptance

- `db/phase2/027_private_writer_admission_schema.sql`, `revoke_stale_v1`: revalidate only the
  bounded selected record prefix before per-item mutations.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`:
  `S13-REVOKE-STALE-BATCH-RANK-01` explicitly requires top-20 overflow to commit the selected
  prefix and requires revalidation against exactly that prefix.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md`: records the source-only defect and deferred
  qualification.
- `docs/DOCUMENT_INDEX.md`: links this record.

Post-change SHA-256 after retry-rank follow-up: migration 027 `E7C800252053B8F195818FC504C1E7F549148445A24618A5EA903EE0B1EB4025`;
qualification prerequisites `B02455AAE32898CEDE1963580C2544D451F22446019F872684BD75D843C9CE93`;
continuation prompt `45DDA98DCC86135A479CFE70A85275BD6BA62E616AA3D838C6F540C9A2FA9396`;
document index `4F87FA12A4F716C8EA71845841650C93D859FAA4066A069D0E38B1E790B9C248`.

## Review, qualification and rollout

## Follow-up source finding

The rank also encodes the retry policy: never-attempted rows precede previously failed rows, with
stable creation-time and ID tie-breaks. The first implementation used that rank to choose the
bounded prefix but re-sorted the chosen records by creation time before item execution. This could
reorder outcomes and event appends relative to the selected retry rank. The plan now carries
`batch_rank` into the ordered record snapshot, processes that JSON array with explicit ordinality,
and revalidation reconstructs the same ordering from the `REVOKE_STALE` failure timestamps before
comparing snapshots. This remains a source-only
change; it has not been SQL-parsed, independently reviewed or runtime-qualified.

The source change has not been independently reviewed or runtime-qualified. After coding closes,
`database-reviewer` should inspect the full lock/trigger/FK/effect graph and compare the bounded
prefix with serial behavior. `functional-test-reviewer` owns the >200 aggregate fixture and
no-partial-effects assertions; `e2e-runner` owns repeated passes that prove later candidates advance.
The candidate migration is not installed; keep candidate grants and activation disabled until the
source review, exact disposable qualification and effective-grant measurement pass. Do not infer a
query plan or runtime performance from this source-only change.
