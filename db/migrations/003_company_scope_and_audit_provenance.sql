BEGIN;

CREATE TABLE IF NOT EXISTS bag.companies (
    company_id uuid PRIMARY KEY,
    source_id text NOT NULL REFERENCES bag.sources(source_id) ON DELETE RESTRICT,
    external_ref text NOT NULL,
    display_name text NOT NULL,
    legal_name text,
    country_code text,
    tax_id_fingerprint text,
    enabled boolean NOT NULL DEFAULT true,
    is_default boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT companies_source_external_ref_uq UNIQUE(source_id, external_ref),
    CONSTRAINT companies_id_source_uq UNIQUE(company_id, source_id)
);

ALTER TABLE bag.access_grants
  ADD COLUMN IF NOT EXISTS company_id uuid,
  ADD COLUMN IF NOT EXISTS effect text NOT NULL DEFAULT 'allow';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'access_grants_effect_check'
      AND conrelid = 'bag.access_grants'::regclass
  ) THEN
    ALTER TABLE bag.access_grants
      ADD CONSTRAINT access_grants_effect_check
      CHECK (effect IN ('allow', 'deny'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'access_grants_company_source_fk'
      AND conrelid = 'bag.access_grants'::regclass
  ) THEN
    ALTER TABLE bag.access_grants
      ADD CONSTRAINT access_grants_company_source_fk
      FOREIGN KEY(company_id, source_id)
      REFERENCES bag.companies(company_id, source_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'access_grants_company_scope_check'
      AND conrelid = 'bag.access_grants'::regclass
  ) THEN
    ALTER TABLE bag.access_grants
      ADD CONSTRAINT access_grants_company_scope_check
      CHECK (company_id IS NULL OR (source_id IS NOT NULL AND all_sources = false));
  END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS access_grants_company_lookup_idx
ON bag.access_grants(company_id, principal_kind, principal_id)
WHERE revoked_at IS NULL AND company_id IS NOT NULL;

ALTER TABLE bag.audit_events
  ADD COLUMN IF NOT EXISTS request_id uuid NOT NULL DEFAULT gen_random_uuid(),
  ADD COLUMN IF NOT EXISTS company_id uuid,
  ADD COLUMN IF NOT EXISTS adapter_kind text,
  ADD COLUMN IF NOT EXISTS adapter_version text,
  ADD COLUMN IF NOT EXISTS upstream_sha text,
  ADD COLUMN IF NOT EXISTS policy_version text,
  ADD COLUMN IF NOT EXISTS metadata_fingerprint text,
  ADD COLUMN IF NOT EXISTS response_bytes bigint,
  ADD COLUMN IF NOT EXISTS truncated boolean NOT NULL DEFAULT false;

ALTER TABLE bag.audit_events
  ADD CONSTRAINT audit_events_response_bytes_nonnegative
  CHECK (response_bytes IS NULL OR response_bytes >= 0);

CREATE INDEX IF NOT EXISTS audit_request_id_idx
ON bag.audit_events(request_id);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    GRANT SELECT ON bag.companies TO business_ai_app;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT SELECT, INSERT, UPDATE ON bag.companies TO business_ai_admin;
  END IF;
END;
$$;

INSERT INTO bag.schema_migrations(version)
VALUES (3)
ON CONFLICT (version) DO NOTHING;

COMMIT;
