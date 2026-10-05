BEGIN;

CREATE SCHEMA IF NOT EXISTS bag;

CREATE TABLE IF NOT EXISTS bag.schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bag.sources (
    source_id text PRIMARY KEY,
    project text NOT NULL CHECK (project IN ('onec','erp','ferma')),
    kind text NOT NULL CHECK (kind IN ('onec_odata','erp_api','ferma_api')),
    display_name text NOT NULL,
    base_url text NOT NULL,
    username_secret_ref text,
    password_secret_ref text,
    read_only boolean NOT NULL DEFAULT true CHECK (read_only = true),
    enabled boolean NOT NULL DEFAULT true,
    tags text[] NOT NULL DEFAULT '{}',
    entity_allow_patterns text[] NOT NULL DEFAULT '{}',
    entity_deny_patterns text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
      (username_secret_ref IS NULL AND password_secret_ref IS NULL)
      OR
      (username_secret_ref IS NOT NULL AND password_secret_ref IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS bag.access_grants (
    grant_id uuid PRIMARY KEY,
    principal_kind text NOT NULL CHECK (principal_kind IN ('subject','group')),
    principal_id text NOT NULL,
    source_id text REFERENCES bag.sources(source_id) ON DELETE CASCADE,
    all_sources boolean NOT NULL DEFAULT false,
    expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
      (all_sources = true AND source_id IS NULL)
      OR
      (all_sources = false AND source_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS access_grants_lookup_idx
ON bag.access_grants(principal_kind, principal_id, source_id)
WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS bag.audit_events (
    event_id uuid PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    principal_subject text NOT NULL,
    client_id text NOT NULL,
    tool_name text NOT NULL,
    source_id text,
    outcome text NOT NULL CHECK (outcome IN ('success','error','denied')),
    query_fingerprint text,
    query_json jsonb,
    returned_items integer,
    duration_ms integer NOT NULL CHECK (duration_ms >= 0),
    detail_code text
);

CREATE INDEX IF NOT EXISTS audit_subject_time_idx
ON bag.audit_events(principal_subject, occurred_at DESC);

CREATE INDEX IF NOT EXISTS audit_source_time_idx
ON bag.audit_events(source_id, occurred_at DESC);

CREATE OR REPLACE FUNCTION bag.reject_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'bag.audit_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS audit_events_no_update_delete ON bag.audit_events;
CREATE TRIGGER audit_events_no_update_delete
BEFORE UPDATE OR DELETE ON bag.audit_events
FOR EACH ROW EXECUTE FUNCTION bag.reject_audit_mutation();

INSERT INTO bag.schema_migrations(version)
VALUES (1)
ON CONFLICT (version) DO NOTHING;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    GRANT USAGE ON SCHEMA bag TO business_ai_app;
    GRANT SELECT ON bag.schema_migrations, bag.sources, bag.access_grants TO business_ai_app;
    GRANT SELECT, INSERT ON bag.audit_events TO business_ai_app;
    REVOKE INSERT, UPDATE, DELETE ON bag.sources, bag.access_grants FROM business_ai_app;
    REVOKE UPDATE, DELETE ON bag.audit_events FROM business_ai_app;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT USAGE ON SCHEMA bag TO business_ai_admin;
    GRANT SELECT, INSERT, UPDATE ON bag.sources, bag.access_grants TO business_ai_admin;
    GRANT SELECT ON bag.audit_events, bag.schema_migrations TO business_ai_admin;
    REVOKE UPDATE, DELETE ON bag.audit_events FROM business_ai_admin;
  END IF;
END;
$$;

COMMIT;
