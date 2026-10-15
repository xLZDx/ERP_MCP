# Simulation program plan: closing the real-write gaps on a synthetic lane

Date: 2026-10-15. Status: PLAN of the non-gating prototype. Nothing here is gate evidence, and no real 1C is touched.

## 1. Decision and limits

The operator (2026-10-15) delegated to the main session everything that was blocked on real systems: simulate the 1C
clone, the checkpoint host, the witness, identities and signing keys with synthetic data and accounts, and run it
through review and focused tests to the end of the project.

What simulation can and cannot establish:

- It can show that the ledger, the writer protocol and the verification chain behave correctly against a deterministic
  stand-in with the same interface and failure modes as the real systems.
- It cannot show anything about the real clone 818HA_p2diff, a real host, real keys held by real people, or real
  identity provisioning. Those stay the real-write qualification items and are never reported as done.
- Gates G0 to G8, S13 formal dependent entry and Release 2 keep their status (NOT_PASSED, NOT APPROVED, NO-GO) until
  GPT-PM rules otherwise. The program asks GPT-PM which gate checks, if any, a simulated lane may legitimately close.
- Every simulated account, key and record is marked `lane = TEST` and synthetic; simulated keys never gain
  production entitlements (S12-G04).

## 2. Workstreams (in order; each ends with an independent focused re-run and a GPT-PM review before push)

| Id | Workstream | Closes (in the simulation only) |
|---|---|---|
| P0 | Migration 013: one DISPATCHED invariant (INSERT as DISPATCHED, direct `records.dispatch_state`), live ACL re-check | F-02, E-03, E-04 |
| P1 | Real Ed25519 (RFC 8032) signature verification in the ledger (pure PL/pgSQL, no extension) and a stdlib Ed25519 signer; keyed-hash stand-ins replaced for evidence, checkpoints and provider attestations; RFC 8032 test vectors | "real signing", D9 Ed25519 |
| P2 | Simulation toolkit: synthetic identity provisioning (persons, distinct logins and sessions, MFA attestation by a simulated IdP, MFA enforced for the HUMAN approval lane), synthetic 1C clone (documents, versions, duplicates, deterministic fingerprints), simulated checkpoint host with readback, simulated witness | C-M01, C-M02, MFA, D9, D10b, D4 as simulated components |
| P3 | Trusted preview and state provider: the simulated 1C signs (Ed25519) the preview digest and the observed business-state digest bound to change and target version; the ledger verifies the signature before storing | A7-B02, B6-g |
| P4 | Reference writer: sends exactly the verified bytes, the simulated 1C returns a signed digest of the bytes it received, the ledger refuses completion if it differs from the approved payload digest | F-01 |
| P5 | End-to-end scenario suite on synthetic data: all four operation kinds, repair, duplicate override, stale preview, tampered bytes, kill switch, crash mid-apply and restart recovery, anchor gap, two concurrent writers, tenant isolation, dump and restore | evidence for the above |
| P6 | Final report (RU and EN), decision log, GPT-PM ruling on what the simulated lane may and may not close | closure record |

## 3. Method

- Operator rules stay: only focused tests written and run by the named agents on disposable `r2-s13-*` containers,
  no CI, lint, full suite or mutation runs, one PR-equivalent range per push after GPT-PM approval, English git
  content, a decision log entry in every commit.
- Each workstream is implemented by an implementation agent, independently re-run by a second agent, then reviewed by
  GPT-PM on the exact head before push.
- Named limits are written down at the moment they are found and carried into the final report.

## 4. Closure ruling (GPT-PM, 2026-10-15, request 8d2c5e70)

Maximum permissible status of simulated items: F-02 prototype (awaiting independent verification); F-01 PARTIAL (offline simulation; receipt not yet signed by the simulated 1C and not wired into the SQL ledger flow); A7-B02 PARTIAL; B6-g OPEN; D9 OPEN; C-M01, C-M02, MFA PARTIAL (simulated IdP only); G0-G8 NOT_PASSED; S13 formal entry NOT APPROVED; Release 2 NO-GO. Named limit: legacy KEYED_HASH_STANDIN keys remain valid after migration 015 (no algorithm-by-policy rule yet).

