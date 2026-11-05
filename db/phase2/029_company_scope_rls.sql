-- R2-US-004: a company-only grant may read rows for that company, but must not inherit
-- access to source-wide rows (which have no company_id) or tenant-wide metadata.
-- Apply only through the disposable Phase 2 migration harness or a verified target.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('029', ARRAY['003']) THEN
  EXECUTE $body$
CREATE OR REPLACE FUNCTION living.row_in_scope(t text, s text, comp text DEFAULT NULL)
RETURNS boolean LANGUAGE sql STABLE AS $fn$
 SELECT t IS NOT NULL AND s IS NOT NULL
  AND t = nullif(current_setting('living.tenant_id',true),'')
  AND s = nullif(current_setting('living.source_id',true),'')
  AND EXISTS(SELECT 1 FROM living.role_scope rs
   WHERE rs.tenant_id=t AND rs.source_id=s
    AND pg_has_role(current_user, rs.role_name::name, 'USAGE')
    AND (rs.company_id IS NULL
         OR (rs.company_id = nullif(current_setting('living.company_id',true),'')
             AND comp IS NOT NULL AND comp = rs.company_id)))
$fn$;

CREATE OR REPLACE FUNCTION living.tenant_in_scope(t text) RETURNS boolean
LANGUAGE sql STABLE AS $fn$
 SELECT t IS NOT NULL AND t = nullif(current_setting('living.tenant_id',true),'')
  AND EXISTS(SELECT 1 FROM living.role_scope rs
   WHERE rs.tenant_id=t AND rs.source_id=nullif(current_setting('living.source_id',true),'')
    AND rs.company_id IS NULL
    AND pg_has_role(current_user, rs.role_name::name, 'USAGE'))
$fn$;
  $body$;
 END IF;
END
$mig$;
COMMIT;
