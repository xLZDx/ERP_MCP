BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_capability_writer')
     OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_capability_acceptor') THEN
    RAISE EXCEPTION 'capability writer and acceptor roles must exist before migration 018';
  END IF;
END;
$$;

CREATE TABLE bag.capability_probe_reservations (
  reservation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id text NOT NULL REFERENCES bag.sources(source_id) ON DELETE CASCADE,
  request_id uuid NOT NULL UNIQUE,
  source_row_version bigint NOT NULL CHECK (source_row_version > 0),
  reserved_at timestamptz NOT NULL,
  UNIQUE (source_id, request_id),
  UNIQUE (reservation_id, source_id, request_id, source_row_version)
);

REVOKE ALL ON TABLE bag.capability_probe_reservations FROM PUBLIC;
REVOKE ALL ON TABLE bag.capability_probe_reservations
  FROM business_ai_app, business_ai_admin, business_ai_control_api,
       business_ai_capability_writer, business_ai_capability_acceptor;
REVOKE ALL ON SEQUENCE bag.capability_probe_reservations_reservation_id_seq
  FROM PUBLIC, business_ai_app, business_ai_admin, business_ai_control_api,
       business_ai_capability_writer, business_ai_capability_acceptor;

-- Preserve each existing observation and its DB timestamp as a historical reservation.
INSERT INTO bag.capability_probe_reservations(source_id, request_id, source_row_version, reserved_at)
SELECT source_id, request_id, source_row_version, observed_at
FROM bag.capability_observations
ORDER BY observed_at, source_id, request_id;

ALTER TABLE bag.capability_observations ADD COLUMN reservation_id bigint;
UPDATE bag.capability_observations AS o
SET reservation_id = r.reservation_id
FROM bag.capability_probe_reservations AS r
WHERE r.source_id = o.source_id
  AND r.request_id = o.request_id
  AND r.source_row_version = o.source_row_version;
ALTER TABLE bag.capability_observations ALTER COLUMN reservation_id SET NOT NULL;

ALTER TABLE bag.capability_observations DROP CONSTRAINT capability_observations_pkey;
ALTER TABLE bag.capability_observations
  ADD CONSTRAINT capability_observations_pkey PRIMARY KEY (source_id, request_id);
ALTER TABLE bag.capability_observations
  ADD CONSTRAINT capability_observations_reservation_fk
  FOREIGN KEY (reservation_id, source_id, request_id, source_row_version)
  REFERENCES bag.capability_probe_reservations(
    reservation_id, source_id, request_id, source_row_version
  );

CREATE INDEX capability_probe_reservations_expiry_idx
  ON bag.capability_probe_reservations(source_id, reserved_at);
CREATE INDEX capability_observations_expiry_idx
  ON bag.capability_observations(source_id, observed_at);

