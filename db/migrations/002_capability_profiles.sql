BEGIN;

ALTER TABLE bag.sources
  ADD COLUMN IF NOT EXISTS platform_version_hint text,
  ADD COLUMN IF NOT EXISTS fallback_kind text,
  ADD COLUMN IF NOT EXISTS fallback_base_url text;

ALTER TABLE bag.sources
  DROP CONSTRAINT IF EXISTS sources_fallback_kind_check;

ALTER TABLE bag.sources
  ADD CONSTRAINT sources_fallback_kind_check
  CHECK (fallback_kind IS NULL OR fallback_kind IN ('onec_http_query'));

CREATE TABLE IF NOT EXISTS bag.source_capabilities (
    source_id text PRIMARY KEY REFERENCES bag.sources(source_id) ON DELETE CASCADE,
    discovered_at timestamptz NOT NULL DEFAULT now(),
    metadata_fingerprint text NOT NULL,
    platform_version text,
    compatibility_status text NOT NULL
      CHECK (compatibility_status IN ('SUPPORTED','SUPPORTED_WITH_FALLBACK','UNSUPPORTED')),
    adapter_profile text NOT NULL
      CHECK (adapter_profile IN (
        'ODATA_JSON_V3',
        'ODATA_ATOM_V3',
        'HTTP_QUERY_FALLBACK',
        'UNSUPPORTED'
      )),
    metadata_supported boolean NOT NULL,
    json_supported boolean NOT NULL,
    atom_supported boolean NOT NULL,
    expand_supported boolean,
    entity_set_count integer NOT NULL CHECK (entity_set_count >= 0),
    evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb
);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    GRANT SELECT, INSERT, UPDATE ON bag.source_capabilities TO business_ai_app;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT SELECT ON bag.source_capabilities TO business_ai_admin;
  END IF;
END;
$$;

INSERT INTO bag.schema_migrations(version)
VALUES (2)
ON CONFLICT (version) DO NOTHING;

COMMIT;
