# ERP_MCP — Reconciliation of Independent Audit Against Current Heads

Date: 2026-10-06

## Current exact heads checked after the independent review

- integration/1c-mvp-production-candidate: 98dabc3d05f47983c65d7e6220a19e2db71cf7de
- feature/admin-control-center-implementation: dff4c81d18e645fed64aed50d148ab8df9109f66
- main: 8481c0e7c794fc2474efb1b56044363043608698
- PR #11 remains Draft / Production NO-GO / DoD PARTIAL.

## Current CI

Integration:
- exact head 98dabc3
- workflow run 37490159346
- SUCCESS

Admin:
- exact head dff4c81
- workflow run 37490816842
- SUCCESS

Therefore the independent audit statement "Admin has no CI run" is stale.

## Admin delta since reviewed 68faa89

Current dff4c81 is two commits ahead of 68faa89 and contains substantial Admin-specific hardening.

Notable additions/changes include:
- src/business_ai_gateway/admin_access.py
- major admin_api.py hardening
- admin_mutations.py validation changes
- admin_probe.py hardening
- admin_session.py hardening
- auth.py/settings.py hardening
- tests/test_admin_mutations_postgres.py
- tests/test_admin_role_matrix.py
- tests/test_admin_web_hardening.py
- expanded auth/session/settings/probe tests
- operational runbook/status/documentation updates

## Current disposition of major Admin findings

### B1 migration collision
OPEN / BLOCKER.

No migration files changed between the reviewed Admin state and current dff4c81.

The Admin 008/009 numbering collision with integration 008/009 therefore remains unresolved.

### B2 cross-source mutation authorization
FIX IMPLEMENTED; exact exploit retest required.

Current code now contains stored-target scope verification through AdminRepository.visible_target() and re-checks target source before:
- grant revoke
- business-role revoke
- capability-override revoke
- semantic mapping create
- semantic profile validate
- semantic profile retire
- company-scope mapping create

Do not mark CLOSED until the original PostgreSQL exploit scenario is replayed against dff4c81.

### M1 empty admin scope fallback
FIX IMPLEMENTED.

Current Settings rejects admin scope unless split() yields exactly one nonempty scope.

Regression tests must still confirm:
- empty string rejected
- whitespace rejected
- multiple scopes rejected
- data-plane scope cannot equal admin scope

### M2 security mutation coverage
IMPROVED, RETEST REQUIRED.

Current Admin branch added real PostgreSQL mutation tests, role matrix tests and web hardening tests. Re-run the exact original 8 mutants. Target: 8/8 KILLED.

### M9 NULL/global role semantics
OPEN / POLICY DECISION + ENFORCEMENT REQUIRED.

Current AdminContext.source_scope still treats any matching source_id=NULL binding as global.

Current create_platform_role only mechanically requires PLATFORM_ADMIN to be global. It does not fully define whether SOURCE_ADMIN, ACCESS_ADMIN, PROFILE_ADMIN or AUDITOR may be global.

Must make policy explicit in:
- code validation
- DB CHECK constraints
- docs
- tests

### M10 expires_at
WEB/API FIX IMPLEMENTED.

AdminMutationService now parses ISO values via _expiry() and requires timezone-aware datetime.

CLI behavior should be verified separately.

### M12 Admin CI / uv.lock
PARTIALLY CLOSED.

- CI: CLOSED, exact current head dff4c81 has successful run 37490816842.
- uv.lock: OPEN, file is still absent from current Admin branch.

## Findings outside Admin that should NOT be fixed in this Admin-only remediation

Do not modify integration-owned behavior in this Admin-only task:
- metadata-error fingerprint lifecycle (M3)
- business_ai_app source_capabilities privilege model (M4)
- integration capability hot-row behavior (M5)
- generic onec_read entity-policy/truncation behavior (M6)
- sidecar/RSV runtime behavior (M7/M8 unless directly required by Admin probe/session boundary)
- real 1C native reconciliation
- production release registry/signing/provenance

Those belong to integration/production tracks.

## Current Admin branch conclusion

Admin is much stronger than at the reviewed SHA and has green CI, but it is not safe to merge into integration/main while B1 remains unresolved.

Before merge-readiness:
1. resolve migration lineage against current integration;
2. replay B2 exact exploit on current head;
3. rerun exact 8 security mutants;
4. define/enforce NULL/global role semantics;
5. add uv.lock / reproducible dependency contract;
6. verify CLI expires-at separately;
7. rerun full local + PostgreSQL + CI evidence;
8. keep Production GO false.
