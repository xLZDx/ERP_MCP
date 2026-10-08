# ERP_MCP Phase 2 — combined client-safety hardening acceptance

Date: 2026-10-09. Branch: `hardening/phase2-client-safety-combined-20261009`. Origin base: `a00d16a077848ca2ebd092e5b99cda90e7350132`. **Release status NO-GO; integration accepted locally only.**

## What was integrated

1. `5a63da8` — P-M1 attestation preflight: reject stale revision/reference and spoofed decision/digest/trust before write-port. Evidence: `docs/phase2/PROMOTION_PM1_HARDENING_REVIEW_2026-10-09.md`.
2. `96d9f7a` (from `4c74af8`) — reject float, infinity, bool and noninteger backend capacity limits.
3. `67f32e1` (from `406a8bd`) — fixed EVALUATION_ONLY/OBSERVED_ONLY trust levels on offline comparison/diff results.
4. `072900d` (from `875bcc9`) — customer-safe readiness snapshot.
5. `4c92d1b` (from `b24dc70`) — fixed OBSERVED_ONLY metadata observation trust label.

This branch does **not** merge or overwrite working-tree edits in `D:\Repo\ERP_MCP-phase2` (parallel `connector_sdk.py`, `drift.py`). Other safety-review branch `af2f36a` remains a historical reproducibility report, not part of this integration chain.

## Exact candidate verification (local)

- `pytest -q tests/phase2`: **760 passed, 180 skipped, 0 failed** in 12.66 seconds.
- `ruff check src/business_ai_gateway/phase2 tests/phase2`: **PASS**.
- `compileall -q src/business_ai_gateway/phase2 tests/phase2`: **PASS**.
- Cherry-pick step reported zero conflicts; `git diff --check` was green on source changes.
- Earlier RED reproduction evidence remains preserved in the respective review documents. Successful isolated test runs are not post-deployment evidence.

## Threat-boundary review

- **Security:** rejected comparisons/metadata/promotion views cannot ordinarily claim native approval by changing public labels. Spoofed `APPROVE`, digest and reviewer flags now fail closed in P-M1. SQL retains independent enforcement obligations.
- **Functional:** positive promotion/rollback and normal metadata/ledger test paths still pass; absence of 1C/Drive access is not replaced with mocks in acceptance.
- **Reliability:** per-backend integer ceilings are correctly validated but remain single-process; distributed throttling/canary/load/fault testing still required.
- **Privacy and authority:** no 1C write API, production credentials, unbounded raw evidence, or elevated production permissions are introduced.
- **Devil's advocate:** fake port results cannot prove deployed Postgres RLS, independent attestor identity, OAuth/source ACL revocation, or native accountant equivalence. Neither `MATCH` nor `PROMOTED` in a unit test is a customer accounting PASS.

## Open completion gates

- G0: scope and donor-license/source-registry decision.
- G1: exact-HEAD PostgreSQL integration/negative tests, capacity/recovery and independent exit approval.
- G2–G4: live read-only 1C + independently attested native reports + ERP-owned Drive OAuth consent.
- G5–G7: admin/UAT, controlled deployment and rollback, owner-signed release decision.
- Exact candidate hosted CI/R1 compatibility and final governance review: NOT_RUN on this combined HEAD.
- **No push, PR, merge to main, production cutover or client-facing promise of completed automation until separate exact-head approvals and real evidence.**

**Local engineering terminal condition:** patches implemented, reviewed and individually/in combination green; clean isolated branch. **Program terminal condition:** not met, because external acceptance and deployment gates remain.

## Further safety patch on this combined branch — SCH-01

Strict scheduler lease/backoff/poison policy numeric validation added after the initial combination. Tests reproduced 10 invalid-number acceptance failures and 6 huge-number/timedelta-overflow failures before mitigation. New final local result after this source change: **778 passed / 180 skipped**, Ruff PASS, compileall PASS. Earlier **760 PASS / 180 SKIP** remains accurate for the prior HEAD only. Full details: `SCHEDULER_DRIFT_CLIENT_SAFETY_REVIEW_2026-10-09.md`.

**DR-01 remains OPEN:** accepted vs observed hash semantics in `drift.classify` require the architecture/acceptance authority to decide; no silent change to a preexisting test contract. This is an additional reason Release 2 stays NO-GO.

## DR-01 — observed versus accepted model (engineering closed)

The offline drift classifier no longer changes the accepted hash on a complete scan, and its first observation cannot self-approve. Added explicit observed candidate hash; four RED test cases passed after correction. Local suite after code change: **780 PASS / 180 SKIP**, Ruff PASS. See `DRIFT_ACCEPTANCE_BOUNDARY_REVIEW_2026-10-09.md`. Live integration and independent acceptance remain NOT_RUN; do not infer a production-ready living model.
