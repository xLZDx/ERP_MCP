# S13 observe-target replay cutover

## Change

Recorded a high-priority legacy cutover defect: `observe_target` remains granted to `writer_role`
and candidate migration 027 has no replacement or revoke. Required an exact versioned replacement,
caller routing and signature-specific old-grant revoke before S13 activation.

## Why

The current source locks the token then record, performs `ON CONFLICT(change_id,generation) DO
NOTHING`, returns success and appends `TARGET_OBSERVED` without checking whether the insert won or
whether an existing immutable observation has the same fingerprint, class and observer. A
conflicting retry can therefore produce an event inconsistent with the stored observation. The
candidate crosswalk already states the exact replay/refusal contract, but it is not wired into
migration 027.

The exact additive entry is `change_ledger.observe_target_v1(text,text,uuid,text,text) RETURNS
boolean` with the legacy parameter order `(tenant_id,company_id,token_id,p_fingerprint,target_class)`.
`observed_by` is derived from the authenticated effective database role. Route the existing
`SqlChangeLedger.observe_target` method to the v1 function and retain caller class `writer`; add no
public MCP tool and do not route this metadata operation through the physical COM writer. Existing
focused-test coverage is not an application call site, and a repository search found no other
application call site at review time. Keep the old grant while the additive entry and adapter route
are qualified. Only after caller routing is proven may cutover revoke the exact legacy signature
from `writer_role`, `PUBLIC`, and all other runtime principals, then grant v1 to the intended
internal writer principal.

## Affected contracts and paths

- `db/phase2/005_change_registry.sql:383-401`: current mutation and event behavior.
- `db/phase2/005_change_registry.sql:1342-1345`: current explicit `writer_role` grant.
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py:112,388-390`: current adapter
  function mapping and method; it still resolves to the unversioned function.
- `db/phase2/027_private_writer_admission_schema.sql`: no `observe_target` replacement/revoke.
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py:112,137-138,388-391`:
  current-turn opt-in versioned mapping; the default still resolves to the legacy function.
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md:93,573`: source/candidate
  crosswalk.
- `docs/phase2/OPERATOR_BACKLOG.md`: ordered S13 cutover blocker.

## Decisions and verification state

Do not edit historical migrations or enable the private writer while the exact mutation/grant map
is incomplete. The eventual replacement must use the accepted common scope/global-ID fence; exact
stored tuple replay is lookup-only and conflict refuses before row/event mutation. Include
signature-specific legacy EXECUTE revocation in the reviewed cutover. This is static source review
only; no migration, test, check, database operation, COM call or production write ran. Both focused
database reviews were read-only; the follow-up found no BLOCKER/MAJOR in the exact route
clarification. Reviewer model/effort were not exposed. Candidate implementation, effective ACLs,
and disposable qualification remain open.

## Current-turn route clarification

Resolved the review's MAJOR design omission by fixing the v1 signature, adapter route, authenticated
observer derivation, and additive-before-revoke sequence in the crosswalk, disposable acceptance,
and the `observe_target` row of the 54-entry source-final grant inventory. A fresh database-reviewer
pass found no BLOCKER/MAJOR in that clarification. The focused adapter implementation now routes
to `observe_target_v1` only when `private_writer_schema_enabled=True`, preserves legacy routing by
default, and cannot fall back to the legacy API when S13 is enabled but v1 is missing. A
code-reviewer found no material finding in that exact change. The whole lock/conflict graph, SQL
function/ACL, role composition, effective grants, and runtime qualification remain open.

The existing GPT-PM request was polled by its durable request ID and is now `cancelled` with
`sendPhase=not-started`, `TASK_EXPIRED`, and no correlated user turn or reply. No GPT-PM review or
approval is claimed. Do not create a replacement review until the complete current implementation
diff is ready for the applicable gate; no commit, stage, or push was performed here.
