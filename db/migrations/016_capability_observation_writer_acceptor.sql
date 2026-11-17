BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='business_ai_capability_writer')
     OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='business_ai_capability_acceptor') THEN
    RAISE EXCEPTION 'capability writer and acceptor group roles must be provisioned before migration 016';
  END IF;
  IF (SELECT rolcanlogin FROM pg_roles WHERE rolname='business_ai_capability_writer')
     OR (SELECT rolcanlogin FROM pg_roles WHERE rolname='business_ai_capability_acceptor') THEN
    RAISE EXCEPTION 'capability writer and acceptor roles must be NOLOGIN group roles';
  END IF;
  IF pg_has_role('business_ai_app', 'business_ai_capability_writer', 'MEMBER')
     OR pg_has_role('business_ai_app', 'business_ai_capability_acceptor', 'MEMBER')
     OR pg_has_role('business_ai_admin', 'business_ai_capability_writer', 'MEMBER')
     OR pg_has_role('business_ai_admin', 'business_ai_capability_acceptor', 'MEMBER')
     OR pg_has_role('business_ai_control_api', 'business_ai_capability_writer', 'MEMBER')
     OR pg_has_role('business_ai_control_api', 'business_ai_capability_acceptor', 'MEMBER') THEN
    RAISE EXCEPTION 'application/admin/control roles must not inherit capability writer or acceptor authority';
  END IF;
END;
$$;

CREATE TABLE bag.capability_observations (
  source_id text PRIMARY KEY REFERENCES bag.sources(source_id) ON DELETE CASCADE,
  request_id uuid NOT NULL UNIQUE,
  observation_id bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  source_row_version bigint NOT NULL CHECK (source_row_version > 0),
  observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  observed_by name NOT NULL,
  metadata_fingerprint text,
  platform_version text,
  compatibility_status text NOT NULL CHECK (
    compatibility_status IN ('SUPPORTED','SUPPORTED_WITH_FALLBACK','UNSUPPORTED')
  ),
  adapter_profile text NOT NULL CHECK (
    adapter_profile IN ('ODATA_JSON_V3','ODATA_ATOM_V3','HTTP_QUERY_FALLBACK','UNSUPPORTED')
  ),
  metadata_supported boolean NOT NULL,
  json_supported boolean NOT NULL,
  atom_supported boolean NOT NULL,
  expand_supported boolean,
  entity_set_count integer NOT NULL CHECK (entity_set_count >= 0),
  evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  register_capabilities_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  accepted_at timestamptz,
  accepted_by name,
  CHECK (NOT metadata_supported OR metadata_fingerprint ~ '^[0-9a-f]{64}$'),
  CHECK ((accepted_at IS NULL) = (accepted_by IS NULL))
);

ALTER TABLE bag.source_capabilities
  ADD COLUMN accepted_observation_id bigint
  CHECK (accepted_observation_id IS NULL OR accepted_observation_id > 0);

CREATE FUNCTION bag.bump_source_row_version()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, bag
AS $$
BEGIN
  NEW.row_version := OLD.row_version + 1;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION bag.bump_source_row_version() FROM PUBLIC;
CREATE TRIGGER sources_row_version_bump
BEFORE UPDATE ON bag.sources
FOR EACH ROW EXECUTE FUNCTION bag.bump_source_row_version();

REVOKE ALL ON TABLE bag.capability_observations FROM PUBLIC;
REVOKE ALL ON TABLE bag.capability_observations FROM business_ai_app, business_ai_admin, business_ai_control_api;
REVOKE ALL ON TABLE bag.capability_observations FROM business_ai_capability_writer, business_ai_capability_acceptor;
REVOKE ALL ON TABLE bag.source_capabilities FROM business_ai_capability_writer, business_ai_capability_acceptor;
GRANT USAGE ON SCHEMA bag TO business_ai_capability_writer, business_ai_capability_acceptor;
GRANT SELECT ON bag.schema_migrations TO business_ai_capability_writer, business_ai_capability_acceptor;

DROP FUNCTION bag.record_capability_observation(
  text, text, text, text, text, boolean, boolean, boolean, boolean, integer, jsonb, jsonb
);
DROP FUNCTION IF EXISTS bag.record_capability_observation(
  text, uuid, text, text, text, text, boolean, boolean, boolean, boolean, integer, jsonb, jsonb
);

