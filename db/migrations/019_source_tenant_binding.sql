BEGIN;

SET LOCAL lock_timeout = '5s';

-- A source-to-tenant binding is explicit control-plane data. Existing sources stay
-- unbound until a global administrator assigns the tenant through the audited API.
ALTER TABLE bag.sources
  ADD COLUMN tenant_id text;

ALTER TABLE bag.sources
  ADD CONSTRAINT sources_tenant_id_nonblank_check
  CHECK (tenant_id IS NULL OR (tenant_id <> '' AND tenant_id = btrim(tenant_id)))
  NOT VALID;

ALTER TABLE bag.sources
  VALIDATE CONSTRAINT sources_tenant_id_nonblank_check;

CREATE OR REPLACE FUNCTION bag.reject_source_tenant_reassignment()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, bag
AS $$
BEGIN
  IF OLD.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
    RAISE EXCEPTION 'source tenant binding is immutable';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION bag.reject_source_tenant_reassignment() FROM PUBLIC;

CREATE TRIGGER sources_tenant_binding_immutable
BEFORE UPDATE OF tenant_id ON bag.sources
FOR EACH ROW EXECUTE FUNCTION bag.reject_source_tenant_reassignment();

COMMIT;
