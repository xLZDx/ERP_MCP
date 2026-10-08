# Phase 2 — DR-01 accepted vs observed structural hash

Date 2026-10-09. Branch `hardening/phase2-client-safety-combined-20261009`. Engineering change only; Release 2 **NO-GO** remains.

## Risk and reproduction

`classify(OK_COMPLETE, accepted=A, observed=B)` previously returned `accepted_hash=B` while emitting `STRUCTURAL_DRIFT`; a caller storing the result could automatically replace an independently accepted model with an unapproved observation. A first capture with no accepted head also manufactured `accepted_hash` and `baseline_established=True`. The existing tests asserted this, despite the project policy forbidding automatic approval. Four RED cases demonstrated the contract conflict, missing candidate field, and failure handling.

## Change

`DriftDecision` now distinguishes `accepted_hash` (unchanged by classification) from `observed_hash` (candidate of a complete capture). In all failures, partial scans and missing hashes, `observed_hash=None`; accepted hash is retained. A first complete observation with no accepted head returns `accepted_hash=None`, `observed_hash=<candidate>`, `baseline_established=False`, `removal_permitted=False`. Complete changed scans emit `STRUCTURAL_DRIFT`, keep old accepted hash and return observed candidate; subsequent B observation still causes drift until a **separate** authorized accepted-head change. `removal_permitted=True` is only candidate-level classification of an existing accepted baseline and never a removal/approval command.

## Independent in-chat review

Security: no source capture alone promotes acceptance. Functional: identical accepted/observed hash stays quiet, and failure/gap/denial cannot silently replace head. Architecture: accepts external authorized CAS/attestation workflow as the only source of a new accepted baseline; no 1C, DB or Drive writes were introduced. Tests: four expected RED cases, later full isolated Phase 2 Python suite **780 PASS / 180 SKIP** with Ruff PASS before final evidence commit. Redefinition of `baseline_established` is deliberately conservative and may require adaptation by future consumers (none presently in committed Phase 2 beyond tests).

## Residual/acceptance

This is an offline pure classifier. It is not integrated into the scheduler's durable cursor, SQL `living.promote_head`, or a live metadata collector. A real source-wide capture plus independent reviewer attestation and authoritatively authorized promotion still gate acceptance. Postgres integration and production deployment NOT_RUN on this source HEAD. Release G0–G7 NO-GO.
