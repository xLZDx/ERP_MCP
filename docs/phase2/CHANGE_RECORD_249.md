# Change record 249 — bridge legacy mutation routes to fenced v1 entries

Date: 2026-10-25  
Scope: S13 candidate source closure for epoch, registry, proposal, claim, approval, budget, sweep-policy, override, target-observation, requester, hold, permit, lease, and anchor/restart boundaries.

## What changed

- Migration 027 replaces the existing caller-facing `bump_epoch`, `register_principal`,
  `register_target`, `approve_registry_change`, `add_epoch_dependency`, `register_verifier_key`,
  `revoke_verifier_key`, `enforce_registry`, and `propose_registry_change` function bodies with
  SECURITY DEFINER bridges to their corresponding v1 bodies. It also bridges old granted
  `propose` to `propose_v1`, and the old granted `claim` signature to `claim_v1`, allocating the
  claim token UUID before ranked-lock acquisition.
- It also replaces the granted `issue_approval_nonce`, `store_approval_text`, `approve`, and
  `reject` bodies with bridges to fenced v1 entries, preallocating nonce/envelope/approval
  identities before ranked locking.
- It also bridges the granted `budget_admin`, `budget_revoke`, and `declare_budget` signatures to
  their fenced v1 bodies so legacy callers share the global grant-ID and parent-first lock order.
- It also bridges the granted `set_sweep_policy` signature to `set_sweep_policy_v1`, preserving
  the operator caller boundary while sharing scope/lifecycle serialization.
- It also bridges the granted `bind_duplicate_override` signature to its v1 body, preserving the
  old return/ACL boundary while preventing duplicate retry events.
- It also bridges the granted `observe_target` signature to its replay-safe v1 body, preserving
  the old token/fingerprint/class API while preventing duplicate observation events.
- It also bridges `declare_business_key` and `declare_target_class` through their existing
  signatures to the fenced requester v1 bodies.
- It also bridges `release_hold`, `cancel_permit`, and `renew_writer_lease` to their fenced v1
  bodies while retaining old signatures, defaults and ACLs.
- It also bridges `declare_anchor_gap`, `declare_unclean_restart`, and `check_anchor` to the fenced
  anchor candidates while preserving legacy signatures/return contracts.
- Existing function signatures, callers, return types, owners, and EXECUTE ACLs remain the public
  boundary. The versioned candidate functions remain revoked from application/private roles.
- All twenty-nine replacements are part of migration 027's transaction; a partial route set is not an
  accepted state.
- Migration candidate SHA-256 is recorded after the final source edit below.
- Added `S13-REGISTRY-LEGACY-BRIDGE-01` and extended `S13-CLAIM-PARENT-RANK-01` to cover old-name
  callers, direct-v1 denial, caller identity, return contracts, epoch/dependency race orders,
  verifier-key material lock races, old-name/flag-on proposal replay and global-ID races, and both
  claim route forms. Both remain `NOT_RUN`.
- Added `S13-NONCE-LEGACY-BRIDGE-01` for the approval-family bridges, direct-v1 denial, both route
  forms, identity preallocation, replay and expiry/interleaving evidence. It remains `NOT_RUN`.
- Added `S13-BUDGET-LEGACY-BRIDGE-01` for legacy and flag-on grant administration/revocation/
  declaration calls, direct-v1 denial, cross-scope ID races and parent/child order. It remains
  `NOT_RUN`.
- Added `S13-SWEEP-POLICY-LEGACY-BRIDGE-01` for old-name/flag-on merge semantics, lifecycle refusal,
  direct-v1 denial and event ordering. It remains `NOT_RUN`.
- Added `S13-OVERRIDE-LEGACY-BRIDGE-01` for old-name/flag-on replay, changed-digest refusal,
  independent approver behavior and direct-v1 denial. It remains `NOT_RUN`.
