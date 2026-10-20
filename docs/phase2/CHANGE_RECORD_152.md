# Change record 152 — add bounded S13 checkpoint suffix inspection

## Goal and scope

Implement the first remaining local S13 capability after CR149's repository-path inventory: read and classify the ordered ledger tail after an authenticated checkpoint without changing lifecycle state or enabling writes.

## Changes and affected contracts

- Added migration `025_lifecycle_checkpoint_suffix.sql`, requiring the complete 001–024 predecessor chain. Its SECURITY DEFINER function is read-only, scope-bound, limited to worker/auditor roles, and returns the exact-anchor match, current chain head, at most 128 ordered suffix events, each event hash/payload, and minimal linked record state. It returns `has_more` instead of silently truncating a larger suffix.
- Added the migration signature and method to `SqlChangeLedger`'s optional lifecycle API.
- Extended `LifecycleCoordinator` with strict structural validation and fail-closed classification. It accepts only a complete ordered suffix of `VERIFY_VERIFIED` events whose linked current record remains APPLIED/VERIFIED, PROVEN_FINISHED, reservation CONSUMED, and dispatch DISPATCHED. Explicit T4/T6/T7/T8/T11/T16 checkpoint-required events return a dedicated NOT_READY reason; all other events, truncation, sequence gaps, mismatched scope/anchor/head, or malformed state are rejected.
- A valid tail still returns `NOT_READY / SHARED_FENCE_UNAVAILABLE`. The implementation does not perform recovery, mutate the ledger, prove anti-rollback latestness, span the physical writer call, or return READY.
- Updated the S13 design, acceptance map, and S14 current closure row with the new source-only state and exact remaining gaps.

## Verification state

- No tests, database commands, migration application, build, or static checks were run in this implementation phase.
- Migration 025 and the Python reader/classifier are **NOT_RUN**. The existing CR143/CR145 PASS evidence covers only the earlier 001–024 migration scope and does not cover this change.
- `functional-test-reviewer` and `e2e-runner` must define and run the S13 suffix scenarios after local coding is complete; database/security/reliability reviews follow against the resulting exact HEAD.
- `governance/DOCUMENT_REGISTRY.md` was not regenerated because the S10 release handoff says it is a machine-dependent navigation artifact and not release evidence.

## Remaining S13 acceptance

- Prove SQL function scope, role grants, bounded behavior, exact ancestor detection, no mutation, reapplication safety, and full 001–025 chain on a disposable PostgreSQL instance.
- Prove Python behavior for valid T13 tail, empty tail, explicit checkpoint-required transitions, unsupported events, T12/T11 handling, malformed payloads, gaps, truncation, stale/foreign anchor, changing chain head, timeout, and unavailable reader.
- Separately design/review/implement complete cross-process admission fencing, bounded recovery-to-READY, all-mutator and physical-writer coverage, transaction-lifetime bound, and authenticated provider anti-rollback. Do not use this read-only feature to imply those gates are met.

## Ownership

- The operator is accountable for delegated project closure; GPT/Codex implemented this local source/doc slice.
- `functional-test-reviewer` and `e2e-runner` own executable test work. Database, security, and reliability reviewers own their risk reviews.
- The actual deployed writer/provider service and its owner remain unidentified in canonical records.
