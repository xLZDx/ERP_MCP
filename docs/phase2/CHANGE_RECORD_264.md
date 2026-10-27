# Change Record 264 — reject zero preallocated S13 identities

## What changed

- Candidate identity writers now reject `NULL` and the all-zero UUID for `claim_v1.p_token_id`,
  `propose_v1.p_change_id`, `propose_registry_change_v1.p_change_id`,
  `record_dispatch_receipt_v1.p_receipt_id`,
  `verify_dispatch_payload_v1.p_verification_id`, `store_approval_text_v1.p_envelope_id`, and
  `approve_v1` / `reject_v1.p_approval_id` with `SCHEMA_INVALID`. `budget_admin_v1` also rejects a
  supplied all-zero grant ID while preserving `NULL` as its generated-ID request.
- `verify_inconclusive_v1` rejects a non-NULL all-zero `p_observation` before ranked locks while
  retaining the legacy `EVIDENCE_UNSIGNED` path for NULL observations.
- Private-writer attempt transitions and evidence lookup now reject an all-zero
  `p_dispatch_cas_id` with their existing stable boundary error before ranked locks, row locks or
  the table CHECK constraint.
- These refusals occur before ranked advisory locks, relation-row locks, or mutation.
- Disposable acceptance now requires unchanged relevant rows and event head for each nil-UUID
  refusal, then a valid nonzero ID through the corresponding adapter route.
- The `budget_admin` design crosswalk and S13 disposable prerequisites now describe the zero grant-
  ID boundary, preserve generated IDs for NULL, define the non-NULL zero observation case without
  changing NULL precedence, and require stable pre-lock dispatch-CAS refusals.

## Why

These candidate APIs accept identities that participate in globally fenced keys or persisted rows.
The referenced legacy tables do not consistently prohibit the all-zero UUID themselves, while
adapter code normally creates these values with `uuid4()`. Enforcing the same nonzero invariant at
  each SQL boundary protects direct owner-level qualification and prevents a sentinel from becoming
  a token, grant, registry, receipt, verification, envelope, or approval identity.

## Evidence and limits

- Candidate guards: `db/phase2/027_private_writer_admission_schema.sql:4491,4591,4688,6235,6660,10167,10280,10544,10620,10724`.
- Dispatch-CAS boundary guards: `db/phase2/027_private_writer_admission_schema.sql:2203,2331,2756,2842,2972,3107,3421,3611`.
- Existing UUID primary keys have no all-zero check: records `004:213-214`, claim tokens `004:309-316`,
  grants `004:350-358`, approvals `004:378-384`, approval envelopes `009:42-51`, registry changes `010:37-47`,
  verify attempt-log identity `008:1824-1828`, dispatch verifications `012:43-51`, and dispatch
  receipts `016:59-71`. Candidate `dispatch_attempts.dispatch_cas_id` has a table CHECK at `027:597`;
  its eight caller boundaries now reject the value before reaching that constraint.
- The disposable `S13-PREALLOCATED-ID-01` criterion covers nil-ID refusals, unchanged state, and the
  `budget_admin_v1` NULL-generated-ID control, and the NULL-observation error-precedence control.
- This candidate remains unparsed, uninstalled and ungranted. No SQL parser, tests, checks, build,
  CI, migration, database operation, COM call, staging, commit or push was run. Invalid-token and
  unchanged-state qualification remain `NOT_RUN`; effective candidate grants remain
  `NOT_VERIFIED`.
- A read-only `code-reviewer` pass and follow-up found no concrete issue in the nine guarded routes,
  including the rule that `budget_admin_v1` rejects only a supplied zero grant ID while preserving
  `NULL` as the generated-ID request. Model and effort metadata were not exposed. This is source
  review only, not runtime qualification.
- The reviewer follow-ups also found no concrete issue in the non-NULL zero-observation refusal or
  the eight dispatch-CAS boundaries; both preserve their specified NULL/error precedence and refuse
  before ranked locks, row locks or DML. Model and effort metadata were not exposed. Runtime
  qualification remains `NOT_RUN`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. After source coding closes, the database reviewer
owns the SQL/grant review; functional-test-reviewer owns the invalid-token and replay cases, and
e2e-runner owns the service-driven claim journey. Next: continue the S13 lock/FK/trigger/effect
closure, then route the exact candidate to post-coding review and disposable qualification.

Candidate migration SHA-256 after this change: E42C87AACCD2E1CD68F0B24682171128955214ABC479E605A88F816569EC78FA.
