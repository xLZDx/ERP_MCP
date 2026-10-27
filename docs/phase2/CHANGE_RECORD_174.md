# Change record 174 — S13 checkpoint permit-signature attachment

## Scope and reason

The frozen S13 source design defines `attach_permit_signature` as a checkpoint-role mutation that
must join the namespace-7 scope fence and lifecycle row before namespace-6 or relation work, then
lock the `records` parent before the `dispatch_permits` child. The legacy adapter had no versioned
candidate route, so candidate mode correctly refused the mutation instead of falling through.

## Changes

- Added `change_ledger.attach_permit_signature_v1` to migration 027. The source-only candidate
  checks the checkpoint role, positive generation and non-empty key/signature; acquires the scope
  fence and a READY lifecycle row; takes the change-ID namespace-6 fence; snapshots and locks the
  scoped record before its permitted dispatch row; compares both complete row snapshots; then
  validates an active ED25519 checkpoint key and the signature over the persisted permit digest
  before updating only `signer_key_id` and `signature`.
- The exact SQL signature remains explicitly revoked from PUBLIC, all application roles, the
  private-writer role and evidence-ingest role. No grant or schema enablement was added.
- Added an opt-in `SqlChangeLedger` route under `private_writer_schema_enabled`; disabled mode keeps
  the existing `attach_permit_signature` call and `checkpoint` caller class.

## Decisions and boundaries

- The candidate uses the S13 design's stated lock sequence and retains the existing signed message
  format (`change-ledger-permit|v1|<permit_digest>`).
- The candidate does not publish a checkpoint, prove current Ivan-lane grants, or qualify
  checkpoint-key revocation races.
- `operator_resolve` remains unimplemented in candidate mode because the legacy booleans cannot
  represent the accepted immutable receipt/completion/outcome/T16 evidence contract.

## Verification state

- Manually inspected the candidate body, adapter dispatch and explicit revoke. No SQL parser,
  test/check, migration, database operation, COM call, staging, commit or push was performed.
- The candidate is source-only. `S13-ATTACH-PERMIT-SIGNATURE-01` remains `NOT_RUN`; the exact
  deployed signature/grant state and concurrent lifecycle/key-revocation behavior remain
  `NOT_VERIFIED`.
- Current full-file SHA-256 values (the migration and adapter also contain pre-existing work from
  earlier turns): migration 027 `7C9D3D956DB9A132718512CF6AD865234A585591060D17FC65976E8BF27775CA`;
  `sql_ledger.py` `80090397096F7085A88C09C9CF2ABA49BCF6D4B164EF3F5E9BE60E8C8A5AF509`;
  qualification prerequisites `4FE5B13056848BE6824F5F449F9E3035076E219B6284DFC2BFCD67AFE7A7968C`.
- Accountable task owner: operator; executor: Codex. The canonical human owner for installed
  database grants is not established by this source-only change.
