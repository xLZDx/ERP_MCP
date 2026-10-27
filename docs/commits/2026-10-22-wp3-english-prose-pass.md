# Change record: Translate reviewed WP3 prose

## Change

- Translated the configuration-family description in `docs/COMPATIBILITY.md` into English.
- Kept the `native_query.read` grammar restriction in `docs/INTEGRATION.md` explicit: SELECT-equivalent query syntax only.
- Retained the Latin configuration identifiers BP, UT, ZUP, and KA alongside their English family names in `docs/COMPATIBILITY.md` for traceability.
- Corrected the inherited WP3 backlog's paired Russian HTML report count from seven to eight, using the 2026-10-21 inventory note.
- Recorded this limited pass and the reviewed literal 1C exceptions in `docs/BACKLOG_INHERITED_2026-10-21.md`.

## Why

The English-policy inventory classifies these paths as prose candidates, but its classification is explicitly path-based. A line-level review found that other Cyrillic matches in the reviewed small documents were literal 1C method, query, configuration, or report identifiers and should remain exact. The inventory also records eight tracked Russian HTML reports outside its scanned extension set; the inherited backlog still said seven.

## Contracts and paths

- The changes affect documentation only; no query code, report values, test data, or 1C identifiers changed.
- `docs/ADAPTER_INTAKE_PLAN.md` and `docs/NATIVE_REPORT_CAPTURE_RUNBOOK.md` were inspected only at their Cyrillic lines; their literal identifiers remain unchanged.
- `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md` was reviewed as a bounded technical contract; its remaining Cyrillic token is the literal 1C document type `ПоступлениеТоваровУслуг` and was preserved.
- `docs/SEMANTIC_PROFILES.md`, `docs/adr/ADR-0008-hybrid-odata-com-analytics-balance.md`, `docs/phase2/S11_OPERATION_RULES_AND_STORY_REGISTER_2026-10-12.md`, `docs/runbooks/COM_BRIDGE_AND_PARITY.md`, and `core/DECISION_LOG.md` were excluded from further content review after inspection showed real-source, clone-measurement, or source-derived examples. No business values are copied into this record. Further edits require sanitized copies or a value-safe review method.
- The 2026-10-20 inventory counts remain historical baseline counts and were not regenerated.

## Decisions

- Preserve literal 1C identifiers even when they contain Cyrillic; translate surrounding prose instead.
- Preserve the SELECT-equivalent syntax restriction for `native_query.read`; wording must not broaden the accepted query grammar.
- Preserve Russian localized reports and semantic/test data under their documented exception candidates; do not delete them.
- Continue WP3 only on pre-screened documentation that can be reviewed without exposing real-source evidence.
- Record unsafe content-selection incidents in `core/LESSONS_LOG.md`; do not repeat source values in follow-up artifacts.
- Following the additional runbook-selection incident, keep that path excluded and do not copy its source-derived contents into project records.
- Following the decision-log scan incident, keep `core/DECISION_LOG.md` excluded from further content scans; use only sanitized or independently value-safe summaries.
- During the coding phase, do not run tests/checks or regenerate customer evidence. Staging deployment remains forbidden; explicit-path Git staging and local commits are authorized by the operator's 2026-10-22 clarification and require exact-patch GPT-PM review per commit.

## Verification state

- Manually reviewed the two translated sentences and the identified literal 1C lines in the listed documents.
- A read-only code-reviewer pass found one MAJOR ambiguity in the `native_query.read` syntax restriction and one traceability concern for configuration abbreviations. Both were corrected; the reviewer rechecked those exact findings and reported no remaining finding in scope.
- The inherited inventory states that eight paired Russian HTML reports were tracked as of 2026-10-21.
- No Cyrillic scanner, tests, checks, builds, CI, database commands, migrations, remote calls, staging, or commit were run for this pass.
