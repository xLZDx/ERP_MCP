# S13 private-writer nil UUID guards

## Change

`PrivateWriterService._identity` now rejects the all-zero UUID in `change_id`, `call_id`,
`permit_id`, and optional `repair_authorization_id` before calling the durable admission store.
`CallIdentity.__post_init__` independently enforces the same nonzero canonical UUID contract for
identities created by any caller. The service also rejects nil dispatch-CAS IDs returned by the
store, nil barrier IDs before lookup/closure/recovery, and nil/noncanonical UUID fields in barrier
snapshots. `PostgresAdmissionStore._uuid_text` rejects nil UUIDs in its durable response decoder,
including barrier origins. The uninstalled S13 candidate SQL also rejects nil UUIDs before writes
in private-writer admission, begin-apply, permit issuance, and barrier close/finish. The new
intent, permit-binding, attempt, barrier, and barrier-call tables also enforce nonzero IDs with
`CHECK` constraints so a future security-definer caller cannot persist nil identifiers.
Startup now accepts only the same canonical lowercase UUID version/variant format produced by
`PrivateWriterService` for its process instance; service-history/fence, attempt-owner and barrier-
origin tables enforce that format too. Serving readiness and nullable UUID projections in the
evidence registry reject the all-zero UUID while preserving their allowed `NULL` state. The
evidence registry also constrains non-NULL `process_instance_id` values to canonical lowercase RFC
UUID text with the supported version/variant pattern.
The evidence-attempt selector and registrar reject nil CAS/call IDs before a read, and their
decoded attempt context rejects nil intent/repair IDs before evidence verification or registration.
`PostgresAdmissionStore` validates process-instance IDs on every admission, invocation, terminal,
recovery, and barrier write before issuing SQL. Returned active/original owner IDs and barrier
origins are checked against the candidate SQL version/variant contract. Its startup method validates
the supplied instance ID before SQL, while `_decode_startup_state` validates returned instance and
nullable readiness UUIDs before exposing them to the coordinator.

## Why

The writer-port `InvocationContext` already rejects a zero change, call, permit, or repair UUID.
Before this change, the service accepted canonical all-zero UUID text into `CallIdentity`, could
persist admission and `mark_invoking`, then failed while constructing the invocation context.
That converted malformed input into durable unresolved work before the writer could be entered.
Similarly, nil CAS/barrier IDs from a malformed store response or caller could cross the Python
boundary despite representing no usable authority/correlation identity. The service now validates
these identities before dispatch/recovery side effects, and the durable-response decoder shares the
nonzero canonical invariant.

## Affected contracts and paths

- `src/erp_mcp_private_writer/service.py`: `CallIdentity.__post_init__`, `_identity`, admission
  and recovery snapshot guards, and barrier request/snapshot validation
- `src/erp_mcp_private_writer/postgres_store.py`: canonical nonzero UUID response decoding,
  process-instance, dispatch-CAS, and barrier-snapshot validation before SQL, plus
  startup/owner/barrier-origin response validation
- `src/erp_mcp_private_writer/postgres_attempt_source.py` and
  `postgres_evidence_registrar.py`: selector, decoded-context and registration input guards
- `src/erp_mcp_private_writer/evidence_trust.py`: process-instance bindings and trust-snapshot
  requests require the canonical RFC UUID version/variant shape
- `db/phase2/027_private_writer_admission_schema.sql`: nonzero UUID checks before private-writer
  admission, begin-apply, permit issuance, and barrier close/finish writes
- `docs/phase2/S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md`: serving-readiness and evidence
  UUID invariants mirrored from the candidate schema
- `dispatch` admission ordering: identity validation precedes `store.admit`
- `src/business_ai_gateway/phase2/change_ledger/write_port.py`:
  `InvocationContext` remains the matching downstream nonzero-UUID contract

## Decision and ownership

Treat all-zero UUIDs as invalid authority and correlation identifiers, matching the existing typed
invocation and receipt-lookup contracts. Validate before storage or physical queue closure and keep
the invariant in both the immutable identity type and durable response decoder.

Accountable task owner: operator. Executor: Codex. Technical owner of the private writer service is
not established by the inspected project records.

## Verification state

This is a source-level correction based on the observed `dispatch` order (`_identity`, `admit`,
`mark_invoking`, then `InvocationContext`), barrier/recovery store boundaries, and SQL security-
definer entry points that otherwise accepted syntactically valid zero UUIDs. No test, check,
build, runtime dispatch, database operation, or COM call ran. The malformed-zero and valid-canonical
cases remain for the assigned functional/E2E phase after coding closes. Current source hashes:
`service.py` `EBF2C8F2F61FBFB2C7DEAA687D14CC4A585FA0730FB8A072DC368666D9E15E0A`;
`postgres_store.py` `E2F76BE618323E80A493CA3689695E1D4F9D160210D04A1D8E414B6EF36C6BBE`;
`postgres_attempt_source.py` `80C0B03933F158FC3DD03AEA5EF016F52FE79B49ABD61F482C09FDB923C21583`;
`postgres_evidence_registrar.py` `5F439A88DBD55857E59FBF0995A2DD718125798E11C6DC5419C0059DE99F37F4`;
candidate `027_private_writer_admission_schema.sql`
`4EC3076ADA998AA8D80BB14FD15C980E4B0A225D7BA92AE3CA4AACC54771E49A`.

## Next step

Continue the source-wide SQL/Python identity crosswalk for any UUID accepted by an S13 write entry
point. After code closure, delegate focused invalid-UUID and valid-control cases (including direct
SQL refusal before durable mutation) to the functional-test and E2E roles.

## Subsequent startup-state boundary closure (2026-10-25)

