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
   For `inventory.movements`, the exact register record EntitySet must exist in this source's live
   metadata. The confirmed mapping specifies company dimension, period/item/warehouse/quantity/
   record-type/recorder fields, source IANA timezone, exact source-specific receipt/expense values,
   and `quantity_encoding: positive_magnitude_by_record_type`. Caller timestamps must include an
   offset and are converted into the mapped source timezone before building the bounded GET filter.
   Unknown record types or negative magnitudes fail closed; a preset candidate never selects the
   EntitySet, field names, timezone or direction values automatically.
   For `accounting.posting_rows`, configure one exact live `AccountingRegister_*` record EntitySet,
   company dimension, IANA source timezone and reviewed projection of period,
   recorder, line number, active state and debit/credit account references. These values are never
   inferred from upstream examples; no virtual-table operation is claimed.
   For `cash.movements`, configure one exact source-confirmed accumulation/accounting-register
   record EntitySet, company dimension, period/line/cash-account/currency/amount/record-type/recorder
   projection, source IANA timezone and exact receipt/expense literals. `amount_encoding` must be
   `positive_magnitude_by_record_type`; no preset name, field, sign or currency interpretation is
   inferred. The exact EntitySet and every selected/company property are rechecked against live
   metadata before GET.
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
- `inventory_movements` reads register rows through the existing pinned OData adapter, applies the
  validated company/time filter, and normalizes receipt/expense to signed quantity deltas. This is
  a data-plane slice, not native-report reconciliation. Cash movement, AR/AP aging and tax/VAT
  remain unavailable without their own source/company semantics.
- `accounting_posting_rows` reads only profile-selected fields from an exact accounting register via
  the existing read-only adapter. Both its EntitySet and all selected/company fields must exist in
  live metadata. It is a bounded company/time listing, not a complete posting trace, accounting
  report or native reconciliation; amount/resource semantics remain unavailable until separately
  mapped and validated for that source/company.
- `cash_movements` reads profile-mapped register rows through the existing pinned OData adapter and
  normalizes only operator-confirmed receipt/expense literals into signed amount deltas. The exact
  selected fields and company scope must be present in live metadata. It does not convert currencies
  or claim cash-flow-report reconciliation; upstream presets provide no universal cash register.

## Synthetic fixture profiles and open-item aging (2026-10-07)

- `receivable_aging` / `payable_aging` read a profile-confirmed settlement record set (concepts `receivable.open_items` / `payable.open_items`: charge and payment rows with due date and settled-document reference, reviewed currency and `opening_items_known`). The collector builds a `SettlementObservation` and reuses `settlement_aging.evaluate_aging`; truncation, unconfirmed opening items, scope mismatch or invalid facts are `INCONCLUSIVE`, a missing profile is denied (`SEMANTIC_PROFILE_UNVALIDATED`). Responses add per-counterparty `summary` (charged, applied, open, unapplied credit).
- A test-only reviewed synthetic fixture profile (`BAG_ENVIRONMENT=test`, `BAG_SYNTHETIC_FIXTURE_PROFILES_FILE` + `_SHA256`, source tag `synthetic-fixture`) lets the Fake1C testbed answer these tools. Responses are labelled `profile_kind=SYNTHETIC_FIXTURE`, `evidence_level=L1`, `native_reconciliation=NOT_RUN` with warning `SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE`; it is never a `bag.semantic_profiles` row, never satisfies the ten-native-reports rule and is hard-denied in production. Regenerate/re-pin with `scripts/synthetic_fixture_profiles.py --write`.

## Duplicate counterparty candidates (SC08, 2026-10-07)

- `counterparty_duplicate_candidates` (input `source_id`, `company_id`, `top`; permission `accounting.read`) reads concept `counterparty.duplicate_candidates`. Its mapping shape is `{entity_set: "Catalog_Counterparties", output_fields: {counterparty_ref: "Ref_Key", code: "Code", name: "Description"}, company_activity: {entity_set: "AccumulationRegister_SettlementItems", counterparty_field: "Counterparty_Key", company_scope: {field, value_type: "guid"}}, match_rule: "normalized_name_v1", required_register_capabilities: []}`.
- The tool is read-only and never merges (`merge_count` is always 0). The fixture profile exists only under `BAG_ENVIRONMENT=test`, is never validated and is never native evidence; responses carry `profile_kind=SYNTHETIC_FIXTURE`, `evidence_level=L1`, `native_reconciliation=NOT_RUN`. In production the tool fails closed with `SEMANTIC_PROFILE_UNVALIDATED` until an operator validates a DB profile (the existing rule of at least ten native PASS cases applies).
- Detection semantics (normalisation, grouping, company scoping, truncation, result schema) are frozen in [SC08_DUPLICATE_COUNTERPARTY_CONTRACT.md](SC08_DUPLICATE_COUNTERPARTY_CONTRACT.md).

## Machine two-source reconciled profiles (test lane only)

A profile may be validated from ten labelled **machine two-source reconciliation** cases instead of ten human native
1C UI reports, under these limits (operator decision 2026-10-08, Rosetta plan 198889, ADR-0008 section 8):

- Evidence class `MACHINE_TWO_SOURCE_RECONCILIATION`, comparison kind `cross_copy_comparison`. It is a comparison of
  two independent machine runs (a hand-written 1C query through COM on a disposable clone, and the production tool
  `accounting_balance_by_analytics`). It is never parity proof and never native evidence.
- Only the test environment, only sources listed in `BAG_MACHINE_RECONCILED_SOURCES`, only the concept
  `account.balance_by_analytics`, only account 521.1, only a company-specific profile with exactly one confirmed mapping.
  Production refuses the setting at startup.
- Only `scripts/semantic_profiles.py validate` accepts machine evidence (with `--artifacts-root` and `--plans-dir`). It
  re-reads the private artifacts (digest, embedded run id and method, exact decimal equality per row key, no truncation,
  no empty result) and checks that the cited approved Rosetta plan names the authorization scope hash. The Admin API
  validate path refuses machine and mixed evidence.
- Every other consumer of `status = 'VALIDATED'` (company scope mappings, access explanation, the other tools) accepts
  native evidence only. The basis is recomputed from the stored cases and contradictions are refused.
- Responses carry `profile_kind = VALIDATED_MACHINE_RECONCILED`, `evidence_level = PROFILE_VALIDATED_MACHINE`,
  `native_reconciliation = MACHINE_TWO_SOURCE` and the warning `MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT`.

The capability fingerprint a profile is bound to ignores the probe stamp `discovered_at`; it records when the source
was probed, not what it supports, and including it made every profile stale after the next probe of a live source.