CREATE FUNCTION bag.reserve_capability_probe(
  p_source_id text,
  p_request_id uuid,
  p_source_row_version bigint
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, bag
AS $$
DECLARE
  reservation_key bigint;
  reserved_time timestamptz;
  observation_accepted_at timestamptz;
  current_source_row_version bigint;
BEGIN
  IF NOT pg_has_role(session_user, 'business_ai_capability_writer', 'MEMBER') THEN
    RAISE EXCEPTION 'caller lacks capability observation writer role';
  END IF;
  IF p_source_id IS NULL OR p_source_id = '' OR p_request_id IS NULL
     OR p_source_row_version IS NULL OR p_source_row_version <= 0 THEN
    RAISE EXCEPTION 'registered source, request id and source version are required';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_source_id, 0));
  SELECT s.row_version INTO current_source_row_version
  FROM bag.sources AS s
  WHERE s.source_id = p_source_id AND s.enabled = TRUE
  FOR SHARE;
  IF NOT FOUND OR current_source_row_version <> p_source_row_version THEN
    RAISE EXCEPTION 'registered source configuration changed before capability probe';
  END IF;

  -- Reject an idempotency key still bound to another source/version before
  -- opportunistic expiry cleanup can remove its old reservation.
  IF EXISTS (
    SELECT 1 FROM bag.capability_probe_reservations AS r
    WHERE r.request_id = p_request_id
      AND (r.source_id <> p_source_id OR r.source_row_version <> p_source_row_version)
  ) THEN
    RAISE EXCEPTION 'request id is bound to a different source version';
  END IF;

  -- Expiry belongs to the reservation generation, not the later observation time.
  -- Preserve the accepted pointer regardless of age; expire other observations only
  -- after their linked reservation's original DB-clock start passes the live window.
  DELETE FROM bag.capability_observations AS o
  USING bag.capability_probe_reservations AS r
  WHERE r.reservation_id = o.reservation_id
    AND o.source_id = p_source_id
    AND r.reserved_at < clock_timestamp() - interval '5 minutes'
    AND NOT EXISTS (
      SELECT 1 FROM bag.source_capabilities AS c
      WHERE c.source_id = o.source_id
        AND c.accepted_observation_id = o.observation_id
    );
  DELETE FROM bag.capability_probe_reservations AS r
  WHERE r.source_id = p_source_id
    AND r.reserved_at < clock_timestamp() - interval '5 minutes'
    AND NOT EXISTS (
      SELECT 1 FROM bag.capability_observations AS o
      WHERE o.reservation_id = r.reservation_id
    );

  SELECT r.reservation_id, r.reserved_at, o.accepted_at
  INTO reservation_key, reserved_time, observation_accepted_at
  FROM bag.capability_probe_reservations AS r
  LEFT JOIN bag.capability_observations AS o
    ON o.reservation_id = r.reservation_id
  WHERE r.source_id = p_source_id AND r.request_id = p_request_id
    AND r.source_row_version = p_source_row_version
  FOR UPDATE OF r;
  IF FOUND THEN
    IF observation_accepted_at IS NOT NULL THEN
      RETURN reservation_key;
    END IF;
    IF reserved_time >= clock_timestamp() - interval '5 minutes' THEN
      RETURN reservation_key;
    END IF;
    DELETE FROM bag.capability_probe_reservations
    WHERE reservation_id = reservation_key;
  ELSIF EXISTS (
    SELECT 1 FROM bag.capability_probe_reservations AS r
    WHERE r.source_id = p_source_id AND r.request_id = p_request_id
  ) THEN
    RAISE EXCEPTION 'request id is bound to a different source version';
  END IF;

  INSERT INTO bag.capability_probe_reservations(
    source_id, request_id, source_row_version, reserved_at
  ) VALUES (p_source_id, p_request_id, p_source_row_version, clock_timestamp())
  RETURNING reservation_id INTO reservation_key;
  RETURN reservation_key;
END;
$$;

DROP FUNCTION bag.record_capability_observation(
  text, uuid, bigint, text, text, text, text, boolean, boolean, boolean, boolean, integer, jsonb, jsonb
);

