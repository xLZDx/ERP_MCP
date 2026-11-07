from __future__ import annotations

import asyncpg

SCHEMA_VERSION = 15


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: asyncpg.Pool | None = None

    async def start(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                dsn=self.url,
                min_size=1,
                max_size=10,
                command_timeout=15,
                max_inactive_connection_lifetime=300,
            )

    async def close(self):
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    def require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("database not started")
        return self.pool

    async def ping(self) -> bool:
        return bool(await self.require_pool().fetchval("SELECT 1"))

    async def assert_schema(self):
        row = await self.require_pool().fetchrow(
            """SELECT min(version) AS minimum, max(version) AS maximum, count(*) AS count,
                      bool_and(name IS NOT NULL AND checksum IS NOT NULL) AS identified
               FROM bag.schema_migrations"""
        )
        if (
            row["minimum"] != 1
            or row["maximum"] != SCHEMA_VERSION
            or row["count"] != SCHEMA_VERSION
            or not row["identified"]
        ):
            raise RuntimeError(
                "unsupported or unidentified schema migration history: "
                f"min={row['minimum']!r}, max={row['maximum']!r}, count={row['count']!r}; "
                f"expected contiguous identified versions 1..{SCHEMA_VERSION}"
            )

    async def assert_control_api_role(self):
        row = await self.require_pool().fetchrow("""
            SELECT pg_has_role(current_user, 'business_ai_control_api', 'USAGE') AS control_member,
                   EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN (current_user, session_user)
                     AND (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolbypassrls OR r.rolreplication)) AS elevated,
                   EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN ('business_ai_owner','business_ai_admin')
                     AND pg_has_role(session_user, r.oid, 'MEMBER')) AS privileged_member,
                   has_table_privilege(current_user, 'bag.admin_audit_events', 'UPDATE,DELETE') AS mutable_audit,
                   has_table_privilege(current_user, 'bag.admin_audit_events', 'TRUNCATE') AS truncate_audit,
                   has_table_privilege(current_user, 'bag.sources', 'DELETE') AS can_delete,
                   has_table_privilege(current_user, 'bag.source_capabilities', 'UPDATE') AS broad_drift_update,
                   EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                     WHERE n.nspname='bag' AND pg_has_role(session_user, c.relowner, 'MEMBER')) AS owns_schema_objects
        """)
        if not row["control_member"] or any(row[key] for key in (
            "elevated", "privileged_member", "mutable_audit", "truncate_audit", "can_delete", "broad_drift_update", "owns_schema_objects"
        )):
            raise RuntimeError("admin control database role violates least-privilege contract")

    async def assert_runtime_role(self):
        row = await self.require_pool().fetchrow("""
            SELECT pg_has_role(current_user, 'business_ai_app', 'USAGE') AS runtime_member,
                   EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN (current_user, session_user)
                     AND (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolbypassrls OR r.rolreplication)) AS elevated,
                   EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN
                     ('business_ai_owner','business_ai_admin','business_ai_control_api')
                     AND pg_has_role(session_user, r.oid, 'MEMBER')) AS privileged_member,
                   has_table_privilege(current_user, 'bag.sources', 'INSERT,UPDATE,DELETE') AS mutable_sources,
                   has_table_privilege(current_user, 'bag.access_grants', 'INSERT,UPDATE,DELETE') AS mutable_grants,
                   has_table_privilege(current_user, 'bag.companies', 'INSERT,UPDATE,DELETE') AS mutable_companies,
                   has_table_privilege(current_user, 'bag.audit_events', 'UPDATE,DELETE') AS mutable_audit,
                   has_table_privilege(current_user, 'bag.audit_events', 'TRUNCATE') AS truncate_audit
        """)
        if not row["runtime_member"] or any(row[key] for key in (
            "elevated", "privileged_member", "mutable_sources", "mutable_grants", "mutable_companies", "mutable_audit", "truncate_audit"
        )):
            raise RuntimeError("runtime database role violates least-privilege contract")

    async def assert_promotion_role(self):
        """Fail closed unless this pool can SET only into isolated, non-inherited actor roles."""
        version = int(await self.require_pool().fetchval("SHOW server_version_num"))
        if version < 160000:
            raise RuntimeError("promotion database requires PostgreSQL 16 SET/INHERIT membership controls")
        row = await self.require_pool().fetchrow("""
            WITH login AS (
                SELECT r.oid, r.rolname FROM pg_catalog.pg_roles r
                WHERE r.rolname = session_user
            ), effective AS (
                SELECT r.oid, r.rolname, r.rolcanlogin, r.rolsuper, r.rolcreaterole, r.rolcreatedb,
                       r.rolreplication, r.rolbypassrls,
                       pg_catalog.pg_has_role(session_user, r.oid, 'MEMBER') AS member,
                       pg_catalog.pg_has_role(session_user, r.oid, 'SET') AS can_set,
                       pg_catalog.pg_has_role(session_user, r.oid, 'USAGE') AS has_usage
                FROM pg_catalog.pg_roles r
            ), actor_roles AS (
                SELECT e.* FROM effective e
                WHERE e.rolname ~ '^r2p_[a-f0-9]{59}$' AND e.can_set
            )
            SELECT
                (session_user IS DISTINCT FROM current_user) AS role_changed_at_login,
                EXISTS (SELECT 1 FROM pg_catalog.pg_roles r
                        WHERE r.rolname IN (session_user,current_user)
                          AND (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb
                               OR r.rolreplication OR r.rolbypassrls)) AS elevated_login,
                EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m
                        JOIN pg_catalog.pg_roles r ON r.oid=m.roleid CROSS JOIN login l
                        WHERE m.member=l.oid AND r.rolname !~ '^r2p_[a-f0-9]{59}$')
                    AS login_direct_non_actor_membership,
                EXISTS (SELECT 1 FROM effective
                        WHERE can_set AND rolname !~ '^r2p_[a-f0-9]{59}$'
                          AND rolname NOT IN (session_user,current_user)) AS can_set_non_actor,
                EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m
                        JOIN pg_catalog.pg_roles r ON r.oid=m.roleid CROSS JOIN login l
                        WHERE m.member=l.oid AND r.rolname IN
                        ('living_owner','living_promoter','living_worker','business_ai_owner','business_ai_admin',
                         'business_ai_control_api','pg_write_all_data','pg_read_all_data',
                         'pg_execute_server_program','pg_read_server_files','pg_write_server_files'))
                    AS sensitive_membership,
                EXISTS (SELECT 1 FROM effective
                        WHERE can_set AND rolname IN
                        ('living_owner','living_promoter','living_worker','business_ai_owner','business_ai_admin',
                         'business_ai_control_api','pg_write_all_data','pg_read_all_data',
                         'pg_execute_server_program','pg_read_server_files','pg_write_server_files'))
                    AS sensitive_set,
                EXISTS (SELECT 1 FROM effective
                        WHERE has_usage AND rolname !~ '^r2p_[a-f0-9]{59}$'
                          AND rolname NOT IN (session_user,current_user)) AS inherited_non_actor_privileges,
                EXISTS (SELECT 1 FROM effective WHERE member AND
                        (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls))
                    AS elevated_membership,
                EXISTS (SELECT 1 FROM effective WHERE can_set AND
                        (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls))
                    AS elevated_set,
                EXISTS (SELECT 1 FROM actor_roles WHERE has_usage) AS actor_privileges_inherited,
                EXISTS (SELECT 1 FROM actor_roles a
                        WHERE a.rolsuper OR a.rolcreaterole OR a.rolcreatedb
                           OR a.rolreplication OR a.rolbypassrls OR a.rolcanlogin) AS actor_elevated,
                EXISTS (SELECT 1 FROM actor_roles a CROSS JOIN pg_catalog.pg_roles r
                        WHERE r.rolname IN
                          ('living_owner','living_worker','business_ai_owner','business_ai_admin',
                           'business_ai_control_api','pg_write_all_data','pg_read_all_data',
                           'pg_execute_server_program','pg_read_server_files','pg_write_server_files')
                          AND pg_catalog.pg_has_role(a.oid,r.oid,'MEMBER')) AS actor_sensitive_membership,
                EXISTS (SELECT 1 FROM actor_roles a
                        WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles p
                                          WHERE p.rolname='living_promoter'
                                            AND pg_catalog.pg_has_role(a.oid,p.oid,'USAGE')))
                    AS actor_missing_promoter,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_roles p ON p.rolname='living_promoter'
                        WHERE pg_catalog.pg_has_role(a.oid,p.oid,'SET')) AS actor_can_set_promoter,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_roles p ON p.rolname='living_promoter'
                        WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m
                                          WHERE m.member=a.oid AND m.roleid=p.oid
                                            AND m.inherit_option IS TRUE
                                            AND m.set_option IS FALSE))
                    AS actor_promoter_grant_not_inherit_only,
                EXISTS (SELECT 1 FROM actor_roles a CROSS JOIN pg_catalog.pg_roles r
                        WHERE r.oid<>a.oid AND r.rolname<>'living_promoter'
                          AND pg_catalog.pg_has_role(a.oid,r.oid,'SET'))
                    AS actor_can_set_unapproved_role,
                EXISTS (SELECT 1 FROM actor_roles a CROSS JOIN pg_catalog.pg_roles r
                        WHERE r.oid<>a.oid AND r.rolname<>'living_promoter'
                          AND pg_catalog.pg_has_role(a.oid,r.oid,'USAGE'))
                    AS actor_inherits_unapproved_role,
                NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n WHERE n.nspname='living')
                    AS living_schema_missing,
                EXISTS (SELECT 1 FROM actor_roles a
                        WHERE NOT EXISTS (
                            SELECT 1 FROM pg_catalog.pg_proc p
                            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                            WHERE n.nspname='living' AND p.proname='set_scope'
                              AND p.pronargs=3 AND pg_catalog.has_function_privilege(a.oid,p.oid,'EXECUTE'))
                           OR NOT EXISTS (
                            SELECT 1 FROM pg_catalog.pg_proc p
                            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                            WHERE n.nspname='living' AND p.proname='promote_head'
                              AND p.pronargs=7 AND pg_catalog.has_function_privilege(a.oid,p.oid,'EXECUTE')))
                    AS actor_missing_promotion_functions,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_namespace n ON n.nspname !~ '^(pg_|information_schema$)'
                        JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
                        WHERE c.relkind IN ('r','p','v','m','f') AND
                          (pg_catalog.has_table_privilege(a.oid,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
                           OR EXISTS (SELECT 1 FROM pg_catalog.pg_attribute x
                                      WHERE x.attrelid=c.oid AND x.attnum>0 AND NOT x.attisdropped
                                        AND pg_catalog.has_column_privilege(a.oid,c.oid,x.attnum,
                                                                            'INSERT,UPDATE,REFERENCES'))))
                    AS actor_direct_dml,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_namespace n ON n.nspname !~ '^(pg_|information_schema$)'
                        JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
                        WHERE c.relkind='S' AND pg_catalog.has_sequence_privilege(a.oid,c.oid,'USAGE,UPDATE'))
                    AS actor_sequence_write,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_namespace n ON n.nspname !~ '^(pg_|information_schema$)'
                        WHERE pg_catalog.pg_has_role(a.oid,n.nspowner,'MEMBER')
                           OR pg_catalog.has_schema_privilege(a.oid,n.oid,'CREATE'))
                    AS actor_schema_authority,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_namespace n ON n.nspname !~ '^(pg_|information_schema$)'
                        JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
                        WHERE pg_catalog.pg_has_role(a.oid,c.relowner,'MEMBER'))
                    AS actor_object_ownership,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_namespace n ON n.nspname !~ '^(pg_|information_schema$)'
                        JOIN pg_catalog.pg_proc p ON p.pronamespace=n.oid
                        WHERE pg_catalog.pg_has_role(a.oid,p.proowner,'MEMBER'))
                    AS actor_routine_ownership,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_namespace n ON n.nspname !~ '^(pg_|information_schema$)'
                        JOIN pg_catalog.pg_type t ON t.typnamespace=n.oid
                        WHERE pg_catalog.pg_has_role(a.oid,t.typowner,'MEMBER'))
                    AS actor_type_ownership,
                EXISTS (SELECT 1 FROM actor_roles a CROSS JOIN login l
                        WHERE NOT EXISTS (
                            SELECT 1 FROM pg_catalog.pg_auth_members m
                            WHERE m.member = l.oid AND m.roleid = a.oid
                              AND m.set_option IS TRUE AND m.inherit_option IS FALSE
                        )) AS actor_grant_not_set_only,
                (SELECT count(*) FROM actor_roles) AS settable_actor_count,
                EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
                        WHERE n.nspname !~ '^(pg_|information_schema$)' AND
                          (pg_catalog.pg_has_role(session_user,n.nspowner,'MEMBER')
                           OR pg_catalog.pg_has_role(session_user,n.nspowner,'SET')))
                    AS owns_user_schema,
                EXISTS (SELECT 1 FROM pg_catalog.pg_class c
                        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                        WHERE n.nspname !~ '^(pg_|information_schema$)' AND
                          (pg_catalog.pg_has_role(session_user,c.relowner,'MEMBER')
                           OR pg_catalog.pg_has_role(session_user,c.relowner,'SET')))
                    AS owns_user_objects,
                EXISTS (SELECT 1 FROM pg_catalog.pg_proc p
                        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                        WHERE n.nspname !~ '^(pg_|information_schema$)' AND
                          (pg_catalog.pg_has_role(session_user,p.proowner,'MEMBER')
                           OR pg_catalog.pg_has_role(session_user,p.proowner,'SET')))
                    AS owns_user_routines,
                EXISTS (SELECT 1 FROM pg_catalog.pg_type t
                        JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace
                        WHERE n.nspname !~ '^(pg_|information_schema$)' AND
                          (pg_catalog.pg_has_role(session_user,t.typowner,'MEMBER')
                           OR pg_catalog.pg_has_role(session_user,t.typowner,'SET')))
                    AS owns_user_types,
                EXISTS (SELECT 1 FROM pg_catalog.pg_database d
                        WHERE d.datname=current_database() AND
                          (pg_catalog.pg_has_role(session_user,d.datdba,'MEMBER')
                           OR pg_catalog.pg_has_role(session_user,d.datdba,'SET')))
                    AS owns_database,
                EXISTS (SELECT 1 FROM actor_roles a
                        JOIN pg_catalog.pg_database d ON d.datname=current_database()
                        WHERE pg_catalog.pg_has_role(a.oid,d.datdba,'MEMBER'))
                    AS actor_owns_database,
                EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
                        JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
                        WHERE n.nspname !~ '^(pg_|information_schema$)' AND c.relkind IN ('r','p','v','m','f') AND
                          (pg_catalog.has_table_privilege(session_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
                           OR pg_catalog.has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
                           OR EXISTS (SELECT 1 FROM pg_catalog.pg_attribute x
                                      WHERE x.attrelid=c.oid AND x.attnum>0 AND NOT x.attisdropped
                                        AND (pg_catalog.has_column_privilege(session_user,c.oid,x.attnum,
                                                                             'INSERT,UPDATE,REFERENCES')
                                             OR pg_catalog.has_column_privilege(current_user,c.oid,x.attnum,
                                                                                'INSERT,UPDATE,REFERENCES')))))
                    AS direct_dml,
                EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
                        JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
                        WHERE n.nspname !~ '^(pg_|information_schema$)' AND c.relkind='S'
                          AND (pg_catalog.has_sequence_privilege(session_user,c.oid,'USAGE,UPDATE')
                               OR pg_catalog.has_sequence_privilege(current_user,c.oid,'USAGE,UPDATE')))
                    AS direct_sequence_write,
                EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
                        WHERE n.nspname !~ '^(pg_|information_schema$)' AND
                          (pg_catalog.has_schema_privilege(session_user,n.oid,'CREATE')
                           OR pg_catalog.has_schema_privilege(current_user,n.oid,'CREATE')))
                    AS can_create_user_objects
        """)
        forbidden = (
            "role_changed_at_login", "elevated_login", "can_set_non_actor",
            "login_direct_non_actor_membership", "sensitive_membership", "sensitive_set",
            "inherited_non_actor_privileges",
            "elevated_membership", "elevated_set",
            "actor_privileges_inherited", "actor_elevated", "actor_sensitive_membership",
            "actor_missing_promoter", "actor_can_set_promoter",
            "actor_promoter_grant_not_inherit_only", "actor_can_set_unapproved_role",
            "actor_inherits_unapproved_role", "living_schema_missing",
            "actor_missing_promotion_functions",
            "actor_direct_dml", "actor_sequence_write", "actor_schema_authority",
            "actor_object_ownership", "actor_routine_ownership", "actor_owns_database",
            "actor_type_ownership",
            "actor_grant_not_set_only", "owns_user_schema", "owns_user_objects",
            "owns_user_routines", "owns_user_types", "owns_database", "direct_dml",
            "direct_sequence_write",
            "can_create_user_objects",
        )
        if row is None or row["settable_actor_count"] < 1 or any(row[key] for key in forbidden):
            raise RuntimeError("promotion database role violates least-privilege contract")
