BEGIN;

ALTER TABLE bag.source_capabilities
  ADD COLUMN IF NOT EXISTS previous_metadata_fingerprint text,
  ADD COLUMN IF NOT EXISTS drift_status text NOT NULL DEFAULT 'UNKNOWN',
  ADD COLUMN IF NOT EXISTS drift_detected_at timestamptz,
  ADD COLUMN IF NOT EXISTS drift_acknowledged_at timestamptz;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'source_capabilities_drift_status_check'
      AND conrelid = 'bag.source_capabilities'::regclass
  ) THEN
    ALTER TABLE bag.source_capabilities
      ADD CONSTRAINT source_capabilities_drift_status_check
      CHECK (drift_status IN ('UNKNOWN', 'STABLE', 'DRIFTED'));
  END IF;
END;
$$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT UPDATE (drift_status, drift_acknowledged_at)
      ON bag.source_capabilities TO business_ai_admin;
  END IF;
END;
$$;

INSERT INTO bag.schema_migrations(version)
VALUES (4)
ON CONFLICT (version) DO NOTHING;

COMMIT;
