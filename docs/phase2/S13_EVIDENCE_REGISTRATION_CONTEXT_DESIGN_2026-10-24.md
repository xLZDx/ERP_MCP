# S13 evidence registration context boundary — 2026-10-24

## Decision

Keep the production evidence verifier and `private_writer_register_evidence_v1` uncomposed until
the verifier can obtain every registration field from an authenticated source. Do not add a
registrar that copies missing values from the envelope, a caller-provided mapping, or a bare
`validator_build_id` string.

This is a source-design decision for the uninstalled migration 027 candidate. It does not grant
database privileges, install SQL, approve a production validator, or qualify S12/S13.

## Current evidence

- `ProductionEvidenceVerifier.verify` parses the original bytes and checks signature, signer,
  process, operation-version and oracle policy. It now takes validation time from the loaded trust
  snapshot instead of caller-provided `trusted_now`; `VerifiedEvidenceRecord` remains an ordinary
  constructible dataclass, and neither type alone proves that a production-approved validator
  produced the result. The loaded timestamp is sampled after the repeatable-read snapshot begins,
  so it is not atomic with the snapshot's revocation view; the verifier result is provisional only.
- `DispatchAttempt` binds the attempt fields used by signature validation, but its declared
  fields omit the database `dispatch_intent_id`, `payload_digest` and nullable
  `repair_authorization_id` required by the SQL evidence composite. `CallIdentity` has the payload
  digest and repair authorization but is not a substitute for the database row or intent ID.
- `private_writer_register_evidence_v1` accepts a caller-supplied composite and checks that its
  tuple equals the locked dispatch attempt and signer scope. It assigns `verified_at` and the
  signed-byte hash in PostgreSQL, but trusts the dedicated `SESSION_USER` to have completed
  canonical parsing and signature validation. A nonblank `validator_build_id` is not itself
  provenance.
- The disposable database currently has no schema `change_ledger` or migration-027 roles and
  relations. Its effective S13 privileges therefore remain `NOT_VERIFIED`; candidate SQL is not
  runtime evidence.

Sources: `src/erp_mcp_private_writer/production_evidence_verifier.py` (`verify`,
`VerifiedEvidenceRecord`); `src/business_ai_gateway/phase2/change/evidence.py`
(`DispatchAttempt`); `src/erp_mcp_private_writer/service.py` (`CallIdentity`);
`db/phase2/027_private_writer_admission_schema.sql` (`private_writer_evidence` and
`private_writer_register_evidence_v1`); `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`
(`Disposable PostgreSQL effective grants`).

## Required registration contract

The eventual private evidence-ingest composition must derive and validate these groups without
trusting caller-selected values:

1. **Signed source:** preserve the exact original envelope bytes; parse one closed version; derive
   the exact record type, digest and typed SQL projection from that parsed record; verify signature,
   signer scope, revocation, process attestation, oracle policy and evidence-version floor.
2. **Attempt binding:** obtain the complete immutable dispatch attempt and intent tuple from an
   authenticated database path, including `dispatch_intent_id`, payload digest and repair
   authorization. Compare it with the verified record before constructing the SQL composite.
   The registration routine must continue to recheck the tuple under its own transaction and
   fences.
3. **Validation time:** the candidate snapshot loader supplies `loaded_at` from the SQL routine's
   `clock_timestamp()` and the verifier uses it for key-validity, revocation and process-age checks;
   a monotonic deadline bounds snapshot retrieval plus verification. The trust source must perform
   a fresh database call and may not return a cached snapshot. The database clock and source identity
   still require independent qualification. Because `loaded_at` can postdate the MVCC snapshot's
   revocation view, the result cannot authorize evidence by itself. Registration must acquire the
   signer key-version row lock and recheck revocation against database-assigned `verified_at` before
   accepting the record. Keep that recheck and signing-time checks mandatory.
4. **Validator provenance:** resolve the executing validator artifact/build identity from an
   authenticated deployment or attestation source and bind it to an explicit approved-build
   policy. Reject absent, stale, ambiguous or mismatched provenance before registration. A plain
   environment variable or nonempty string is not proof.
5. **Database principal:** authenticate the registration pool as the dedicated
   `private_writer_evidence_ingest` identity. The writer/admission process must not receive direct
   evidence-table, signer-registry or registration credentials. The composite-registration
   routine remains the only write path and is unavailable until the above sources are qualified.

