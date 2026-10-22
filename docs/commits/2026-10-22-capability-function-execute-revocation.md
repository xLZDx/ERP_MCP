# Change record: Restrict capability observation function execution

## Change

- Added `db/migrations/015_capability_observation_execute_boundary.sql` to revoke `PUBLIC EXECUTE` from `bag.record_capability_observation(...)`, remove direct grants from the admin/control runtime roles when present, grant the required application role, then fail transactionally if either admin/control role retains effective EXECUTE through direct or inherited membership. The migration fails if the application role is missing.
- Advanced the gateway migration schema version from 14 to 15 and updated the migration-acceptance utility's unknown-future version fixture from 15 to 16.
- Extended `scripts/verify_schema.py` to assert that PUBLIC/admin/control lack effective EXECUTE while `business_ai_app` retains it.
- Updated operator-facing schema-version references from 14 to 15.
- Added a lesson recording that explicit role grants do not override PostgreSQL's default PUBLIC function privilege.

## Why

A read-only disposable-database grant audit found the routine executable by PUBLIC. A focused security review confirmed the function is `SECURITY DEFINER`, can upsert source-scoped capability fields, and lacks caller/source authorization inside its body. The authenticated HTTP/MCP path was not found to expose an unauthenticated route; the reviewer classified this as a MINOR least-privilege and integrity-boundary gap. The application registry calls this routine through the `business_ai_app` connection, so retain that explicit grant while removing the broader default privilege.

## Contracts and paths

- `db/migrations/015_capability_observation_execute_boundary.sql`
- `src/business_ai_gateway/db.py`
- `scripts/verify_schema.py`
- `scripts/migration_acceptance.py`
- `docs/MANUAL_ACCEPTANCE_USER.md`
- `docs/QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md`
- `core/LESSONS_LOG.md`
- The prior migration 014 is left unchanged; this is a forward-only ACL correction.
- No table, function body, source data, or gate state changes. No new caller role is authorized by this migration.

## Migration runbook and safety

**Preconditions:** version 014 is applied and its exact `bag.record_capability_observation(text,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)` identity exists; deployment uses the reviewed migration runner; the required application role `business_ai_app` exists. The migration explicitly fails if that role is absent or if an existing `business_ai_admin`/`business_ai_control_api` role retains effective EXECUTE after all ACL changes, including the final application grant, so the runner cannot record version 15 with a missing application grant or broader effective runtime access.

**Apply:** allow the standard migration runner to execute version 015 transactionally. The REVOKE and GRANT statements are idempotent and make no row changes. Do not apply manually or to a production database as part of this change.

**Verify after the authorized disposable run:** inspect the routine's effective ACL using `aclexplode(COALESCE(proacl, acldefault('f', proowner)))`; confirm there is no EXECUTE entry for grantee OID 0 (`PUBLIC`), that `has_function_privilege('business_ai_app', p.oid, 'EXECUTE')` is true, and that effective EXECUTE is false for `business_ai_admin` and `business_ai_control_api`. Then use the application registry's existing authenticated metadata path. Record exact schema version and catalog result. Test authors/executors own mapped runtime cases after coding is complete.

**Abort/rollback:** if migration preflight or catalog identity fails, `business_ai_app` is absent, or admin/control retains effective EXECUTE through membership, the standard migration transaction must fail and leave version 15 unapplied; preserve the database for reviewer inspection. Transaction rollback also restores the pre-migration ACL, including PUBLIC EXECUTE, until the membership/grant cause is corrected and migration 015 is retried. Do not report PUBLIC access as removed on an aborted migration. There is no reverse migration that restores PUBLIC access after a successful application, because that would reintroduce the reviewed exposure; the scoped grant can be reapplied manually only under a separately reviewed repair decision. No destructive/data rewrite is involved.

**Owner:** operator is accountable for the delegated project; Codex implemented the local source change; database and security reviewer roles own their independent review; functional-test-reviewer/e2e-runner own mapped execution.

## Decisions

- Keep `business_ai_app` as the only explicit function grantee because `src/business_ai_gateway/registry.py` is the identified application caller and uses that runtime role.
- Do not grant the function to admin/control roles absent a verified application call path.
- Distinguish the disposable catalog finding from the missing `change_ledger` schema; migration 015 does not qualify S13 grants or the private writer boundary.

## Verification state

- Implemented only. The preceding disposable catalog query and read-only security review are the evidence that motivated the change; they are not post-migration verification.
- Read-only database and security reviewers statically reviewed the initial implementation. GPT-PM's exact-patch review then found two MAJOR source-level counterexamples: an admin/control role inheriting `business_ai_app` could regain effective EXECUTE after an early check, and uncast ACL-verifier parameters could select text overloads while receiving integer OIDs. The migration now performs its negative effective-privilege checks after every grant, and the verifier explicitly types both OID arguments and the role-name argument. A fresh exact-patch review is pending; neither the earlier review nor these source edits prove installed ACLs or runtime behavior.
- The security reviewer clarified that an inherited admin/control grant causes a transactional refusal and therefore leaves the pre-015 PUBLIC ACL in place until the cause is fixed and migration 015 is retried. The runbook states this failure-path limit explicitly.
- `tests/test_migrate_runner.py:50` still uses 15 as the unknown future version. Its expected fixture should move to 16 under the functional-test-reviewer ownership rule after coding is complete; the primary agent did not edit test source.
- No tests, checks, builds, CI, migrations, database writes, deployment, push, or PR were run. Migration application and post-migration ACL verification remain **NOT_RUN** under the active restriction.
