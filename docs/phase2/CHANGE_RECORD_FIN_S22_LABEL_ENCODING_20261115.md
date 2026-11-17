# FIN-S2.2 change record — validate approver label encoding

Date: 2026-11-15
Task: FIN-S2.2 — Implement the protected approval page and session boundary

## Finding

Manual source review found that the service-provided approver label was checked for type,
length, and control characters, but not for strict UTF-8 encodability. A lone surrogate could
survive HTML escaping and make the final response encoding raise instead of returning a safe
refusal.

## Decision

Reuse the page's existing strict boundary-text validator for the approver label before HTML
rendering. Invalid encoding, forbidden control characters, or an invalid label shape makes the
current context unavailable and prevents a success page. Valid labels and canonical preview
bytes remain unchanged.

## Verification and limits

This is source-level evidence only. Tests and checks were not run because operator rule 4
prohibits pytest and automatic checks. The named regression must be added by the test role and
remains `NOT_RUN`; FIN-S2.2 remains unaccepted until the verification gate is available.
