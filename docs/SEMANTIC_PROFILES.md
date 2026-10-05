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
   metadata is supported and the source drift state is acknowledged `STABLE`. The profile JSON
   carries the pinned Aprovodka candidate entity names/confidence and their original source path;
   every entry remains `CANDIDATE_ONLY` and is not sent to OData.
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
4. Review and explicitly confirm every mapping before profile validation. Confirmation requires
   controlled evidence references, raises the mapping to `CONFIRMED`/`HIGH`, updates the profile
   fingerprint and appends a `MAPPING_CONFIRMED` lifecycle event:

   ```text
   python scripts/semantic_profiles.py confirm-mapping --profile-id PROFILE_UUID \
     --concept account.balance_and_turnovers --evidence-file mapping-review.json \
     --actor OPERATOR_ID
   ```

   For `account.balance_and_turnovers`, the mapping must specify the exact source-confirmed
   `AccountingRegister_*` EntitySet, `balanceAndTurnovers` method, a company-scope field/value type,
   and property names for all seven canonical output fields. The CLI adds the matching exact
   register capability dependency; it rejects guessed virtual-table names.
   For `sales` and `purchases`, the mapping must specify a source-confirmed `Document_*` EntitySet,
   company dimension/value type, date order field, and canonical output-field projection. Runtime
   applies only the reviewed company equality and bounded paging; callers cannot supply filters or
   entity names.
   For `inventory.balance`, the mapping must name an exact source-confirmed
   `AccumulationRegister_*` EntitySet, the `Balance` method, company dimension/value type, and
   reviewed item/warehouse/quantity field projection. The CLI pins that exact EntitySet/method as a
   live register-capability dependency. Runtime requires a timezone-qualified point-in-time period;
   it does not infer stock by summing documents or fall back to turnover queries.
   For `bank.balance`, use the same exact accumulation-register `Balance` capability and company
   scope requirements, with reviewed bank-account/currency/amount field projection. Common preset
   candidates such as `AccumulationRegister_ДенежныеСредстваБезналичные` are hints only; no account
   or amount field name is inferred from the preset.
   For `receivable.balance` and `payable.balance`, each mapping independently selects the exact
   accumulation register and projects counterparty, contract and amount. These snapshots do not
   calculate aging or infer overdue status; aging remains unavailable until a source-specific due
   date/settlement semantic mapping and native-report reconciliation are approved.
5. Validate only after at least ten distinct native 1C report reconciliations passed. The evidence
   file contains `native_reconciliation_cases`, each with `case_id`, `status: "PASS"`, and a
   `native_report_ref` to controlled external evidence:

   ```text
   python scripts/semantic_profiles.py validate --profile-id PROFILE_UUID \
     --evidence-file native-evidence.json --actor OPERATOR_ID
   ```

   Validation rechecks source metadata/capability fingerprints, acknowledged drift, exact scope,
   every mapping's explicit confirmation and capability dependency, and the ten-case evidence set. Failure leaves the profile
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
- `accounting_balance_and_turnovers` is the first profile-driven canonical MCP tool. It requires an
  exact source/company grant, a `VALIDATED` profile, a `CONFIRMED`/`HIGH` mapping, stable matching
  metadata/capability fingerprints and a current positive `balanceAndTurnovers` capability. It
  builds the company condition only from the profile's reviewed field and the registered company's
  external reference, then dispatches through the pinned OData sidecar. The result is projected to
  the seven canonical keys in `output_fields`; if any source field is missing, the call fails rather
  than silently substituting a value. Amount representations are preserved as supplied by 1C (no
  implicit currency or decimal conversion).
- The tool does not accept caller-supplied EntitySets, OData filters, or register arguments. Missing,
  unconfirmed or stale profiles/capabilities are audited and denied before register data dispatch.
  A company-specific grant cannot be widened into a source-wide read by this tool.
- `sales_documents` and `purchase_documents` use the same exact source/company and profile gates.
  Each result is projected to document reference/number/date, counterparty, amount, currency and
  posted state using the validated source mapping. OData execution remains in the existing pinned
  adapter path; callers cannot supply an EntitySet or filter.
- `inventory_balance` reuses the pinned `Balance(Period, Condition)` semantics for accumulation
  registers. It requires exact source metadata confirmation for the mapped register's `Balance`
  operation and profile-projected item reference, warehouse reference and quantity. Preset names
  remain candidate hints only; company scoping must be explicitly mapped and confirmed.
- `bank_balance` uses the same pinned point-in-time `Balance` operation with a separate confirmed
  source mapping for bank-account reference, currency reference and amount. Preset confidence does
  not authorize a register call or determine the output-field names.
- `receivable_balance` and `payable_balance` return only point-in-time counterparty/contract amounts
  from distinct validated mappings. They do not return aging buckets, overdue days or a combined
  net position.
- Other canonical accounting tools (cash/bank, inventory movements, AR/AP aging, tax/VAT and posting trace)
  remain unimplemented; no customer preset is promoted based on
  upstream names or confidence labels.
