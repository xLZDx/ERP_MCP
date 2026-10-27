# Change record 172 — S13 cosign entries

## Scope and reason

Closes the frozen S13 scope-fence/FK-parent-prelock gap for signed T16 witness cosign submission.
The legacy `witness_cosign_signed` still inserted a generated child ID without the common namespace-7
scope fence, namespace-6 ID plan, record-parent row lock, or durable exact-retry identity.

## Changes

- Added ungranted `change_ledger.witness_cosign_signed_v1` to migration 027. It allocates the
  candidate cosign ID before ranked locks; acquires the scope/lifecycle and sorted namespace-6
  record, completion-evidence, and cosign identities; checks an exact scope-bound replay against
  the immutable proof envelope; requires `recovery_witness` capability and `TRIAGE_REQUIRED` plus
  an open `CALL_OWNERSHIP` hold for a new submission; and locks/revalidates record/hold snapshots
  before checking the permit child and inserting the explicit cosign ID.
- Added a fail-closed preflight for duplicate historical signed-cosign identities and a partial
  unique index over `(change_id, signer, signer_session, completion_proof.evidence_id)`.
- Added the opt-in `SqlChangeLedger` route. With S13 disabled, the existing legacy method remains
  selected; with it enabled, the new route fails closed because candidate EXECUTE remains revoked.
- Added ungranted `anchor_gap_cosign_v1` with a canonical-evidence replay arbiter, hold-parent
  snapshot/lock/revalidation, replay after consumption/release, and a new-submission open-hold gate;
  exposed it only through the opt-in adapter surface.
- Updated `S13-WITNESS-COSIGN-REPLAY-01`, added `S13-ANCHOR-GAP-COSIGN-REPLAY-01`, and updated the
  scope-fence design and continuation records. Both qualifications remain `NOT_RUN`.

## Decisions and boundaries

- Kept additive rollout disabled and did not grant the candidate. This source does not establish
  installed-schema privileges, eliminate the legacy caller surface, or qualify runtime locking.
- Exact retries return the existing ID without mutation/event, including after consumption. A new
  evidence ID must match the current record generation and permit call before insertion. Stored
  proof-envelope mismatch refuses with `COSIGN_IDENTITY_CONFLICT`.
- Anchor cosign retries bind the canonical JSONB evidence digest and compare full JSONB on replay,
  so a digest collision with different evidence refuses instead of aliasing.
- The candidate does not change physical 1C writes, registry authority, or private-key custody.

## Verification state

- Source inspected manually after the edit; no SQL parser, migration, test, check, build, database
  write, COM operation, staging, commit, or push was performed.
- Runtime, effective candidate grants, concurrent retry behavior, T16 consumption, and migration
  preflight are `NOT_RUN` / `NOT_VERIFIED`.
- Current file SHA-256: migration 027
  `C3D5E2C3829D951DF9B08F4D685CE67C7510FED725AD6CFB5079A877EF8560DA`; `sql_ledger.py`
  `27935E958F21019A7AF2F6EBBACA2D50DECE8F4A1474E089882C7831D32FC8CD`.
- Accountable task owner: operator; executor: Codex. Technical owner for installed DB roles and
  schema is not established by this source-only change.
