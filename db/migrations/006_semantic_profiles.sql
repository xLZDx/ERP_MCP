BEGIN;

CREATE OR REPLACE FUNCTION bag.native_reconciliation_evidence_valid(evidence jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT CASE
    WHEN jsonb_typeof(evidence->'native_reconciliation_cases') IS DISTINCT FROM 'array'
      THEN false
    ELSE
      jsonb_array_length(evidence->'native_reconciliation_cases') >= 10
      AND NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements(evidence->'native_reconciliation_cases') AS cases(item)
        WHERE jsonb_typeof(item) IS DISTINCT FROM 'object'
           OR item->>'status' IS DISTINCT FROM 'PASS'
           OR NULLIF(btrim(item->>'case_id'), '') IS NULL
           OR NULLIF(btrim(item->>'native_report_ref'), '') IS NULL
      )
      AND (
        SELECT count(DISTINCT item->>'case_id')
        FROM jsonb_array_elements(evidence->'native_reconciliation_cases') AS cases(item)
      ) = jsonb_array_length(evidence->'native_reconciliation_cases')
  END
$$;

CREATE TABLE IF NOT EXISTS bag.semantic_profiles (
    profile_id uuid PRIMARY KEY,
    source_id text NOT NULL REFERENCES bag.sources(source_id) ON DELETE RESTRICT,
    company_id uuid,
    preset_id text NOT NULL,
    profile_name text NOT NULL,
    profile_version integer NOT NULL CHECK (profile_version > 0),
    status text NOT NULL DEFAULT 'DRAFT'
      CHECK (status IN ('DRAFT','NEEDS_VALIDATION','VALIDATED','STALE','RETIRED')),
    metadata_fingerprint text NOT NULL,
    capability_fingerprint text NOT NULL,
    profile_fingerprint text NOT NULL,
    preset_repository text NOT NULL,
    preset_upstream_sha text NOT NULL,
    profile_json jsonb NOT NULL DEFAULT '{}'::jsonb
      CHECK (jsonb_typeof(profile_json) = 'object'),
    validation_evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb
      CHECK (jsonb_typeof(validation_evidence_json) = 'object'),
    created_by text NOT NULL,
    validated_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    validated_at timestamptz,
    retired_at timestamptz,
    CONSTRAINT semantic_profiles_company_source_fk
      FOREIGN KEY (company_id, source_id)
      REFERENCES bag.companies(company_id, source_id) ON DELETE RESTRICT,
    CONSTRAINT semantic_profiles_validation_state_check CHECK (
      status <> 'VALIDATED' OR
      (validated_by IS NOT NULL AND validated_at IS NOT NULL AND
       bag.native_reconciliation_evidence_valid(validation_evidence_json))
    ),
    CONSTRAINT semantic_profiles_retired_state_check CHECK (
      status <> 'RETIRED' OR retired_at IS NOT NULL
    ),
    CONSTRAINT semantic_profiles_scope_version_uq
      UNIQUE (source_id, company_id, preset_id, profile_version)
);

CREATE TABLE IF NOT EXISTS bag.semantic_mappings (
    mapping_id uuid PRIMARY KEY,
    profile_id uuid NOT NULL REFERENCES bag.semantic_profiles(profile_id) ON DELETE RESTRICT,
    canonical_concept text NOT NULL,
    mapping_json jsonb NOT NULL CHECK (jsonb_typeof(mapping_json) = 'object'),
    evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb
      CHECK (jsonb_typeof(evidence_json) = 'object'),
    mapping_status text NOT NULL DEFAULT 'CANDIDATE'
      CHECK (mapping_status IN ('CANDIDATE','CONFIRMED','REJECTED')),
    confidence text NOT NULL DEFAULT 'LOW'
      CHECK (confidence IN ('LOW','MEDIUM','HIGH')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (profile_id, canonical_concept)
);

CREATE INDEX IF NOT EXISTS semantic_profiles_lookup_idx
  ON bag.semantic_profiles(source_id, company_id, status, metadata_fingerprint);
CREATE INDEX IF NOT EXISTS semantic_mappings_profile_idx
  ON bag.semantic_mappings(profile_id, canonical_concept);
CREATE UNIQUE INDEX IF NOT EXISTS semantic_profiles_source_version_uq
  ON bag.semantic_profiles(source_id, preset_id, profile_version)
  WHERE company_id IS NULL;

CREATE OR REPLACE FUNCTION bag.invalidate_semantic_profiles_on_metadata_drift()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, bag
AS $$
BEGIN
  UPDATE bag.semantic_profiles
  SET status = 'STALE'
  WHERE source_id = NEW.source_id
    AND status = 'VALIDATED'
    AND metadata_fingerprint IS DISTINCT FROM NEW.metadata_fingerprint;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION bag.invalidate_semantic_profiles_on_metadata_drift() FROM PUBLIC;

DROP TRIGGER IF EXISTS source_capabilities_invalidate_semantic_profiles
  ON bag.source_capabilities;
CREATE TRIGGER source_capabilities_invalidate_semantic_profiles
AFTER UPDATE OF metadata_fingerprint ON bag.source_capabilities
FOR EACH ROW
WHEN (OLD.metadata_fingerprint IS DISTINCT FROM NEW.metadata_fingerprint)
EXECUTE FUNCTION bag.invalidate_semantic_profiles_on_metadata_drift();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    GRANT SELECT ON bag.semantic_profiles, bag.semantic_mappings TO business_ai_app;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT SELECT, INSERT, UPDATE ON bag.semantic_profiles, bag.semantic_mappings
      TO business_ai_admin;
  END IF;
END;
$$;

INSERT INTO bag.schema_migrations(version)
VALUES (6)
ON CONFLICT (version) DO NOTHING;

COMMIT;