- Added `S13-OBSERVE-LEGACY-BRIDGE-01` for old-name/flag-on replay, token-generation races,
  changed-observation refusal and direct-v1 denial. It remains `NOT_RUN`.
- Added `S13-REQUESTER-MUTATION-LEGACY-BRIDGE-01` for business-key and target-class old-name/
  flag-on behavior, parent/child order and direct-v1 denial. It remains `NOT_RUN`.
- Added `S13-WRITER-RESOURCE-LEGACY-BRIDGE-01` for hold release, permit cancellation, lease renewal,
  defaults, concurrent route orders and direct-v1 denial. It remains `NOT_RUN`.
- Added `S13-ANCHOR-LEGACY-BRIDGE-01` for old-name/flag-on anchor/restart calls, same-head replay,
  stale-head refusal and direct-v1 denial. It remains `NOT_RUN`.

## Why

The v1 epoch writers, dependency reader, verifier-key routes, registry proposal path, ordinary
proposal path and claim route already take their required scope/global/key fences, but legacy names
remained granted and reachable without those shared fences. Mixed old/new calls could therefore
race a fresh dependency snapshot against principal/target epoch changes, bypass verifier-key
serialization, race same-person proposal replay or reuse a global change ID across scopes, invert
the grant/record claim order, or race approval nonce, envelope and approval IDs outside the ranked
fences. The bridges make the current signatures share the candidate boundary without granting the
new signatures directly.

## Scope and verification state

- This is candidate SQL source only. Migration 027 is not asserted installed, parsed, or granted;
  effective ACLs and runtime transaction behavior remain `NOT_VERIFIED`.
- No SQL parser, migration, database operation, test/check/build/CI, COM, staging, commit, or push
  ran. The legacy bridges and exact races remain `NOT_RUN` pending the post-coding qualification
  phase.
- Other S13 legacy/candidate routes, FK/trigger/effect closure, and physical Ivan COM writer
  boundaries remain separate open work.

## Ownership and next action

- Accountable task owner: operator; executor: Codex.
- After coding closes, `functional-test-reviewer` owns the mapped behavior scenarios and the
  `database-reviewer` owns effective privileges and lock-order review.
- Next: finish the full reachable S13 caller/FK/trigger/effect source closure, then qualify these
  twenty bridges atomically on the approved disposable schema before any candidate grant or enablement.

## 2026-10-25 ordinary proposal legacy-name bridge

After the epoch and registry legacy names were routed through their fenced v1 bodies in the same
transactional migration, the previous reason to leave `propose` unbridged no longer applied.
Migration 027 now preserves the granted legacy signature and routes it to `propose_v1`; the direct
v1 signature remains explicitly revoked. The qualification criterion now races old-name and
flag-on proposals, including same-person replay and cross-scope reuse of one global `change_id`.
Candidate migration SHA-256 after this edit:
`45FF128E57FF7E294899D5808EB791CCB5A53B65EC605F19A10C620C1EA812EC`. Qualification remains
`NOT_RUN`; this source edit does not permit candidate grants or enablement.

## 2026-10-25 approval-family legacy-name bridges

The old granted `issue_approval_nonce`, `store_approval_text`, `approve`, and `reject` names now
call their fenced v1 bodies from SECURITY DEFINER wrappers. The issuance bridge reproduces the
existing lowercase 64-hex nonce format; the other wrappers allocate their envelope/approval UUIDs
before entering the candidate lock plan. Existing old signatures/ACLs remain and direct v1 grants
remain revoked. The disposable criterion covers both old-name and flag-on routes; it remains
`NOT_RUN`. No SQL parse, test/check, database operation or migration occurred. Candidate migration
SHA-256 after this edit: `FB563CEF6194575DBC04EFF3CEC2A610E21F0F254777E64E5A1BAA78FF3B5448`.

## 2026-10-25 budget-writer legacy-name bridges