CREATE FUNCTION bag.record_capability_observation(
    p_source_id text,
    p_request_id uuid,
    p_reservation_id bigint,
    p_source_row_version bigint,
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
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, bag
AS $$
DECLARE
  observation_key bigint;
  observation_accepted_at timestamptz;
  reservation_time timestamptz;
  current_source_row_version bigint;
  current_accepted_reservation_id bigint;
  current_accepted_observation_id bigint;
  observation_exists boolean;
BEGIN
  IF NOT pg_has_role(session_user, 'business_ai_capability_writer', 'MEMBER') THEN
    RAISE EXCEPTION 'caller lacks capability observation writer role';
  END IF;
  IF p_source_id IS NULL OR p_source_id = '' OR p_request_id IS NULL
     OR p_reservation_id IS NULL OR p_source_row_version IS NULL OR p_source_row_version <= 0 THEN
    RAISE EXCEPTION 'registered source, request, reservation and source version are required';
  END IF;
  IF p_metadata_supported AND (p_metadata_fingerprint IS NULL
      OR p_metadata_fingerprint !~ '^[0-9a-f]{64}$') THEN
    RAISE EXCEPTION 'supported metadata observation requires a valid fingerprint';
  END IF;
  IF p_entity_set_count IS NULL OR p_entity_set_count < 0 THEN
    RAISE EXCEPTION 'entity set count must be nonnegative';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_source_id, 0));
  SELECT s.row_version INTO current_source_row_version
  FROM bag.sources AS s
  WHERE s.source_id = p_source_id AND s.enabled = TRUE
  FOR SHARE;
  IF NOT FOUND OR current_source_row_version <> p_source_row_version THEN
    RAISE EXCEPTION 'registered source configuration changed during observation';
  END IF;

  SELECT r.reserved_at INTO reservation_time
  FROM bag.capability_probe_reservations AS r
  WHERE r.reservation_id = p_reservation_id
    AND r.source_id = p_source_id
    AND r.request_id = p_request_id
    AND r.source_row_version = p_source_row_version
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'capability probe reservation is missing or stale';
  END IF;

  SELECT o.observation_id, o.accepted_at
  INTO observation_key, observation_accepted_at
  FROM bag.capability_observations AS o
  WHERE o.source_id = p_source_id AND o.request_id = p_request_id
    AND o.reservation_id = p_reservation_id;
  observation_exists := FOUND;
  IF observation_exists AND observation_accepted_at IS NOT NULL THEN
    SELECT o.reservation_id, o.observation_id
    INTO current_accepted_reservation_id, current_accepted_observation_id
    FROM bag.source_capabilities AS c
    JOIN bag.capability_observations AS o
      ON o.source_id = c.source_id
     AND o.observation_id = c.accepted_observation_id
    WHERE c.source_id = p_source_id;
    IF FOUND AND current_accepted_observation_id = observation_key THEN
      RETURN observation_key;
    END IF;
    RETURN NULL;
  END IF;

  SELECT o.reservation_id, o.observation_id
  INTO current_accepted_reservation_id, current_accepted_observation_id
  FROM bag.source_capabilities AS c
  JOIN bag.capability_observations AS o
    ON o.source_id = c.source_id
   AND o.observation_id = c.accepted_observation_id
  WHERE c.source_id = p_source_id;
  IF FOUND AND p_reservation_id <= current_accepted_reservation_id THEN
    RETURN NULL;
  END IF;

  IF reservation_time < clock_timestamp() - interval '5 minutes' THEN
    RAISE EXCEPTION 'capability probe reservation is stale';
  END IF;
  IF observation_exists THEN
    RETURN observation_key;
  END IF;

  INSERT INTO bag.capability_observations(
      source_id, request_id, reservation_id, source_row_version, observed_by,
      metadata_fingerprint, platform_version, compatibility_status, adapter_profile,
      metadata_supported, json_supported, atom_supported, expand_supported,
      entity_set_count, evidence_json, register_capabilities_json, accepted_at, accepted_by
  ) VALUES (
      p_source_id, p_request_id, p_reservation_id, p_source_row_version, session_user,
      CASE WHEN p_metadata_supported THEN p_metadata_fingerprint ELSE NULL END,
      p_platform_version, p_compatibility_status, p_adapter_profile,
      p_metadata_supported, p_json_supported, p_atom_supported, p_expand_supported,
      p_entity_set_count, COALESCE(p_evidence_json, '{}'::jsonb),
      COALESCE(p_register_capabilities_json, '{}'::jsonb), NULL, NULL
  )
  ON CONFLICT (source_id, request_id) DO UPDATE SET
    reservation_id = EXCLUDED.reservation_id,
    source_row_version = EXCLUDED.source_row_version,
    observed_at = clock_timestamp(),
    observed_by = EXCLUDED.observed_by,
    metadata_fingerprint = EXCLUDED.metadata_fingerprint,
    platform_version = EXCLUDED.platform_version,
    compatibility_status = EXCLUDED.compatibility_status,
    adapter_profile = EXCLUDED.adapter_profile,
    metadata_supported = EXCLUDED.metadata_supported,
    json_supported = EXCLUDED.json_supported,
    atom_supported = EXCLUDED.atom_supported,
    expand_supported = EXCLUDED.expand_supported,
    entity_set_count = EXCLUDED.entity_set_count,
    evidence_json = EXCLUDED.evidence_json,
    register_capabilities_json = EXCLUDED.register_capabilities_json
  RETURNING observation_id INTO observation_key;
  RETURN observation_key;
