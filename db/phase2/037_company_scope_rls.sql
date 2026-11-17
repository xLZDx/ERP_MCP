-- Restore company-only RLS isolation without rewriting the published base migration.
BEGIN;
DO $mig$
BEGIN
 IF living.record_migration('037', ARRAY['001','002','003','004','005','006','007','008','009','010','011','012','013','014','015','016','017','018','019','020','021','022','023','024','025','026','027','030','031','032','033','034','035','036']) THEN
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
