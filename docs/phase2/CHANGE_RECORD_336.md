# Change record 336 — read-only effective-grants recheck

## Ownership and method

- Date: 2026-10-27.
- Accountable owner: operator; evidence collection owner: Codex; query/review role: database-reviewer.
- Read-only transaction against the project disposable endpoint `127.0.0.1:18432`, asserted from the project lane environment before connecting. The server reports internal PostgreSQL port 5432.
- The agent loaded the database URL in-process and did not print any URL, password, token, or business data. The connection was `business_ai_admin` to `business_ai`, PostgreSQL 16.15, with `transaction_read_only=on` and repeatable-read isolation.

## Catalog evidence

The bounded catalog query inspected candidate/legacy role names and memberships in `pg_roles`/`pg_auth_members`; `change_ledger` and its effective schema privileges in `pg_namespace`; table grants in `information_schema.role_table_grants`; `private_writer%` types in `pg_type`; and relevant existing functions plus per-role `has_function_privilege(..., 'EXECUTE')` results in `pg_proc`.

- The `change_ledger` schema is absent.
- Candidate private-writer types, relations and functions are absent.
- Candidate roles `business_ai_private_writer`, `private_writer_evidence_ingest`, and `ledger_owner` are absent; the inspected legacy ledger roles are also absent. Membership query returned no rows.
- `information_schema.role_table_grants` returned no candidate rows; there were no matching routines on which `has_function_privilege` could be evaluated.
- `business_ai_admin`, `business_ai_app`, and `business_ai_control_api` are present as non-superuser login roles without `BYPASSRLS`, `CREATEDB`, or `CREATEROLE`. `business_ai` is a superuser/BYPASSRLS/CREATEDB/CREATEROLE role and must be treated as an owner/admin class, not an application principal.

## Conclusion and limits

Migration-027 effective grants are `NOT_MEASURABLE` on this endpoint because its candidate schema, routines, types, and roles are not installed. The result does not establish an EXECUTE denial or candidate ACL correctness. It also does not report measured 1C `CT14Писатель` rights; those remain as recorded in the CT14 project artifacts. No state was changed and no migration, test, check, build, service restart, or business query ran.

Keep candidate evidence-ingest/registration privileges withheld. Re-measure only after source review and authorized installation of the exact candidate in an invocation-owned disposable database. `database-reviewer` owns the later effective-privilege measurement; Codex owns coordinating candidate installation only after the code/test/review gates. The operator remains accountable for the external writer/trust authorization.
