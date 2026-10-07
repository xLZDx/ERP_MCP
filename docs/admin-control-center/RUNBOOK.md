# Admin Control Center operator runbook

Current operational contract: [Operations Runbook](OPERATIONS_RUNBOOK.md). The continuation
uses connect-time DNS pinning, verified step-up and bounded policy explanation; that runbook
supersedes earlier rollout details in this handoff guide.

## Purpose

Operate the Admin Control Center without weakening the ERP_MCP read-only data plane.

## Pre-activation checklist

1. Deploy migrations through schema version 11.
2. Verify database privileges with scripts/check_db_privileges.py.
3. Register a dedicated OIDC client for the Admin Control Center.
4. Configure a distinct admin audience and scope; do not reuse onec:read.
5. Configure BAG_ADMIN_CONTROL_DATABASE_URL with the business_ai_control_api credential.
6. Configure exact 1C host allowlist and approved CIDRs.
7. Bootstrap at least one PLATFORM_ADMIN subject/group through scripts/admin.py.
8. Leave admin mutations and business capability enforcement disabled until bootstrap verification is complete.

## Bootstrap first platform administrator

Use the operator/admin database credential:

    python scripts/admin.py platform-role-add       --kind subject       --principal <oidc-sub>       --role PLATFORM_ADMIN       --created-by <operator-id>       --reason "Initial Admin Control Center bootstrap"

Record the returned binding ID in controlled deployment evidence.

## Activation order

1. BAG_ADMIN_API_ENABLED=true
2. BAG_ADMIN_UI_ENABLED=true
3. Verify /admin/ OIDC login and /admin/v1/me.
4. Confirm the intended platform role and delegated source scope.
5. Run safe source-probe smoke against one approved non-production/test 1C endpoint.
6. Enable BAG_ADMIN_MUTATIONS_ENABLED=true.
7. Exercise one create/revoke test grant and verify admin_audit_events.
8. Configure business-role/capability assignments.
9. Enable BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED=true only when intended callers have policy.
10. Enable only fixed company-aware canonical operations with validated semantic profiles. Admin company-scope mappings are candidates and do not authorize reads.

## Incident / break-glass

If Admin UI behavior is suspect:
- disable BAG_ADMIN_UI_ENABLED and BAG_ADMIN_MUTATIONS_ENABLED;
- keep MCP runtime and existing access policy intact;
- use operator CLI with business_ai_admin only from the controlled operator environment;
- do not delete policy/audit rows;
- inspect admin_audit_events and runtime audit correlation.

If business capability policy causes unintended denials, disable BAG_BUSINESS_CAPABILITY_ENFORCEMENT_ENABLED as an application rollback while preserving assignments for investigation.

## Revocation

Web revocation uses the exact grant_id / binding_id / assignment_id / override_id plus expected row_version. Broad-match revoke is not a web contract.

For an employee departure:
1. disable/revoke identity in the IdP;
2. revoke ERP_MCP grants/roles as required;
3. preserve rows and audit history.

## Source onboarding

A source probe:
- accepts only a configured allowed host;
- optionally requires every resolved address to lie in approved CIDRs;
- follows no redirects;
- performs GET/HEAD-only behavior through the existing read-only 1C client;
- resolves secret references server-side;
- does not return credential values.

Registration must be reviewed after probe. Company discovery is advisory; manual company registration by source_id + external_ref remains authoritative.

## Rollback

Routine rollback is configuration/application rollback:
- turn off UI/API mutations/capability enforcement;
- deploy previous application version if needed;
- leave additive migrations 008-011 in place.

Dropping policy/audit tables or deleting history is destructive and requires explicit C4 approval.

## Evidence capture

For release/pilot record:
- exact commit SHA;
- migration max version;
- DB privilege checker output;
- full pytest/Ruff/compileall/Bandit/pip-audit output;
- real IdP login smoke;
- safe source-probe target and result;
- platform-role bootstrap binding ID;
- admin audit event IDs for test mutation/revoke;
- company-scope mapping/profile fingerprint for each enabled company-aware operation.
