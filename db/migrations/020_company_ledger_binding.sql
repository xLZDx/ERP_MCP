BEGIN;

SET LOCAL lock_timeout = '5s';

-- Admin company UUIDs and change-ledger company keys are separate identities.
-- Existing companies remain unbound until a global administrator assigns one.
ALTER TABLE bag.companies
  ADD COLUMN ledger_company_id text;

ALTER TABLE bag.companies
  ADD CONSTRAINT companies_ledger_company_id_nonblank_check
  CHECK (ledger_company_id IS NULL OR
         (ledger_company_id <> '' AND ledger_company_id = btrim(ledger_company_id)))
  NOT VALID;

ALTER TABLE bag.companies
  VALIDATE CONSTRAINT companies_ledger_company_id_nonblank_check;

CREATE OR REPLACE FUNCTION bag.reject_ledger_company_reassignment()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, bag
AS $$
BEGIN
  IF OLD.ledger_company_id IS NOT NULL
     AND NEW.ledger_company_id IS DISTINCT FROM OLD.ledger_company_id THEN
    RAISE EXCEPTION 'ledger company binding is immutable';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION bag.reject_ledger_company_reassignment() FROM PUBLIC;

CREATE TRIGGER companies_ledger_binding_immutable
BEFORE UPDATE OF ledger_company_id ON bag.companies
FOR EACH ROW EXECUTE FUNCTION bag.reject_ledger_company_reassignment();

COMMIT;
