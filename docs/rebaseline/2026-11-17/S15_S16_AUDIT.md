# S15/S16 implementation and design audit — 2026-11-17

Static Python-reviewer pass at HEAD 4318857 with dirty services.py. No tests,
runtime calls, DB/listener activity or source edits were performed.

## Implementation facts

Reviewed S15 oracle/verifier/ab_compare/reconcile/read_interface and S16
services/core/contracts/fakes/registries/tools/ingress/approval_page, their sprint
plans, FIN-S16 acceptance record, verify-evidence and named test inventory.

The dirty services.py:336 change requires are_independent to return exact True
instead of accepting truthiness. It matches core.py:399-406; no defect was
established in that one-line change. Existing tests do not prove the new
non-boolean edge case; keep its previously recorded qualification limit.

## S15: implemented logic, missing operational ports

ReceiptReader at read_interface.py:44-49 and reconciliation ports at
reconcile.py:109-125 are protocols. No real reader/ledger adapter was found by
the inspected source search. The recorded 899-pass result is synthetic/focused,
not G8/native accounting acceptance.

Oracle tables are independent of writer imports (oracle.py:1-10,97-111).
Verifier returns PARTIAL_UNVERIFIED for incomplete mapping (verifier.py:241-293).
A/B comparison uses multiset/provenance and treats read failure as inconclusive
(ab_compare.py:159-225). Reconciliation refuses listing errors and never resends
(reconcile.py:196-315). No defect in these inspected pure-logic paths was confirmed.

Reconciliation CLEAN depends on the adapter's complete document population,
including unmarked documents and declared scope (reconcile.py:115-121,225-228,
293-299). A protocol cannot establish authenticated-base provenance or actual
completeness; qualify the operational adapter before native reconciliation claims.

## S16: bounded fake-backed approval surface

Core locks/replay/anchors are process-local (core.py:128-152). ChangeStore
requires atomic port operations (contracts.py:249-263); the inspected concrete
implementation is InMemoryChangeStore (fakes.py:56-169). Restart/cross-process
durability and replay exclusion require a durable atomic store and qualification.

CHANGE_RECORD_FIN_S16_ACCEPTANCE_20261116 binds the 90-pass five-module run to
71cd251 and explicitly excludes durable storage, live auth/ingress and deployment.
That bounded result does not satisfy the entire S16 plan DoD:378-394. Retain its
bounded acceptance while keeping operational integration and product acceptance
separate. No new S15/S16 defect-level finding was confirmed in this static pass;
missing adapters/store are implementation/qualification backlog, not fake-test bugs.
