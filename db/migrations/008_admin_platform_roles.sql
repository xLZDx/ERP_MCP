BEGIN;

CREATE TABLE IF NOT EXISTS bag.platform_role_bindings (
    binding_id uuid PRIMARY KEY,
    principal_kind text NOT NULL CHECK (principal_kind IN ('subject','group')),
    principal_id text NOT NULL,
    role_name text NOT NULL CHECK (
        role_name IN (
            'PLATFORM_ADMIN',
            'SOURCE_ADMIN',
            'ACCESS_ADMIN',
            'PROFILE_ADMIN',
            'AUDITOR'
        )
    ),
    source_id text REFERENCES bag.sources(source_id) ON DELETE RESTRICT,
    expires_at timestamptz,
    revoked_at timestamptz,
    created_by_subject text,
    created_by_client text,
    reason text,
    row_version bigint NOT NULL DEFAULT 1 CHECK (row_version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (role_name <> 'PLATFORM_ADMIN' OR source_id IS NULL)
);

CREATE INDEX IF NOT EXISTS platform_role_bindings_lookup_idx
ON bag.platform_role_bindings(principal_kind, principal_id, role_name, source_id)
WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS platform_role_bindings_source_idx
ON bag.platform_role_bindings(source_id, role_name)
WHERE revoked_at IS NULL AND source_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS platform_role_bindings_active_uq
ON bag.platform_role_bindings(
    principal_kind,
    principal_id,
    role_name,
    COALESCE(source_id, '')
)
WHERE revoked_at IS NULL;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    GRANT SELECT ON bag.platform_role_bindings TO business_ai_app;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT SELECT, INSERT, UPDATE ON bag.platform_role_bindings TO business_ai_admin;
  END IF;
END;
$$;

INSERT INTO bag.schema_migrations(version)
VALUES (8)
ON CONFLICT (version) DO NOTHING;

COMMIT;
