# Change record 121 — implement local S12 v2.0 evidence fixtures

## What changed

- Added `src/business_ai_gateway/phase2/change/evidence.py` with closed version-1 envelopes for `DispatchReceipt`, `OutcomeEvidence`, and `CompletionProof`; canonical JSON, domain-separated digest/signature preimages, synthetic signing helpers, and exact dispatch-attempt binding.
- Added `src/business_ai_gateway/phase2/simulation/governed_write_v2.py` with an in-memory synthetic ledger and coordinator. It consumes each `(change_id, claim_generation)` once, retains a base hold after uncertain outcomes, accepts `APPLIED` only with a valid writer receipt plus completion proof, and reaches `VERIFIED` only after separate complete matching read-back evidence.
- Added operation-semantic validation before `VERIFIED`: POST must read back as POSTED; CREATE_DRAFT and UNPOST as UNPOSTED; POST/UNPOST must bind the exact approved target/pre-image and receipt version while showing an advanced version; draft creation must match the receipt's returned target/version. The observed version is not predicted; it is cross-bound to the writer receipt and checked against the pre-image.
- Reconciled the current SDLC state, operator backlog, and S14 queue to show the semantic-review correction and focused rerun status accurately.

## Why

GPT owner approval `9f20b7a3-d812-4f3a-8b67-5c3d291dd718` approved the S12 Contract Freeze v2.0 for local engineering. Its acceptance matrix requires separate signed evidence types and a synthetic fake-port path before focused tests. These fixtures make the freeze falsifiable without connecting to PostgreSQL, COM, a real 1C base, or a production identity registry.

## Contracts and decisions

- The v2.0 operation allowlist is only `CREATE_DRAFT`, `POST`, and `UNPOST`. The latter two require an approved target and pre-version.
- Outcome and completion evidence may bind to a durable dispatch attempt when a receipt is absent; missing evidence cannot authorize `APPLIED` or `VERIFIED`.
- An uncertain writer result remains `APPLY_UNKNOWN`, keeps the synthetic base-wide hold, and cannot be retried for that generation.
- Ed25519 uses the repository's explicitly non-production implementation. Key mapping and service identities are synthetic fixtures, not authenticated trust.
- A fresh read-only code review found that signed matching flags/digests alone could accept a semantically contradictory posting state/version and release the hold. The coordinator now checks operation-specific observed state and version relation before accepting `VERIFIED`; the test agent added signed contradictory-outcome cases.
- Security re-review found receipt-binding gaps for a created draft target and the writer-returned version. The coordinator and frozen v2.0 outcome section now require the independent observation to match those receipt values; E2E rejects mismatched POST/UNPOST targets and pre-images, POST versions, and CREATE_DRAFT targets/versions while retaining the hold.
- Reliability review found the in-memory pre-consume recovery gap. Recovery now records `APPLY_UNKNOWN` with invocation count zero and retains the base hold; the fixture has no supervisor proof or API to release it, so this state is an explicit terminal held limitation rather than a false no-effect claim.
- This change does not implement SQL constraints, migrations, an operational writer/COM adapter, or real process/session supervision. No gate status changes.

## Affected paths

- `src/business_ai_gateway/phase2/change/evidence.py`
- `src/business_ai_gateway/phase2/simulation/governed_write_v2.py`
- `tests/phase2/test_s12_governed_write_v2_e2e.py`
- `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md`
- `README.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/phase2/CHANGE_RECORD_121.md`
- `governance/DOCUMENT_REGISTRY.md` (generated after the final Markdown edits)

## Verification state

- `functional-test-reviewer`: `python tests/phase2/test_s12_evidence_v2.py` — final run 6 tests passed, 0 failed/errors (0.250 s). Scope: canonical closed envelopes, signature/role separation, attempt/CAS/auth/permit binding, pre-image, movement summary, and malformed/missing success-result rejection.
- `e2e-runner`: `$env:PYTHONPATH='src'; python tests/phase2/test_s12_governed_write_v2_e2e.py` — final run: 20/20 passed (`OK`, 2.127 s; tool wall time 5.772 s) on worktree based at `1ec73879ade35b112c428c9885b55c46452aa7df`. Covers one-call/concurrent dispatch, authorization freshness, unknown/hold/recovery, pre-consume recovery with count 0 and no writer entry, partial evidence, no retry, receipt-bound target/version, POST/UNPOST semantics, and successful UNPOST to VERIFIED. One earlier run failed an overstrict assertion expecting no PRE_CAS check on duplicate dispatch; the E2E agent narrowed it to assert no post-CAS writer authorization and no writer call, then reran green.
- Both runs used only the local in-memory synthetic lane on the worktree based at `1ec73879ade35b112c428c9885b55c46452aa7df`; source and test files were uncommitted. These results are not PostgreSQL, COM, production, or formal gate evidence.
- Final file SHA-256: `evidence.py` `b6705b54d683d04f78c11edea48ec9da9b518ebed5364639d63591f13c770853`; `governed_write_v2.py` `35cff947d18779543beebdf931273d6882a5971d423f155ddf799dbb225c8fd1`; functional tests `714cffa7f242d9a3f1dfebe0cfe19ff8dc85caaef6189fab5a35034387ae4fac`; E2E tests `e5642eb670c2ee08b9a3870a2d302223b61130f71342fb174f8da4c8e030d38c`.
- Iteration history: the first functional direct run stopped at import with a syntax error (`evidence.py`, extra closing parenthesis); no scenario executed. The first E2E diagnostic command was the prohibited pytest invocation listed below and is excluded. After conversion to `unittest`, an intermediate run reported 1 pass / 3 errors (receipt attempt binding was missing), then the suite reached 14/14 before later semantic reviews found gaps. A subsequent run exposed an unsupported test helper (`OutcomeEvidence.verify`); the E2E agent corrected it to `verify_record_signature`. The semantic/receipt-bound suite reached 17/17, then a first pre-consume recovery run exposed an overstrict assertion about PRE_CAS on duplicate dispatch; the assertion was narrowed to the actual no-writer/no-post-CAS contract, and the final 20/20 run passed. All runs used the uncommitted worktree based at `1ec73879ade35b112c428c9885b55c46452aa7df`.
- **Out-of-policy diagnostic attempt (not accepted as evidence):** an initial run used `\.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s12_governed_write_v2_e2e.py` and reported 3 failures, 1 pass while implementation defects were present. `AGENTS.md` prohibits pytest; the result is excluded from acceptance. The E2E agent converted its file to standard-library `unittest`; all subsequent E2E results above used direct Python invocation.
- Fresh security, reliability, silent-failure, and code reviews (GPT-6 Luna, medium) found no code BLOCKER/MAJOR. Reviewers identified receipt-binding and operation-coverage gaps, now closed by code/tests, plus a documentation drift finding that is corrected in the current status rows. They confirmed the pre-consume recovery window transitions to held `APPLY_UNKNOWN` without claiming a writer call; no signed supervisor proof or API releases that hold. This is fail-closed; no persistent store or supervised resolution is implemented in this prototype.
- No build, lint, typecheck, CI, migration, real database, real COM, staging, or production action was part of this change.
- Exact-tree GPT review remains pending for the receipt-to-read-back clarification and final source/doc set; no push is authorized yet. Formal S12, G1–G8, real COM/DB, deployed identity, durability, and production qualification remain open or NOT_RUN as recorded in the gate packet.

## Delivery

This record belongs in the same local commit as the source and documentation changes it describes. A fresh GPT approval for the exact resulting commit is required before any push.