`PostgresAdmissionStore` now rejects malformed process-instance IDs before every SQL write entry
that accepts an active/current/original process owner, and rejects nil dispatch-CAS/barrier/event
UUID objects before SQL. Barrier-finish input snapshots validate barrier ID, process origin, and
call-ID arrays before JSON serialization. The call snapshot decoder validates active owner IDs;
barrier and startup decoders validate barrier-origin and service-instance IDs against the SQL
version/variant pattern. Startup input is rejected before query; startup output also requires
canonical nonzero `service_instance_id` and nullable `readiness_ref`. Invalid durable output fails
closed as `STORE_OUTCOME_UNKNOWN`. The candidate SQL startup routine requires the canonical process
UUID before base-lock/history/fence mutation and allocates ready references with PostgreSQL UUID
generation.

The candidate trust-snapshot loader also classifies an all-zero UUID inside
`p_process_instance_ids` as an invalid request before reading signer/process binding rows, matching
`EvidenceTrustSnapshotRequest`'s existing Python constructor contract.

The Python `TrustedProcessBinding` and `TrustSnapshotRequest` contracts now require process IDs to
match the same canonical lowercase UUID version/variant pattern already required by signed S12
evidence. SQL also checks process-attestation primary keys against that pattern and rejects invalid
trust-snapshot UUID arrays as `TRUST_SNAPSHOT_REQUEST_INVALID` after authenticating the ingest
session but before reading binding rows. The source hashes are `evidence_trust.py`
`580FBB1D5C39B9BBEFBE788C36F6D5272802C7496063F8BB8B2D9F76D0BA2038` and candidate SQL
`4EC3076ADA998AA8D80BB14FD15C980E4B0A225D7BA92AE3CA4AACC54771E49A`.

The candidate also rejects the all-zero UUID in non-NULL `private_writer_serving_fences.readiness_ref`
and in each nullable UUID projection field of `private_writer_evidence` (`writer_receipt_id`,
`outcome_dispatch_receipt_id`, `outcome_challenge_id`, `completion_proof_id`, and `challenge_id`),
and requires every non-NULL evidence `process_instance_id` to match the canonical RFC UUID
version/variant pattern. These checks preserve nullable semantics while preventing a sentinel UUID
from masquerading as an actual readiness or evidence identity.

This closes the adapter side of `S13-INSTANCE-UUID-01` across store entry/response boundaries. It
does not prove deployed SQL behavior or database state preservation. Cases for no SQL query on
malformed IDs, unchanged history/fence on direct SQL refusal, malformed owner/barrier/startup
responses, nil typed UUID inputs, and canonical positive controls remain `NOT_RUN`. Updated
`postgres_store.py` SHA-256: `E2F76BE618323E80A493CA3689695E1D4F9D160210D04A1D8E414B6EF36C6BBE`. Candidate SQL SHA-256: `4EC3076ADA998AA8D80BB14FD15C980E4B0A225D7BA92AE3CA4AACC54771E49A`.

## Subsequent coordinator process-identity closure (2026-10-25)

`PrivateWriterService` now rejects invalid process-instance UUIDs in startup state, pending-call
owners, ordinary call lookup, admission decisions, barrier origins, and physical barrier
acknowledgements. `PostgresWriterReceiptRegistrar` validates the caller process ID before receipt
parsing or attempt/build-provenance lookups. A non-NULL readiness reference must be canonical and
nonzero, while remaining a distinct UUID domain from process-instance IDs. The qualification plan
adds collaborator call-count assertions and canonical UUIDv4 controls. No tests, checks, SQL parse,
database operation, migration, COM call, stage, commit, or push ran. The candidate SQL remains
unparsed/uninstalled and all new cases remain `NOT_RUN`.

Current SHA-256: `service.py`
`BC5DE9BB99653036CC18EEEB742F3526248B633C179EF188D36EF7657E74E17A`; `postgres_evidence_registrar.py`
`FBB37D653F3D8CF7685DE47A7D2A2F3CE1C957B27D7D96E26F37BD23FB144475`; `postgres_store.py`
`E2F76BE618323E80A493CA3689695E1D4F9D160210D04A1D8E414B6EF36C6BBE`; `evidence_trust.py`
`580FBB1D5C39B9BBEFBE788C36F6D5272802C7496063F8BB8B2D9F76D0BA2038`; candidate SQL
`4EC3076ADA998AA8D80BB14FD15C980E4B0A225D7BA92AE3CA4AACC54771E49A`.

## Subsequent direct-SQL process-identity guards (2026-10-25)

The additive SQL entry points now apply the process UUID version/variant pattern directly to
startup, admission, invocation, terminal, recovery and barrier process-ID parameters before their
binding/fence/row reads. Recovered receipt attachment validates both active and original owners;
barrier finishing validates the snapshot origin, and authenticated barrier-ack ingestion validates
origin and writer process IDs before barrier lookup. Existing per-function refusal codes are
preserved. This does not establish PostgreSQL evaluation/lock behavior: direct-call negative cases,
zero-delta evidence, and valid controls remain `NOT_RUN`; the candidate remains unparsed/uninstalled.
Candidate SQL SHA-256: `6CBF1D23EAF3775C4AB44CE8E4E93B30B1FEF6A0C6277E914840DA326AADA8E9`.

The evidence-ingest registration guard also rejects a malformed non-NULL
`p_record.process_instance_id` before the attempt or signer-key lookup; accepted NULL projections
remain NULL. Current candidate SQL SHA-256 after this guard:
`F53623131EC07C61A4DFF7367BC259B861FD764A0B8D79BEDAF8664517F0E0A3`. The direct-call ordering,
zero-delta rejection and NULL/valid controls are mapped to
`S13-PROCESS-UUID-CONSUMERS-01` and remain `NOT_RUN`.
