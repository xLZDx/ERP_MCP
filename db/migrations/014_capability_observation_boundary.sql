BEGIN;

ALTER TABLE bag.source_capabilities
  ALTER COLUMN metadata_fingerprint DROP NOT NULL;

ALTER TABLE bag.source_capabilities
  DROP CONSTRAINT IF EXISTS source_capabilities_drift_status_check;

ALTER TABLE bag.source_capabilities
  ADD CONSTRAINT source_capabilities_drift_status_check
  CHECK (drift_status IN ('UNKNOWN', 'STABLE', 'DRIFTED', 'NEEDS_VALIDATION'));

CREATE OR REPLACE FUNCTION bag.record_capability_observation(
    p_source_id text,
    p_metadata_fingerprint text,
    p_platform_version text,
    p_compatibility_status text,
    p_adapter_profile text,
    p_metadata_supported boolean,
    p_json_supported boolean,
    p_atom_supported boolean,
    p_expand_supported boolean,
    p_entity_set_count integer,
    p_evidence_json jsonb,
    p_register_capabilities_json jsonb
)
RETURNS TABLE(
    drift_status text,
    previous_metadata_fingerprint text,
    drift_detected_at timestamptz,
    drift_acknowledged_at timestamptz,
    evidence_json jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, bag
AS $$
BEGIN
  IF p_metadata_supported AND (p_metadata_fingerprint IS NULL
      OR p_metadata_fingerprint !~ '^[0-9a-f]{64}$') THEN
    RAISE EXCEPTION 'supported metadata observation requires a valid fingerprint';
  END IF;

  RETURN QUERY
  INSERT INTO bag.source_capabilities(
      source_id, discovered_at, metadata_fingerprint, platform_version,
      compatibility_status, adapter_profile, metadata_supported,
      json_supported, atom_supported, expand_supported, entity_set_count,
      evidence_json, register_capabilities_json, drift_status
  )
  VALUES(
      p_source_id, now(),
      CASE WHEN p_metadata_supported THEN p_metadata_fingerprint ELSE NULL END,
      p_platform_version, p_compatibility_status, p_adapter_profile,
      p_metadata_supported, p_json_supported, p_atom_supported,
      p_expand_supported, p_entity_set_count, p_evidence_json,
      p_register_capabilities_json,
      CASE WHEN p_metadata_supported THEN 'STABLE' ELSE 'NEEDS_VALIDATION' END
  )
  ON CONFLICT(source_id) DO UPDATE SET
      discovered_at = now(),
      previous_metadata_fingerprint = CASE
        WHEN EXCLUDED.metadata_fingerprint IS NOT NULL
         AND bag.source_capabilities.metadata_fingerprint IS DISTINCT FROM EXCLUDED.metadata_fingerprint
        THEN bag.source_capabilities.metadata_fingerprint
        ELSE bag.source_capabilities.previous_metadata_fingerprint
      END,
      metadata_fingerprint = COALESCE(EXCLUDED.metadata_fingerprint,
                                      bag.source_capabilities.metadata_fingerprint),
      platform_version = EXCLUDED.platform_version,
      compatibility_status = EXCLUDED.compatibility_status,
      adapter_profile = EXCLUDED.adapter_profile,
      metadata_supported = EXCLUDED.metadata_supported,
      json_supported = EXCLUDED.json_supported,
      atom_supported = EXCLUDED.atom_supported,
      expand_supported = EXCLUDED.expand_supported,
      entity_set_count = EXCLUDED.entity_set_count,
      evidence_json = EXCLUDED.evidence_json,
      register_capabilities_json = EXCLUDED.register_capabilities_json,
      drift_status = CASE
        WHEN NOT EXCLUDED.metadata_supported THEN 'NEEDS_VALIDATION'
        WHEN bag.source_capabilities.drift_status = 'DRIFTED' THEN 'DRIFTED'
        WHEN bag.source_capabilities.metadata_fingerprint IS NULL THEN 'STABLE'
        WHEN bag.source_capabilities.metadata_fingerprint IS DISTINCT FROM EXCLUDED.metadata_fingerprint THEN 'DRIFTED'
        ELSE 'STABLE'
      END,
      drift_detected_at = CASE
        WHEN NOT EXCLUDED.metadata_supported THEN bag.source_capabilities.drift_detected_at
        WHEN bag.source_capabilities.metadata_fingerprint IS DISTINCT FROM EXCLUDED.metadata_fingerprint THEN now()
        ELSE bag.source_capabilities.drift_detected_at
      END,
      drift_acknowledged_at = CASE
        WHEN NOT EXCLUDED.metadata_supported THEN NULL
        WHEN bag.source_capabilities.metadata_fingerprint IS DISTINCT FROM EXCLUDED.metadata_fingerprint THEN NULL
        ELSE bag.source_capabilities.drift_acknowledged_at
      END
  RETURNING bag.source_capabilities.drift_status,
            bag.source_capabilities.previous_metadata_fingerprint,
            bag.source_capabilities.drift_detected_at,
            bag.source_capabilities.drift_acknowledged_at,
            bag.source_capabilities.evidence_json;
END;
$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    REVOKE INSERT, UPDATE ON bag.source_capabilities FROM business_ai_app;
    GRANT UPDATE (evidence_json) ON bag.source_capabilities TO business_ai_app;
    GRANT EXECUTE ON FUNCTION bag.record_capability_observation(
      text, text, text, text, text, boolean, boolean, boolean, boolean,
      integer, jsonb, jsonb
    ) TO business_ai_app;
  END IF;
END;
$$;

INSERT INTO bag.schema_migrations(version)
VALUES (14)
ON CONFLICT (version) DO NOTHING;

COMMIT;
