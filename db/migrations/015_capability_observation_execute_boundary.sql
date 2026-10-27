REVOKE EXECUTE ON FUNCTION bag.record_capability_observation(
  text, text, text, text, text, boolean, boolean, boolean, boolean,
  integer, jsonb, jsonb
) FROM PUBLIC;

DO $$
DECLARE
  runtime_role text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    RAISE EXCEPTION 'required role business_ai_app is missing';
  END IF;

  FOREACH runtime_role IN ARRAY ARRAY['business_ai_admin', 'business_ai_control_api'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime_role) THEN
      EXECUTE format(
        'REVOKE EXECUTE ON FUNCTION bag.record_capability_observation(text,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb) FROM %I',
        runtime_role
      );
    END IF;
  END LOOP;
END;
$$;

GRANT EXECUTE ON FUNCTION bag.record_capability_observation(
  text, text, text, text, text, boolean, boolean, boolean, boolean,
  integer, jsonb, jsonb
) TO business_ai_app;

DO $$
DECLARE
  runtime_role text;
BEGIN
  FOREACH runtime_role IN ARRAY ARRAY['business_ai_admin', 'business_ai_control_api'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime_role)
       AND has_function_privilege(
         runtime_role,
         'bag.record_capability_observation(text,text,text,text,text,boolean,boolean,boolean,boolean,integer,jsonb,jsonb)'::regprocedure,
         'EXECUTE'
       ) THEN
      RAISE EXCEPTION 'runtime role % retains effective EXECUTE on bag.record_capability_observation', runtime_role;
    END IF;
  END LOOP;
END;
$$;
