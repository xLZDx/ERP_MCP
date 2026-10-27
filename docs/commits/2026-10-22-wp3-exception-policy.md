# Change record: Decide WP3 text-preservation policy

## Change

- Added a durable decision to `core/DECISION_LOG.md` to preserve localized documentation, semantic/test strings, and literal 1C identifiers during WP3 cleanup.
- Required future scanner exceptions to be exact and reviewed instead of exempting broad mixed directories from a path-only classification.
- Clarified that direct operator quotations remain verbatim for audit fidelity while surrounding prose is translated; the whole decision log is not exempted.
- Linked the decision and its still-open precise-allowlist work from `docs/BACKLOG_INHERITED_2026-10-21.md`.

## Why

The English-policy inventory labels localization, literal names, and semantic test data as exception candidates, while explicitly warning that its classification is path-based rather than line-level. A broad directory allowlist could also hide prose that should be translated.

## Contracts and paths

- Documentation/governance only; no fixture, localized document, source code, scanner, or gate was changed.
- Evidence source: `docs/commits/2026-10-20-english-policy-inventory.md`.

## Decisions

- Preserve existing semantic and localized content; do not delete or translate data values.
- Preserve short direct operator quotes verbatim, with English surrounding text and narrowly anchored future scanner exceptions.
- Do not claim an exact allowlist until it can be derived without exposing source/business data and with line-level precision.

## Verification state

- Manually reviewed the inventory's exception-category definitions and safety caveat.
- No tests, checks, builds, CI, migrations, staging, or commits were run for this decision record.