The Python result type should not be treated as an unforgeable authorization token. The
composition must own verifier invocation, trusted time, authenticated attempt lookup, build
attestation and registration in one private service boundary; database-side tuple/revocation
rechecks remain mandatory. Any lookup function added for the ingest identity must accept an exact
call/scope selector, return only that immutable attempt, have an explicit row/field limit, and be
reviewed for enumeration and cross-tenant disclosure before it is granted.

## Acceptance evidence before wiring

- Contract review confirms every SQL projection column has one source field and exact nullability
  for each supported envelope type, including outcome versions 1–3 and no-entry receipts.
- Independent security/database review accepts the authenticated attempt lookup, validator-build
  attestation, clock, database identity, least-privilege ACL and race/revocation behavior.
- After all coding closes, `functional-test-reviewer` and `e2e-runner` qualify canonical-byte
  parsing, duplicate/unknown fields, wrong attempt/scope, all supported projections, invalid or
  stale keys, process/oracle policy, replay, outage, timeout and refusal-before-write on a
  confirmed disposable database.
- Runtime evidence records exact migration revision, effective privileges, correlated registration
  result and replay behavior. Until then registration remains disabled and qualification is
  `NOT_RUN`.

## Strict trust-snapshot JSON decoding — 2026-10-24

Static inspection found that Python's default JSON decoder accepts duplicate object keys with
last-key-wins behavior and accepts the non-standard constants `NaN`, `Infinity` and `-Infinity`.
The production trust-source candidate now rejects duplicate keys recursively, escaped unpaired
surrogates, all floating values (including `1e999`), non-integer/out-of-range numeric values,
nesting deeper than 32, more than 1,000,000 JSON values, and raw JSON text or compact dictionary
representation larger than 8 MiB. The raw-text scan counts byte size, nesting and values before
`json.loads`; the driver-dictionary path uses an iterative shape/size preflight before any
serializer. Both enforce the same schema-compatible leaves. All invalid forms map to
`TRUST_SNAPSHOT_PAYLOAD_INVALID`.

GPT-PM's adversarial pre-commit review of the exact decoder snapshot identified that
`asyncio.timeout` cannot preempt synchronous parsing. The byte/depth/node/value bounds now limit
its input and structural work; they do not establish a measured wall-clock ceiling. Worst-case
duration and allocation against the default three-second source budget remain an explicit
qualification case. The source result remains provisional and cannot authorize registration.

This closes only local parser-source findings. It does not establish the SQL function's output,
database role, effective grants, canonical envelope verification, or registration authority.
`WP5-JSON-DECODER-01` owns the duplicate-key, escape, numeric, Unicode, depth/node/byte, valid
boundary, error-sanitization and worst-case resource scenarios. State: implemented in source,
not runtime-qualified (`NOT_RUN`).

## Ownership and next dependency

Accountable task owner: operator. Executor: Codex. The Ivan stack is the recorded technical owner
of its remote host boundary, not of validator-build provenance. Current project records do not
identify a human/service authority for the approved validator build, trusted clock, or oracle-policy
administration. These are specific ownership/provenance gaps; they do not block independent source
work. The next implementation step is to define and review those three authority contracts and an
exact, least-privilege attempt-context read path. Only then implement the registrar composition.

No test, check, build, migration, database write, COM call, or evidence registration was run for
this design note.

## Exact attempt-context lookup candidate — 2026-10-25

Migration 027 now contains a source-only `private_writer_evidence_attempt_v1` lookup candidate,
and `PostgresEvidenceAttemptSource` has a bounded read-only adapter for its exact-selector result.
It requires the exact dispatch CAS ID, call ID, tenant, company, organization and base fingerprint;
returns at most one fixed-shape row containing only immutable dispatch context; returns `NULL` for
an exact-selector miss; and denies every `SESSION_USER` except the dedicated evidence-ingest role.
It exposes no table grant, and both function execution and result-type usage remain explicitly
revoked from application and evidence-ingest roles until independent database/security review has
accepted its cross-scope enumeration boundary. The lookup does not by itself authorize registration
or replace the registration routine's tuple and revocation rechecks.

