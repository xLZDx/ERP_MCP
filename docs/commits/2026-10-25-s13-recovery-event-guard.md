# S13 recovery guard and claim replay authorization

## Change

The migration 027 candidate's recovery event sink ran after recovery rows and `sweep_runs` had been written, but called the top-level transaction assertion that rejects an already-assigned transaction ID. That made normal recovery roll back at event append. The sink now checks only that its transaction is READ COMMITTED and read/write.

The deferred recovery core was also failing before doing work when reached from `kill_switch_v1(OFF)`: that caller already owns namespace-2 and namespace-7 advisory locks and the lifecycle row. The core now keeps the full first-participant assertion for ordinary recovery and uses the transaction-mode guard only for the deferred internal route. The deferred wrapper/core/sink remain revoked from PUBLIC and runtime roles; the public kill-switch entry verifies operator entitlement.

## Evidence and limits

A read-only `database-reviewer` source review found the nested-guard blocker and confirmed the correction on re-review. The inspected source slice has no remaining BLOCKER/MAJOR finding. This is not SQL parse, migration, installed privilege, runtime, or disposable qualification evidence. No tests/checks, SQL parser, migration, database operation, or COM operation was run.

## Scope and ownership

- Candidate: `db/phase2/027_private_writer_admission_schema.sql` only for code.
- Accountable task owner: operator; executor: Codex.
- Reviewer: `database-reviewer` role; model/effort metadata unavailable.
- Next: finish aggregate source closure, then assign the completed SQL candidate to the designated test roles and specialist review.
A second source review of the same candidate found that `claim_v1` returned a current-generation token replay before checking `caller_role() == record.requester`. The ownership check now runs immediately after the locked-scope recheck and before replay. This retains lookup-only replay before readiness/switch/fresh budget checks while preventing another scoped requester from receiving the token. The database reviewer found no BLOCKER/MAJOR in this relocation. This remains source-only, not parser/runtime/qualification evidence.

Final candidate SHA-256 after the recovery-guard and claim-replay corrections: `65A05258DADD1C9F86D5FE2041045D0013635F27AC6E71D21F0895D64B0D9BFE`. Source locations: recovery sink `027:7167-7174`, deferred core guard `027:7217-7228`, requester replay authorization `027:5172-5182`.

## Legacy release route lock-order bridge

The all-path source scan found a reachable legacy `release_claim(text,text,uuid)` implementation in migration 004 that locks `claim_tokens` before `records` (004:746-756). Candidate `claim_v1` locks the record before replaying/locking the current token (027:5143-5159), so leaving the legacy route on its old body would retain a token→record versus record→token deadlock cycle when this candidate is later enabled. Migration 027 now replaces only the legacy function body with a call to `release_claim_v1`, retaining its signature and existing EXECUTE ACLs. The bridge uses a fixed `search_path` and schema-qualified target; the v1 routine remains revoked from application roles and preserves the old no-readiness-check and result/event behavior.

The actual `database-reviewer` source follow-up found no BLOCKER/MAJOR in identity preservation, authorization, SECURITY DEFINER safety, semantic parity, or removal of this lock inversion. The review relied on PostgreSQL SECURITY DEFINER semantics and `caller_role()` at migration 004:61-65; no SQL installation or runtime proof was performed. Source comments at the ACL boundary now record that the old `claim(...)` grant must be revoked atomically with enabling the S13 adapter, after all callers are routed: legacy claim locks record before grant, while `claim_v1` locks grant before record, and the old routine also does not participate in namespace-7 epoch serialization. Candidate migration SHA-256 after this documentation-only SQL comment: `C232E6C1C20C9B8C47C67BE38EFF046BA3CD0DD1113D7407158C564087D45F8F`. Bridge source: migration 027:5446-5455; additive/cutover ACL note: migration 027:9393-9402; legacy claim/release source: migration 004:647-771. Effective runtime ACLs and lock-wait behavior remain `NOT_VERIFIED`/`NOT_RUN`.

## Scope and ownership

- Candidate: `db/phase2/027_private_writer_admission_schema.sql`; documentation files are checkpoint/decision records only.
- Accountable task owner: operator; executor: Codex.
- Reviewer: `database-reviewer` role; model/effort metadata unavailable.
- Next: continue source-wide lock/trigger/FK/effect closure; then perform the authorized disposable SQL and functional/E2E qualification after coding closes.

## Claim replay key-identity and lock-plan closure

The source scan then found that `claim_v1` could return a live token for an `UPDATE_DRAFT` replay with a different `p_key_hash` (or with `NULL` after a keyed claim), because that key is represented only by the `key_locks` row when no `business_keys` declaration exists. The replay fast path now validates the supplied key against the current record-owned key lock and treats absent/present mismatch as `DIGEST_MISMATCH`. Candidate planning snapshots the business-key row and at most one owner key-lock row; after the record parent, it locks and re-reads the business-key and owner key rows and compares full planned tuples before returning or admitting. More than one owner key row fails closed. The existing `change_budget` and current claim-token locks precede the key-lock row, matching the qualification prerequisite's child order. The planned owned-key identity joins the sorted namespace-4 fences before row locks.

An actual read-only `database-reviewer` first found an error-precedence regression in the initial guard placement; it was moved inside the live-token branch after grant and amount/count checks, leaving fresh-claim validation and `NULL` semantics unchanged. That reviewer then found a MAJOR child-order issue in the first row-lock placement; the owner-key row lock was moved after budget and token. Final focused source re-review found no remaining blocker in this slice, including plan/current equality, bounded cardinality, NULL/no-business-key replay and fresh-claim precedence. This does not prove SQL validity, installed ACLs, or runtime behavior. Final candidate migration SHA-256: `5753ECC81B95820A3CEF434B9FD83EAA1D86B00AF52A525A44012F19B6721202`. Source anchors: migration 027:5077-5100, 5133-5145, 5168-5228; prerequisite `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:626`. Reviewer role: `database-reviewer`; model/effort unavailable.

## Begin-apply fence-before-row correction

The same source inventory showed `change_ledger_begin_apply_v1` acquired the parent `records` and child `claim_tokens` rows before taking its namespace-6 call/token/record/intent identity fences. The operation now takes those sorted global fences after the switch/scope/lifecycle entry gates and before either row lock; it then locks the parent record, re-reads and validates the token child, rechecks scope, and retains exact consumed-token replay and call-ID conflict behavior. An actual read-only `database-reviewer` pass found no BLOCKER/MAJOR in the fence key set, pre-lock token hint use, parent-first rows, stale-generation checks, replay tuple, or call-ID conflict path. Candidate `begin_apply_v1` grant text is to requester/writer roles, but installed effective privileges and runtime waits are not measured. Final candidate migration SHA-256: `01D28ABA725B8E3546CB8BC81057747056AA815FDFF6030BE48937E2866C4DAD`; source `027:2375-2449`, fence helper `027:1371-1385`, prerequisite `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:103,107-108`. This remains source-only, not SQL-validity or runtime proof. Reviewer role: `database-reviewer`; model/effort unavailable.
