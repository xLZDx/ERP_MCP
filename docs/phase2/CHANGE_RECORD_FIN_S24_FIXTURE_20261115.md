# FIN-S2.4 synthetic ingress fixture correction — 2026-11-15

## Scope

This change corrects only the synthetic authentication fixture in
`tests/phase2/test_s16_private_ingress.py`. It does not change ingress source,
deployment wiring, production bindings, or the authenticated runtime boundary.

## Finding and correction

The positive approver-session scenario constructed a current principal expiry
but retained `created_at` and `last_seen_at` from the fixed historical fixture.
The ingress correctly rejected that session as expired by its idle-age policy,
so the scenario failed before reaching its intended success assertion. Both
positive and malformed-approver synthetic sessions now set those timestamps
from the same current `now` used for their bounded expiry values. The malformed
case still has an empty principal identifier and remains a negative control.

## Verification and limits

The functional-test-reviewer ran:

`uv run --locked --extra dev python -m pytest tests/phase2/test_s16_private_ingress.py -q`

Exit code 0; 9 passed, 1 `httpx2` deprecation warning, 0.35 seconds. This is
focused fixture evidence only. It does not establish a live listener or prove
the production binding set; FIN-S2.4/FIN-S3.2 runtime evidence remains separate.
