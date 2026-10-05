BEGIN;

CREATE TABLE IF NOT EXISTS bag.semantic_profile_events (
    event_id uuid PRIMARY KEY,
    profile_id uuid NOT NULL REFERENCES bag.semantic_profiles(profile_id) ON DELETE RESTRICT,
    actor text NOT NULL,
    action text NOT NULL
      CHECK (action IN ('CREATED','MAPPING_ADDED','VALIDATED','RETIRED')),
    details_json jsonb NOT NULL DEFAULT '{}'::jsonb
      CHECK (jsonb_typeof(details_json) = 'object'),
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS semantic_profile_events_profile_time_idx
  ON bag.semantic_profile_events(profile_id, occurred_at DESC);

CREATE OR REPLACE FUNCTION bag.reject_semantic_profile_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'bag.semantic_profile_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS semantic_profile_events_no_update_delete
  ON bag.semantic_profile_events;
CREATE TRIGGER semantic_profile_events_no_update_delete
BEFORE UPDATE OR DELETE ON bag.semantic_profile_events
FOR EACH ROW EXECUTE FUNCTION bag.reject_semantic_profile_event_mutation();

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    GRANT SELECT ON bag.semantic_profile_events TO business_ai_app;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT SELECT, INSERT ON bag.semantic_profile_events TO business_ai_admin;
    REVOKE UPDATE, DELETE ON bag.semantic_profile_events FROM business_ai_admin;
  END IF;
END;
$$;

INSERT INTO bag.schema_migrations(version)
VALUES (7)
ON CONFLICT (version) DO NOTHING;

COMMIT;
