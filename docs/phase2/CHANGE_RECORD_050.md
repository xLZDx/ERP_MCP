# Change record 050 — record approved G0 closure

## What changed

- Recorded G0 as `PASSED` / engineering `COMPLETE` / external evidence `SATISFIED` in the gate manifest, bound to the approved G0 evidence-index SHA-256.
- Refreshed the existing S11 node evidence digest to match the reconciled S11 exit package.
- Updated the G0 closure matrix and decision log with the exact GPT-PM request, approved HEAD, and scope limitations.
- Preserved all other gate states, OB-15 deferrals, and production authorization.

## Why

GPT-PM returned `G0 PASS APPROVED` for the SHA-256-bound G0 index and the operator's recorded OB-01/OB-15 decisions. The plan closes G0 after this gate-specific approval; the gate manifest therefore records that decision without implying any later gate has passed.

## Contracts and paths

- `governance/GATE_MANIFEST.json`
- `docs/phase2/G0_EVIDENCE_INDEX_2026-10-15.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `core/DECISION_LOG.md`
- `governance/DOCUMENT_REGISTRY.md`
- This record

## Verification state

- GPT-PM request: `935d6eed-4690-46f6-867f-8085ea38a11d`; approved HEAD `fb6362b504a7e9bc3a3b75ca23ac024116729d58`; evidence index SHA-256 `be3c57eef57e513046a43b35dd95f7a5bbcf22a9354612edc2fe980c1e2ac51a`.
- `node scripts/validate_gate_manifest.mjs` passed: `gate manifest ok: 10 gates, 10 nodes`. Its first run identified the stale S11 exit-package digest; the manifest now binds the reconciled file SHA-256 `146da7154e5225fca487bfd3b282b2e1a871d1589f54d9ad70de5cf4c075c05a`.
- `git diff --check` completed without findings.
- No tests or migrations run. G1–G8 and formal S13 remain unapproved; production authorization remains NONE.
- Exact-range GPT-PM review is required before push.