Source candidate hash: `661D71F81D1B3E5AF70E9F11C185D6D0ECB5542FDD5BED20F96B7BEB4666EEF0`.
`S13-ATTEMPT-CONTEXT-LOOKUP-01` remains `NOT_RUN`: qualify exact match, wrong scope/call/CAS,
malformed selector, explicit not-found mapping, unauthorized session identity, fixed field count, immutability,
and refusal to enumerate. Both SQL and Python adapters are source-only and unreviewed as a combined
contract. No SQL parsing, installation, privilege query, test, or database action ran. Registrar
composition remains disabled pending lookup review and the separate validator-build provenance
decision.

**Bounded JSON result correction, 2026-10-25:** the Python adapter caps the SQL JSON result at 128
KiB. The SQL function bounds nine returned text columns to 2,048 UTF-8 bytes each; JSON escaping
can expand control bytes sixfold, so the cap leaves fixed key/structure overhead while remaining
finite. `PostgresEvidenceAttemptSource` accepts asyncpg's documented default JSON/JSONB string
decoding and rejects custom decoded-object codecs so the byte and duplicate-key rules cannot be
bypassed; see the upstream [asyncpg type-conversion
documentation](https://github.com/MagicStack/asyncpg/blob/master/docs/usage.rst). This exact-text
rule applies to the attempt-context adapter; `PostgresEvidenceTrustSource` separately retains the
WP5 bounded dictionary-tree path described above.
Python adapter SHA-256: `C87E76B17E1A384A4720771E744D82082C6B833B2A68FF86D8430EAFDA115A75`.
The runtime path remains unqualified, and this does not establish an approved database privilege
boundary.

## Related-record verification against one trust revision — 2026-10-25

`ProductionEvidenceVerifier.verify_set` accepts a tuple of up to five supported envelopes, rejects
duplicate causal roles and multiple outcome versions, validates each record's attempt/cross-record
binding before trust lookup, and loads one fresh snapshot for the complete set. It independently
checks every record's signer, validity/revocation window, policy, process binding, digest, and
signature against that same snapshot, returning one `VerifiedEvidenceRecord` per exact envelope
with a common trust revision and validation time. This closes the source-level gap in
`S13-PRODUCTION-EVIDENCE-VERIFY-01` at the verifier-only stage. Registrar composition and a
database candidate were added in a later source-only pass, described below.

Verifier candidate SHA-256: `C5449DB80783D0A81211E3223E4FDA883BB3661E0748BCFF351BCE90580FF44C`.
The acceptance scenario remains `NOT_RUN`; no test, SQL parse, migration, database call, or COM
operation was performed for this change. Production crypto/provider provenance and authoritative
build provenance remain separate gates.

**Local agent review disposition, 2026-10-25:** an actual read-only `code-reviewer` pass inspected
`verify_set` and its interaction with the attempt-context adapter and reported no concrete finding.
Resolved model/effort metadata was unavailable (`UNKNOWN`). This is source review only; it does not
change the `NOT_RUN` qualification state.

## Registrar composition and trust-revision admission — 2026-10-25

The current candidate now composes `PostgresWriterReceiptRegistrar` with the production verifier
for single receipts and typed evidence sets. It carries the verifier's trust revision into the
registration payload. Candidate 027 stores that revision on each evidence row, compares it while
holding `private_writer_trust_registry_revision FOR SHARE` before attempt/key/scope/lifecycle/fence
locks, and retains that lock through commit. Seven trust-registry tables acquire the same row
`FOR UPDATE` in `BEFORE STATEMENT` triggers; their existing `AFTER ROW` triggers advance the
revision. A revision guard prevents reset/deletion, and `TRUNCATE` is refused for the revision and
mutable outcome-floor table. A stale snapshot refuses with
`EVIDENCE_REGISTER_TRUST_REVISION_STALE` before evidence insertion or lookup-only replay.

This is source composition only. Candidate 027 is still unparsed, uninstalled and ungranted;
registration, stale-revision, trust-writer ordering, and replay cases remain `NOT_RUN`. The source
does not establish approved production crypto, validator build provenance, or runtime DB identity.
Next: finish source and ACL closure, then assign the mapped evidence and lock-race scenarios to the
functional/E2E roles and an exact candidate SQL/ACL review to the relevant specialists.

## Legacy mutator cutover candidate — 2026-10-25

Migration 027 now revokes runtime execution of the legacy operator-resolution routes
`operator_resolve` and `operator_close_failed_verify`, plus known direct dispatch/terminal/recovery
routes: `begin_apply`, `issue_permit`, `record_call`, `complete_signed`, `complete_lock_busy`,
`verify_signed`, `resolve_unknown_signed`, `verify_inconclusive`, `retry_verify`, both
`recover_sweep` overloads, and `revoke_stale`. These historical signatures were granted to
requester/approver/operator/writer/worker roles in migrations 004–007; exact source grants and
effects are enumerated in `S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`. The revokes
preserve migration history and do not change installed databases.

Candidate migration SHA-256: `5AFDB908B616B68C70527F45ED7193B6712DB17F74232615A24909557780BEE4`.
This is a partial source cutover: `S13-LEGACY-MUTATOR-CUTOVER-ACL-01` remains `NOT_RUN` until the
full signature/role inventory is reconciled, the candidate is independently reviewed, and
role-by-role effective rights are measured in the disposable database. No SQL parsing, migration,
database operation, or test was run.

## Approval-envelope storage candidate — 2026-10-25

Migration 027 now defines ungranted `issue_approval_nonce_v1`, `store_approval_text_v1`,
`approve_v1`, and `reject_v1` candidates, selected only when the explicit S13 schema flag is enabled.
The adapter preallocates the 64-character nonce, envelope UUID, and approval UUID before invocation.
Nonce issue takes namespace 7, snapshots at most 199 expired nonces for the scoped record, prelocks
the record and nonce identities, locks the parent record before sorted nonce children, revalidates
the exact expired set, then marks it expired and inserts the caller-preallocated nonce with the
legacy 10-minute lifetime and approver checks. Envelope storage takes the namespace-2 switch fence,
namespace-7 scope fence, lifecycle row, and namespace-6 record/nonce/envelope identities; it locks
the parent record before the nonce child, checks global envelope-ID collision, retains exact
`(change_id, nonce)` lookup-only replay (including after lifecycle advancement or nonce expiry),
keeps changed-text and wrong-requester refusal, validates the issued nonce for a new row, rechecks
canonical JSON and the stored envelope, inserts the caller-preallocated ID, and appends only the
digest event. Approval takes the switch/scope/lifecycle fences and prelocks change, nonce, and
approval IDs; exact S12 approval replay returns the existing ID only for the same nonce, approver,
digest/version while authorization is APPROVED or CLAIMED. New approval preserves independent
approver/session, envelope, epoch, duplicate-override, nonce-consumption and digest-event checks.
Rejection prelocks the same parent/nonce/approval identities and stays one-shot; unlike approval it
does not add a switch-OFF predicate, matching the legacy path. The recovery candidate already expires
nonces after parent records under the common scope fence. No new EXECUTE grant is present and legacy
routes remain the default. The candidate set still requires whole-graph review and qualification;
the feature flag must stay off and these candidates must not be granted or enabled yet.

Candidate migration SHA-256: `30D0D1092E21C719019EB3D53779AC1EBCF654DF922989390CBEE122859DE954`;
adapter SHA-256: `73AC1AC4DE9053F81E55D43284A48A2C6E761F2F0BD628A0F868EDF5629460C3`. Read-only
`database-reviewer` passes found no concrete source finding in the final envelope, nonce-issue,
reject, and approval candidates.
Resolved reviewer model/effort metadata was unavailable (`UNKNOWN`). `S13-NONCE-RANK-01` remains
`NOT_RUN`; source review does not establish SQL validity, effective privileges, or runtime ordering.
No SQL parsing, test, migration, database operation, or COM call was run for these candidates.

## Fenced validation candidate and legacy bridge — 2026-10-25

Migration 027 now defines ungranted `validate_v1(text,text,uuid)` and changes the still-granted
historical `validate(text,text,uuid)` signature to delegate to the same SECURITY DEFINER function.
The adapter selects v1 only under the explicit private-writer schema flag; legacy adapter calls now
also reach the fenced body after migration application. The function takes namespace 2, namespace 7,
and the lifecycle row before reading a non-locking record/business-key plan; it prelocks the global
change ID and exact historical namespace-4 key `(4,hashtext(t||':'||c||':'||base_fingerprint||':'||key_hash))`
before locking record then business-key rows. It revalidates both full row snapshots, preserves the
mandatory-key check for new `CREATE_DRAFT` validation, keeps terminal-state replay lookup-only, and
retains budget precheck, duplicate detection, authorized override, and the single `VALIDATED` event.
The legacy bridge resolves a real mixed-route issue: otherwise an old direct caller could hold the
record while waiting for namespace 4 as a v1 caller held namespace 4 while waiting for the record.

An actual read-only `database-reviewer` initially raised that mixed-route inversion; after the
legacy bridge was added, a fresh pass found no residual concurrency, behavior, or security finding.
Resolved model/effort metadata was unavailable (`UNKNOWN`). `S13-VALIDATE-RANK-01` remains
`NOT_RUN`; this source review does not prove migration validity, installed grants, or runtime lock
behavior. Candidate migration SHA-256:
`FE7DBADA2B548CA71F5272FF61C995997BCF7649F2F5ADBF9078C09C4A46855B`; adapter SHA-256:
`56BD13BA08AC2D95F991A58D84EE53C2CA3C2278FF17EB89FE29AA65B393CAD6`. No SQL parsing, tests,
migration, database operation, staging, commit, or push ran.

## Canonical envelope parser single-pass dispatch — 2026-10-24

`ProductionEvidenceVerifier._parse` previously tried all seven supported `from_json` classes on the
same envelope, which could repeat JSON decode and canonical serialization up to seven times for a
2 MiB input. It now performs one strict UTF-8 decode with recursive duplicate-key and constant
rejection, matches exactly one class by its complete `SCHEMA` field set, verifies byte-for-byte
canonical serialization, and constructs only that envelope type. Malformed or unknown forms map to
`EVIDENCE_ENVELOPE_INVALID` before any trust-snapshot lookup. This preserves the exact-type boundary
without trusting a caller-provided discriminator. It is source-only; per-schema behavior, parse
count, CPU/allocation and zero-source-call refusals remain `NOT_RUN` under
`WP5-VERIFIER-DECODE-01`.

**Pre-parse resource bound, 2026-10-24; tightened 2026-10-26:** the verifier lexically preflights
decoded text before `json.loads`, refusing more than 32 nested containers or 100,000 structural
nodes (object keys plus JSON values); the existing 2 MiB byte ceiling remains the outer bound.
Counting keys matters because the standard decoder materializes object pairs before the duplicate-
key hook runs. The scanner leaves full grammar validation to `json.loads`. This limits pathological
depth and tree/pair-list allocation but does not demonstrate acceptable CPU or peak memory. The
updated scanner remains unreviewed and untested; `WP5-VERIFIER-DECODE-01` is `NOT_RUN` and owns
exact key/value boundary, malformed-text and zero-trust-source-call scenarios.

The verifier's integer callback accepts only signed 64-bit evidence integers and rejects tokens
outside that range before constructing a Python integer. It also rejects every floating-point token
before float construction, matching the canonical evidence serializer's integer-only numeric
contract. Exact min/max, overflow, long-token and float-token cases remain part of the same `NOT_RUN`
qualification.

**Static review disposition, 2026-10-24:** the actual `code-reviewer` (GPT-6 Luna, low effort)
reviewed parser SHA-256
`DD1BEA6D2982EC8ECCF5700FDB427BD579A364705E9CA8D6025C59BDCAE3800E` and reported no scanner
finding. This is source review only; wall-clock and peak-allocation behavior remains unmeasured,
and all `WP5-VERIFIER-DECODE-01` executable scenarios remain `NOT_RUN`.

## Caller-scope pre-fence lookup refinement — 2026-10-25

`private_writer_register_evidence_v1` now performs its non-locking dispatch-attempt plan lookup
using the caller's exact CAS ID, tenant, company, organization and base fingerprint. An attempt
miss returns `EVIDENCE_IDENTITY_CONFLICT` immediately, before reading signer-key material. The
signer-key plan lookup then binds key ID/version and signer role/service/host to the caller tuple
and requires a key-scope row for that exact attempt scope before the routine derives base, scope,
key-material or namespace-fence identities. The trust-registry revision row is still locked first,
as required by the trust-revision writer ordering contract. The later locked rereads and complete
attempt/key-scope comparison remain mandatory.

This prevents a foreign CAS or a same-identity key scoped only to another tenant/base from
selecting unrelated base/key material for later locks. Qualification
`S13-EVIDENCE-REGISTER-PREFENCE-SCOPE-01` requires both negative cases, held-lock controls, stable
refusal and zero evidence/event deltas; it remains `NOT_RUN`. Candidate migration SHA-256:
`B328810BEC11A92ACC8FBA7100D8CB5C52442B7160781A34046611EC5A094D67`. No SQL parsing,
installation, grant, database operation or test was run.

### Candidate owner-role guard — 2026-10-25

The candidate migration additionally requires the existing `ledger_owner` role to be `NOINHERIT`
and to have no memberships in either direction. The disposable acceptance scenario checks these
catalog facts together with its non-login and non-superuser attributes; otherwise inherited or
assumable role privileges could exceed the reviewed SECURITY DEFINER owner boundary. This remains
a fail-closed source precondition, not a measured installed-role state. Updated candidate SHA-256:
`9FD636675D0B6A09F0D93BD15B511CC441B396913BCF198E509ACCA42EE7BA0A`.

### Operator resolution target-lock closure — 2026-10-25

The `operator_resolve_v1` source candidate prelocks namespace 4 for both its owned target-lock
set and the full bounded active-target parent snapshot before target-row `FOR SHARE`. The
qualification matrix adds sparse-plan contention against an unrelated active target. This is a
source candidate only; the trace and stale-plan behavior remain `NOT_RUN`. Current candidate
SHA-256: `CAC75207D5D9E031B9C5061B5B1EF81487238909B7BC946FA454FDFDF44A898F`.

## Terminal attempt-evidence association postcondition — 2026-10-25

The verified-success and recovered-terminal transition routines now check every required
`(dispatch_cas_id,evidence_ref,evidence_purpose)` association immediately after their narrowly
targeted `ON CONFLICT(dispatch_cas_id,evidence_ref) DO NOTHING` inserts. A missing or differently
purposed association returns `EVIDENCE_IDENTITY_CONFLICT/P0001` before completion/verification,
attempt finalization, base-slot release, or recovery-event append. The exact terminal replay paths
continue to validate the complete existing evidence tuple before returning.

The recovery-terminal path also preflights existing per-purpose ownership for outcome, completion,
post-completion challenge, and read attestation. A different reference for an occupied purpose now
returns the stable identity conflict before insert arbitration, rather than leaking a partial-index
unique violation.

Qualification `S13-ATTEMPT-EVIDENCE-LINK-01` captures the valid terminal transition, exact replay,
and conflicting evidence-purpose owner outcomes. It remains `NOT_RUN`; no corrupted guarded-table
state is manufactured. Candidate migration SHA-256 is
`9FD636675D0B6A09F0D93BD15B511CC441B396913BCF198E509ACCA42EE7BA0A`. No SQL parsing,
installation, grant, database operation or test was run.

## Persisted evidence resolver and production verification boundary — 2026-10-26

A concrete `PostgresWriterEvidenceResolver` now implements the existing service resolver contract.
It loads a complete immutable attempt through `PostgresEvidenceAttemptSource`, selects one to five
exact evidence references through candidate `private_writer_load_evidence_records_v1`, preserves
original signed bytes, re-derives each reference from the parsed typed record, and verifies each
record with `ProductionEvidenceVerifier.verify_set` against one fresh trust snapshot. Its SQL
routine returns only the requested envelopes for the exact dispatch CAS, call, tenant, company,
organization, base fingerprint, change ID, claim generation and operation; it caps references at
five and each envelope at 2 MiB, returns no table rows on any missing/mismatched reference, requires
the evidence-ingest session identity and remains explicitly ungranted.

The service no longer uses evaluation-only `TrustedIdentityRegistry` signature verification for
these resolved records. It requires the production verifier result to be the result associated with
each returned record, then applies the pure S12 conditional-conflict structural/binding predicate.
Production runtime composition requires the concrete PostgreSQL resolver. These Python result
objects are not unforgeable capabilities; this is source structure only and does not authorize any
SQL routine or deployment.

State: source implemented; code-reviewer review found and verified closure of a trust-source injection MAJOR and rechecked closure of a minor multidimensional-array selector edge. Independent DB/security/Python review, SQL parsing, disposable SQL and service E2E qualification are `NOT_RUN`. The 15-case functional suite previously passed against
candidate migration hash `9D0B5B2A30D6FB1C6185F10D60310745BC79EC175C71D691C44FE09B0A6249FF`; that hash predates
this resolver routine and does not cover its SQL. Effective grants remain `NOT_VERIFIED`. No
migration was applied and no live credentials, COM, or evidence registration were used.
Next: functional-test-reviewer adds exact selector/scope/miss/limit/role-denial SQL cases; E2E
runner qualifies the real resolver and service T16 journey in an owned disposable database; then
independent database/security and Python reviews assess exact current hashes. Accountable owner:
operator; executor/closure owner: Codex.




