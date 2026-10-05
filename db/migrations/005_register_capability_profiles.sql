BEGIN;

ALTER TABLE bag.source_capabilities
  ADD COLUMN IF NOT EXISTS register_capabilities_json jsonb NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'source_capabilities_register_capabilities_object_check'
      AND conrelid = 'bag.source_capabilities'::regclass
  ) THEN
    ALTER TABLE bag.source_capabilities
      ADD CONSTRAINT source_capabilities_register_capabilities_object_check
      CHECK (jsonb_typeof(register_capabilities_json) = 'object');
  END IF;
END;
$$;

INSERT INTO bag.schema_migrations(version)
VALUES (5)
ON CONFLICT (version) DO NOTHING;

COMMIT;
