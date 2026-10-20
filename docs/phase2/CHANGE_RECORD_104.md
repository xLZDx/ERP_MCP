# Change record 104 — harden S13 recovery design after PM review

## What changed

- Revised `S13_KILL_SWITCH_RECOVERY_DESIGN.md` to address three PM-raised major issues: T9 can create unresolved work after T12's selection phase; selected-batch size alone cannot prove completion; and prior failure rows need stage-specific confirmed-success cleanup.
- Distinguished currently eligible work from unresolved work whose next retry is not yet due.
- Added acceptance cases for T9-to-T12 transitions, delayed T12/VERIFY work, stale stage failures, `GAP_BOUND`, and concurrent sweeps.

## Why

The first PM design review approved the bounded-retry direction but found that it could clear the switch when a later stage created new unresolved state, when an item was not yet eligible, or when an old stage failure was cleared without a confirmed successful retry.

## Decisions and scope

- Keep one bounded sweep per request; only a final scope-locked check of both eligible and unresolved state may permit OFF.
- Clear stage failure rows only after documented durable success predicates; preserve unresolved failures.
- This remains a design-only correction. Migration 020 is not implemented and awaits a new PM ruling.

## Review and verification state

- PM Bridge review `a739eead-d442-425a-b358-38b214981c54` returned `APPROVE WITH CHANGES` with three MAJOR findings; the design now incorporates the required changes and is ready for a targeted design re-review.
- Source review only. Tests, SQL checks, database commands, migrations, and formal gate transitions: `NOT_RUN`.

## Contracts and paths

- `docs/phase2/S13_KILL_SWITCH_RECOVERY_DESIGN.md`
- `db/phase2/006_change_sweeps.sql`
- `db/phase2/008_change_hardening_b.sql`
- `db/phase2/019_ed25519_action_only.sql` (separate pending R-03 implementation)
