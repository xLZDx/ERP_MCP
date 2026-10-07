# ERP_MCP — Independent Consensus Audit Snapshot (2026-10-06)

## Provenance

Independent read-only review returned on 2026-10-06. Local reviewer panel only; no external AI reviewers were used.

Important limitation: the audited repository state moved while the review was running. Findings must therefore be reconciled against current branch heads before remediation.

## Audit verdict at reviewed snapshot

| Area | Verdict |
|---|---|
| Production | NO-GO |
| Admin -> integration merge | NO-GO |
| Integration | Conditional, synthetic-pilot only |
| Admin | Not ready at reviewed SHA |
| Real 1C accounting correctness | NO-GO |

The review reported 0 native-report reconciliations against the required >=10 acceptance cases.

## Reviewed repository snapshot

- main: 8481c0e7c794fc2474efb1b56044363043608698
- integration reviewed: fc61b1c17281ea6586be8e4e2dafc370855ed306
- later integration observed during review: 42ecfbeb780d6afde87cb108a0faa293c4301f6e
- admin reviewed: 6a645bb002deeb1ef14e24dec7d7b7532ea74b36
- later admin clean archive used for mutation reproduction: 68faa8994e4fafdb3940adad8ce9207319858163
- local original worktree: D:\Repo\ERP_MCP on phase/p6-rsv-bridge-boundary, dirty and intentionally untouched

## Confirmed findings from the independent review

### B1 — BLOCKER — migration identity collision

Integration and Admin used the same migration integer versions for different content.

Integration:
- 008_confirmed_semantic_mappings.sql
- 009_audit_semantic_profile_fingerprint.sql

Admin:
- 008_admin_platform_roles.sql
- 009_admin_mutation_control.sql
- 010_business_capability_policy.sql
- 011_company_scope_mappings.sql

scripts/migrate.py identifies migration state by integer version only.

Runtime reproduction on PostgreSQL 16 showed:
- existing integration v9 + admin migrations can result in schema version 11 while critical admin objects are absent;
- reverse ordering can leave integration objects/triggers absent;
- no checksum or migration-name identity is persisted;
- duplicate migration numbers are not rejected by CI.

### B2 — BLOCKER at reviewed Admin SHA — cross-source mutation authorization

At the reviewed clean Admin SHA, an ACCESS_ADMIN scoped to source-a plus AUDITOR scoped to source-b could revoke a grant in source-b because route authorization and object visibility were composed incorrectly.

The same pattern was identified for:
- business role revoke
- capability override revoke
- semantic mapping create
- semantic profile validate
- semantic profile retire
- company-scope mapping create

### M1 — empty admin scope fallback

At the reviewed SHA an empty admin OAuth scope could fall through to the data-plane onec:read scope. Whitespace-only scope behaved differently.

### M2 — admin mutation-test weakness

At clean admin commit 68faa89, 8/8 selected security mutants survived the full suite:
- revoked binding filter
- expiry filter
- no-binding 403
- token-none 401
- can_admin_source
- row_version
- idempotency replay
- request fingerprint

### M3 — metadata transport failure mutates persistent semantic truth

A simulated metadata ReadTimeout was persisted as a metadata-error fingerprint, caused DRIFTED, and transitioned a VALIDATED profile to STALE.

After metadata recovery:
- drift stayed sticky;
- profile stayed STALE;
- no direct STALE -> VALIDATED path was demonstrated;
- invalidation was not represented as a semantic profile lifecycle event.

### M4 — runtime DB role can update source_capabilities

business_ai_app could UPDATE bag.source_capabilities, including drift state, contradicting the documented least-privilege model.

### M5 — capability hot-row churn

Repeated identical capability saves update the same row. The review measured 999/1000 identical calls causing physical MVCC churn. TOAST growth was demonstrated only with synthetic large JSON and should not be generalized without production-size evidence.

### M6 — generic onec_read remains broad

