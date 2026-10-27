# WP2/S13 effective-grants recheck — 2026-10-25

## Scope and method

Read-only catalog inspection of the explicitly disposable local PostgreSQL lane. The in-process
Python snippet loaded `LaneEnv` from `scripts/real1c/gateway_client.py`, obtained the admin DSN
with `LaneEnv.load().dsn("admin")`, connected with `asyncpg`, and executed the catalog queries in
a `REPEATABLE READ`, `READ ONLY` transaction. The DSN and passwords were not printed or written to
disk. No schema, role, grant, or data was changed.

Connection identity reported by PostgreSQL: database `business_ai`, session role
`business_ai_admin`, PostgreSQL 16.15, configured local endpoint `127.0.0.1:18432` (server-side
container address `172.26.0.3:5432`).

The role query sampled the candidate writer/evidence identities and existing application roles:
`private_writer_evidence_ingest`, `business_ai_private_writer`, `business_ai_app`,
`requester_role`, `writer_role`, `worker_role`, `operator_role`, `approver_role`, `auditor_role`,
and `checkpoint_role`. For present roles it read `rolcanlogin`, `rolsuper`, `rolbypassrls`, and
direct membership count. A separate namespace query looked for `change_ledger`; effective table,
function, and type checks were conditional on that schema being present.

## Result

- Of the sampled role names, only `business_ai_app` exists. It has `LOGIN`, is not superuser, does
  not bypass RLS, and has zero direct role memberships.
- The `change_ledger` schema is absent from this database.
- Therefore no S13 candidate table, function, or type exists here. Effective privileges on the
  candidate evidence lookup/registration functions and result types are **NOT_MEASURABLE** in this
  snapshot; there are no installed objects on which to evaluate them. This is not evidence that a
  future installation's ACL is correct or denied.
- The source candidate's evidence-ingest grants remain deliberately withheld pending a
  certificate-mapped, isolated service identity and security acceptance. No grant was attempted.
- This query does not establish the 1C `CT14Писатель` rights or a physical COM transaction boundary.

## Exact observed output

```text
ROLES [{'rolname': 'business_ai_app', 'rolcanlogin': True, 'rolsuper': False, 'rolbypassrls': False, 'memberships': 0}]
SCHEMA_INSTALLED False
database=business_ai role=business_ai_admin server=172.26.0.3/32 port=5432
version=PostgreSQL 16.15 on x86_64-pc-linux-musl
configured_host=127.0.0.1 configured_port=18432
```

## Acceptance state and next dependency

`WP2_EFFECTIVE_GRANTS` is **NOT_VERIFIED** for the S13 candidate: the disposable database has no
candidate schema or service roles. The next safe sequence is to complete source code, establish
and review the isolated evidence-ingest identity, then have the test/database reviewer install the
candidate only in the disposable lane and measure exact effective role/table/function/type
privileges. Accountable task owner: operator. Executor: Codex. A technical owner for the
build-attestation and credential-to-service mapping is not established in canonical project
records. No functional test, SQL parser, migration, schema install, grant, database write, COM call,
staging, commit, or push ran for this recheck.

## Fresh catalog recheck — 2026-10-25 03:30 UTC

The same disposable endpoint was queried again in a top-level `REPEATABLE READ READ ONLY`
transaction, loading the `admin` DSN in process from `LaneEnv`; no DSN or password was printed.
The connection again reported database `business_ai`, session role `business_ai_admin`, PostgreSQL
16.15, server `172.26.0.3:5432` (configured endpoint `127.0.0.1:18432`). Of the eleven sampled
candidate/runtime role names, only `business_ai_app` existed; it has LOGIN, no superuser,
CREATEROLE, CREATEDB or BYPASSRLS, and INHERIT. `to_regnamespace('change_ledger')` returned false.
Consequently the conditional ACL queries had no objects to enumerate: table grants 0, routine ACL
rows 0 and type ACL rows 0. These zero row counts mean the schema is absent; they are not evidence
of effective denial or of correct future grants. No role, schema, grant, or data was changed.

## Candidate 027 availability check — 2026-10-25