The granted legacy `budget_admin`, `budget_revoke`, and `declare_budget` names now route through
fenced v1 bodies in migration 027. Old signatures/ACLs remain and direct v1 calls stay revoked.
`S13-BUDGET-LEGACY-BRIDGE-01` covers old-name/flag-on routes, direct-v1 denial, global ID races,
update/revoke/declaration and parent/child order. It remains `NOT_RUN`. Candidate migration SHA-256:
`DD98CD5025C6F7DA3CD4D7F414545AA85F0C2194B6AA4486DB680AD9D70E20AB`.
## 2026-10-25 sweep-policy legacy-name bridge

Migration 027 now routes the granted `set_sweep_policy` signature through the scope/lifecycle-fenced
v1 routine, preserving its old signature and EXECUTE boundary while keeping direct v1 calls
revoked. Qualification `S13-SWEEP-POLICY-LEGACY-BRIDGE-01` covers merge/replay, absent-row races,
lifecycle refusals, and event order; it remains `NOT_RUN`. Candidate migration SHA-256:
`D80747E50BD875192959B85F163930B534C385E346C618684CE988534F66C046`. No parser, migration, grant,
database or test action ran.

## 2026-10-25 override-binding legacy-name bridge

Migration 027 now preserves the granted `bind_duplicate_override` signature as a SECURITY DEFINER
bridge to `bind_duplicate_override_v1`; direct v1 execution remains revoked. The bridge gives
legacy retries the candidate lookup-only behavior, preventing duplicate `OVERRIDE_BOUND` events.
`S13-OVERRIDE-LEGACY-BRIDGE-01` covers old-name/flag-on replay, changed digest, independent
approvers and direct-v1 denial; it remains `NOT_RUN`. Current migration SHA-256:
`A5F6793CF9F3DC97A41D4580E87DB3174C936C96441A121047EAB9422333956A`. No SQL parse, migration,
grant, database operation or test ran.

## 2026-10-25 target-observation legacy-name bridge

Migration 027 now preserves the granted `observe_target` signature as a SECURITY DEFINER bridge to
`observe_target_v1`; direct v1 execution remains revoked. This gives legacy callers the candidate's
stale-token revalidation and lookup-only exact replay, preventing a second `TARGET_OBSERVED` event.
`S13-OBSERVE-LEGACY-BRIDGE-01` covers both route forms and remains `NOT_RUN`. Current migration
SHA-256: `B2DC518A5F4D2F52F148D631FDFD1BC64D5CB38951A671193ADA18E87CCA95DE`. No SQL parse, migration,
grant change, database operation or test ran.

## 2026-10-25 requester business-key and target-class bridges

Migration 027 now routes the granted `declare_business_key` and `declare_target_class` names through
their fenced v1 bodies while preserving old caller signatures, defaults, owners and EXECUTE ACLs.
Direct v1 entries remain revoked. `S13-REQUESTER-MUTATION-LEGACY-BRIDGE-01` covers both route forms,
parent/child order, replay and refusal behavior; it remains `NOT_RUN`. Current migration SHA-256:
`EAD14928E49E9112C40C39011185BC79F17B7F616108E6C93B25FBE7F5A34164`. No SQL parse, migration,
grant or test ran.

## 2026-10-25 writer resource legacy-name bridges

Migration 027 now preserves the granted `release_hold`, `cancel_permit`, and `renew_writer_lease`
signatures/defaults as bridges to the fenced v1 routines; direct v1 execution remains revoked.
`S13-WRITER-RESOURCE-LEGACY-BRIDGE-01` covers old-name/flag-on races, stale generations, replay,
resource rollback and event order. It remains `NOT_RUN`. Current migration SHA-256:
`A045D51E00173BCB45BFFD9596F15EA0223D2A8D89C60E745B6F688CC50DEB30`. No SQL parse, migration,
grant change, database operation or test ran.

## 2026-10-25 anchor/restart legacy-name bridges

