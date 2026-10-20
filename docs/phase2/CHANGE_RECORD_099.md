# Change record 099 — R-03 Ed25519 new-action design

## What changed

- Added `R03_ED25519_NEW_ACTION_DESIGN.md`, an implementation-ready design for a non-gating S13 prototype hardening change.
- The design proposes additive migration 019 with Ed25519-only checks at four mutating entrypoints: `record_evidence`, `record_checkpoint`, `attach_permit_signature`, and `record_dispatch_receipt`.
- It preserves the internal legacy verifier branch for existing verification behavior, avoids rewriting migrations 015–018 or stored data, and defines focused tests for functional-test-reviewer/e2e-runner after implementation.

## Why

At source HEAD `ec6379e`, migrations 015 and 018 allow the shared `KEYED_HASH_STANDIN` verifier to reach new signed actions. Migration 017's receipt-purpose guard covers Ed25519 rows only. Independent security/database reviews confirmed the conditional source path but found no evidence that affected keys or a production writer exist in deployment. The design records a local, data-preserving prototype option while keeping deployed inventory, custody, and formal-gate claims open.

## Decisions and scope

- Compared a narrow guard at the four mutating APIs with changing the shared verifier and adding a new historical API. Chose the narrow guards because no runtime-accessible historical verifier consumer was identified.
- This is a design record only. No SQL, application code, tests, database, key rows, production configuration, or gate manifest changed.
- The proposed migration is for disposable prototype databases only until separate production approval, inventory/custody evidence, and rollout/restore planning exist.
- R-03 remains OPEN; G1–G8, S13, Release 2, and production authorization remain unchanged.

## Review and verification state

- `code-architect` / GPT-6 Luna medium recommended the narrow four-entrypoint design and highlighted that the generic verifier is not a runtime-accessible historical API.
- `database-reviewer` / GPT-6 Luna medium recommended an additive migration 019, retaining current error codes and the shared dispatcher while refusing non-Ed25519 keys at write boundaries. It identified harnesses and focused tests that must be updated.
- `security-reviewer` / GPT-6 Luna medium confirmed the conditional legacy-key authorization path across evidence, checkpoint, permit, and receipt operations; no deployed keys or exploit were established.
- `reliability-reviewer` / GPT-6 Luna medium separately identified a S13 kill-switch recovery follow-up; it is outside this design's scope and remains in the ordered queue.
- No tests, builds, migrations, database queries, or production operations were run.

## Acceptance and follow-up

Before implementing migration 019, obtain the requested PM design ruling. If approved, finish all code and test-harness changes before test execution; have `functional-test-reviewer` and `e2e-runner` own the focused disposable-PostgreSQL tests, then run a fresh DB specialist review. Do not promote formal S13/G1 or perform a production cutover from this prototype evidence.

## Contracts and paths

- `docs/phase2/R03_ED25519_NEW_ACTION_DESIGN.md`
- `db/phase2/015_ed25519_signatures.sql`
- `db/phase2/016_dispatch_receipt.sql`
- `db/phase2/017_receipt_hardening.sql`
- `db/phase2/018_wire_payload_receipt.sql`
- `tests/phase2/_pg_harness.py`
- `tests/phase2/test_change_ledger_dump_restore.py`
- `tests/phase2/test_change_hardening_g_sql.py`
- `tests/phase2/test_change_hardening_h_sql.py`
- `tests/phase2/test_s14_wire_receipt_sql.py`
- `tests/phase2/test_simulation_e2e_sql.py`