A separate top-level PostgreSQL `REPEATABLE READ READ ONLY` inspection loaded `LaneEnv.dsn("admin")` in process and queried `pg_database`, `current_user`, `transaction_read_only`, `to_regnamespace('change_ledger')`, sampled candidate/runtime roles and membership, and conditional table/routine/type ACL catalogs. It observed database `business_ai`, session role `business_ai_admin`, `transaction_read_only=on`, no `change_ledger` schema, none of the sampled candidate roles/memberships, and zero applicable ACL rows because the schema is absent. Therefore migration-027 effective grants are **NOT_MEASURABLE** on this endpoint. Zero ACL rows here mean “candidate objects are absent,” not “access is denied” and not “future privileges are correct.” This does not measure the 1C `CT14Писатель` role. No schema, role, grant or data was changed; no DSN/password was printed; no migration, test, check, build, CI or service restart ran. The current SQL candidate SHA-256 at this observation is `F524AD655C42DD64676366D942A2C79177C1F6DCCB2F60F94E49BA72272ED77F`; because source edits continue, recompute before any later qualification.

## Fresh candidate-role and routine recheck — 2026-10-25 10:59 UTC

The `database-reviewer` repeated the catalog inspection on disposable PostgreSQL port 18432 in a
top-level `REPEATABLE READ READ ONLY` transaction. The DSN was loaded from `LaneEnv` in process and
not printed. The connection reported database `business_ai`, `current_user=business_ai_admin`,
PostgreSQL 16.15, and `transaction_read_only=on`; `to_regnamespace('change_ledger')` returned
NULL. Candidate application roles `approver_role`, `auditor_role`, `business_ai_private_writer`,
`checkpoint_role`, `ledger_owner`, `operator_role`, `private_writer_evidence_ingest`,
`requester_role`, `worker_role`, and `writer_role` were absent. The only roles in that candidate
set that existed were `business_ai` and `business_ai_admin`; no application-role memberships
were found. `information_schema.role_table_grants` returned zero candidate rows. The checked
candidate routines `apply_write(text,text,jsonb)`, `claim_call(text)`, and `lookup_outcome(text)`
all resolved to NULL through `to_regprocedure`; their `has_function_privilege` results were
therefore NULL / not measurable, not false.

Result: S13 effective grants remain **NOT_MEASURABLE** because the schema, routines and dedicated
roles are absent on this disposable endpoint. This does not establish 1C `CT14Писатель` rights or
the Ivan host's actual transaction boundary. The candidate is not installed or granted here. No
DDL, migration, business-data read, test/check, or file access outside `D:\Repo\ERP_MCP` occurred.
Accountable task owner: operator; executor: Codex; database-reviewer performed this read-only
observation. Next: finish and review the candidate source and isolated service-identity mapping,
then measure exact effective privileges only after the schema is installed in the approved
disposable database.

## Fresh read-only role and grant audit — 2026-10-25 16:25:53 UTC

LaneEnv.load() from scripts/real1c/gateway_client.py supplied the endpoint in process. Before
querying catalogs, docker ps --filter publish=18432 identified the disposable container
erpmcp-e2e-real1c-postgres-1 (postgres:16-alpine, 127.0.0.1:18432 mapped to server port
5432). The connection set default_transaction_read_only=on; catalog queries ran in a
REPEATABLE READ READ ONLY transaction. Sanitized identity: database business_ai, current and
session user business_ai_admin, server 172.26.0.3:5432, read-only transaction confirmed.

pg_roles showed business_ai with SUPERUSER, CREATEROLE, CREATEDB and BYPASSRLS; the login roles
business_ai_admin, business_ai_app and business_ai_control_api were non-superuser, non-
BYPASSRLS and lacked CREATEROLE/CREATEDB. No relevant memberships were present. The change_ledger
schema and candidate roles ledger_owner, business_ai_private_writer and
private_writer_evidence_ingest were absent. Therefore migration 027 table/function effective
privileges are NOT_MEASURABLE; absence of ACL rows is not a denial result and says nothing about
the candidate's future effective rights. SQL source role definitions are not installed-state
evidence. This also does not establish the 1C CT14Писатель rights or Ivan's transaction boundary.

No DDL, migration, data read, grant change, test/check, build, CI, or service restart ran; no DSN,
password, token or secret was emitted. Accountable owner: operator; executor: Codex; database-reviewer
performed this read-only audit. Next: after S13 source closure and review, apply the approved candidate
only in the disposable lane and repeat object-specific effective-privilege measurement.

## Current-turn database-reviewer catalog check — 2026-10-25 17:51 UTC