END;
$$;

CREATE OR REPLACE FUNCTION bag.accept_capability_observation(
    p_source_id text,
    p_request_id uuid,
    p_observation_id bigint
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
DECLARE
  observation bag.capability_observations%ROWTYPE;
  source_key text;
  current_source_row_version bigint;
  accepted_reservation_id bigint;
BEGIN
  IF NOT pg_has_role(session_user, 'business_ai_capability_acceptor', 'MEMBER') THEN
    RAISE EXCEPTION 'caller lacks capability observation acceptor role';
  END IF;
  SELECT o.source_id INTO source_key
  FROM bag.capability_observations AS o
  WHERE o.source_id = p_source_id AND o.request_id = p_request_id
    AND o.observation_id = p_observation_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'capability observation provenance is missing or stale';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(source_key, 0));
  SELECT s.row_version INTO current_source_row_version
  FROM bag.sources AS s
  WHERE s.source_id = source_key AND s.enabled = TRUE
  FOR SHARE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'capability observation source is no longer registered and enabled';
  END IF;
  SELECT o.* INTO observation
  FROM bag.capability_observations AS o
  WHERE o.source_id = source_key AND o.request_id = p_request_id
    AND o.observation_id = p_observation_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'capability observation provenance is missing or stale';
  END IF;
  IF current_source_row_version <> observation.source_row_version THEN
    RAISE EXCEPTION 'registered source configuration changed after observation';
  END IF;
  IF NOT pg_has_role(observation.observed_by, 'business_ai_capability_writer', 'MEMBER') THEN
    RAISE EXCEPTION 'capability observation was not recorded by the trusted writer role';
  END IF;
  IF observation.accepted_at IS NOT NULL THEN
    RETURN QUERY SELECT c.drift_status, c.previous_metadata_fingerprint,
      c.drift_detected_at, c.drift_acknowledged_at, c.evidence_json
    FROM bag.source_capabilities AS c
    WHERE c.source_id = source_key AND c.accepted_observation_id = p_observation_id;
    RETURN;
  END IF;
  IF observation.observed_at > clock_timestamp()
     OR observation.observed_at < clock_timestamp() - interval '5 minutes' THEN
    RAISE EXCEPTION 'capability observation is stale';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM bag.capability_probe_reservations AS r
    WHERE r.reservation_id = observation.reservation_id
      AND r.source_id = observation.source_id
      AND r.request_id = observation.request_id
      AND r.source_row_version = observation.source_row_version
      AND r.reserved_at <= clock_timestamp()
      AND r.reserved_at >= clock_timestamp() - interval '5 minutes'
  ) THEN
    RAISE EXCEPTION 'capability probe reservation is missing or stale';
  END IF;

  SELECT o.reservation_id INTO accepted_reservation_id
  FROM bag.source_capabilities AS c
  JOIN bag.capability_observations AS o
    ON o.source_id = c.source_id
   AND o.observation_id = c.accepted_observation_id
  WHERE c.source_id = source_key;
  IF FOUND AND observation.reservation_id <= accepted_reservation_id THEN
    RETURN;
  END IF;

  RETURN QUERY
  INSERT INTO bag.source_capabilities(
      source_id, discovered_at, metadata_fingerprint, platform_version,
      compatibility_status, adapter_profile, metadata_supported,
      json_supported, atom_supported, expand_supported, entity_set_count,
      accepted_observation_id, evidence_json, register_capabilities_json, drift_status
  ) VALUES (
      observation.source_id, observation.observed_at, observation.metadata_fingerprint,
      observation.platform_version, observation.compatibility_status,
      observation.adapter_profile, observation.metadata_supported,
      observation.json_supported, observation.atom_supported, observation.expand_supported,
      observation.entity_set_count, p_observation_id, observation.evidence_json,
      observation.register_capabilities_json,
      CASE WHEN observation.metadata_supported THEN 'STABLE' ELSE 'NEEDS_VALIDATION' END
  )
  ON CONFLICT(source_id) DO UPDATE SET
      discovered_at = EXCLUDED.discovered_at,
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
      accepted_observation_id = EXCLUDED.accepted_observation_id,
      evidence_json = jsonb_set(
        COALESCE(EXCLUDED.evidence_json, '{}'::jsonb),
        '{semantic_capabilities}',
        COALESCE(bag.source_capabilities.evidence_json->'semantic_capabilities', '{}'::jsonb)
          || COALESCE(EXCLUDED.evidence_json->'semantic_capabilities', '{}'::jsonb),
        true
      ),
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
        WHEN bag.source_capabilities.metadata_fingerprint IS DISTINCT FROM EXCLUDED.metadata_fingerprint THEN EXCLUDED.discovered_at
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

  UPDATE bag.capability_observations AS o
  SET accepted_at = clock_timestamp(), accepted_by = session_user
  WHERE o.source_id = source_key AND o.request_id = p_request_id
    AND o.observation_id = p_observation_id;
