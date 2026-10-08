# Phase 2 — anti-promotion guard on reference results

**Scope:** isolated branch `hardening/phase2-budget-validation`, parent change `4c74af8`; Phase 2 reference classes only. **Production NO-GO unchanged.**

## Finding and remedy

The frozen dataclasses `Comparison`, `PurchaseComparison`, `ObservedDiff` and `ObservedMetadata` exposed overridable public trust/authority labels. A local caller could construct a `MATCH` comparison with `authority='NATIVE_PASS'` or a structural diff with `trust_level='VALIDATED'` without possessing an independent report or approval. This does not prove a current external injection route, but violates the invariant that these helpers only yield evaluation/observation evidence. `__post_init__` now rejects any value other than `EVALUATION_ONLY` / `OBSERVED_ONLY`.

## Reproduction, verification and adversarial review

- Before patch: nine negative tests **RED**; all were able to construct escalated-label objects.
- After initial patch: 342 passed, 65 skipped; after adversarial spoof-object tests and final fix: **345 passed, 65 skipped** in 10.66 seconds. A further metadata-observation guard added four tests; latest complete suite: **349 passed, 65 skipped** in 7.11 seconds. PostgreSQL integration tests are not run on this new head.
- Ruff on Phase 2 source and tests: **PASS** (final log `var/phase2-final-ruff.log`); exact-head release CI, live connectors and production runtime checks are **NOT_RUN**.
- Security review: nine wrong-string labels failed RED before patch. Three more RED tests showed that custom objects with forged equality could defeat a simple string comparison. Final constructors enforce `type(label) is str` and exact fixed value; all 12 initial dedicated tests PASS. Three additional RED tests reproduced false trust labels on 1C `ObservedMetadata`, including forged equality, and one positive test preserves `OBSERVED_ONLY`: **16 targeted cases PASS**. Construction and `dataclasses.replace` call `__post_init__`. This is not a signed attestation and does not make the object cryptographically authentic.
- Architecture review: no network, DB, authorization grant, evidence workflow or automatic model promotion was added. The comparator verdict remains `EVALUATION_ONLY` even when arithmetic matches.
- Test review: no production or integration skips were reclassified as PASS. Existing positive comparison tests remain green.

## Residual release gates

Independent native 1C evidence and accountant attestation, external Drive OAuth consent, real target IdP, end-to-end connectors, user/admin acceptance and production authorization are still required. This guard is a supporting code slice, not completion of G0-G7 or S0-S10.