An additional read-only catalog audit used the in-process `LaneEnv.dsn("admin")` and `asyncpg`
inside a `REPEATABLE READ`, `READ ONLY` transaction. PostgreSQL reported database `business_ai`,
`session_user=current_user=business_ai_admin`, server `172.26.0.3:5432` (configured endpoint
`127.0.0.1:18432`). The `business_ai` login has SUPERUSER, CREATEROLE, CREATEDB and BYPASSRLS;
`business_ai_admin`, `business_ai_control_api` and `business_ai_app` are login roles without those
flags. The current non-system table-grant view returned 39 privilege rows, all granted to
`business_ai_admin`; applicable relations had INSERT/SELECT/UPDATE, while `audit_events`,
`source_capabilities` and `schema_migrations` were SELECT-only. No relevant memberships were
present.

The `change_ledger` schema and S13 roles (`ledger_owner`, `business_ai_private_writer`,
`private_writer_evidence_ingest`, and the requester/writer/worker/operator/approver/auditor/
checkpoint roles) remain absent. Candidate routines and candidate ACL rows therefore remain
`NOT_MEASURABLE`, not denied. This current-state check adds no 1C `CT14Писатель` or COM transaction-
boundary evidence. No business rows, DDL, migration, grant, test/check, build, CI, or restart was
performed; credentials stayed in process. Accountable owner: operator; executor: Codex;
database-reviewer performed this catalog-only observation.

## Current-turn database-reviewer recheck — 2026-10-26

A read-only `asyncpg` transaction loaded the disposable-lane admin DSN in process through
`LaneEnv.load().dsn("admin")`; no DSN, credential or business rows were printed or read. The
connection identified database `business_ai`, PostgreSQL 16.15 at `172.26.0.3:5432`, with current
role `business_ai_admin`. The `change_ledger` schema is absent. Of the enumerated S13 runtime and
owner roles plus `business_ai_admin` and `business_ai_app`, only the latter two exist; both are
`LOGIN`, `INHERIT`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE` and `NOBYPASSRLS`. The
`information_schema.role_table_grants` query returned zero rows for `change_ledger`, and the
candidate-function inventory plus `has_function_privilege` checks found zero installed candidate
functions for either existing role.

Therefore effective S13 grants remain `NOT_MEASURABLE`, because the candidate schema, roles and
functions are not installed; this is not evidence that candidate grants are denied. No DDL, grant,
migration, database write, test, check, build, CI or service restart occurred. Accountable owner:
operator; executor: Codex; read-only catalog audit: database-reviewer.

## Supplemental current-state recheck — 2026-10-26 10:12:11 UTC

Database-reviewer repeated the catalog query through `LaneEnv.load()` and `env.dsn("admin")`,
without printing the DSN or credentials. The session was `business_ai_admin` / database
`business_ai` on PostgreSQL 16.15, port 5432, in `REPEATABLE READ READ ONLY`. The candidate
`change_ledger` schema and candidate type/routines remain absent. The enumerated private-writer and
legacy runtime roles and memberships are absent. `information_schema.role_table_grants` returned
no `change_ledger` rows. Existing `business_ai_admin`, `business_ai_app` and
`business_ai_control_api` are non-superuser and `NOBYPASSRLS`; `business_ai` is superuser and
`BYPASSRLS`.

The routine inventory returned no rows, so although the query included `has_function_privilege`,
that function was not evaluated for any installed S13 routine. Effective grants therefore remain
`NOT_MEASURABLE` because candidate objects are absent, not because access is denied. No file or DB
state changed; no DDL, migration, grant, business-data read, test, check, build, CI or restart ran.
Accountable owner: operator; evidence executor: Codex; read-only catalog reviewer: database-reviewer.

## Supplemental current-state recheck — 2026-10-27

The database-reviewer loaded the DSN in-process from `LaneEnv.load().dsn('admin')`, verified the
configured endpoint mapped to loopback port 18432 and connected read-only to database `business_ai`
as `business_ai_admin` (server-internal PostgreSQL port 5432). The candidate `change_ledger` schema
and all five candidate runtime roles (`business_ai_private_writer`,
`private_writer_evidence_ingest`, `checkpoint_role`, `writer_role`, `worker_role`) were absent; no
candidate memberships, table/sequence grants, or S13 routines existed to measure. Result:
`NOT_MEASURABLE_CANDIDATE_SCHEMA_ABSENT`, not a privilege denial. An initial probe's port
expectation incorrectly treated the host-mapped port as the server-internal port; it was corrected
after checking endpoint and server identity, before any business-data query. The DSN/credentials
were never printed. No DDL, migration, grants, data writes, tests, or service restart occurred.
Owner: Codex for the read-only evidence; operator accountable. Next: measure exact effective grants
after the candidate is installed only in an approved disposable database.
