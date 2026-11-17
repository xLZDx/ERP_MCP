# FIN-S2.1 change record — CSRF token validation import

Date: 2026-11-15
Task: FIN-S2.1 — Put approval decisions in the S16 core

## Finding

Manual source review of `src/erp_mcp_s16/core.py` found that `S16Core.decide()` calls
`re.fullmatch()` to validate the CSRF token, but the module did not import `re`. A decision
request reaching that condition could raise `NameError` instead of returning the documented
fail-closed result.

## Decision

Add only the missing standard-library import. Keep the existing exact 64-character lowercase
hexadecimal token contract unchanged. Do not weaken validation or add a fallback that accepts
unvalidated tokens.

## Verification and limits

This is a source correction based on direct inspection. Tests and checks were not run because
the operator's rule 4 prohibits pytest and automatic checks. FIN-S2.1 remains unaccepted until
the focused regression suite and required sprint evidence can be executed under the governing
rules.