Migration 027 now routes the granted `declare_anchor_gap`, `declare_unclean_restart`, and
`check_anchor` signatures through fenced v1 bodies, preserving legacy owners/ACLs and return
contracts while keeping direct v1 revoked. `S13-ANCHOR-LEGACY-BRIDGE-01` covers old-name/flag-on
races, exact-head replay, stale-head refusal and lock order; it remains `NOT_RUN`. Current migration
SHA-256: `7157041478217248DAB88D18D9AB91D574B229BDEE8730362F6EB61B699D9FA8`. No parse, migration,
grant, database operation or test ran.

## 2026-10-25 dispatch receipt and payload-verification legacy-name bridges

Migration 027 now preserves the granted `require_dispatch_receipt`, `record_dispatch_receipt`,
and `verify_dispatch_payload` signatures as SECURITY DEFINER bridges to their fenced v1 bodies.
The wrappers allocate receipt/verification UUIDs before entering the ranked candidate lock plans;
the old caller-facing signatures and existing grants remain, while direct v1 execution stays
revoked. `S13-DISPATCH-RECEIPT-LEGACY-BRIDGE-01` covers route parity, replay, identity conflicts,
global ID races, caller identity, effective grants and lock order. It remains `NOT_RUN`. Current
candidate migration SHA-256: `F15DC7C042158AC2FE8F77ABAA485DCA09ED5972FC5FFBC516C2B6F2D52FCCFE`. No SQL parse, migration, grant, database operation or test ran.

## 2026-10-25 checkpoint permit-signature legacy-name bridge

Migration 027 now preserves the legacy `attach_permit_signature` signature as a SECURITY DEFINER
bridge to `attach_permit_signature_v1`, retaining its caller-facing arguments, `void` result,
checkpoint-role policy and pre-existing legacy ACL while the direct v1 entry remains revoked.
`S13-PERMIT-SIGNATURE-LEGACY-BRIDGE-01` covers effective grants, direct-v1 denial, key/permit
rotation races and the scope/lifecycle/key-material/global-ID/parent-child lock order. It remains
`NOT_RUN`; the route is source-only pending approved disposable qualification. Current candidate
migration SHA-256: `1A733B2D9C3FC6326CE5CBDD847F8D204E594BDC77D02948AD62DD315E37C5C7`. No SQL parse,
migration, grant, database operation or test ran.

## 2026-10-25 revocation bridge source checkpoint

The current additive migration preserves the old `revoke_change` signature as a fenced bridge to
`revoke_change_v1`; this keeps the old EXECUTE ACL visible for audit while enforcing operator-only
authorization inside the candidate routine. Worker `EPOCH_DEPENDENCY` calls through the old name
are intentionally refused with `NOT_ENTITLED`. Together with the earlier checkpoint-signature and
kill-switch bridges, this closes those old-name routes at the source level; the exact installed
ACL, SQLSTATE/return behavior, and lock order are still `NOT_RUN`/`NOT_VERIFIED`. Current candidate
migration SHA-256: `042BB9149C7B5AC17DB696B31E0BE14E4EEB8D444797F8AB60E83154A48948AB`. No SQL parse,
migration, grant, database operation or test ran.

## 2026-10-25 operator-only revoke-change legacy bridge

Migration 027 now routes the old `revoke_change` signature to the fenced
`revoke_change_v1`, preserving its legacy owner, return type and EXECUTE ACL while direct v1 access
remains revoked. The v1 body intentionally allows only operator identities, so workers that could
previously request `EPOCH_DEPENDENCY` revocation through the old name now receive `NOT_ENTITLED`;
the authorization contraction is explicit in `S13-REVOKE-CHANGE-LEGACY-BRIDGE-01`. Qualification
remains `NOT_RUN`. Current candidate migration SHA-256:
`042BB9149C7B5AC17DB696B31E0BE14E4EEB8D444797F8AB60E83154A48948AB`. No SQL parse, migration,
grant, database operation or test ran.

