BEGIN;

ALTER TABLE bag.semantic_mappings
  ADD CONSTRAINT semantic_mappings_confirmed_confidence_check
  CHECK (mapping_status <> 'CONFIRMED' OR confidence = 'HIGH');

ALTER TABLE bag.semantic_profile_events
  DROP CONSTRAINT semantic_profile_events_action_check,
  ADD CONSTRAINT semantic_profile_events_action_check
    CHECK (action IN (
      'CREATED','MAPPING_ADDED','MAPPING_CONFIRMED','MAPPING_CHANGED_INVALIDATED',
      'VALIDATED','RETIRED'
    ));

CREATE OR REPLACE FUNCTION bag.invalidate_validated_profile_on_mapping_change()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, bag
AS $$
DECLARE
  affected_profile_id uuid;
  affected_mapping_id uuid;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    affected_profile_id := OLD.profile_id;
    affected_mapping_id := OLD.mapping_id;
    UPDATE bag.semantic_profiles SET status='STALE'
    WHERE profile_id=affected_profile_id AND status='VALIDATED';
    IF FOUND THEN
      INSERT INTO bag.semantic_profile_events(
        event_id, profile_id, actor, action, details_json
      ) VALUES (
        gen_random_uuid(), affected_profile_id, session_user,
        'MAPPING_CHANGED_INVALIDATED',
        jsonb_build_object('mapping_id', affected_mapping_id, 'operation', TG_OP)
      );
    END IF;
  END IF;

  IF TG_OP <> 'DELETE' AND (TG_OP <> 'UPDATE' OR NEW.profile_id IS DISTINCT FROM OLD.profile_id) THEN
    affected_profile_id := NEW.profile_id;
    affected_mapping_id := NEW.mapping_id;
    UPDATE bag.semantic_profiles SET status='STALE'
    WHERE profile_id=affected_profile_id AND status='VALIDATED';
    IF FOUND THEN
      INSERT INTO bag.semantic_profile_events(
        event_id, profile_id, actor, action, details_json
      ) VALUES (
        gen_random_uuid(), affected_profile_id, session_user,
        'MAPPING_CHANGED_INVALIDATED',
        jsonb_build_object('mapping_id', affected_mapping_id, 'operation', TG_OP)
      );
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION bag.invalidate_validated_profile_on_mapping_change() FROM PUBLIC;

DROP TRIGGER IF EXISTS semantic_mapping_change_invalidates_profile
  ON bag.semantic_mappings;
CREATE TRIGGER semantic_mapping_change_invalidates_profile
AFTER INSERT OR UPDATE OR DELETE ON bag.semantic_mappings
FOR EACH ROW EXECUTE FUNCTION bag.invalidate_validated_profile_on_mapping_change();

INSERT INTO bag.schema_migrations(version)
VALUES (8)
ON CONFLICT (version) DO NOTHING;

COMMIT;
