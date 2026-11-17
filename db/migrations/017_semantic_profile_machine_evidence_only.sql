-- Native report evidence has no trusted immutable-artifact verifier yet. Do not allow a row
-- to become VALIDATED unless the evidence came through the separately verified machine path.
-- NOT VALID avoids scanning existing rows, while PostgreSQL enforces the rule on new/updated rows.
ALTER TABLE bag.semantic_profiles
  ADD CONSTRAINT semantic_profiles_validation_machine_evidence_only
  CHECK (
    status <> 'VALIDATED'
    OR validation_evidence_json->>'evidence_basis' IS NOT DISTINCT FROM 'MACHINE'
  ) NOT VALID;

