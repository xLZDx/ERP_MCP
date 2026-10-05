# Semantic profile and preset operations

Semantic profiles are source/company-scoped configuration. The Aprovodka BP 3.0, UT 11, ZUP 3.1,
and ERP 2 entries identify upstream preset candidates only; neither a preset ID nor Aprovodka's
upstream `verified` label proves that an object or accounting meaning exists in a customer base.

## Operator workflow

Use the operator-only CLI with `BAG_ADMIN_DATABASE_URL` in production:

1. Refresh source capabilities and acknowledge metadata drift through the established capability
   workflow.
2. Create a draft pinned to the exact source and optional company:

   ```text
   python scripts/semantic_profiles.py create --source-id BASE_ID --company-id COMPANY_UUID \
     --preset-id bp30 --profile-name "BP accounting v1" --actor OPERATOR_ID
   ```

   Omit `--company-id` only for an intentionally source-wide profile. Creation fails unless live
   metadata is supported and the source drift state is acknowledged `STABLE`.
3. Add each concept mapping from a JSON object. Mapping rows always start as `CANDIDATE`/`LOW`:

   ```text
   python scripts/semantic_profiles.py add-mapping --profile-id PROFILE_UUID \
     --concept receivable --mapping-file mapping.json --actor OPERATOR_ID
   ```

   A mapping may list exact `required_register_capabilities` as `{ "entity_set", "method" }` pairs.
   Each pair must have positive evidence for the same source and current metadata fingerprint.
   Never put raw accounting result rows, credentials, or customer documents in profile/evidence JSON.
   Mapping evidence is restricted to controlled `evidence_refs` and short `notes`; CLI JSON inputs
   are capped at 256 KB.
4. Validate only after at least ten distinct native 1C report reconciliations passed. The evidence
   file contains `native_reconciliation_cases`, each with `case_id`, `status: "PASS"`, and a
   `native_report_ref` to controlled external evidence:

   ```text
   python scripts/semantic_profiles.py validate --profile-id PROFILE_UUID \
     --evidence-file native-evidence.json --actor OPERATOR_ID
   ```

   Validation rechecks source metadata/capability fingerprints, acknowledged drift, exact scope,
   every mapping capability dependency and the ten-case evidence set. Failure leaves the profile
   unvalidated. The service stores only case IDs/report references plus an evidence-manifest hash,
   not report contents. JSON inputs are capped at 256 KB, and mapping evidence accepts only
   controlled references and short notes.
5. Retire obsolete versions with the `retire` command. Profile lifecycle actions are recorded in
   `bag.semantic_profile_events`, which is append-only.

## Runtime contract

- Only `VALIDATED` profiles are eligible; matching source, company and current metadata fingerprint
  are mandatory.
- Capability dependencies are independently checked. Missing, cross-source or stale evidence
  raises `CAPABILITY_UNSUPPORTED`; a semantic profile never bypasses the source capability gate.
- Metadata changes mark validated profiles `STALE`. A metadata-drift acknowledgement does not
  revalidate accounting semantics; reconciliation and a new profile version are required.
- Runtime DB role can read profiles/events but cannot edit them. Admin role can create/update
  profile content and append events but cannot delete profiles/events or mutate event history.
- These commands prepare a profile; they do not expose canonical accounting MCP tools. Such tools
  remain unavailable until company-filtered reads and source-specific validated mappings are wired
  end to end.
