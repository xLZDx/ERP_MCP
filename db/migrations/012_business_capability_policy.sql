CREATE TABLE IF NOT EXISTS bag.business_roles (
    role_id text PRIMARY KEY,
    display_name text NOT NULL,
    description text NOT NULL,
    built_in boolean NOT NULL DEFAULT true,
    enabled boolean NOT NULL DEFAULT true,
    policy_version text NOT NULL DEFAULT 'rbac-v1',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bag.business_role_capabilities (
    role_id text NOT NULL REFERENCES bag.business_roles(role_id) ON DELETE RESTRICT,
    capability_key text NOT NULL,
    PRIMARY KEY(role_id, capability_key)
);

CREATE TABLE IF NOT EXISTS bag.business_role_assignments (
    assignment_id uuid PRIMARY KEY,
    principal_kind text NOT NULL CHECK (principal_kind IN ('subject','group')),
    principal_id text NOT NULL,
    role_id text NOT NULL REFERENCES bag.business_roles(role_id) ON DELETE RESTRICT,
    source_id text NOT NULL REFERENCES bag.sources(source_id) ON DELETE RESTRICT,
    company_id uuid,
    expires_at timestamptz,
    revoked_at timestamptz,
    created_by_subject text,
    created_by_client text,
    reason text,
    row_version bigint NOT NULL DEFAULT 1 CHECK (row_version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT business_role_assignment_company_source_fk
      FOREIGN KEY(company_id, source_id)
      REFERENCES bag.companies(company_id, source_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS business_role_assignments_active_uq
ON bag.business_role_assignments(
    principal_kind, principal_id, role_id, source_id, COALESCE(company_id::text, '')
)
WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS bag.capability_overrides (
    override_id uuid PRIMARY KEY,
    principal_kind text NOT NULL CHECK (principal_kind IN ('subject','group')),
    principal_id text NOT NULL,
    capability_key text NOT NULL,
    source_id text NOT NULL REFERENCES bag.sources(source_id) ON DELETE RESTRICT,
    company_id uuid,
    effect text NOT NULL CHECK (effect IN ('allow','deny')),
    expires_at timestamptz,
    revoked_at timestamptz,
    created_by_subject text,
    created_by_client text,
    reason text,
    row_version bigint NOT NULL DEFAULT 1 CHECK (row_version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT capability_override_company_source_fk
      FOREIGN KEY(company_id, source_id)
      REFERENCES bag.companies(company_id, source_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS capability_overrides_active_uq
ON bag.capability_overrides(
    principal_kind, principal_id, capability_key, source_id,
    COALESCE(company_id::text, ''), effect
)
WHERE revoked_at IS NULL;

INSERT INTO bag.business_roles(role_id, display_name, description, built_in, enabled)
VALUES
  ('VIEWER','Viewer','Safe accounting reads',true,true),
  ('ACCOUNTANT','Accountant','Accounting reads and review workflows',true,true),
  ('SENIOR_ACCOUNTANT','Senior Accountant','Broader accounting review capabilities',true,true),
  ('TAX_REVIEWER','Tax Reviewer','Tax review and evidence',true,true),
  ('AUDITOR_BUSINESS','Business Auditor','Read data and audit evidence',true,true),
  ('EXECUTIVE','Executive','Executive and financial summaries',true,true),
  ('PAYROLL_REVIEWER','Payroll Reviewer','Payroll review with supporting reads',true,true)
ON CONFLICT(role_id) DO NOTHING;

INSERT INTO bag.business_role_capabilities(role_id, capability_key)
VALUES
  ('VIEWER','source.status.read'),
  ('VIEWER','company.list'),
  ('VIEWER','metadata.read'),
  ('VIEWER','accounting.read'),
  ('VIEWER','sales.read'),
  ('VIEWER','purchases.read'),
  ('VIEWER','inventory.read'),
  ('ACCOUNTANT','source.status.read'),
  ('ACCOUNTANT','company.list'),
  ('ACCOUNTANT','metadata.read'),
  ('ACCOUNTANT','accounting.read'),
  ('ACCOUNTANT','ar.read'),
  ('ACCOUNTANT','ap.read'),
  ('ACCOUNTANT','sales.read'),
  ('ACCOUNTANT','purchases.read'),
  ('ACCOUNTANT','bank.read'),
  ('ACCOUNTANT','cash.read'),
  ('ACCOUNTANT','inventory.read'),
  ('ACCOUNTANT','invoice.reconcile'),
  ('ACCOUNTANT','month_close.review'),
  ('SENIOR_ACCOUNTANT','source.status.read'),
  ('SENIOR_ACCOUNTANT','company.list'),
  ('SENIOR_ACCOUNTANT','metadata.read'),
  ('SENIOR_ACCOUNTANT','accounting.read'),
  ('SENIOR_ACCOUNTANT','ar.read'),
  ('SENIOR_ACCOUNTANT','ap.read'),
  ('SENIOR_ACCOUNTANT','sales.read'),
  ('SENIOR_ACCOUNTANT','purchases.read'),
  ('SENIOR_ACCOUNTANT','bank.read'),
  ('SENIOR_ACCOUNTANT','cash.read'),
  ('SENIOR_ACCOUNTANT','inventory.read'),
  ('SENIOR_ACCOUNTANT','invoice.reconcile'),
  ('SENIOR_ACCOUNTANT','month_close.review'),
  ('SENIOR_ACCOUNTANT','financial_statements.read'),
  ('TAX_REVIEWER','company.list'),
  ('TAX_REVIEWER','metadata.read'),
  ('TAX_REVIEWER','accounting.read'),
  ('TAX_REVIEWER','tax.review'),
  ('TAX_REVIEWER','audit.evidence.read'),
  ('AUDITOR_BUSINESS','company.list'),
  ('AUDITOR_BUSINESS','metadata.read'),
  ('AUDITOR_BUSINESS','accounting.read'),
  ('AUDITOR_BUSINESS','audit.evidence.read'),
  ('EXECUTIVE','source.status.read'),
  ('EXECUTIVE','company.list'),
  ('EXECUTIVE','financial_statements.read'),
  ('EXECUTIVE','executive_summary.read'),
  ('EXECUTIVE','ar.read'),
  ('EXECUTIVE','ap.read'),
  ('EXECUTIVE','sales.read'),
  ('EXECUTIVE','purchases.read'),
  ('PAYROLL_REVIEWER','company.list'),
  ('PAYROLL_REVIEWER','metadata.read'),
  ('PAYROLL_REVIEWER','payroll.review')
ON CONFLICT(role_id, capability_key) DO NOTHING;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_app') THEN
    GRANT SELECT ON
      bag.business_roles,
      bag.business_role_capabilities,
      bag.business_role_assignments,
      bag.capability_overrides
      TO business_ai_app;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_admin') THEN
    GRANT SELECT, INSERT, UPDATE ON
      bag.business_roles,
      bag.business_role_capabilities,
      bag.business_role_assignments,
      bag.capability_overrides
      TO business_ai_admin;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'business_ai_control_api') THEN
    GRANT SELECT ON bag.business_roles, bag.business_role_capabilities
      TO business_ai_control_api;
    GRANT SELECT, INSERT, UPDATE ON
      bag.business_role_assignments,
      bag.capability_overrides
      TO business_ai_control_api;
  END IF;
END;
$$;
