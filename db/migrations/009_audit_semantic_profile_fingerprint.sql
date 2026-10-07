BEGIN;

ALTER TABLE bag.audit_events
  ADD COLUMN IF NOT EXISTS profile_fingerprint text;

INSERT INTO bag.schema_migrations(version)
VALUES (9)
ON CONFLICT (version) DO NOTHING;

COMMIT;
