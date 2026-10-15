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
| P5 | Combined synthetic end-to-end scenarios | Implemented; independent verification pending | Scenario SQL and migration regression code are present; unexecuted scenarios remain NOT_RUN until fresh focused evidence exists. |
| P6 | RU/EN report, decision log and closure ruling | In progress | This report records the supplied GPT-PM verdict. A new diff review is not claimed. |

## 3. Current review ruling

GPT-PM request `e81a6d35` approved range `7201cac..598a7a5` as a prototype. Maximum statuses: F-02 CLOSED prototype,
F-01 PARTIAL, A7-B02 PARTIAL, B6-g OPEN, D9 OPEN, C-M01/C-M02/MFA PARTIAL. G0-G8 remain NOT_PASSED; formal S13 entry
remains NOT APPROVED; Release 2 remains NO-GO. Named limits are R-01 opt-in receipt gate, R-02 digest model mismatch,
R-03 legacy KEYED_HASH_STANDIN keys remain accepted after migration 015, and R-04 no combined bytes-to-clone-to-ledger
test in the reviewed range.

The current unreviewed work adds the combined SQL scenario file and migration 017. It does not change the ruling until
independently verified and reviewed against the exact diff.

## 4. Execution method and remaining evidence

Only focused tests are in scope, on disposable `r2-s13-*` PostgreSQL containers, one test file at a time. No full suites,
CI, lint, typecheck, build, or mutation runs are permitted. Independent verification, test outputs, and a fresh exact-diff
GPT-PM review are not yet recorded for the current changes. No push is authorized by this checkpoint.
