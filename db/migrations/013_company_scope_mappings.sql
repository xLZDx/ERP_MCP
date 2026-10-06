CREATE TABLE IF NOT EXISTS bag.company_scope_mappings (
    scope_mapping_id uuid PRIMARY KEY,
    profile_id uuid NOT NULL REFERENCES bag.semantic_profiles(profile_id) ON DELETE RESTRICT,
    entity_set text NOT NULL,
    company_property text NOT NULL,
    literal_kind text NOT NULL CHECK (literal_kind IN ('guid','string')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(profile_id, entity_set)
);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT SELECT, INSERT, UPDATE ON bag.company_scope_mappings TO business_ai_admin;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_control_api') THEN
    GRANT SELECT, INSERT, UPDATE ON bag.company_scope_mappings TO business_ai_control_api;
  END IF;
END;
$$;