The old claim that a company-only grant could use onec_read to read another company was disproved.

Remaining issue:
- generic onec_read is source-wide;
- empty entity allowlist defaults broad;
- expand/select/navigation policy is not fully constrained by entity policy;
- truncation/paging semantics are incomplete.

### M7 — observability gaps

Dependency metrics are not wired across all real dependency paths. Audit-failure alert semantics may miss the first failure depending on series behavior.

### M8 — sidecar/RSV resilience gaps

Reported code-level concerns:
- sidecar circuit breaker includes client errors;
- sidecar logging/request correlation gaps;
- shared bearer model;
- fanout path integration incomplete;
- RSV process concurrency unbounded.

### M9 — platform role NULL scope semantics

source_id = NULL acts as global scope for all platform roles, while DB constraints explicitly model only part of this policy. The semantic contract must be explicit and mechanically enforced.

### M10 — expires_at validation

At the reviewed service path, ISO strings could reach asyncpg as strings and trigger DataError.

### M11 — policy model/enforcement concerns

Two policy layers coexist:
- access grants
- business roles/capability overrides

Business capability enforcement was optional by default and company-scope mapping lifecycle/invalidation needed stronger guarantees.

### M12 — Admin branch CI/dependency reproducibility at reviewed snapshot

At the reviewed point:
- no GitHub CI evidence was available for Admin;
- uv.lock was absent.

### M13 — documentation consistency

The review found:
- multiple competing "current authoritative" sections;
- stale D-gate tables;
- device/tool-output leakage in tracked documents;
- stale/inaccurate role descriptions;
- incomplete README tool inventory;
- upstream naming inconsistencies.

### M14 — append-only audit owner/TRUNCATE caveat

Triggers protected UPDATE/DELETE in normal roles but owner-level TRUNCATE was not blocked.

## Mutation results reported

Admin clean 68faa89:
- 8/8 targeted security mutants survived.

Integration fc61b1c:
- strong tests killed several important mutations;
- grant expiry and source-host validation survived clean runs;
- some other mutation results were inconclusive due concurrent scratch-tree edits.

## Documentation truthfulness findings

- Production fail-closed: configuration-level support, not deployed proof.
- Read-only by construction: production zero-write proof still open.
- Company isolation: synthetic/partial.
- Runtime role "SELECT + INSERT audit only": false at reviewed state because source_capabilities is writable.
- Append-only audit: mostly true for normal roles; TRUNCATE caveat remains.
- Native reconciliation: 0 recorded at review.
- Migration safety between trees: false.
- Release publication/signing/attestation/provenance: not established.
- Production readiness docs correctly say NO-GO.

## Real 1C evidence status at review

Present:
- disposable local 1C 8.3.27
- RSV v1.3.0
- ping
- bridge kill/reconnect
- metadata operations

Missing:
- real OData metadata handshake/fingerprint evidence
- >=10 native-report reconciliations
- production-equivalent pilot
- complete reference/Ferma native-observer evidence

## Independent remediation order

P0 before merge:
- migration collision
- cross-source admin mutation authorization
- strict admin scope validation
- Admin CI
- reproducible dependency lock

P1 before synthetic pilot:
- runtime DB privilege split
- metadata-failure lifecycle
- capability upsert churn
- generic entity policy/truncation
- admin route/mutation regression tests
- grant expiry/source-host/rate-limit tests
- documentation cleanup

P2 before real 1C pilot:
- >=10 native report reconciliations
- real OData metadata handshake
- sidecar/RSV resilience and dependency metrics

P3 before production:
- registry publication/signing/attestation/provenance
- PITR/rollback rehearsal
- SLO/burn-rate alerts
- audit TRUNCATE protection
- final Admin UX/accessibility
- mandatory production capability-enforcement policy

## Final independent review conclusion

Production GO cannot be claimed. The most important merge blocker is migration identity collision. At the reviewed Admin SHA, a cross-source mutation authorization bypass was also runtime-reproduced.