CREATE FUNCTION bag.record_capability_observation(
    p_source_id text,
    p_request_id uuid,
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
  observation_observed_at timestamptz;
  current_source_row_version bigint;
BEGIN
  IF NOT pg_has_role(session_user, 'business_ai_capability_writer', 'MEMBER') THEN
    RAISE EXCEPTION 'caller lacks capability observation writer role';
  END IF;
  IF p_source_id IS NULL OR p_source_id = '' OR p_request_id IS NULL THEN
    RAISE EXCEPTION 'registered source id and request id are required';
  END IF;
  IF p_source_row_version IS NULL OR p_source_row_version <= 0 THEN
    RAISE EXCEPTION 'registered source version is required';
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

  SELECT o.observation_id, o.accepted_at, o.observed_at
  INTO observation_key, observation_accepted_at, observation_observed_at
  FROM bag.capability_observations AS o
  WHERE o.source_id = p_source_id AND o.request_id = p_request_id;
  IF FOUND AND (observation_accepted_at IS NOT NULL
      OR (observation_observed_at <= clock_timestamp()
          AND observation_observed_at >= clock_timestamp() - interval '5 minutes')) THEN
    RETURN observation_key;
  END IF;
  IF FOUND THEN
    DELETE FROM bag.capability_observations
    WHERE source_id = p_source_id AND request_id = p_request_id;
  END IF;
  -- The observation ID is GENERATED ALWAYS. Replace the source's previous
  -- observation under the advisory lock so the new row receives a fresh ID
  -- from the identity sequence without permitting an explicit identity write.
  DELETE FROM bag.capability_observations
  WHERE source_id = p_source_id;

  INSERT INTO bag.capability_observations(
      source_id, request_id, source_row_version, observed_by, metadata_fingerprint, platform_version,
      compatibility_status, adapter_profile, metadata_supported,
      json_supported, atom_supported, expand_supported, entity_set_count,
      evidence_json, register_capabilities_json, accepted_at, accepted_by
  )
  VALUES(
      p_source_id, p_request_id, p_source_row_version, session_user,
      CASE WHEN p_metadata_supported THEN p_metadata_fingerprint ELSE NULL END,
      p_platform_version, p_compatibility_status, p_adapter_profile,
      p_metadata_supported, p_json_supported, p_atom_supported,
      p_expand_supported, p_entity_set_count,
      COALESCE(p_evidence_json, '{}'::jsonb),
      COALESCE(p_register_capabilities_json, '{}'::jsonb), NULL, NULL
  )
  RETURNING observation_id INTO observation_key;

  RETURN observation_key;
END;
$$;

CREATE FUNCTION bag.accept_capability_observation(
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
BEGIN
  IF NOT pg_has_role(session_user, 'business_ai_capability_acceptor', 'MEMBER') THEN
    RAISE EXCEPTION 'caller lacks capability observation acceptor role';
  END IF;
  SELECT o.source_id INTO source_key
  FROM bag.capability_observations AS o
  WHERE o.source_id = p_source_id
    AND o.request_id = p_request_id
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
  WHERE o.source_id = source_key
    AND o.request_id = p_request_id
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
    WHERE c.source_id = source_key
      AND c.accepted_observation_id = p_observation_id;
    RETURN;
  END IF;
  IF observation.observed_at > clock_timestamp()
     OR observation.observed_at < clock_timestamp() - interval '5 minutes' THEN
    RAISE EXCEPTION 'capability observation is stale';
  END IF;

  RETURN QUERY
  INSERT INTO bag.source_capabilities(
      source_id, discovered_at, metadata_fingerprint, platform_version,
      compatibility_status, adapter_profile, metadata_supported,
      json_supported, atom_supported, expand_supported, entity_set_count,
      accepted_observation_id,
      evidence_json, register_capabilities_json, drift_status
  )
  VALUES(
      observation.source_id, observation.observed_at, observation.metadata_fingerprint,
      observation.platform_version, observation.compatibility_status,
      observation.adapter_profile, observation.metadata_supported,
      observation.json_supported, observation.atom_supported,
      observation.expand_supported, observation.entity_set_count,
      p_observation_id,
      observation.evidence_json, observation.register_capabilities_json,
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
  WHERE o.source_id = source_key AND o.observation_id = p_observation_id;
END;
$$;

CREATE FUNCTION bag.read_accepted_capability_observation(
    p_source_id text,
    p_request_id uuid,
    p_observation_id bigint
)
RETURNS TABLE(
    source_id text,
    metadata_fingerprint text,
    platform_version text,
    compatibility_status text,
    adapter_profile text,
    metadata_supported boolean,
    json_supported boolean,
    atom_supported boolean,
    expand_supported boolean,
    entity_set_count integer,
    evidence_json jsonb,
    register_capabilities_json jsonb,
    previous_metadata_fingerprint text,
    drift_status text,
    drift_detected_at timestamptz,
    drift_acknowledged_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, bag
AS $$
  SELECT c.source_id, c.metadata_fingerprint, c.platform_version,
         c.compatibility_status, c.adapter_profile, c.metadata_supported,
         c.json_supported, c.atom_supported, c.expand_supported, c.entity_set_count,
         c.evidence_json, c.register_capabilities_json, c.previous_metadata_fingerprint,
         c.drift_status, c.drift_detected_at, c.drift_acknowledged_at
  FROM bag.capability_observations AS o
  JOIN bag.source_capabilities AS c
    ON c.source_id = o.source_id
   AND c.accepted_observation_id = o.observation_id
  JOIN bag.sources AS s
    ON s.source_id = o.source_id
   AND s.enabled = TRUE
   AND s.row_version = o.source_row_version
  WHERE o.source_id = p_source_id
    AND o.request_id = p_request_id
    AND o.observation_id = p_observation_id
    AND o.accepted_at IS NOT NULL
    AND pg_has_role(o.accepted_by, 'business_ai_capability_acceptor', 'MEMBER')
$$;

REVOKE ALL ON FUNCTION bag.record_capability_observation(
  text, uuid, bigint, text, text, text, text, boolean, boolean, boolean, boolean, integer, jsonb, jsonb
) FROM PUBLIC, business_ai_app, business_ai_admin, business_ai_control_api, business_ai_capability_acceptor;
REVOKE ALL ON FUNCTION bag.accept_capability_observation(text, uuid, bigint)
  FROM PUBLIC, business_ai_app, business_ai_admin, business_ai_control_api, business_ai_capability_writer;
REVOKE ALL ON FUNCTION bag.read_accepted_capability_observation(text, uuid, bigint)
  FROM PUBLIC, business_ai_admin, business_ai_control_api, business_ai_capability_writer,
       business_ai_capability_acceptor;
GRANT EXECUTE ON FUNCTION bag.record_capability_observation(
  text, uuid, bigint, text, text, text, text, boolean, boolean, boolean, boolean, integer, jsonb, jsonb
) TO business_ai_capability_writer;
GRANT EXECUTE ON FUNCTION bag.accept_capability_observation(text, uuid, bigint)
  TO business_ai_capability_acceptor;
GRANT EXECUTE ON FUNCTION bag.read_accepted_capability_observation(text, uuid, bigint)
  TO business_ai_app;

DO $$
DECLARE
  runtime_role text;
BEGIN
  FOREACH runtime_role IN ARRAY ARRAY['business_ai_app', 'business_ai_admin', 'business_ai_control_api'] LOOP
    IF has_function_privilege(runtime_role,
         'bag.record_capability_observation(text,uuid,bigint,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)'::regprocedure,
         'EXECUTE')
       OR has_function_privilege(runtime_role,
         'bag.accept_capability_observation(text,uuid,bigint)'::regprocedure,
         'EXECUTE')
       OR (runtime_role <> 'business_ai_app' AND has_function_privilege(runtime_role,
         'bag.read_accepted_capability_observation(text,uuid,bigint)'::regprocedure,
         'EXECUTE'))
       OR pg_has_role(runtime_role, 'business_ai_capability_writer', 'MEMBER')
       OR pg_has_role(runtime_role, 'business_ai_capability_acceptor', 'MEMBER') THEN
      RAISE EXCEPTION 'runtime role % retains capability writer or acceptor authority', runtime_role;
    END IF;
  END LOOP;
  IF NOT has_function_privilege('business_ai_app',
       'bag.read_accepted_capability_observation(text,uuid,bigint)'::regprocedure, 'EXECUTE') THEN
    RAISE EXCEPTION 'runtime app role must read only accepted observation state';
  END IF;
  IF has_function_privilege('business_ai_capability_writer',
       'bag.accept_capability_observation(text,uuid,bigint)'::regprocedure, 'EXECUTE')
     OR has_function_privilege('business_ai_capability_acceptor',
       'bag.record_capability_observation(text,uuid,bigint,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)'::regprocedure,
       'EXECUTE') THEN
    RAISE EXCEPTION 'capability writer and acceptor authorities must remain separate';
  END IF;
END;
$$;

COMMIT;
