# SC08 duplicate-counterparty detection contract

Status: FROZEN for the SC08 sprint at the commit that introduces this file. Detection semantics
(sections 1-12) must not change without a new amendment (A3) approved by GPT-PM. Tests may add
assertions; they may not weaken a rule. The commit hash of this file is quoted in the sprint plan.

Authority: operator rebaseline of 2026-10-07 (explicit answer "implement" for SC08
`duplicate-counterparty`), recorded in `docs/SCOPE_FREEZE_BASELINE_2026-10-06.md` (rebaseline entry written with this file) and in
Amendment A2 of `docs/E2E_ACCEPTANCE_CONTRACT.md` (written in this sprint, effective only on GPT-PM
approval). Scope: one read-only MCP tool. Nothing here is native 1C
reconciliation, a merge capability or production evidence.

Scenario (unchanged, `testbed/scenarios/accounting_scenarios.json`): "Potential duplicate
counterparties can be identified without merge"; expected class `anomaly`; checks
`candidate_count == 2` and `merge_count == 0`; `native_reconciliation` NOT_RUN.

## 1. Tool

Name `counterparty_duplicate_candidates`; concept `counterparty.duplicate_candidates`; permission
`accounting.read` (existing key, no migration). Input is exactly `source_id: str`, `company_id: str`,
`top: int = 2000`. A non-UUID `company_id` is audited `denied` with `INVALID_COMPANY_ID` and raises
`ValueError`; `top < 1` raises `ValueError`. `row_limit = min(top, settings.max_rows, 2000)`. No input
can influence a write, a merge or the matching rule.

## 2. Catalog fields that participate

Entity `Catalog_Counterparties`, fields `Ref_Key` (GUID string, identity), `Code` (string, echoed only,
may be empty) and `Description` (string, the ONLY matching field). Nothing else is read or matched
(no tax id: the catalog has none; Fake1C `METADATA` and its pinned fingerprint stay unchanged).

## 3. Normalisation pipeline `normalized_name_v1` (exact, in this order)

1. `unicodedata.normalize("NFKC", value)`.
2. `str.casefold()`.
3. Replace every maximal run of characters matching the Unicode regex `[\W_]+` with a single space.
4. Strip leading and trailing whitespace.
5. An empty result means the counterparty is excluded from matching (not an error, not a candidate).

Legal-form tokens (LLC, OOO, Ltd, ...) are NOT stripped in v1. A `Description` that is not a string,
or a row without `Ref_Key`/`Code`/`Description` keys, makes the scan INCONCLUSIVE
`COUNTERPARTY_FACT_INVALID`. An empty-string `Description` or `Code` is a valid value.

## 4. Candidate key and group rule

The candidate key is the normalised name. A group is the set of counterparties sharing one key and
containing at least TWO distinct `Ref_Key` values (compared case-insensitively as GUIDs). Two catalog
rows with the same `Ref_Key` are a data fault: INCONCLUSIVE `COUNTERPARTY_FACT_INVALID`, never a
"duplicate pair". A counterparty cannot be a member twice and cannot pair with itself. A counterparty
belongs to exactly one group (its key).

## 5. Determinism

Members are sorted by lower-cased `Ref_Key`; groups are sorted by `match_key`. `group_id` is
`dup-` + the first 16 hex digits of `sha256("normalized_name_v1\0" + match_key)`. The result is
independent of upstream row order and of duplicated upstream activity rows.

## 6. Bounded two-phase company scoping

The catalog has no company dimension, so scope comes from activity, activity first:

1. Read `AccumulationRegister_SettlementItems` with the company filter of the validated mapping,
   selecting `Counterparty_Key` and the company field, deterministic `$orderby`, `top = row_limit`.
2. Collect the set of non-empty counterparty GUIDs. A null/empty/all-zero `Counterparty_Key` means "no
   counterparty" and is ignored; any other malformed value is `COUNTERPARTY_FACT_INVALID`. A row whose
   company field differs from the requested company is `COMPANY_SCOPE_MISMATCH`.
3. Only if step 1 was not truncated: read `Catalog_Counterparties` (`Ref_Key`, `Code`, `Description`,
   `$orderby Ref_Key asc`, `top = row_limit`).
4. Candidates are the catalog rows whose `Ref_Key` is in the activity set; catalog rows without company
   activity are never returned and never counted. Each read is issued at most once (no paging).

