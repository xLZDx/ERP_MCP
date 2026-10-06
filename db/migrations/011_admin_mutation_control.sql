ALTER TABLE bag.sources
  ADD COLUMN IF NOT EXISTS row_version bigint NOT NULL DEFAULT 1 CHECK (row_version > 0);

ALTER TABLE bag.companies
  ADD COLUMN IF NOT EXISTS row_version bigint NOT NULL DEFAULT 1 CHECK (row_version > 0);

ALTER TABLE bag.access_grants
  ADD COLUMN IF NOT EXISTS created_by_subject text,
  ADD COLUMN IF NOT EXISTS created_by_client text,
  ADD COLUMN IF NOT EXISTS create_reason text,
  ADD COLUMN IF NOT EXISTS revoked_by_subject text,
  ADD COLUMN IF NOT EXISTS revoke_reason text,
  ADD COLUMN IF NOT EXISTS row_version bigint NOT NULL DEFAULT 1 CHECK (row_version > 0),
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS bag.admin_audit_events (
    event_id uuid PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    request_id uuid NOT NULL,
    actor_subject text NOT NULL,
    actor_client_id text NOT NULL,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id text,
    source_id text,
    company_id uuid,
    reason text,
    idempotency_key text,
    policy_version text,
    before_fingerprint text,
    after_fingerprint text,
    safe_change_json jsonb NOT NULL DEFAULT '{}'::jsonb
      CHECK (jsonb_typeof(safe_change_json) = 'object'),
    outcome text NOT NULL CHECK (outcome IN ('success','error','denied','conflict')),
    detail_code text
);

CREATE INDEX IF NOT EXISTS admin_audit_time_idx
ON bag.admin_audit_events(occurred_at DESC);

CREATE INDEX IF NOT EXISTS admin_audit_actor_time_idx
ON bag.admin_audit_events(actor_subject, occurred_at DESC);

CREATE INDEX IF NOT EXISTS admin_audit_source_time_idx
ON bag.admin_audit_events(source_id, occurred_at DESC)
WHERE source_id IS NOT NULL;

CREATE OR REPLACE FUNCTION bag.reject_admin_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'bag.admin_audit_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS admin_audit_events_no_update_delete ON bag.admin_audit_events;
CREATE TRIGGER admin_audit_events_no_update_delete
BEFORE UPDATE OR DELETE ON bag.admin_audit_events
FOR EACH ROW EXECUTE FUNCTION bag.reject_admin_audit_mutation();

CREATE TABLE IF NOT EXISTS bag.admin_idempotency (
    actor_subject text NOT NULL,
    idempotency_key text NOT NULL,
    command_name text NOT NULL,
    request_fingerprint text NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('pending','success','error')),
    result_json jsonb,
    detail_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '24 hours'),
    PRIMARY KEY(actor_subject, idempotency_key)
);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_control_api') THEN
    GRANT USAGE ON SCHEMA bag TO business_ai_control_api;
    GRANT SELECT ON
      bag.schema_migrations,
      bag.sources,
      bag.companies,
      bag.access_grants,
      bag.source_capabilities,
      bag.semantic_profiles,
      bag.semantic_mappings,
      bag.semantic_profile_events,
      bag.audit_events,
      bag.platform_role_bindings,
      bag.admin_audit_events,
      bag.admin_idempotency
      TO business_ai_control_api;

    GRANT INSERT, UPDATE ON
      bag.sources,
      bag.companies,
      bag.access_grants,
      bag.platform_role_bindings,
      bag.semantic_profiles,
      bag.semantic_mappings
      TO business_ai_control_api;

    GRANT UPDATE (drift_status, drift_acknowledged_at)
      ON bag.source_capabilities TO business_ai_control_api;

    GRANT INSERT ON bag.semantic_profile_events, bag.admin_audit_events
      TO business_ai_control_api;

    GRANT INSERT, UPDATE ON bag.admin_idempotency
      TO business_ai_control_api;

    REVOKE DELETE ON ALL TABLES IN SCHEMA bag FROM business_ai_control_api;
    REVOKE UPDATE, DELETE ON bag.audit_events, bag.admin_audit_events, bag.semantic_profile_events
      FROM business_ai_control_api;
  END IF;
END;
$$;