END;
$$;

REVOKE ALL ON FUNCTION bag.reserve_capability_probe(text, uuid, bigint)
  FROM PUBLIC, business_ai_app, business_ai_admin, business_ai_control_api,
       business_ai_capability_acceptor;
REVOKE ALL ON FUNCTION bag.record_capability_observation(
  text, uuid, bigint, bigint, text, text, text, text,
  boolean, boolean, boolean, boolean, integer, jsonb, jsonb
) FROM PUBLIC, business_ai_app, business_ai_admin, business_ai_control_api,
         business_ai_capability_acceptor;
GRANT EXECUTE ON FUNCTION bag.reserve_capability_probe(text, uuid, bigint)
  TO business_ai_capability_writer;
GRANT EXECUTE ON FUNCTION bag.record_capability_observation(
  text, uuid, bigint, bigint, text, text, text, text,
  boolean, boolean, boolean, boolean, integer, jsonb, jsonb
) TO business_ai_capability_writer;

DO $$
DECLARE
  runtime_role text;
BEGIN
  FOREACH runtime_role IN ARRAY ARRAY['business_ai_app', 'business_ai_admin', 'business_ai_control_api'] LOOP
    IF has_function_privilege(runtime_role,
         'bag.reserve_capability_probe(text,uuid,bigint)'::regprocedure, 'EXECUTE')
       OR has_function_privilege(runtime_role,
         'bag.record_capability_observation(text,uuid,bigint,bigint,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)'::regprocedure,
         'EXECUTE') THEN
      RAISE EXCEPTION 'runtime role % retains capability reservation or writer authority', runtime_role;
    END IF;
  END LOOP;
  IF NOT has_function_privilege('business_ai_capability_writer',
       'bag.reserve_capability_probe(text,uuid,bigint)'::regprocedure, 'EXECUTE')
     OR NOT has_function_privilege('business_ai_capability_writer',
       'bag.record_capability_observation(text,uuid,bigint,bigint,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)'::regprocedure,
       'EXECUTE')
     OR has_function_privilege('business_ai_capability_acceptor',
       'bag.reserve_capability_probe(text,uuid,bigint)'::regprocedure, 'EXECUTE')
     OR has_function_privilege('business_ai_capability_acceptor',
       'bag.record_capability_observation(text,uuid,bigint,bigint,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)'::regprocedure,
       'EXECUTE') THEN
    RAISE EXCEPTION 'capability reservation/writer and acceptor authorities are not separated';
  END IF;
END;
$$;

COMMIT;