## 7. Truncation

A read is truncated when `len(rows) >= row_limit` (exactly at the limit counts) or the read page
reports `truncated`. A truncated activity read stops the scan before any catalog read. Any truncation
returns status `INCONCLUSIVE`, reason `COUNTERPARTY_ROWS_TRUNCATED`, `groups: []`,
`candidate_count: 0`, `truncated: true`, audited outcome `error`; a partial FINDING is never returned.

## 8. Status semantics

`PASS` (reason `NO_DUPLICATE_CANDIDATES`): complete scan, zero groups, `groups: []`,
`candidate_count: 0`, `group_count: 0`. `FINDING` (reason `DUPLICATE_CANDIDATES_FOUND`): at least one
group. `INCONCLUSIVE`: one of `COUNTERPARTY_ROWS_TRUNCATED`, `SOURCE_RESPONSE_INVALID` (a read result
was not a list), `COUNTERPARTY_FACT_INVALID`, `COMPANY_SCOPE_MISMATCH`; each is audited as `error`.

## 9. Public result schema

`source_id`, `company_id`, `concept`, `profile_fingerprint`, `metadata_fingerprint`, `status`,
`reason`, `match_rule` (`normalized_name_v1`), `candidate_count` (members across all groups),
`group_count`, `merge_count` (the literal integer 0, never computed), `groups` (each `group_id`,
`match_key`, `match_basis` = `NORMALIZED_NAME`, `members` = list of `counterparty_id`, `code`, `name`),
`truncated`, `native_approval_inferred` (false), `human_review_required` (true) and the profile
provenance block last (`profile_kind=SYNTHETIC_FIXTURE`, `evidence_level=L1`,
`native_reconciliation=NOT_RUN`, `warnings` for the fixture profile). The payload carries no other
evidence-level key. Seed expectation for company one: one group of exactly the two "Synthetic customer"
counterparties, `candidate_count == 2`, `group_count == 1`, `merge_count == 0`.

## 10. Privacy

Names and codes appear only in the response to a caller already authorised for the source/company and
`accounting.read`. They never appear in audit rows, logs, metrics or evidence artifacts. The audit
query holds only `company_id`, `concept` and `top`; the completion row uses `detail_code`
`SYNTHETIC_FIXTURE_PROFILE` (or `<marker>:<reason>` for an INCONCLUSIVE outcome),
`returned_items = group_count`.

## 11. Profile validator requirements

The mapping is `{entity_set: "Catalog_Counterparties", output_fields: {counterparty_ref: "Ref_Key",
code: "Code", name: "Description"}, company_activity: {entity_set:
"AccumulationRegister_SettlementItems", counterparty_field: "Counterparty_Key", company_scope: {field,
value_type: "guid"}}, match_rule: "normalized_name_v1", required_register_capabilities: []}`. Unknown
keys, a non-`Catalog_` entity in the catalog slot, a non-register activity entity, duplicate output
field names and a non-empty `required_register_capabilities` are rejected. A DB profile for the
concept always wins over the code-level fixture profile; the fixture profile exists only when
`BAG_ENVIRONMENT=test`, is hash-pinned and is refused in production, where the tool fails closed with
`SEMANTIC_PROFILE_UNVALIDATED`. A DB-validated profile needs the existing native evidence (at least ten
native PASS cases); the fixture profile is never validated and never native evidence.

## 12. Mutation matrix (each rule must fail a test when broken independently)

Case, whitespace, Unicode (NFKC compatibility characters) and punctuation/underscore variants of one
name group together; different names do not; blank and punctuation-only names are excluded; the same
`Ref_Key` twice is `COUNTERPARTY_FACT_INVALID`; two- and three-member groups; a catalog counterparty
without company activity is not returned; company two does not see company one's pair; null-counterparty
activity rows are ignored; activity truncation stops before the catalog read; catalog truncation is
INCONCLUSIVE with no partial FINDING; shuffled input and duplicated activity rows give the identical
result; `group_id` is stable; `merge_count` is 0 in every branch; no write verb reaches Fake1C or the
sidecar; no counterparty name appears in audit rows or the gateway log; production/no-profile fails
closed with zero upstream reads; `accounting.read` denial is audited with zero upstream reads. An
implementation that normalises or groups differently from sections 3-6 must fail at least one of
these tests.
