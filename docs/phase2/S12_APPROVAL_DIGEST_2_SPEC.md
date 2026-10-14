# S12-APPROVAL-2: shared canonical approval digest (design specification)

Status: DRAFT for the non-gating prototype. Source: GPT-PM design ruling e5d92b7a (2026-10-14), Option 2.
Not gate evidence. Release 2: NO-GO. G0-G8: NOT_PASSED. No real 1C write.

## 1. Purpose

`Approved(P) => ExecutedPayload = ReviewedPayload(P)`. One digest definition is shared by the SQL ledger and the
offline model `business_ai_gateway.phase2.change.proposal`. It replaces both `S12-APPROVAL-1` (offline) and
`S12-APPROVAL-SQL-1` (SQL). Existing digests of the old versions are never reinterpreted as version 2; prototype
approvals made under them cannot authorize a real write.

## 2. Canonical serialization

The digest input is one canonical UTF-8 text, produced by a single trusted service and stored by the ledger as
text. The ledger hashes the stored bytes as given: `approval_digest = sha256(stored canonical text)`.
`jsonb::text` is never used as the contract.

Rules (equal to the offline `canonical_json`): keys sorted, compact separators `,` and `:`, ASCII-only output
(non-ASCII escaped as `\uXXXX`), no floats and no NaN, decimals as canonical text without trailing zeros,
datetimes as aware UTC text, absent optional fields written as JSON `null` (never omitted).

## 3. Closed field list

The envelope has exactly these top-level keys; neither implementation may add or omit one:

| Key | Content |
|---|---|
| digest_version | the literal `S12-APPROVAL-2` |
| change_id | server-assigned change identity (one-time approval anchor) |
| kind | operation kind (all four kinds are covered) |
| scope | tenant, company, organization, base_fingerprint |
| payload | the full canonical payload, or `null` for UNPOST and REPAIR kinds that carry none |
| payload_digest | sha256 of canonical payload plus target_version (CT2), recomputed by the writer |
| target_ref, target_version | exact target and its version at preview |
| business_state_digest | digest of the authenticated observed target state at preview |
| parent_change_id, repair_for | lineage and repair link |
| declared_target_class | declared class of the target |
| allowed_effects | server-derived list, sorted |
| budget | the declared budget |
| duplicate_override | override pair or `null` |
| rule_table_version | `S11-RULES-2026-10-12` until changed by a new ruling |
| epoch_dependencies | sorted (principal, epoch) pairs |
| preview_digest | digest of the exact preview shown to the approver |
| approval_nonce | one-time nonce issued to the approver for this envelope |
| expires_at | expiry |

Note: the repository field names above come from revision 6 section 3 and the S13 findings document; the first
implementation task reconciles them against the actual columns of migrations 004-008 and records any difference
here before code is written.

## 4. Binding rules

1. Immutable storage: the canonical text is stored once per change and never updated; `approve` compares only
   the digest computed from the stored text.
2. Writer binding: before dispatch the writer recomputes the payload digest from the payload it is about to send
   and compares it with the stored envelope. A mismatch refuses dispatch with a fail-closed code.
3. Preview binding: a material change after preview (target version, scope, epoch dependency, business state,
   effects, budget) requires a new proposal or a fresh approval. Stale previews are refused at approve and at apply.
4. Replay: approval is one-time per (change_id, approval_nonce); claim generations, idempotency and fencing at
   execution stay as in batches A and B.
5. Data protection: the stored canonical payload is commercially sensitive; access control, retention and audit
   redaction are part of the implementation (audit records carry digests, not payload text).

## 5. Required tests (cross-language)

Python and PostgreSQL compute the digest from the same stored text and compare, for: all four operation kinds,
null fields, Unicode, decimal normalization, field-order changes, altered budget, changed target, repairs and
stale versions. Negative tests: payload substituted after approval, replayed approval, stale preview, digest of a
different version. The tests run only as focused tests on disposable `r2-s13-*` containers by the named agents,
after sprint coding is complete.

## 6. Migration plan (prototype)

Add migration 009 with a canonical-text column and the version-2 digest function; invalidate or version-gate
prototype rows of `S12-APPROVAL-SQL-1`; update `change/proposal.py::approval_digest`, the port SPEC in
`sql_ledger.py` and `checkpoint.py`, and the harness `FILES` tuple. Sequenced after batch B round 3 is committed,
because those files are under edit by the B6 work.
