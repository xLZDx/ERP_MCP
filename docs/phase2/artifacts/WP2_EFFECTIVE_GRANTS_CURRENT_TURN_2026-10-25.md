# WP2 effective-grants current-turn observation — 2026-10-25

## Method

The database-reviewer used the repository `.venv`, loaded `LaneEnv` from `scripts/real1c/gateway_client.py`, obtained the local disposable database URL in-process, and ran read-only PostgreSQL catalog queries inside a `REPEATABLE READ`, `READ ONLY` transaction. The URL and credentials were not printed. No catalog object, role, grant, or row was changed; no migration, parser, test, check, or build was run.

## Observed state

- Connection: database `business_ai`, current role `business_ai_admin`, PostgreSQL 16.15, `transaction_read_only=on`.
- `change_ledger` is absent (`to_regnamespace` returned `NULL`). No schema objects, table grants, sequence grants, function grants, or RLS policies were measurable in this database.
- `business_ai_admin`: LOGIN, not superuser, INHERIT, no CREATEDB/CREATEROLE, no replication, no BYPASSRLS. Its only observed membership was itself.
- `business_ai`: database owner and superuser; it is not inherited by `business_ai_admin`.
- Candidate runtime roles were absent: `business_ai_private_writer`, `private_writer_evidence_ingest`, `ledger_owner`, `requester_role`, `approver_role`, `operator_role`, `writer_role`, `worker_role`, `auditor_role`, and `checkpoint_role`.

## Acceptance interpretation

The effective grants for candidate 027 are `NOT_MEASURABLE`, because the candidate schema and roles are not installed. Zero catalog rows mean there were no candidate objects to inspect; they do not demonstrate either denial or correct future grants. This observation does not measure the 1C role `CT14Писатель` or the COM transaction boundary. Candidate SQL SHA-256 at the end of this turn: `C3CA1A6FF9E6A2A7F56B717456F8A7F35B782FB6A34387C62A779660DC1099DA`.

## Next dependency

After all in-scope coding is complete, have the database reviewer install the candidate only in the disposable database and query effective privileges for every service role, table, sequence, routine, and type. Accountable task owner: operator; executor: Codex. No human is assigned in canonical records for the candidate service identity's certificate/build-attestation mapping. Do not treat this catalog observation as a passing S13 grant gate.

## 1C effective-role evidence inspected this turn

The in-repository source `testlane/onec_extension/STATUS.md` (dated 2026-10-12, sections 4–7) and `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` were inspected as the authoritative historical clone measurement. They record `CT14_NARROW` with only `CT14Писатель` plus `ЗапускВнешнегоСоединения`: 53 adopted objects were probed through `ПравоДоступа`, and the effective rights matched the final `Rights.xml`. The receipt document has Read/Insert/Update/Posting/UndoPosting; the organization document sequence has Read/Update; other required objects are read-only and four session parameters are Get-only. Delete, interactive rights, administration, payment-document additions, and marker-attribute View/Edit are false for this role. The report also warns that standard accounting roles inherit marker View/Edit and API writers can mutate the marker, so it is not trusted provenance by itself.

This is a recorded 2026-10-12 disposable file-clone result, not a fresh measurement on Ivan's licensed lane or a client-server base. I did not run the COM script or inspect credentials during this turn. It does not close the current physical writer boundary, prove the clone mapping now in use, or measure candidate PostgreSQL 027 grants.

## Same-turn read-only refresh addendum (2026-10-25)

A fresh database-reviewer refresh ran against the same local disposable lane, using `.venv` Python, the in-process `LaneEnv.load()` DSN, and a `REPEATABLE READ READ ONLY` transaction. Credentials were not printed and no files, roles, grants, or database objects were changed. The result reconfirms database `business_ai`, user `business_ai_admin`, PostgreSQL 16.15, and absent `change_ledger` schema. All candidate S13 roles are absent, there are zero `change_ledger` table/sequence grant rows, and `has_function_privilege` is `NOT_MEASURABLE` because the candidate procedures do not resolve. This remains `NOT_MEASURABLE`, not a denial or grant pass.

Correction to the earlier membership summary above: the refresh found three built-in membership rows (`pg_monitor` membership in `pg_read_all_settings`, `pg_read_all_stats`, and `pg_stat_scan_tables`) and no membership involving `business_ai_admin` or any candidate S13 role. The previous sentence saying the admin's only membership was itself is superseded by this query result.

Current candidate 027 SHA-256 after the source-only trust-time edits in this turn: `7105E332AD506A83FF1B280417E1EA5ADA1FA55CE95DDCADDEDC84932F5D2F8C`. The candidate remains unparsed, uninstalled and ungranted. A separate Ivan-lane 1C rights measurement is not included in this PostgreSQL refresh.

## Same-turn connection-role reconciliation — 2026-10-25

I independently re-read both configured `LaneEnv` URLs in separate PostgreSQL `REPEATABLE READ
READ ONLY` transactions after the owner-URL report appeared to conflict with the earlier admin-URL
record. The `admin` URL connects to `business_ai` as `business_ai_admin` (`rolsuper=false`,
`rolbypassrls=false`); the `owner` URL connects to the same database as `business_ai`
(`rolsuper=true`, `rolbypassrls=true`). Neither URL printed its DSN. For both identities,
`change_ledger` was absent, the selected candidate S13 roles were absent, and the count of
`information_schema.role_table_grants` rows for that schema was zero. These are two distinct
connection identities, not conflicting observations; candidate privileges remain
`NOT_MEASURABLE` until the candidate is installed in the disposable database. This follow-up used
catalog reads only and did not install objects, change grants, run a parser/test/check, or inspect
business rows.

The candidate file currently resolves to SHA-256
`0FA7451D1AB424EB857CF5E4F11833C89F6502C4906F6789AAE76FD439B6AA21` (`Get-FileHash`,
2026-10-25). This supersedes the earlier `7105…` snapshot hash above for the current worktree;
the role reconciliation itself did not edit migration 027.

After the current-turn Ed25519-only replay/new-write source correction, migration 027 now hashes to
`B239A157BA77793C0BF254AB7B0C4BFDED4223990891A5FC57A933B1039D24C5`. This is a source snapshot
only; the candidate remains unparsed, uninstalled and ungranted.
