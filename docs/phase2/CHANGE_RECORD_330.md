# Change record 330 — disambiguate supervisor revocation lookup in barrier ACK SQL

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator by explicit delegation; executor: Codex.
- Candidate migration 027 was already untracked in the shared worktree. This increment fixes a
  runtime error discovered by the full signed acknowledgement fixture; earlier migration origin
  is not attributed.
- No configured database, remote host, COM, keys, staging, commit, or push was used.

## Defect and change

After the nested composite-field correction, the exact disposable `register_barrier_ack` path
advanced to supervisor validation and failed with PostgreSQL `column reference "sk.key_id" is
ambiguous`. In that PL/pgSQL function, `sk` is a `%ROWTYPE` variable, and its field reference in an
`EXISTS` query against key revocations was ambiguous to the parser. The code now copies the locked
supervisor key ID/version into dedicated scalar variables and uses those variables in the
revocation predicate. The lock, key identity, validity and revocation policy are unchanged.

## Verification state

- Current candidate migration 027 SHA-256:
  `29CA6DB680C29707682B922CFA83823D4A53A1A8D79B90E18FB93272BD210FD7`.
- The functional-test reviewer ran the exact focused module on an invocation-owned PostgreSQL 16
  fixture: `uv run pytest -q tests/phase2/test_s13_barrier_ack_sql.py` — **6 passed in 50.59 s**,
  exit 0. Test SHA-256: `866F8DE65F5F209AEAD13B24544636525D7D982958E035508CABCC4FFD42D1D6`.
  It proves active exact binding permits durable ACK insertion; absent/base/service/host/revoked
  binding refusals add no ACK row; binding share-lock order precedes trust-revision/advisory work;
  EXECUTE remains default-denied; registration-first makes revocation wait until ACK commit, while
  revocation-first makes registration return `NOT_ENTITLED` without an ACK row.
- No configured-lane grant was measured or changed; the lane lacks candidate schema/roles. The
  current hash includes the follow-on trigger alias fix documented below; no result on `E1CF...`
  qualifies the final candidate.
- Fresh `database-reviewer` and `security-reviewer` passes reviewed exactly this migration hash
  after the six-case result. Both reported no actionable finding in the ACK registration/trigger
  path. Their scope is source/candidate only: they do not establish installed schema, configured
  grants, trusted validator provenance, or a physical COM boundary. Reviewer runtime model/effort
  metadata were not returned.

## Next steps

1. Fresh database and security reviewers: review only this exact candidate hash and the result above;
   return the exact findings with a clear scope limit if later SQL edits invalidate the hash.
2. After all S13 coding closes, the functional-test reviewer reruns the complete S13 disposable SQL
   suite against the then-final hash; old full-suite evidence is not transferable.
3. Codex keeps the registration routine revoked until authenticated evidence-ingest identity and
   validator build provenance are separately established.

## Follow-on runtime correction (same registration acceptance)

The full insertion fixture then reached the acknowledgement INSERT trigger and exposed the same
PL/pgSQL name-shadowing class inside `private_writer_barrier_ack_guard_v1()`: an unused `%ROWTYPE`
variable named `p` made `p.supervisor_key_id` ambiguous with the nested-query alias `p`. The
trigger-local variable was unused outside SQL and has been removed. This does not change validation
policy or privileges.

- Current candidate migration 027 SHA-256: `29CA6DB680C29707682B922CFA83823D4A53A1A8D79B90E18FB93272BD210FD7`.
- The exact focused test above passed on this hash. This follow-on candidate also supersedes the
  `E1CF...` hash above; results on earlier hashes do not qualify it. Full S13 candidate SQL suite,
  broader system qualification and exact-hash independent reviews remain open.

## Updated next steps

1. Fresh database and security reviewers: review only this exact candidate hash and the result above;
   return the exact findings with a clear scope limit if later SQL edits invalidate the hash.
2. After all S13 coding closes, the functional-test reviewer reruns the complete S13 disposable SQL
   suite against the then-final hash; old full-suite evidence is not transferable.
3. Codex keeps the registration routine revoked until authenticated evidence-ingest identity and
   validator build provenance are separately established.
