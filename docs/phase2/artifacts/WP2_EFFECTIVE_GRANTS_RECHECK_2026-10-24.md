# WP2 effective database-grant recheck — 2026-10-24

## Result

**Effective runtime grants: `NOT_VERIFIED`.** A read-only connection reached the local disposable
`business_ai` database through the in-repository lane environment on port `18432`, with
`transaction_read_only=on`. The `change_ledger` schema was absent. The only selected project roles
present in `pg_roles` were `business_ai_admin`, `business_ai`, and `business_ai_app`; the runtime
roles (`writer_role`, `worker_role`, `requester_role`, `operator_role`, `auditor_role`, and
`checkpoint_role`) and S13 principals (`business_ai_private_writer` and
`private_writer_evidence_ingest`) were absent. No matching lifecycle, legacy mutation, or S13
functions existed in `pg_proc`, and the role-membership query returned no memberships involving
the requested role set.

This does **not** prove that runtime roles have no privilege elsewhere or on another database. It
means the requested disposable database currently cannot measure those privileges because the
candidate schema and roles are not installed. No S13 grant should be inferred as allowed or
denied from this result.

## Read-only method

The probe used `scripts/real1c/gateway_client.py:LaneEnv.load()` and `LaneEnv.dsn("admin")` in
process. Before connecting, it required `environment == "test"`, loopback host, and PostgreSQL
port `18432`; the connection set `default_transaction_read_only=on`. No DSN, password, token, or
business data was printed.

The sanitized SQL checks were:

```sql
SELECT current_database(), current_user, session_user,
       current_setting('transaction_read_only');

SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolbypassrls
FROM pg_roles
WHERE rolname = ANY($1::text[])
ORDER BY rolname;

SELECT granted.rolname AS granted_role, member.rolname AS member_role,
       am.admin_option, am.inherit_option, am.set_option
FROM pg_auth_members am
JOIN pg_roles granted ON granted.oid = am.roleid
JOIN pg_roles member ON member.oid = am.member;

SELECT to_regnamespace('change_ledger') IS NOT NULL;

SELECT p.oid, p.proname, pg_get_function_identity_arguments(p.oid), r.rolname AS owner
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_roles r ON r.oid = p.proowner
WHERE n.nspname = 'change_ledger' AND p.proname = ANY($1::text[]);

SELECT has_function_privilege($1, $2, 'EXECUTE');
```

The final `has_function_privilege` call was not applicable because the target roles and routines
were absent. It was not treated as a false result.

## Evidence and limits

- Observed at `2026-10-24 20:35 UTC` by the local Codex execution.
- Database identity was `business_ai_admin`; session and transaction were read-only.
- Present selected roles: `business_ai`, `business_ai_admin`, `business_ai_app`.
- `change_ledger` schema, queried legacy/S13 routines, all selected runtime roles and selected
  memberships: absent.
- No tests, DDL, migration, database write, COM call, service restart, staging, commit, or push ran.

## Next step

After the accepted additive schema is installed on this disposable lane, rerun the same
role-by-signature effective-privilege and membership checks as the database reviewer. Reconcile
direct grants, inherited memberships, ownership, `PUBLIC`, and default privileges before enabling
any versioned route or claiming the real writer boundary.

## 1C role evidence boundary

The repository's measured `CT14Писатель` effective-rights record is `testlane/onec_extension/STATUS.md`
§§4, 5 and 7 and `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` §§6–7. The spike file is present
in this repository; the earlier sentence claiming it was absent was an inventory error and is
superseded. These records describe the 818HA_p2diff clone, 53 adopted objects, measured
`ПравоДоступа` results and denied post/delete/admin capabilities. They do not identify or prove
that Ivan's currently configured COM clone is the same base, and they explicitly record marker
tampering by users with inherited document update rights. Therefore they are evidence for the
measured clone only; Ivan-host effective rights and current clone/base correlation remain
`NOT_VERIFIED`.

## 2026-10-25 disposable PostgreSQL recheck

An actual read-only `database-reviewer` role audit connected through the project lane environment
to the disposable PostgreSQL endpoint mapped at local port 18432. It used `.venv` Python,
`LaneEnv.load()` and `env.dsn('admin')` in-process, with `default_transaction_read_only=on` and an
explicit `REPEATABLE READ READ ONLY` transaction. No DSN or credential was printed. Sanitized
identity: database `business_ai`, PostgreSQL 16.15, server port 5432 inside the lane, session/current
role `business_ai_admin`, read-only transaction enabled.

Observed state: `change_ledger` does not exist in this database; the candidate roles
`business_ai_private_writer`, `private_writer_evidence_ingest`, `ledger_owner`, `worker_role`,
`writer_role`, `operator_role`, `auditor_role` and `checkpoint_role` are absent; the selected
`information_schema.role_table_grants` query returned zero rows. Six sampled candidate function
signatures (`recover_sweep_v1`, recovery GAP, recovery VERIFY, `retry_verify_v1`,
`verify_inconclusive_v1`, `record_recovered_no_entry_v1`) were absent. Since those signatures are
not installed, their effective EXECUTE privileges are `NOT_MEASURABLE`, not denied. This proves
only the current disposable lane state; migration 027 remains uninstalled/ungranted here.

The reviewer also read the two in-scope CT14 records above; it did not freshly measure 1C rights.
Those files record clone-only CT14_NARROW rights and are not evidence for Ivan's current host/base.
No tests, DDL, migration, database write, COM call, service restart, staging, commit or push ran.

## Next step

The disposable-lane blocker for effective S13 grants is the absent installed `change_ledger` schema
and candidate roles/functions. After source code closes and installation is authorized on that
disposable database, install the additive candidate there, then rerun direct/inherited table and
function privilege checks. Separately correlate Ivan's licensed clone identity/base before making
any live-host CT14 rights claim. The accountable task owner is the operator; Codex executes the
source and authorized disposable work.