## 2026-10-25 permit-signature and kill-switch legacy-name bridges

Migration 027 now preserves the `attach_permit_signature` and operator-granted `kill_switch`
signatures as SECURITY DEFINER bridges to their fenced v1 bodies. The former retains its
checkpoint-role policy and `void` result; the latter retains the operator entry boundary and
versioned stop/recovery behavior. Direct v1 signatures remain revoked. Qualification criteria
`S13-PERMIT-SIGNATURE-LEGACY-BRIDGE-01` and `S13-KILL-SWITCH-LEGACY-BRIDGE-01` remain `NOT_RUN`;
the latter explicitly requires stopped-to-OFF refusal as `RECOVERY_NOT_READY` with no partial
recovery/mode/event effects. Current candidate migration SHA-256:
`AE51A476C8AB904206EC581F2BF96EE92AF1DD50F66F07011CEE903F38A9AEF3`. No SQL parse, migration,
grant, database operation or test ran.

## 2026-10-25 signed evidence legacy bridge and active-overload reconciliation

Migration 027 now preserves the active 12-argument `record_evidence` signature as a SECURITY
DEFINER bridge to `record_evidence_v1`, allocating the global evidence ID before ranked lock work.
The earlier 10-argument overload was dropped by migration 007 and is deliberately not recreated;
direct v1 access stays revoked. `S13-EVIDENCE-LEGACY-BRIDGE-01` covers exact immutable replay,
cross-scope ID collisions, signer-key races, caller identity and effective old grants. Qualification
remains `NOT_RUN`. Current candidate migration SHA-256:
`BDCBD890DC058FBFB301914E80EABEF6F70DB54A272F7C059BE368BB7259A6FA`. No SQL parse, migration,
grant, database operation or test ran.

## 2026-10-25 signed-evidence and witness-cosign legacy bridges

Migration 027 now preserves the active 12-argument `record_evidence` signature and the
operator-granted `witness_cosign_signed` signature as SECURITY DEFINER bridges to their fenced v1
bodies. Each keeps its caller-facing contract; evidence recording allocates `evidence_id` before
ranked locks. The retired 10-argument evidence overload remains absent, and direct v1 access stays
revoked. `S13-EVIDENCE-LEGACY-BRIDGE-01` and `S13-WITNESS-COSIGN-LEGACY-BRIDGE-01` remain
`NOT_RUN`. Current candidate migration SHA-256:
`F5512DDABC08A019A0C3387DB9A3BCE8C3FD1C345D8D25403B5FBC30F3C77D3C`. No SQL parse, migration,
grant, database operation or test ran.

## 2026-10-25 anchor-gap cosign legacy bridge

Migration 027 now preserves the operator-granted `anchor_gap_cosign` signature as a SECURITY
DEFINER bridge to `anchor_gap_cosign_v1`; the old ACL remains the entry boundary and direct v1
execution remains revoked. `S13-ANCHOR-GAP-COSIGN-LEGACY-BRIDGE-01` covers same-signer/session
replay, independent signers, stale heads, scope isolation and hold-parent/cosign-child lock order.
It remains `NOT_RUN`. Current candidate migration SHA-256:
`121B770E6FB57255EEEA4DA05B398E28B4BD242253DA5E9456F737A9B4722F9F`. No SQL parse, migration,
grant, database operation or test ran.

## 2026-10-25 legacy-route boundary comment alignment

Clarified in migration 027 and the SQL adapter that the preserved `attach_permit_signature` name
routes through the candidate v1 body when migration 027 is installed, while direct versioned
adapter selection remains feature-gated. This is source-only; no runtime flag, database grant or
installed-schema behavior was changed. Current candidate migration SHA-256:
`491868C5DCA58F1F38E61FFB89AC6D8BAC791E3778E2B600D0906506E7C8D26C`. No SQL parse, migration,
grant, database operation or test ran.
