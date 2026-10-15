# Simulation program plan: synthetic lane checkpoint

Date: 2026-10-15. Status: checkpoint for the NON-GATING prototype. Nothing here is gate evidence, and no real 1C is touched.

## 1. Decision and limits

The operator delegated simulation of unavailable systems with synthetic accounts, keys, identities and data. The simulation
can exercise ledger and writer behavior against deterministic stand-ins. It cannot establish behavior of clone
818HA_p2diff, real hosts, real identities, or real key custody.

G0-G8 remain NOT_PASSED, formal S13 entry remains NOT APPROVED, and Release 2 remains NO-GO. The supplied GPT-PM ruling
allows prototype-level closure and partial findings only. Synthetic accounts, keys and records remain `lane = TEST` and
must never acquire production authority.

## 2. Workstream status

| Id | Workstream | State | Evidence / limit |
|---|---|---|---|
| P0 | Migration 013 dispatch invariant and live ACL re-check | F-02 CLOSED as prototype | GPT-PM ruling for 7201cac..598a7a5; not production qualification. |
| P1 | Ed25519 verifier/signer and RFC 8032 vectors | Implemented in prototype; D9 OPEN | Synthetic crypto fixtures do not establish production identity or key custody. |
| P2 | Synthetic identities, clone, checkpoint host, witness and MFA lane | PARTIAL | C-M01, C-M02 and MFA remain PARTIAL; identity-provider evidence is simulated. |
| P3 | Signed preview and observed state | PARTIAL / OPEN | A7-B02 PARTIAL; B6-g OPEN. |
| P4 | Reference writer and clone-signed receipt wired to SQL ledger | PARTIAL | Combined SQL path and receipt hardening are implemented. Ledger digest remains the 009 typed-payload digest rather than wire-byte digest, and the receipt marker is opt-in. F-01 remains PARTIAL. |
| P5 | Combined synthetic end-to-end scenarios | Runtime verified on the synthetic lane | Independent focused runs passed 849 tests across 16 files. The requested `test_change_port.py` path does not exist; `test_change_ledger_port.py` passed 16/16. This is not production or release-gate evidence. |
| P6 | RU/EN report, decision log and closure ruling | Exact-range GPT-PM APPROVE received; approved code range pushed | GPT-PM request `9e9dc3a4-48f8-405e-a89e-d0903c8d5549` approved `598a7a50bbe131ede43c28f7e1bac39804c70df5..2edc82eab3f2a99a08bc07581ff7a37e08a22e75` as a NON-GATING prototype. No confirmed BLOCKER/MAJOR; two MINOR report references were historical and are corrected in this document follow-up. The approved range was pushed to `origin/main`. |

## 3. Current review ruling

GPT-PM request `e81a6d35` approved range `7201cac..598a7a5` as a prototype. Maximum statuses: F-02 CLOSED prototype,
F-01 PARTIAL, A7-B02 PARTIAL, B6-g OPEN, D9 OPEN, C-M01/C-M02/MFA PARTIAL. G0-G8 remain NOT_PASSED; formal S13 entry
remains NOT APPROVED; Release 2 remains NO-GO. Named limits are R-01 opt-in receipt gate, R-02 digest model mismatch,
R-03 legacy KEYED_HASH_STANDIN keys remain accepted after migration 015, and R-04 no combined bytes-to-clone-to-ledger
test in the reviewed range.

The current work adds the combined SQL scenario file and migration 017 and has passed the listed independent focused runs.
Independent database and end-to-end reviews are complete. The latter's MINOR test-wording finding was addressed; the test
still deliberately does not claim that a receipt over the actual received wire-byte digest is rejected. GPT-PM request
`9e9dc3a4-48f8-405e-a89e-d0903c8d5549` returned APPROVE for the exact range
`598a7a50bbe131ede43c28f7e1bac39804c70df5..2edc82eab3f2a99a08bc07581ff7a37e08a22e75`; that approved range is now
on `origin/main`. Findings and limits did not change G0-G8, S13, or Release 2 status.

## 4. Execution method and remaining evidence

Only focused tests were run, on one disposable `r2-s13-*` PostgreSQL container, one test file at a time. No full suites,
CI, lint, typecheck, build, or mutation runs were used. Independent test and migration-review evidence is recorded in
the change records and scratchpad logs. Exact-range GPT-PM approval was recorded above and the approved code range was
pushed. The approval covers only the stated prototype range; G0-G8 remain NOT_PASSED, formal S13 remains NOT APPROVED,
and Release 2 remains NO-GO.
